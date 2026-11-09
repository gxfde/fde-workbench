"""短期执行授权票据的服务层接线（V3.1 任务书 §9 前置 3；N1 首跑补码轮，2026-11-09）。

P1-1 实施轮落了**纯函数**（``execution_authorization.py`` 的
``issue_execution_grant`` / ``verify_execution_grant``），但**生产零调用方**——
5.10 闸未过故 HTTP 发行面不建（避免「结构存在但永远 409」的死面，AGENTS
已预告「随通道开放轮落地」）。D-1 拍板开闸（2026-11-09）后，本模块把
**发行 + 校验双接线**落到宿主通道执行路径：

- **发行**：run 发起（人工动作——``start_run`` 已过项目权限闸）时，为该 run
  签一张短期票据，绑定 **用户 / 项目 / Run / 工作目录 / 允许动作**，TTL 15min
  （``GRANT_TTL_SECONDS``）；
- **校验**：**spawn 之前**必须校验通过（票据绑定 ``run_id``、动作集合覆盖、
  未过期、签名恒比较），否则**拒绝执行**——不 spawn、不计费、落 L2；
- **密钥**：自 ``FDE_JWT_SECRET`` **域分离派生**
  （``sha256("fde-agent-execution-grant-v1:" + secret)``）——不新增配置项、
  不落盘、不进 argv/env/日志（前置 9）；派生密钥与 JWT 签名密钥不同钥。

**票据不是「第二道人工闸」**：人工授权点仍是 ``start_run`` 本身（发起人已过
权限闸与能力闸）；票据提供的是**绑定约束与短 TTL**（run ↔ 工作目录 ↔ 动作
集合）与**可审计的授权指纹**（``agent_runs.authorization_id`` 落 sha256
指纹，**不落明文票据**）。§9 目标里的 HTTP 发行面
（``POST /agents/runs/{id}/authorize-execution``）**仍未建**——留待独立的
人工复核轮，避免死面；本模块**不代拍板**、不新增自动放行路径。
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from fde_api.agents.execution_authorization import (
    EXECUTION_ACTIONS,
    ExecutionGrantError,
    issue_execution_grant,
    verify_execution_grant,
)

# 域分离前缀——派生密钥与 JWT 签名密钥不同钥（密钥混用禁令）。
GRANT_SECRET_DOMAIN = b"fde-agent-execution-grant-v1:"

# 宿主通道执行所需的最小动作集合：读任务书 → 写产物 → 执行命令。
# **不含** artifact.publish——产物入库由平台侧 ``_finalize`` 完成，
# 不是被 spawn 的 zcode 进程的动作（最小权限：多给即少给）。
HOST_CHANNEL_ACTIONS: tuple[str, ...] = (
    "workspace.read",
    "workspace.write",
    "command.run",
)


def derive_grant_secret(jwt_secret: str) -> bytes:
    """自 JWT 密钥派生票据签名密钥（sha256 域分离，32 字节）。

    纯函数；``jwt_secret`` 为空或过短时不静默降级——调用方须传入已配置的
    密钥（``Settings.jwt_secret`` 有 ``min_length=32`` 约束）。
    """
    if not jwt_secret:
        raise ExecutionGrantError("malformed", "票据签名密钥为空（未配置 FDE_JWT_SECRET）。")
    return hashlib.sha256(GRANT_SECRET_DOMAIN + jwt_secret.encode("utf-8")).digest()


def issue_run_grant(
    *,
    jwt_secret: str,
    user_id: str,
    project_id: str,
    run_id: str,
    workspace: str,
    actions: tuple[str, ...] = HOST_CHANNEL_ACTIONS,
    issued_at: datetime | None = None,
) -> str:
    """为一次 run 签发短期授权票据（绑定五要素）。"""
    unknown = set(actions) - EXECUTION_ACTIONS
    if unknown:
        raise ExecutionGrantError("malformed", f"未注册动作：{'、'.join(sorted(unknown))}。")
    return issue_execution_grant(
        derive_grant_secret(jwt_secret),
        user_id=user_id,
        project_id=project_id,
        run_id=run_id,
        workspace=workspace,
        actions=list(actions),
        issued_at=issued_at or datetime.now(UTC),
    )


def verify_run_grant(
    *,
    jwt_secret: str,
    token: str,
    run_id: str,
    required_actions: tuple[str, ...] = HOST_CHANNEL_ACTIONS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """校验票据（形状 → 签名 → 过期 → run 绑定 → 动作覆盖）。"""
    return verify_execution_grant(
        token,
        derive_grant_secret(jwt_secret),
        run_id=run_id,
        now=now or datetime.now(UTC),
        required_actions=list(required_actions),
    )


def grant_fingerprint(token: str) -> str:
    """票据指纹（sha256 hex，64 字符）——供 ``agent_runs.authorization_id`` 留痕。

    **只存指纹不存票据本体**：票据是能力凭证，落到日志或通用列会扩大暴露面
    （红线：凭据只经进程环境内存管道、不落盘不进 argv）。
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def authorize_host_run(
    *,
    jwt_secret: str,
    user_id: str,
    project_id: str,
    run_id: str,
    workspace: str,
    session_factory: Any,
) -> str:
    """宿主 run 执行授权三步合一：发行 → spawn 前校验 → 落授权指纹。

    校验失败抛 ``ExecutionGrantError``——调用方（``agents/service``）映射为
    503 + L2 + 零计费，且**未 spawn**（fail-closed 顺序由本函数保证：校验
    在任何外部副作用之前）。通过后把 ``agent_runs.authorization_id`` 落
    **指纹**（sha256，非票据本体）、``workspace_ref`` 落归一化工作目录。

    （自 ``agents/service.py`` 拆出：热点文件预算闸「只许拆、不许长」，
    2026-11-09。）
    """
    token = issue_run_grant(
        jwt_secret=jwt_secret,
        user_id=user_id,
        project_id=project_id,
        run_id=run_id,
        workspace=workspace,
    )
    verify_run_grant(jwt_secret=jwt_secret, token=token, run_id=run_id)
    fingerprint = grant_fingerprint(token)
    from fde_api.agents.models import AgentRun

    with session_factory() as session, session.begin():
        run_row = session.get(AgentRun, run_id)
        if run_row is not None:
            run_row.authorization_id = fingerprint
            run_row.workspace_ref = workspace[:255]
    return fingerprint


__all__ = [
    "GRANT_SECRET_DOMAIN",
    "HOST_CHANNEL_ACTIONS",
    "authorize_host_run",
    "derive_grant_secret",
    "grant_fingerprint",
    "issue_run_grant",
    "verify_run_grant",
]
