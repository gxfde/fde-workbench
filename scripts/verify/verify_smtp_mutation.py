#!/usr/bin/env python3
"""SMTP 通道变异验证（注册制试用开闸 R1，2026-11-17）。

机械自证「测试有判别力」：对四处关键接线各做一次
「改坏 → 用例必须红 → 字节还原 → 用例必须绿」的往返。

- **变异不落地**：每个锚点先读原字节，try/finally 无条件还原（字节级一致，
  还原后再断言 sha256 与开工前相同）；
- **红绿双向判定**：变异后 pytest 必须**非零退出**（红），还原后必须**零退出**
  （绿）——任一方向不成立即判失败；
- **覆盖面**：通道解析分支／SMTP 错误分类／注册面开闸通道无关／STARTTLS 强制；
- **换行风格无关**：锚点按 LF/CRLF 两种形态匹配（仓内文件混用两种换行）。

用法（仓根执行，需已装齐服务端依赖与可连的测试库）::

    python scripts/verify/verify_smtp_mutation.py

退出码 0＝四组变异全部「红→绿」成立；非 0＝存在无判别力的用例（必须修）。
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
TEST_TARGET = "tests/test_mailing_smtp.py"


@dataclass(frozen=True)
class Mutation:
    """一处变异锚点：文件 + 原字节 + 变异字节 + 用途说明。"""

    name: str
    relative_path: str
    old: bytes
    new: bytes
    note: str


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="M1 channel-resolve: SMTP branch removed",
        relative_path="server/src/fde_api/mailing/channel.py",
        old=b"    if settings.smtp_enabled:\n        return CHANNEL_SMTP\n",
        new=b"    if settings.smtp_enabled:\n        return CHANNEL_SES\n",
        note="SMTP channel mis-resolved as SES",
    ),
    Mutation(
        name="M2 error-classification: 4xx no longer retryable",
        relative_path="server/src/fde_api/mailing/smtp_client.py",
        old=b"if 400 <= code < 500:",
        new=b"if 400 <= code < 400:",
        note="4xx must stay throttle/retryable",
    ),
    Mutation(
        name="M3 registration-gate: SES-only again",
        relative_path="server/src/fde_api/registration/service.py",
        old=b"        and channel_enabled(settings)\n",
        new=b"        and settings.ses_enabled\n",
        note="registration gate must stay channel-agnostic",
    ),
    Mutation(
        name="M4 tls-discipline: STARTTLS skipped",
        relative_path="server/src/fde_api/mailing/smtp_client.py",
        old=b"client.starttls(context=ssl.create_default_context())",
        new=b"pass  # mutation: skip STARTTLS (plaintext fallback)",
        note="TLS must be enforced (no plaintext fallback)",
    ),
)


def _apply_mutation(original: bytes, old: bytes, new: bytes) -> bytes | None:
    """按 LF/CRLF 两种形态落锚点；命中返回变异后字节，否则 None。"""
    for newline in (b"\n", b"\r\n"):
        old_needle = old.replace(b"\n", newline)
        new_needle = new.replace(b"\n", newline)
        if old_needle in original:
            return original.replace(old_needle, new_needle, 1)
    return None


def _run_pytest() -> int:
    """跑目标测试文件（cwd＝server/），返回 pytest 退出码。"""
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", TEST_TARGET, "-q", "-p", "no:cacheprovider"],
        cwd=SERVER,
        capture_output=True,
        text=True,
    )
    tail = (completed.stdout or completed.stderr or "").strip().splitlines()[-3:]
    for line in tail:
        print(f"      {line}")
    return completed.returncode


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def main() -> int:
    failures: list[str] = []
    for mutation in MUTATIONS:
        path = ROOT / mutation.relative_path
        if not path.exists():
            failures.append(f"{mutation.name}: anchor file missing {mutation.relative_path}")
            print(f"[FAIL] {mutation.name}: anchor file missing")
            continue
        original = path.read_bytes()
        mutated = _apply_mutation(original, mutation.old, mutation.new)
        if mutated is None:
            failures.append(f"{mutation.name}: anchor bytes not found (source changed?)")
            print(f"[FAIL] {mutation.name}: anchor bytes not found")
            continue
        before = _digest(path)
        print(f"\n=== {mutation.name} ===")
        print(f"    {mutation.note}")
        try:
            path.write_bytes(mutated)
            red_code = _run_pytest()
        finally:
            path.write_bytes(original)
        after = _digest(path)
        if red_code == 0:
            failures.append(f"{mutation.name}: suite still green after mutation (no discrimination)")
            print(f"[FAIL] {mutation.name}: suite still green after mutation")
            continue
        print(f"    mutated exit={red_code} (RED ok)")
        green_code = _run_pytest()
        if green_code != 0:
            failures.append(f"{mutation.name}: suite still red after restore (exit={green_code})")
            print(f"[FAIL] {mutation.name}: suite still red after restore")
            continue
        if before != after:
            failures.append(f"{mutation.name}: restore not byte-identical ({before} != {after})")
            print(f"[FAIL] {mutation.name}: restore not byte-identical")
            continue
        print(f"    restored exit=0 (GREEN ok) / sha256 {before} identical")
    print("\n================ mutation summary ================")
    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1
    print(f"[PASS] {len(MUTATIONS)} mutations all red->green, byte-identical restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
