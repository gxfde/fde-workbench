from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from scripts.deploy.deployment_coordinator import Plan, Target, inspect, run

REPO = Path(__file__).resolve().parents[2]
TARGET = Target("a" * 64, "first")
CANDIDATE = "1" * 40

WORKER = """
from pathlib import Path
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from scripts.deploy import deployment_coordinator as coordinator
from scripts.deploy.deployment_coordinator import Plan, Target, run

root = Path(sys.argv[1])
mode = sys.argv[2]
key = sys.argv[3]

def wait(name):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if (root / name).exists():
            return True
        time.sleep(0.01)
    return False

if mode in ('publish', 'release'):
    if os.name == 'nt':
        import msvcrt as locking
        lock_name = 'locking'
    else:
        import fcntl as locking
        lock_name = 'flock'
    acquire = getattr(locking, lock_name)

    def signal_contention(*args):
        try:
            return acquire(*args)
        except OSError:
            (root / 'writer-waiting').touch()
            raise

    setattr(locking, lock_name, signal_contention)

if mode == 'release':
    original_guard = coordinator._state_guard
    original_write = coordinator._write_record
    completed_written = False

    def track_completed(slot, record):
        global completed_written
        original_write(slot, record)
        completed_written = record.status == 'completed'

    @contextmanager
    def gate_release(slot, *, write=False):
        if write and completed_written:
            (root / 'entered').touch()
            if not wait('release'):
                raise OSError('test never released the writer')
        with original_guard(slot, write=write):
            yield

    coordinator._state_guard = gate_release
    coordinator._write_record = track_completed

def apply():
    with (root / 'writes').open('a', encoding='ascii') as f:
        f.write(key + '\\n')
    if mode in ('hold', 'publish'):
        (root / 'entered').touch()
        return wait('release')
    if mode == 'child':
        child = subprocess.Popen([sys.executable, '-B', '-c', sys.argv[4], str(root)],
                                 cwd=str(Path(sys.executable).resolve().parent),
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        return child.wait() == 0
    return True

result = run(root, Target(key * 64, 'project-' + key), key * 40,
             Plan(lambda: True, apply, lambda: True))
print(result.status, flush=True)
"""

CHILD = """
from pathlib import Path
import sys
import time
root = Path(sys.argv[1])
(root / 'child-started').touch()
try:
    for _ in range(500):
        if (root / 'probe-child').exists():
            (root / 'child-answered').touch()
        if (root / 'release').exists():
            break
        time.sleep(0.02)
finally:
    (root / 'child-done').touch()
"""

READER = """
from pathlib import Path
import sys
import time
from scripts.deploy import deployment_coordinator as coordinator

root = Path(sys.argv[1])
original = coordinator._read_record

def hold_read_handle(slot):
    with (slot / 'state.json').open('rb'):
        (root / 'reader-open').touch()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and not (root / 'reader-close').exists():
            time.sleep(0.01)
        if not (root / 'reader-close').exists():
            raise RuntimeError('reader was never released')
        return original(slot)

coordinator._read_record = hold_read_handle
print(coordinator.inspect(root).status, flush=True)
"""


def accept():
    return True


class DeploymentCoordinatorTests(unittest.TestCase):
    def test_failed_verification_blocks_next_request_even_for_another_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            self.assertEqual(inspect(root).status, "idle")
            first = run(root, Target("a" * 64, "first"), "1" * 40, Plan(
                lambda: True, lambda: calls.append("first") is None, lambda: False,
            ))
            second = run(root, Target("b" * 64, "second"), "2" * 40, Plan(
                lambda: True, lambda: calls.append("second") is None, lambda: True,
            ))
            self.assertEqual(first.status, "verification_failed")
            self.assertEqual(second.status, "occupied")
            self.assertEqual(inspect(root), first)
            self.assertEqual(calls, ["first"])

    def test_success_releases_and_later_request_has_new_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = Plan(accept, accept, accept)
            first = run(root, TARGET, CANDIDATE, plan)
            self.assertEqual(first.status, "completed")
            self.assertEqual(inspect(root).status, "idle")
            second = run(root, TARGET, CANDIDATE, plan)
            self.assertEqual(second.status, "completed")
            self.assertNotEqual(first.record.request_id, second.record.request_id)

    def test_precondition_failed_or_uncertain_apply_leaves_slot(self):
        for phase, failure, status, expected in (
            ("preflight", None, "precondition_failed", ["preflight"]),
            ("apply", None, "execution_failed", ["preflight", "apply"]),
            ("apply", TimeoutError, "unknown", ["preflight", "apply"]),
            ("apply", SystemExit, "unknown", ["preflight", "apply"]),
        ):
            with self.subTest(status=status, failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                calls = []

                def step(name):
                    def call():
                        calls.append(name)
                        if name != phase:
                            return True
                        if failure:
                            raise failure("synthetic secret that must never be persisted")
                        return False
                    return call

                plan = Plan(step("preflight"), step("apply"), step("verify"))
                first = run(root, TARGET, CANDIDATE, plan)
                self.assertEqual((first.status, first.record.step), (status, phase))
                self.assertEqual(first.reason, "step_interrupted" if failure else "step_rejected")
                self.assertEqual(calls, expected)
                self.assertEqual(inspect(root), first)
                self.assertNotIn("synthetic secret", (root / "active/state.json").read_text())
                self.assertNotIn("synthetic secret", repr(first))

    def test_empty_malformed_or_missing_root_never_executes(self):
        for state in (None, b"synthetic secret", b'{"schema_version":[]}', b"x" * 4097):
            with self.subTest(state=state is None), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.assertEqual(run(root, TARGET, CANDIDATE, Plan(accept, accept, lambda: False)).status,
                                 "verification_failed")
                path = root / "active/state.json"
                if state is not None:
                    path.write_bytes(state)
                else:
                    path.unlink()
                observed = inspect(root)
                self.assertEqual((observed.status, observed.reason, observed.record),
                                 ("unknown", "state_unavailable", None))
                calls = []
                plan = Plan(*(lambda: calls.append("called") is None for _ in range(3)))
                self.assertEqual(run(root, TARGET, CANDIDATE, plan).status, "occupied")
                self.assertEqual(run(root / "absent", TARGET, CANDIDATE, plan).status, "unknown")
                self.assertEqual(run(root, Target("secret", "first"), CANDIDATE, plan).status,
                                 "rejected")
                self.assertEqual(calls, [])

    def test_reservation_without_guard_is_occupied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "active").mkdir()
            self.assertEqual(inspect(root).status, "unknown")
            self.assertEqual(run(root, TARGET, CANDIDATE, Plan(accept, accept, accept)).status,
                             "occupied")

    def test_first_atomic_publish_failure_blocks_all_steps_and_immediate_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            plan = Plan(*(lambda: calls.append("called") is None for _ in range(3)))
            with patch("scripts.deploy.deployment_coordinator.os.replace",
                       side_effect=OSError("injected filesystem failure")):
                self.assertEqual(run(root, TARGET, CANDIDATE, plan).reason, "state_write_failed")
            self.assertEqual(run(root, TARGET, CANDIDATE, plan).status, "occupied")
            self.assertEqual(calls, [])

    def test_record_replaced_during_verification_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "active/state.json"

            def verify():
                payload = json.loads(state.read_bytes())
                payload["request_id"] = "f" * 32
                state.write_text(json.dumps(payload), encoding="ascii")
                return True

            first = run(root, TARGET, CANDIDATE, Plan(accept, accept, verify))
            self.assertEqual((first.status, first.reason), ("unknown", "state_write_failed"))
            self.assertEqual(inspect(root).record.request_id, "f" * 32)
            self.assertEqual(run(root, TARGET, CANDIDATE, Plan(accept, accept, accept)).status,
                             "occupied")

    def test_failed_release_does_not_remove_foreign_entries_or_report_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            extra = root / "active/foreign"

            def verify():
                extra.touch()
                return True

            result = run(root, TARGET, CANDIDATE, Plan(accept, accept, verify))
            self.assertEqual((result.status, result.reason), ("unknown", "release_failed"))
            self.assertEqual((inspect(root).status, inspect(root).reason),
                             ("unknown", "release_pending"))
            self.assertTrue(extra.is_file())
            self.assertEqual(run(root, TARGET, CANDIDATE, Plan(accept, accept, accept)).status,
                             "occupied")

    def test_failure_between_unlink_and_rmdir_preserves_empty_occupancy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = Plan(accept, accept, accept)
            with patch.object(Path, "rmdir", side_effect=OSError("injected rmdir failure")):
                first = run(root, TARGET, CANDIDATE, plan)
            self.assertEqual((first.status, first.reason), ("unknown", "release_failed"))
            self.assertEqual(list((root / "active").iterdir()), [])
            self.assertEqual(inspect(root).status, "unknown")
            self.assertEqual(run(root, TARGET, CANDIDATE, plan).status, "occupied")

    def test_stale_pid_and_timestamp_do_not_reclaim(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(root, TARGET, CANDIDATE, Plan(accept, accept, lambda: False))
            state = root / "active/state.json"
            payload = json.loads(state.read_bytes())
            for pid in (os.getpid(), 2147483647):
                payload.update(pid=pid, updated_at="2000-01-01T00:00:00+00:00")
                state.write_text(json.dumps(payload), encoding="ascii")
                self.assertEqual(run(root, TARGET, CANDIDATE, Plan(accept, accept, accept)).status,
                                 "occupied")

    def wait_for_file(self, path):
        deadline = time.monotonic() + 9
        while time.monotonic() < deadline:
            if path.exists():
                return
            time.sleep(0.02)
        self.fail(f"missing synchronization marker: {path.name}")

    def worker(self, root, cwd, mode, key):
        cwd.mkdir(exist_ok=True)
        return subprocess.Popen(
            [sys.executable, "-B", "-c", WORKER, str(root), mode, key, CHILD],
            cwd=cwd, env={**os.environ, "PYTHONPATH": str(REPO)}, text=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def finish(self, process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def assert_worker_status(self, process, expected):
        try:
            stdout, stderr = process.communicate(timeout=8)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), expected)
        finally:
            self.finish(process)

    def test_independent_processes_with_different_cwd_and_targets_serialize(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner = self.worker(root, root / "tree-a", "hold", "a")
            try:
                self.wait_for_file(root / "entered")
                self.assertEqual((inspect(root).status, inspect(root).record.step), ("running", "apply"))
                self.assert_worker_status(self.worker(root, root / "tree-b", "normal", "b"), "occupied")
                self.assertEqual((root / "writes").read_text().splitlines(), ["a"])
                (root / "release").touch()
                self.assert_worker_status(owner, "completed")
                self.assert_worker_status(self.worker(root, root / "tree-b", "normal", "b"), "completed")
                self.assertEqual((root / "writes").read_text().splitlines(), ["a", "b"])
            finally:
                self.finish(owner)

    def test_concurrent_reader_holds_handle_without_breaking_publish_and_release(self):
        for phase, read_status in (("publish", "running"), ("release", "unknown")):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                owner = self.worker(root, root / "tree-a", phase, "a")
                reader = None
                try:
                    self.wait_for_file(root / "entered")
                    reader = subprocess.Popen(
                        [sys.executable, "-B", "-c", READER, str(root)], cwd=REPO, text=True,
                        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    )
                    self.wait_for_file(root / "reader-open")
                    (root / "release").touch()
                    self.wait_for_file(root / "writer-waiting")
                    self.assertEqual(inspect(root).status, "unknown")
                    (root / "reader-close").touch()
                    self.assert_worker_status(reader, read_status)
                    self.assert_worker_status(owner, "completed")
                    self.assertEqual(inspect(root).status, "idle")
                finally:
                    if reader is not None:
                        self.finish(reader)
                    self.finish(owner)

    def test_hard_killed_owner_with_child_still_running_does_not_unlock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner = self.worker(root, root / "tree-a", "child", "a")
            try:
                self.wait_for_file(root / "child-started")
                self.finish(owner)
                (root / "probe-child").touch()
                self.wait_for_file(root / "child-answered")
                before = inspect(root)
                self.assertEqual((before.status, before.record.step), ("running", "apply"))
                self.assert_worker_status(self.worker(root, root / "tree-b", "normal", "b"), "occupied")
                self.assertEqual(inspect(root), before)
                self.assertEqual((root / "writes").read_text().splitlines(), ["a"])
            finally:
                self.finish(owner)
                (root / "release").touch()
                if (root / "child-started").exists():
                    self.wait_for_file(root / "child-done")
