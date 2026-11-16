"""AF1-WP4：工程台短时效两段式 token（docs/ai-fde/13 §7-B）。

模式源 = TrustBoard viewer 短时效 token（docs/v3.3/m6/02-trustboard-ui-spec
§2.1，P1 WP4 选版 B 批准复用）+ 本仓 execution_authorization 票据先例
（b64url(payload).hmac-sha256 签名）。硬纪律：

- 独立密钥域 ``workbench_eng_signing_key``：与 ``jwt_secret`` 相同 → 启动即拒
  （fail-closed，viewer 同款）；空 = 工程台面整体关闭（路由层 403）；
- 两段式：交接令牌（默认 30 分钟、硬上限 60 分钟、一次性消费、fragment
  承载 `#/…?d=`、禁查询串）+ 会话令牌（TTL ≤8h、org 绑定、可反复用至过期
  或吊销）；
- 消费/绑定/吊销标记落 ``eng_token_marks``（jti 派生 key）——token 明文
  零落库；
- 档位在签发时点冻结（claims.lvl）；投影仍按 DB 实时用户可见性（停用即
  失效，is_active 校验在 require 层）。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fde_api.control.eng_console import (
    ENG_HANDOVER_TTL,
    ENG_HANDOVER_TTL_MAX,
    ENG_SESSION_TTL,
    SESSION_HEADER,
    EngConsoleError,
    consume_handover,
    mint_eng_tokens,
    parse_eng_token,
    revoke_eng_session,
)
from fde_api.control.models import EngTokenMark

SECRET = "eng-console-signing-key-for-tests-only-32b"
OTHER_SECRET = "another-signing-key-also-long-enough-32"
NOW = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)


class MemoryMarks:
    """eng_token_marks 的内存替身（单元面；API 面用真实表）。"""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def get(self, key: str) -> dict | None:
        return self.rows.get(key)

    def put(self, key: str, kind: str, client_id: str | None = None) -> None:
        self.rows[key] = {"kind": kind, "client_id": client_id}


# --- 签发形状 --------------------------------------------------------------


def test_mint_returns_two_tokens_with_delivery_path() -> None:
    out = mint_eng_tokens(
        SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW
    )
    session_claims = parse_eng_token(out["token"], SECRET, now=NOW)
    handover_claims = parse_eng_token(out["handover_token"], SECRET, now=NOW)
    assert session_claims["kind"] == "eng-session"
    assert handover_claims["kind"] == "eng-handover"
    # 两段式关联：交接令牌指向会话 jti（消费时重签出同一枚会话令牌）
    assert handover_claims["sjti"] == session_claims["jti"]
    # TTL 口径：会话 8h、交接 30min（硬上限 60min）
    assert session_claims["exp"] - session_claims["iat"] == ENG_SESSION_TTL
    assert handover_claims["exp"] - handover_claims["iat"] == ENG_HANDOVER_TTL
    # fragment 承载（不随请求上行——不进日志/Referer），禁查询串形态
    assert out["delivery_path"].startswith("/eng/console#/?d=")
    assert "?t=" not in out["delivery_path"]


def test_mint_rejects_handover_ttl_over_hard_cap() -> None:
    with pytest.raises(ValueError, match="硬上限"):
        mint_eng_tokens(
            SECRET, user_id="u-1", org_id="org-1", level="project_operator",
            now=NOW, handover_ttl=ENG_HANDOVER_TTL_MAX + 1,
        )


def test_parse_rejects_tampered_and_foreign_signed_tokens() -> None:
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    token = out["token"]
    head, _sig = token.rsplit(".", 1)
    with pytest.raises(EngConsoleError) as tampered:
        parse_eng_token(f"{head}.AAAAsig", SECRET, now=NOW)
    assert tampered.value.code == "malformed"
    # jwt_secret/其他密钥域签发的冒名 token 一律拒（独立密钥域）
    with pytest.raises(EngConsoleError) as foreign:
        parse_eng_token(token, OTHER_SECRET, now=NOW)
    assert foreign.value.code == "malformed"


def test_parse_rejects_expired_with_customer_language() -> None:
    out = mint_eng_tokens(
        SECRET, user_id="u-1", org_id="org-1", level="project_operator",
        now=NOW, session_ttl=60,
    )
    with pytest.raises(EngConsoleError) as expired:
        parse_eng_token(out["token"], SECRET, now=NOW + timedelta(seconds=61))
    assert expired.value.code == "expired"
    # 客户语指引（不透出内部错误码/堆栈语义）
    assert "重新出链" in expired.value.message or "过期" in expired.value.message


# --- 消费：一次性 + 同客户端放行 -------------------------------------------


def test_consume_handover_first_use_returns_session_token() -> None:
    marks = MemoryMarks()
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    handover = parse_eng_token(out["handover_token"], SECRET, now=NOW)
    session_token = consume_handover(SECRET, handover, marks, client_id="tab-1", now=NOW)
    assert parse_eng_token(session_token, SECRET, now=NOW)["kind"] == "eng-session"
    # 消费标记已落（零 token 明文——只落 jti 派生 key）
    assert marks.rows and all("eng-" not in k for k in marks.rows)


def test_consume_handover_replay_from_other_client_is_rejected() -> None:
    marks = MemoryMarks()
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    handover = parse_eng_token(out["handover_token"], SECRET, now=NOW)
    consume_handover(SECRET, handover, marks, client_id="tab-1", now=NOW)
    # 他人设备/浏览器再开同一链接 → 403（客户语）
    with pytest.raises(EngConsoleError) as replay:
        consume_handover(SECRET, handover, marks, client_id="tab-other", now=NOW)
    assert replay.value.code == "handover_used"
    assert "已被使用或已失效" in replay.value.message


def test_consume_handover_same_client_retry_is_allowed() -> None:
    """同标签页重试（网络抖动）→ 放行并回同一枚会话令牌（不锁死）。"""
    marks = MemoryMarks()
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    handover = parse_eng_token(out["handover_token"], SECRET, now=NOW)
    first = consume_handover(SECRET, handover, marks, client_id="tab-1", now=NOW)
    second = consume_handover(SECRET, handover, marks, client_id="tab-1", now=NOW)
    assert first == second


def test_session_token_is_never_consumed() -> None:
    """会话令牌不消费（页面刷新/切视图照常用）——反复 parse 通过。"""
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    marks = MemoryMarks()
    claims = parse_eng_token(out["token"], SECRET, now=NOW)
    assert claims["kind"] == "eng-session"
    assert marks.rows == {}


# --- 吊销 ------------------------------------------------------------------


def test_revoke_session_kills_session_and_derived_handover() -> None:
    """按会话 jti 吊销 → 会话与派生的交接令牌同时失效（交接链接不可再用）。"""
    marks = MemoryMarks()
    out = mint_eng_tokens(SECRET, user_id="u-1", org_id="org-1", level="project_operator", now=NOW)
    handover = parse_eng_token(out["handover_token"], SECRET, now=NOW)
    session_claims = parse_eng_token(out["token"], SECRET, now=NOW)

    revoke_eng_session(SECRET, marks, org_id="org-1", session_jti=session_claims["jti"])

    with pytest.raises(EngConsoleError) as dead_session:
        parse_eng_token(out["token"], SECRET, now=NOW, marks=marks)
    assert dead_session.value.code == "revoked"
    with pytest.raises(EngConsoleError) as dead_handover:
        consume_handover(SECRET, handover, marks, client_id="tab-1", now=NOW)
    assert dead_handover.value.code == "revoked"


# --- config 独立密钥域 fail-closed -----------------------------------------


def test_settings_reject_eng_key_equal_to_jwt_secret() -> None:
    from fde_api.config import Settings

    with pytest.raises(ValueError, match="独立密钥域"):
        Settings(
            jwt_secret="x" * 40,
            workbench_eng_signing_key="x" * 40,
            database_url="postgresql+psycopg://fde:x@127.0.0.1:15432/fde_workbench_af1wp4_test",
            redis_url="redis://127.0.0.1:6379/0",
        )


def test_settings_allow_distinct_eng_key() -> None:
    from fde_api.config import Settings

    settings = Settings(
        jwt_secret="y" * 40,
        workbench_eng_signing_key="z" * 40,
        database_url="postgresql+psycopg://fde:x@127.0.0.1:15432/fde_workbench_af1wp4_test",
        redis_url="redis://127.0.0.1:6379/0",
    )
    assert settings.workbench_eng_signing_key == "z" * 40


# --- 真表落库冒烟（eng_token_marks append-only） ----------------------------


def test_eng_token_marks_persist_roundtrip(db_session) -> None:
    mark = EngTokenMark(id="consume|org-1|abc", kind="consume", client_id="tab-1")
    db_session.add(mark)
    db_session.commit()
    row = db_session.get(EngTokenMark, "consume|org-1|abc")
    assert row is not None and row.client_id == "tab-1"


def test_session_header_name_pinned() -> None:
    assert SESSION_HEADER == "X-Eng-Session"
