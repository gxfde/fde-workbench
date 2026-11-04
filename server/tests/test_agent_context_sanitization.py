"""goal-d4：上下文脱敏渲染器的 CI 脱敏断言（技术实施方案 §5 红线段）。

毒化输入渲染后 grep 盘符路径/凭证模式/禁区词零命中——「gitleaks 旁再加
一条脱敏断言」的服务端落点；禁区词 fail-closed（命中即拒绝发起）。
"""
from __future__ import annotations

import pytest

from fde_api.agents.context import (
    SANDBOX_AGENT_DISCIPLINE,
    SanitizationError,
    redact_patterns,
    render_masked_context,
)


def _render(items=None, **overrides):
    payload = dict(
        project_code="somwyn",
        agent_name="ZCode 沙箱智能体",
        capability="agent.code.write",
        confirmed_items=items if items is not None else [],
    )
    payload.update(overrides)
    return render_masked_context(**payload)


def test_poisoned_inputs_render_with_zero_sensitive_hits() -> None:
    """毒化输入：盘符/令牌/PEM 全被遮蔽，原文零命中；代号放行。"""
    rendered = _render(
        [
            {
                "text": "诊断材料在 C:\\Users\\客户\\机密.docx，密钥 sk-abcdef1234567890",
                "classification": "流程",
                "source_refs": ["src-1"],
                "confirmed": True,
            }
        ],
        template_skeleton="交付计划骨架，路径参照 D:/backup/历史.zip 的结构",
        knowledge_snippets=[
            {
                "id": "kb-1",
                "text": "参考 -----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----",
            }
        ],
    )
    body = rendered.text
    # 盘符路径（两种分隔符）零命中，占位符在位
    assert "C:\\Users" not in body and "D:/backup" not in body
    assert body.count("[REDACTED_PATH]") == 2
    # 令牌/PEM 零命中
    assert "sk-abcdef1234567890" not in body and "[REDACTED_TOKEN]" in body
    assert "BEGIN RSA PRIVATE KEY" not in body and "[REDACTED_KEY]" in body
    # 代号与确认事实放行；纪律与分区在位
    assert "somwyn" in body and "src-1" in body and "诊断材料在" in body
    assert SANDBOX_AGENT_DISCIPLINE in body
    assert "## 已确认业务问题" in body and "## 模板骨架" in body and "## 知识片段" in body
    # 反向账：问题引用集合供产物校验（C-1）对账
    assert rendered.problem_refs == ("src-1",)
    assert rendered.redactions == 4


def test_forbidden_term_fails_closed_before_any_execution() -> None:
    """禁区词（真实客户名等）：任何片段命中 → SanitizationError，run 拒发。"""
    def _expect_forbidden(**kwargs):
        with pytest.raises(SanitizationError) as raised:
            _render(**kwargs)
        assert raised.value.code == "forbidden_term_detected"

    _expect_forbidden(
        confirmed_items=[
            {
                "text": "真实客户全称有限公司希望三年内完成数字化。",
                "classification": "战略",
                "source_refs": ["src-9"],
                "confirmed": True,
            }
        ],
        forbidden_terms=["真实客户全称"],
    )
    # 知识片段同样过闸（任何路径漏进来都拦在落盘前）
    _expect_forbidden(
        confirmed_items=[],
        knowledge_snippets=[{"id": "kb-2", "text": "摘录提到真实客户全称的项目"}],
        forbidden_terms=["真实客户全称"],
    )


def test_unconfirmed_items_never_enter_context() -> None:
    """AI 不得看到未拍板内容：confirmed 非 True 的条目直接丢弃。"""
    rendered = _render(
        [
            {"text": "已确认问题", "classification": "流程", "source_refs": ["a", "b"], "confirmed": True},
            {"text": "未确认的猜测（含 C:\\secret.docx）", "classification": "疑似", "source_refs": ["z"], "confirmed": False},
        ]
    )
    assert "已确认问题" in rendered.text
    assert "未确认的猜测" not in rendered.text and "C:\\secret" not in rendered.text
    assert rendered.problem_refs == ("a", "b")


def test_item_metadata_rendered_and_empty_sections_marked() -> None:
    """severity/module 透出；无确认问题/无骨架/无知识片段时显式标注。"""
    rendered = _render(
        [
            {
                "text": "库存与订单数据割裂",
                "classification": "数据",
                "source_refs": ["ref-7"],
                "confirmed": True,
                "severity": "high",
                "module": "数据集成",
            }
        ]
    )
    assert "severity=high" in rendered.text and "module=数据集成" in rendered.text
    empty = _render([])
    assert "暂无已确认业务问题" in empty.text
    assert "未提供模板骨架" in empty.text and "未检索到知识片段" in empty.text
    assert empty.problem_refs == ()


def test_redact_patterns_handles_plain_text_and_invalid_items() -> None:
    """无敏感内容的文本零改写；非字符串条目 fail-closed。"""
    text, hits = redact_patterns("普通描述文字，无路径无密钥。")
    assert text == "普通描述文字，无路径无密钥。" and hits == 0
    with pytest.raises(SanitizationError) as raised:
        _render([{"text": None, "classification": "x", "source_refs": [], "confirmed": True}])
    assert raised.value.code == "invalid_context_item"


def test_source_refs_pass_through_pattern_masking() -> None:
    """goal-c CR-017：source_refs 与正文同尺——毒化引用（盘符路径）不得原样进
    渲染文本与 problem_refs；良形代号引用（src-1）行为不变。"""
    rendered = _render(
        [
            {
                "text": "诊断依据见引用材料",
                "classification": "数据",
                "source_refs": ["C:\\客户\\材料\\扫描件.pdf", "D:/backup/历史.zip", "src-1"],
                "confirmed": True,
            }
        ]
    )
    body = rendered.text
    # 盘符原文零命中，占位符在位（两条不同盘符引用同遮一个占位符，去重后渲染一处）
    assert "C:\\客户" not in body and "D:/backup" not in body
    assert "[REDACTED_PATH]" in body and "src-1" in body
    # problem_refs 收已遮蔽形态（与产物校验对账同规），良形代号引用原样保留
    assert rendered.problem_refs == ("[REDACTED_PATH]", "src-1")
    assert "src-1" in rendered.problem_refs and "C:\\客户" not in rendered.problem_refs


def test_source_refs_masking_counts_redactions() -> None:
    """CR-017：引用遮蔽计入 redactions（防「引用面漏遮但计数看不出」的回归形态）。"""
    rendered = _render(
        [
            {
                "text": "问题描述",
                "classification": "数据",
                "source_refs": ["C:\\x\\y.pdf"],
                "confirmed": True,
            }
        ]
    )
    assert rendered.redactions == 1


from test_agents_d4_harness import d4_app, d4_client, d4_settings  # noqa: F401  (pytest fixture)


def test_forbidden_term_returns_422_via_service_gate(db_session, d4_client, d4_app, d4_settings) -> None:
    """E2E fail-closed：禁区词经服务闸 → 422 forbidden_term_detected，零 run 落库。"""
    from sqlalchemy import select as _select
    from test_agents_d4_harness import api_client, seed_agent
    from test_document_drafts_api import _persist_project
    from fde_api.agents.models import AgentRun
    d4_app.config["SETTINGS"] = d4_app.config["SETTINGS"].model_copy(
        update={"agent_forbidden_terms": "真实客户全称"}
    )
    leader = api_client(d4_client, db_session, d4_settings, "project_lead")
    project = _persist_project(db_session, leader.user, code="D4TERM")
    from test_goal_d2_s0_closeout import _confirmed_guidance

    _confirmed_guidance(
        db_session,
        project,
        leader.user,
        problems=[{"text": "真实客户全称希望完成数字化", "classification": "战略", "source_refs": ["s1"], "confirmed": True}],
    )
    agent = seed_agent(db_session, d4_settings)
    body = leader.post(f"/api/v1/agents/{agent.id}/run", json={"project_id": project.id, "idempotency_key": "term-1"})
    assert body.status_code == 422
    assert body.json["error"]["code"] == "forbidden_term_detected"
    assert db_session.scalar(_select(AgentRun)) is None  # 零 run 落库（不发起执行）
