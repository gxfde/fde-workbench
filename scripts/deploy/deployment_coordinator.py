"""Single-slot coordination for a trusted local directory and an internal plan.

No deployment commands, target discovery, or stale-lock recovery live here.
Callers must share a stable root on the same local filesystem. An occupied slot
is never reclaimed by another request, including after an interrupted write.
"""
from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import re
import stat
import time
from uuid import uuid4


@dataclass(frozen=True)
class Target:
    fingerprint: str
    project: str


@dataclass(frozen=True)
class Plan:
    preflight: Callable[[], bool]
    apply: Callable[[], bool]
    verify: Callable[[], bool]


@dataclass(frozen=True)
class Record:
    schema_version: int
    request_id: str
    target_fingerprint: str
    project: str
    candidate: str
    step: str
    status: str
    pid: int
    updated_at: str
    reason: str


@dataclass(frozen=True)
class Result:
    status: str
    reason: str
    record: Record | None = None


_PHASES = {
    ("preflight", "reserved", "none"),
    ("preflight", "precondition_failed", "step_rejected"),
    ("apply", "running", "none"),
    ("apply", "execution_failed", "step_rejected"),
    ("verify", "running", "none"),
    ("verify", "verification_failed", "step_rejected"),
    ("verify", "completed", "none"),
    *((step, "unknown", "step_interrupted") for step in ("preflight", "apply", "verify")),
}


def _matches(pattern: str, value: object) -> bool:
    return type(value) is str and re.fullmatch(pattern, value) is not None


def _valid_identity(fingerprint: object, project: object, candidate: object) -> bool:
    return (_matches(r"[0-9a-f]{64}", fingerprint)
            and _matches(r"[a-z0-9][a-z0-9_-]{0,62}", project)
            and _matches(r"[0-9a-f]{40}", candidate))


def _plain(path: Path, predicate: Callable[[int], bool]) -> os.stat_result:
    info = path.lstat()
    if (not predicate(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise ValueError("unexpected_path_type")
    return info


def _slot(root: Path) -> Path:
    if not root.is_absolute():
        raise ValueError("relative_root")
    _plain(root, stat.S_ISDIR)
    return root / "active"


@contextmanager
def _state_guard(slot: Path, *, write: bool = False):
    # Windows can reject replace/rmdir while a read handle is open. The guard
    # never moves and covers only file I/O, not any deployment step.
    lock = slot.parent / "state.guard"
    if write:
        try:
            with lock.open("xb"):
                pass
        except FileExistsError:
            pass
    if _plain(lock, stat.S_ISREG).st_nlink != 1:
        raise ValueError("linked_guard")
    if os.name == "nt":
        import msvcrt

        def acquire(fd):
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        def acquire(fd):
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    deadline = time.monotonic() + (3 if write else 0)
    with lock.open("rb") as file:
        while True:
            try:
                acquire(file.fileno())
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.02)
        yield


def _read_record(slot: Path) -> Record:
    _plain(slot, stat.S_ISDIR)
    path = slot / "state.json"
    if _plain(path, stat.S_ISREG).st_nlink != 1:
        raise ValueError("linked_record")
    with path.open("rb") as file:
        raw = file.read(4097)
    if len(raw) > 4096:
        raise ValueError("oversized_record")
    record = Record(**json.loads(raw))
    if not (type(record.schema_version) is int and record.schema_version == 1
            and _matches(r"[0-9a-f]{32}", record.request_id)
            and _valid_identity(record.target_fingerprint, record.project, record.candidate)
            and (record.step, record.status, record.reason) in _PHASES
            and type(record.pid) is int and 0 < record.pid < 2**32
            and _matches(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+00:00",
                         record.updated_at)):
        raise ValueError("invalid_record")
    datetime.fromisoformat(record.updated_at)
    return record


def inspect(root: Path) -> Result:
    """Read the last recorded phase, not the liveness of the owner or backend."""
    try:
        slot = _slot(root)
        try:
            with _state_guard(slot):
                try:
                    slot.lstat()
                except FileNotFoundError:
                    return Result("idle", "none")
                try:
                    record = _read_record(slot)
                except FileNotFoundError:
                    return Result("unknown", "state_unavailable")
        except FileNotFoundError:
            # No guard has been published. A reservation may already exist.
            try:
                slot.lstat()
            except FileNotFoundError:
                return Result("idle", "none")
            return Result("unknown", "state_unavailable")
    except (OSError, ValueError, TypeError, RecursionError):
        return Result("unknown", "state_unavailable")
    if record.status == "completed":
        return Result("unknown", "release_pending", record)
    return Result(record.status, record.reason, record)


def _write_record(slot: Path, record: Record) -> None:
    # The temporary entry stays within the occupied directory even on failure.
    pending = slot / (".state-" + uuid4().hex)
    with pending.open("xb") as file:
        file.write(json.dumps(asdict(record), sort_keys=True).encode("ascii"))
        file.flush()
        os.fsync(file.fileno())
    os.replace(pending, slot / "state.json")


def run(root: Path, target: Target, candidate: str, plan: Plan) -> Result:
    """Run once; only an explicitly true result advances each step."""
    if not _valid_identity(target.fingerprint, target.project, candidate):
        return Result("rejected", "invalid_identity")
    try:
        slot = _slot(root)
        slot.mkdir()
    except FileExistsError:
        return Result("occupied", "slot_occupied", inspect(root).record)
    except (OSError, ValueError):
        return Result("unknown", "state_unavailable")

    request_id = uuid4().hex
    previous: Record | None = None

    def record_phase(step: str, status: str, reason: str = "none") -> Result:
        nonlocal previous
        entry = Record(1, request_id, target.fingerprint, target.project, candidate,
                       step, status, os.getpid(), datetime.now(timezone.utc).isoformat(
                           timespec="seconds"), reason)
        with _state_guard(slot, write=True):
            if previous is not None and _read_record(slot) != previous:
                raise ValueError("state_changed")
            _write_record(slot, entry)
            previous = entry
        return Result(status, reason, entry)

    steps = (
        ("preflight", "reserved", "precondition_failed", plan.preflight),
        ("apply", "running", "execution_failed", plan.apply),
        ("verify", "running", "verification_failed", plan.verify),
    )
    try:
        for step, started, failed, operation in steps:
            record_phase(step, started)
            try:
                accepted = operation() is True
            except (Exception, KeyboardInterrupt, SystemExit):
                return record_phase(step, "unknown", "step_interrupted")
            if not accepted:
                return record_phase(step, failed, "step_rejected")
        result = record_phase("verify", "completed")
    except (OSError, ValueError, TypeError, RecursionError, KeyboardInterrupt):
        return Result("unknown", "state_write_failed", inspect(root).record)

    try:
        with _state_guard(slot, write=True):
            owner = _read_record(slot)
            if owner != result.record or any(p.name != "state.json" for p in slot.iterdir()):
                return Result("unknown", "release_failed", result.record)
            (slot / "state.json").unlink()
            slot.rmdir()
    except (OSError, ValueError, TypeError, RecursionError, KeyboardInterrupt):
        return Result("unknown", "release_failed", result.record)
    return result
