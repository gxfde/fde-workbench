"""help_fetch tool: the AI assistant's read-only access to the bundled manual.

The manual ships in the API image (fde_api/control/bundled/help_manual.md);
without it the server-side model has no grounding for workflow questions.
"""
from __future__ import annotations

import json

import pytest

from fde_api.auth.models import User
from fde_api.control import help_bundle
from fde_api.control.ai_tool_loop import READ_ONLY_TOOLS, tool_definitions
from fde_api.control.mcp_gateway import TOOLS, call_tool
from fde_api.control.service import ControlServiceError
from pathlib import Path


_BUNDLED = Path(__file__).resolve().parents[1] / "src" / "fde_api" / "control" / "bundled" / "help_manual.md"
_HELP_PAGE = Path(__file__).resolve().parents[2] / "desktop" / "src" / "renderer" / "src" / "help" / "HelpPage.tsx"
pytestmark = pytest.mark.skipif(not _BUNDLED.exists(), reason="bundled help manual not shipped with this checkout")


@pytest.fixture
def ai_user(app, db_session):
    user = User(
        username=f"help-fetch-{id(db_session)}",
        display_name="help-fetch",
        password_hash="unused",
        role="admin",
        is_active=True,
        must_change_password=False,
    )
    db_session.add(user)
    db_session.commit()
    return user


def test_help_tool_is_registered_and_read_only():
    description, capability, properties, effect, risk = TOOLS["help_fetch"]
    assert effect == "read" and risk == 0
    assert capability is None
    assert set(properties) == {"heading", "offset"}
    assert "help_fetch" in READ_ONLY_TOOLS


def test_help_fetch_is_offered_to_every_ai_level():
    names = {item["function"]["name"] for item in tool_definitions([])}
    assert "help_fetch" in names


def test_gates_read_is_registered_capability_gated_and_read_only():
    description, capability, properties, effect, risk = TOOLS["gates_read"]
    assert effect == "read" and risk == 0
    assert capability == "project.read"
    assert set(properties) == {"project_id"}
    assert "gates_read" in READ_ONLY_TOOLS
    with_capability = {item["function"]["name"] for item in tool_definitions(["project.read"])}
    assert "gates_read" in with_capability
    without_capability = {item["function"]["name"] for item in tool_definitions([])}
    assert "gates_read" not in without_capability


def test_help_fetch_lists_sections_on_head_request(app, db_session, ai_user):
    """no heading → manual head with the section index attached."""
    rows = help_bundle.section_index()
    assert rows and all({"number", "title", "characters"} <= set(r) for r in rows)

    claims = {"sub": ai_user.id, "capabilities": []}
    result = call_tool(db_session, user=ai_user, claims=claims, allowed=[],
                       name="help_fetch", arguments={})
    payload = json.loads(json.dumps(result))
    assert payload["source"] == "workbench_help_manual"
    assert payload["heading"] == ""
    assert payload["total_characters"] > 5000
    assert [s["title"] for s in payload["sections"]] == [r["title"] for r in rows]
    assert "故障排查" in "".join(s["title"] for s in payload["sections"])


def test_help_fetch_locates_a_section_by_keyword(app, db_session, ai_user):
    result = call_tool(db_session, user=ai_user, claims={"sub": ai_user.id, "capabilities": []},
                       allowed=[], name="help_fetch", arguments={"heading": "故障排查"})
    assert result["heading"]
    assert "故障排查" in str(result["heading"])
    assert "###" in str(result["text"]) or "1." in str(result["text"])
    assert result["next_offset"] is None  # section fits one window


def test_help_fetch_pages_with_next_offset(app, db_session, ai_user):
    head = call_tool(db_session, user=ai_user, claims={"sub": ai_user.id, "capabilities": []},
                     allowed=[], name="help_fetch", arguments={})
    first_window = len(head["text"])
    paged = call_tool(db_session, user=ai_user, claims={"sub": ai_user.id, "capabilities": []},
                      allowed=[], name="help_fetch", arguments={"offset": first_window})
    assert paged["offset"] == first_window
    assert paged["next_offset"] in (None, head["total_characters"] - first_window + (head["total_characters"] - first_window))
    assert paged["next_offset"] is not None or paged["offset"] + len(paged["text"]) >= paged["total_characters"]


def test_help_fetch_rejects_bad_offset(app, db_session, ai_user):
    with pytest.raises(ControlServiceError) as caught:
        call_tool(db_session, user=ai_user, claims={"sub": ai_user.id, "capabilities": []},
                  allowed=[], name="help_fetch", arguments={"offset": -1})
    assert caught.value.code == "invalid_request"


def test_unmatched_heading_falls_back_to_manual_head(app, db_session, ai_user):
    result = call_tool(db_session, user=ai_user, claims={"sub": ai_user.id, "capabilities": []},
                      allowed=[], name="help_fetch", arguments={"heading": "不存在的章节XYZ"})
    assert result["offset"] == 0
    assert result["heading"] == ""


def test_section_index_reports_every_manual_section(app):
    titles = [entry["title"] for entry in help_bundle.section_index()]
    # The bundled manual's fixed table of contents (14 numbered sections + 1
    # unnumbered somwyn walkthrough between §4 and §5).
    assert len(titles) >= 15
    assert any("门禁" in t for t in titles)
    assert any("报价收款" in t or "标签页" in t for t in titles)


def test_bundled_manual_and_ui_help_page_stay_in_sync():
    """UI 使用帮助的每个主题都必须能在服务端内置手册里检索到。

    2026-10「实操示例：证据文件怎么写（somwyn 样板）」只写在 HelpPage、内置手册漏收，
    help_fetch 对该话题零命中。此后任一侧新增章节必须同步另一侧，否则本测试拦截。
    """
    if not _HELP_PAGE.exists():
        pytest.skip("desktop help page not present in this checkout")
    page_text = _HELP_PAGE.read_text("utf-8")
    manual_text = _BUNDLED.read_text("utf-8")
    topics = [
        "开始前", "角色与权限", "项目工作台", "门禁", "实操示例", "somwyn",
        "哈希清单", "隐私铁律", "报价收款", "集成桥", "任务中心",
        "AI Server 对话", "管理页", "故障排查", "已知功能缺口", "发布与升级",
    ]
    for topic in topics:
        assert topic in page_text, f"UI 使用帮助缺少主题：{topic}"
        assert topic in manual_text, f"内置手册缺少主题（help_fetch 将检索不到）：{topic}"


def test_manual_gate_sop_mapping_matches_seeds():
    """手册里的 G↔S 对应必须与 seeds/gates.json 的 node_key 一致。"""
    gates = json.loads(
        (Path(__file__).resolve().parents[1] / "seeds" / "gates.json").read_text("utf-8")
    )["gates"]
    manual_text = _BUNDLED.read_text("utf-8")
    assert gates
    for gate in gates:
        pair = f"{gate['gate_key']}↔{gate['node_key']}"
        assert pair in manual_text, f"内置手册缺少门禁↔SOP 阶段对应：{pair}"
