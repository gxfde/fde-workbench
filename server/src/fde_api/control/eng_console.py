"""AF1-WP4：工程台短时效两段式 token（docs/ai-fde/13 §7-B，P1 选版 B）。

模式源 = TrustBoard viewer 短时效 token（docs/v3.3/m6/02-trustboard-ui-spec
§2.1 整改修订版）+ 本仓 ``agents/execution_authorization`` 票据先例
（b64url(payload).hmac-sha256）。差异面（工程台 ≠ 客户 viewer）：密钥域独立
（``workbench_eng_signing_key``）、会话绑定签发时点档位（claims.lvl，投影层
再按 DB 实时用户可见性复核）、写代理面只接受会话令牌。

硬纪律（规格 §7-B / 13 §6）：
- 独立密钥域：与 ``jwt_secret`` 相同 → config 校验启动即拒（fail-closed）；
  空 = 工程台面整体关闭（路由层 403 ``eng_disabled``）。
- 两段式：交接令牌（默认 30 分钟、硬上限 60 分钟、一次性消费、fragment
  承载 ``/eng/console#/?d=``，禁查询串）+ 会话令牌（TTL ≤8h，可反复用至
  过期/吊销，不消费）。
- 交接令牌 jti 派生自会话 jti（HMAC）——按会话吊销时派生的交接链接一并失效
  （viewer WP6-R4 验收 21 同款语义）。
- 消费/绑定/吊销标记落 ``eng_token_marks``（jti 派生 key）——token 明文零落库。
- 过期/吊销/重放对客户/工程人员一律客户语（不透出内部错误码/堆栈）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime
from typing import Any, Protocol

ENG_SESSION_TTL = 8 * 3600
ENG_HANDOVER_TTL = 30 * 60
ENG_HANDOVER_TTL_MAX = 60 * 60
SESSION_HEADER = "X-Eng-Session"

_DELIVERY_PREFIX = "/eng/console#/?d="


class EngConsoleError(Exception):
    """工程台票据拒绝（code：malformed/expired/revoked/handover_used/disabled）。"""

    def __init__(self, code: str, message: str, status: int = 403):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class MarksRepo(Protocol):
    """``eng_token_marks`` 的最小访问面（测试用内存替身同签名）。"""

    def get(self, key: str) -> dict[str, Any] | None: ...

    def put(self, key: str, kind: str, client_id: str | None = None) -> None: ...


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as error:
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。") from error


def _signature(secret: str, payload_segment: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_segment.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _sign_claims(secret: str, claims: dict[str, Any]) -> str:
    segment = _b64url_encode(
        json.dumps(claims, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    return f"{segment}.{_signature(secret, segment)}"


def derived_handover_jti(secret: str, session_jti: str) -> str:
    """交接令牌 jti = HMAC(session jti)——吊销时可从会话推导派生链接。"""
    digest = hmac.new(secret.encode("utf-8"), f"handover-jti|{session_jti}".encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:32]


def _mark_key(secret: str, org_id: str, jti: str, purpose: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{purpose}|{org_id}|{jti}".encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:48]


def mint_eng_tokens(
    secret: str,
    *,
    user_id: str,
    org_id: str | None,
    level: str,
    now: datetime,
    project_id: str | None = None,
    handover_ttl: int = ENG_HANDOVER_TTL,
    session_ttl: int = ENG_SESSION_TTL,
) -> dict[str, str]:
    """签发两段式：会话令牌 + 交接令牌（交付链接 fragment 承载）。"""
    if not secret:
        raise EngConsoleError("disabled", "工程台未启用：未配置独立签名密钥域。", 503)
    if handover_ttl <= 0 or handover_ttl > ENG_HANDOVER_TTL_MAX:
        raise ValueError(f"交接令牌 TTL 超出硬上限（1..{ENG_HANDOVER_TTL_MAX} 秒）。")
    if session_ttl <= 0 or session_ttl > ENG_SESSION_TTL:
        raise ValueError(f"会话令牌 TTL 须为 1..{ENG_SESSION_TTL} 秒。")
    issued = int(now.timestamp())
    session_jti = uuid.uuid4().hex
    session_claims = {
        "kind": "eng-session", "uid": user_id, "org": org_id, "lvl": level,
        "project": project_id, "jti": session_jti,
        "iat": issued, "exp": issued + session_ttl,
    }
    handover_claims = {
        "kind": "eng-handover", "uid": user_id, "org": org_id, "lvl": level,
        "project": project_id, "jti": derived_handover_jti(secret, session_jti),
        "sjti": session_jti, "sjiat": issued, "sexp": issued + session_ttl,
        "iat": issued, "exp": issued + handover_ttl,
    }
    token = _sign_claims(secret, session_claims)
    handover_token = _sign_claims(secret, handover_claims)
    return {"token": token, "handover_token": handover_token, "delivery_path": f"{_DELIVERY_PREFIX}{handover_token}"}


def parse_eng_token(
    token: str,
    secret: str,
    *,
    now: datetime,
    marks: MarksRepo | None = None,
) -> dict[str, Any]:
    """验签 + 过期 + 吊销（marks 提供时）；返回 claims，不消费。"""
    if not secret:
        raise EngConsoleError("disabled", "工程台未启用：未配置独立签名密钥域。", 503)
    parts = token.split(".")
    if len(parts) != 2:
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。")
    segment, signature = parts
    # 票据段恒 ASCII（b64url 闭集）：非 ASCII 输入在签名比较前即拒——
    # 否则 _signature 的 ascii encode 抛 UnicodeEncodeError 变 500（评审 edge #1）
    if not (segment.isascii() and signature.isascii()):
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。")
    if not hmac.compare_digest(_signature(secret, segment), signature):
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。")
    try:
        claims = json.loads(_b64url_decode(segment).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。") from error
    if not isinstance(claims, dict):
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。")
    raw_exp = claims.get("exp")
    exp_value = int(raw_exp) if isinstance(raw_exp, (int, float)) else 0
    if exp_value < int(now.timestamp()):
        raise EngConsoleError("expired", "工程台授权已过期，请从 Workbench 重新出链。", 403)
    if marks is not None:
        org = str(claims.get("org") or "")
        for jti in filter(None, (claims.get("jti"), claims.get("sjti"))):
            if marks.get(_mark_key(secret, org, str(jti), "revoke")):
                raise EngConsoleError(
                    "revoked", "工程台授权已被回收，请向交付团队索取新的访问链接。", 403
                )
    return claims


def consume_handover(
    secret: str,
    claims: dict[str, Any],
    marks: MarksRepo,
    *,
    client_id: str,
    now: datetime,
) -> str:
    """交接令牌一次性消费：首用落消费标记并回签发时那枚会话令牌；
    同客户端重试放行（网络抖动不锁死）；异客户端重放一律拒（客户语）。"""
    if claims.get("kind") != "eng-handover":
        raise EngConsoleError("malformed", "工程台访问凭证无效，请向交付团队索取新的访问链接。")
    org = str(claims.get("org") or "")
    handover_jti = str(claims.get("jti") or "")
    # 吊销闸（会话 jti 或派生交接 jti 命中即拒——交接链接不可再用）
    for jti in filter(None, (handover_jti, claims.get("sjti"))):
        if marks.get(_mark_key(secret, org, str(jti), "revoke")):
            raise EngConsoleError(
                "revoked", "工程台授权已被回收，请向交付团队索取新的访问链接。", 403
            )
    consume_key = _mark_key(secret, org, handover_jti, "consume")
    existing = marks.get(consume_key)
    if existing is not None:
        if existing.get("client_id") != client_id:
            raise EngConsoleError(
                "handover_used", "此访问链接已被使用或已失效，请向交付团队索取新的访问链接。", 403
            )
    else:
        marks.put(consume_key, "consume", client_id)
    session_claims = {
        "kind": "eng-session", "uid": claims.get("uid"), "org": claims.get("org"),
        "lvl": claims.get("lvl"), "project": claims.get("project"),
        "jti": claims.get("sjti"), "iat": claims.get("sjiat"), "exp": claims.get("sexp"),
    }
    return _sign_claims(secret, session_claims)


def revoke_eng_session(
    secret: str,
    marks: MarksRepo,
    *,
    org_id: str | None,
    session_jti: str,
) -> None:
    """按会话 jti 吊销：会话与其派生的交接链接同时失效。

    标记落库时点由 ``EngTokenMark.created_at``（TimestampMixin）承载。
    """
    marks.put(_mark_key(secret, str(org_id or ""), session_jti, "revoke"), "revoke")
    marks.put(
        _mark_key(secret, str(org_id or ""), derived_handover_jti(secret, session_jti), "revoke"),
        "revoke",
    )
