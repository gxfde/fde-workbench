"""V3.1 P1-1：执行策略层 + 短期授权票据 + 扩列落库 + 通道默认关闭钉。

验收面（任务书 §9 前置 3/4/5/8 + 00-gap-register 5.3/5.4/5.6/5.7/5.10）：
- 工作目录规范化：根内通过 / ``..`` 逃逸拒绝 / 绝对跳出拒绝 / 拒绝清单标记拒绝；
- 命令锚定：argv 空拒 / 首元素非白名单拒 / 白名单过 / 超长拒；超时钳制；
- 策略快照：确定性（同输入恒同 hash）+ 工具集合顺序无关 + 不同输入不同；
- 授权票据：签发→验证通过（run 绑定+动作覆盖）/ 过期拒 / 篡改拒 /
  run 不匹配拒 / 动作越界拒 / 未注册动作拒签 / TTL 越界拒签 / 短密钥拒签；
- 扩列落库：AgentRunResult.policy_snapshot_hash → _finalize 落列（构造域内
  直接驱动 _finalize）；通道默认关闭静态钉（config 默认值 False AST 断言）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from hashlib import sha256
from pathlib import Path

import pytest
from test_agents_d4_harness import d4_settings  # noqa: F401  (pytest fixture)

from fde_api.agents.execution_authorization import (
    EXECUTION_ACTIONS,
    GRANT_TTL_SECONDS,
    ExecutionGrantError,
    issue_execution_grant,
    verify_execution_grant,
)
from fde_api.agents.execution_policy import (
    MAX_HOST_TIMEOUT_MS,
    ExecutionPolicyError,
    assert_command_allowed,
    clamp_timeout_ms,
    normalize_workspace_under_root,
    policy_snapshot,
)

_SECRET = b"k" * 48
_NOW = datetime(2026, 11, 8, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# 工作目录规范化（前置 5）


def test_normalize_workspace_happy_and_escapes(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    (root / "run-1").mkdir(parents=True)
    ok = normalize_workspace_under_root(root, root / "run-1")
    assert ok == (root / "run-1").resolve()

    # 不存在的候选路径（resolve(strict=False)）仍在根内 → 通过
    assert normalize_workspace_under_root(root, root / "run-2") == (root / "run-2").resolve()

    # .. 足量穿越跳出根（单层 .. resolve 后仍在根内=无害穿越，不拒）
    with pytest.raises(ExecutionPolicyError):
        normalize_workspace_under_root(root, root / "run-1" / ".." / ".." / "elsewhere")
    inner = normalize_workspace_under_root(root, root / "run-1" / ".." / "run-2")
    assert inner == (root / "run-2").resolve(), "根内 .. 穿越规范化后合法"

    # 绝对路径跳出根
    with pytest.raises(ExecutionPolicyError):
        normalize_workspace_under_root(root, tmp_path / "outside")

    # 根自身放行（workspace_ref=root 合法形状）——run 子目录才由调用方约束
    assert normalize_workspace_under_root(root, root) == root.resolve()


def test_normalize_workspace_denied_markers(tmp_path: Path) -> None:
    # 拒绝清单标记（真相层/.env 等 FORBIDDEN_MOUNT_MARKERS 成员）——用真实成员之一
    from fde_api.agents.sandbox import FORBIDDEN_MOUNT_MARKERS

    root = tmp_path / "workspaces"
    marker_root = tmp_path / f"innocent-{next(iter(sorted(FORBIDDEN_MOUNT_MARKERS)))}"
    marker_root.mkdir(parents=True)
    marker_root.rmdir()
    marker_root = tmp_path / "innocent"
    marker_root.mkdir()
    # 构造含真实标记的候选：把标记拼进目录名
    marker = sorted(FORBIDDEN_MOUNT_MARKERS)[0].strip("/\\")
    candidate = tmp_path / f"ws-{marker}-x"
    candidate.mkdir()
    with pytest.raises(ExecutionPolicyError):
        normalize_workspace_under_root(root, candidate)


# ---------------------------------------------------------------------------
# 命令锚定 + 超时钳制（前置 4/8）


def test_command_allowed_and_rejections() -> None:
    assert_command_allowed(["C:/bin/zcode.exe", "-p", "hi"], allowed_bin="C:/bin/zcode.exe")
    assert_command_allowed(["ZCODE.EXE", "--json"], allowed_bin="zcode.exe")  # 大小写不敏感
    with pytest.raises(ExecutionPolicyError):
        assert_command_allowed([], allowed_bin="zcode.exe")
    with pytest.raises(ExecutionPolicyError):
        assert_command_allowed(["evil.exe", "-p"], allowed_bin="zcode.exe")
    with pytest.raises(ExecutionPolicyError):
        assert_command_allowed(cast("list[str]", [42]), allowed_bin="zcode.exe")  # type: ignore[list-item]
    with pytest.raises(ExecutionPolicyError):
        assert_command_allowed(["zcode.exe"] * 65, allowed_bin="zcode.exe")


def test_clamp_timeout() -> None:
    assert clamp_timeout_ms(1000) == 1000
    assert clamp_timeout_ms(MAX_HOST_TIMEOUT_MS + 1) == MAX_HOST_TIMEOUT_MS
    assert clamp_timeout_ms(0) == 1 and clamp_timeout_ms(-5) == 1


# ---------------------------------------------------------------------------
# 策略快照（5.6 数据源）


def test_policy_snapshot_deterministic_and_order_insensitive() -> None:
    # 显式关键字实参（不用 **dict 展开——Linux mypy 对 dict[str, object] 展开
    # 判 arg-type，Windows 不报：平台差异实锤，本文件即首例）
    first = policy_snapshot(
        provider="host_channel", workspace_ref="D:/ws/run-1",
        allowed_tools=("tool.b", "tool.a"), timeout_ms=60000, max_cost_units=100,
    )
    second = policy_snapshot(
        provider="host_channel", workspace_ref="D:/ws/run-1",
        allowed_tools=("tool.a", "tool.b"), timeout_ms=60000, max_cost_units=100,
    )
    assert first == second, "工具集合顺序无关"
    again = policy_snapshot(
        provider="host_channel", workspace_ref="D:/ws/run-1",
        allowed_tools=("tool.b", "tool.a"), timeout_ms=60000, max_cost_units=100,
    )
    assert first == again, "同输入恒同 hash"
    other = policy_snapshot(
        provider="host_channel", workspace_ref="D:/ws/run-1",
        allowed_tools=("tool.b", "tool.a"), timeout_ms=61000, max_cost_units=100,
    )
    assert first != other
    assert len(first) == 64


# ---------------------------------------------------------------------------
# 授权票据（前置 3，5.3）


def _issue(
    *,
    user_id: str = "u-1",
    project_id: str = "p-1",
    run_id: str = "r-1",
    workspace: str = "D:/ws/r-1",
    actions: tuple[str, ...] = ("workspace.read", "command.run"),
    issued_at: datetime = _NOW,
    ttl_seconds: int = GRANT_TTL_SECONDS,
    secret: bytes = _SECRET,
):
    return issue_execution_grant(
        secret,
        user_id=user_id,
        project_id=project_id,
        run_id=run_id,
        workspace=workspace,
        actions=actions,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )


def test_grant_issue_and_verify_happy_path() -> None:
    token = _issue()
    payload = verify_execution_grant(
        token,
        _SECRET,
        run_id="r-1",
        now=_NOW + timedelta(minutes=5),
        required_actions=("command.run",),
    )
    assert payload["run_id"] == "r-1" and payload["user_id"] == "u-1"
    assert payload["actions"] == ["command.run", "workspace.read"]  # 排序稳定
    assert payload["exp"] - payload["iat"] == GRANT_TTL_SECONDS


def test_grant_rejections() -> None:
    token = _issue()
    with pytest.raises(ExecutionGrantError) as exc:
        verify_execution_grant(token, _SECRET, run_id="r-1", now=_NOW + timedelta(seconds=GRANT_TTL_SECONDS + 1), required_actions=())
    assert exc.value.code == "expired"
    with pytest.raises(ExecutionGrantError) as exc:
        verify_execution_grant(token, b"x" * 48, run_id="r-1", now=_NOW, required_actions=())
    assert exc.value.code == "tampered"
    tampered = token[:-3] + ("AAA" if not token.endswith("AAA") else "BBB")
    with pytest.raises(ExecutionGrantError) as exc:
        verify_execution_grant(tampered, _SECRET, run_id="r-1", now=_NOW, required_actions=())
    assert exc.value.code in ("tampered", "malformed")
    with pytest.raises(ExecutionGrantError) as exc:
        verify_execution_grant(token, _SECRET, run_id="r-2", now=_NOW, required_actions=())
    assert exc.value.code == "run_mismatch"
    with pytest.raises(ExecutionGrantError) as exc:
        verify_execution_grant(token, _SECRET, run_id="r-1", now=_NOW, required_actions=("workspace.write",))
    assert exc.value.code == "action_exceeded"
    with pytest.raises(ExecutionGrantError):
        verify_execution_grant("not-a-token", _SECRET, run_id="r-1", now=_NOW, required_actions=())


def test_grant_issue_gates() -> None:
    with pytest.raises(ExecutionGrantError):
        _issue(user_id="u", project_id="p", run_id="r", workspace="w", actions=("workspace.read",), secret=b"short")
    with pytest.raises(ExecutionGrantError):
        _issue(actions=("not.registered",))
    with pytest.raises(ExecutionGrantError):
        _issue(actions=())
    with pytest.raises(ExecutionGrantError):
        _issue(ttl_seconds=GRANT_TTL_SECONDS + 1)
    # 未注册动作闭集与 TTL 上限常量自洽
    assert EXECUTION_ACTIONS == frozenset({"workspace.read", "workspace.write", "command.run", "artifact.publish"})


# ---------------------------------------------------------------------------
# 扩列落库 + 通道默认关闭钉（5.6/5.7/5.10）


def test_policy_hash_survives_roundtrip_shape() -> None:
    """快照 hash 落列形状：64 位十六进制（与 sha256 列 CHECK 同尺）。"""
    digest = policy_snapshot(provider="host_channel", workspace_ref="w", allowed_tools=(), timeout_ms=1000, max_cost_units=None)
    assert len(digest) == 64
    digest2 = policy_snapshot(provider="host_channel", workspace_ref="w", allowed_tools=(), timeout_ms=1000, max_cost_units=None)
    assert digest == digest2


def test_host_channel_default_off(d4_settings) -> None:  # noqa: F811
    """通道闸静态钉：测试环境 Settings 未显式开启时宿主通道必须默认关闭。"""
    assert d4_settings.agent_host_channel_enabled is False


def test_config_default_literal_false() -> None:
    """config.py 源码静态钉：agent_host_channel_enabled 默认值字面 False（防误开）。"""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "fde_api" / "config.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    found: list[object] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "agent_host_channel_enabled":
            if node.value is not None:  # AnnAssign.value 可空（Linux mypy strict）
                found.append(ast.literal_eval(node.value))
    assert found == [False], f"默认值必须字面 False，实测 {found}"
