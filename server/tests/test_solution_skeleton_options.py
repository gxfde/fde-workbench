"""T-A5 方案骨架模板：方案三选项 + 取舍 + 明确不做 + 验收标准（可导出）。

台账验收口径：「三选项 + 取舍 + out_of_scope + 验收标准四段齐备且可导出」。
本文件把这四段拆成独立用例钉住，避免后续模板改动把任一段悄悄丢掉。

路径口径（实施轮实测）：
- 桌面「生成骨架」按钮打的是 `POST /api/v1/projects/{id}/solutions/skeleton`
  （`desktop/src/renderer/src/solutions/SolutionDesign.tsx:89`）⇒ 本条覆盖的就是
  用户实际拿到的骨架，不是旁路产物。
- `server/src/fde_api/workflows/compiler.py:compile_delivery_preview`（本体编译路径）
  **无任何生产调用方**（全仓仅 `server/tests/test_delivery_compiler.py` 引用）⇒
  不在本条范围，不改（免得给未接线路径埋一套没人看的文案）。
"""
import pytest
from sqlalchemy import select

from test_document_drafts_api import (
    _persist_doc_template,
    _persist_project,
    authorized_client_factory,  # noqa: F401  (leader 夹具依赖)
    leader_client,  # noqa: F401  (pytest fixture)
)
from test_goal_d2_s0_closeout import _confirmed_guidance
from fde_api.documents.models import ProjectDocumentVersion
from fde_api.guidance.models import PresurveyIntake


OUT_OF_SCOPE_TEXT = "本轮不含仓储机器人"
OPTIONS_HEADING = "## 方案选项与取舍"
OUT_OF_SCOPE_HEADING = "## 明确不做（本阶段不包含）"


def _skeleton(db_session, leader_client, code, *, out_of_scope=()):
    """落一个「有 confirmed 指引」的项目，返回其骨架响应体。"""
    project = _persist_project(db_session, leader_client.user, code=code)
    db_session.add(PresurveyIntake(
        project_id=project.id, industry="零售连锁", interview_mode="onsite",
        updated_by_user_id=leader_client.user.id,
    ))
    db_session.commit()
    _confirmed_guidance(
        db_session, project, leader_client.user,
        problems=({"text": "门店巡检靠人工", "classification": "customer_stated", "source_refs": [], "confirmed": True},),
        success=({"text": "巡检覆盖率≥90%", "classification": "human_added", "source_refs": [], "confirmed": True},),
        out_of_scope=out_of_scope,
    )
    response = leader_client.post(f"/api/v1/projects/{project.id}/solutions/skeleton", json={})
    assert response.status_code == 201, response.json
    return project, response.json["data"]


def test_skeleton_has_three_options_and_tradeoff_placeholders(db_session, leader_client):
    """三选项 + 取舍：售前从零起草前先有骨架位，四个占位行必须齐备。"""
    _project, item = _skeleton(db_session, leader_client, "TA5-OPTIONS")
    design = item["design_markdown"]
    assert OPTIONS_HEADING in design
    assert "- 选项 A：" in design and "- 选项 B：" in design and "- 选项 C：" in design
    assert "- 取舍：" in design
    # 占位行必须带「待补」提示，否则人工分不清「已定」与「待写」。
    for marker in ("选项 A：待补", "选项 B：待补", "选项 C：待补", "取舍：待补"):
        assert marker in design, f"缺占位提示：{marker}"


def test_skeleton_has_explicit_out_of_scope_section_and_keeps_risks_prefix(db_session, leader_client):
    """「明确不做」独立成段（out_of_scope 单独可见），risks 段既有前缀不回归。"""
    _project, item = _skeleton(
        db_session, leader_client, "TA5-OUTOFSCOPE",
        out_of_scope=({"text": OUT_OF_SCOPE_TEXT, "classification": "customer_stated", "source_refs": [], "confirmed": True},),
    )
    design = item["design_markdown"]
    assert OUT_OF_SCOPE_HEADING in design
    assert OUT_OF_SCOPE_TEXT in design
    # 独立成段后不再重复 risks 段的「本阶段不包含：」前缀——重复一遍就是噪音。
    assert f"{OUT_OF_SCOPE_HEADING}\n- {OUT_OF_SCOPE_TEXT}" in design
    # 既有契约：risks 段仍带「本阶段不包含」前缀（goal-d2 用例钉住三类前缀同段）。
    assert "本阶段不包含" in item["risks_dependencies"]
    # 段前留空行：售前在 textarea 里直接改原始 markdown，空行是可扫读性的实际成本。
    assert f"\n\n{OUT_OF_SCOPE_HEADING}\n" in design
    assert f"\n\n{OPTIONS_HEADING}\n" in design


def test_skeleton_section_order_places_options_before_path_and_out_of_scope_last(db_session, leader_client):
    """段序固定：方案设想 → 方案选项与取舍 → 实施路径 → 明确不做。"""
    _project, item = _skeleton(
        db_session, leader_client, "TA5-ORDER",
        out_of_scope=({"text": OUT_OF_SCOPE_TEXT, "classification": "customer_stated", "source_refs": [], "confirmed": True},),
    )
    design = item["design_markdown"]
    positions = [
        design.index("## 方案设想（待人工修订）"),
        design.index(OPTIONS_HEADING),
        design.index("## 实施路径（待人工修订）"),
        design.index(OUT_OF_SCOPE_HEADING),
    ]
    assert positions == sorted(positions), f"段序被破坏：{positions}"


def test_skeleton_without_out_of_scope_keeps_placeholder_section(db_session, leader_client):
    """无 out_of_scope 条目时段落不能消失——否则「明确不做」是可选的，违反台账验收。"""
    _project, item = _skeleton(db_session, leader_client, "TA5-NO-OUTOFSCOPE", out_of_scope=())
    design = item["design_markdown"]
    assert OUT_OF_SCOPE_HEADING in design
    assert "- 待补：本阶段明确不做的范围" in design


def test_skeleton_acceptance_criteria_section_carries_confirmed_criteria(db_session, leader_client):
    """验收标准段：成功标准条目搬运 + 「验收口径待补」标记齐备。"""
    _project, item = _skeleton(db_session, leader_client, "TA5-ACCEPTANCE")
    acceptance = item["acceptance_criteria"]
    assert "巡检覆盖率≥90%" in acceptance
    assert "验收口径待补" in acceptance


def test_skeleton_options_sections_survive_sow_export(db_session, leader_client):
    """可导出：四段要进得去冻结的 SOW 快照，不能只活在草稿界面。"""
    project, item = _skeleton(
        db_session, leader_client, "TA5-EXPORT",
        out_of_scope=({"text": OUT_OF_SCOPE_TEXT, "classification": "customer_stated", "source_refs": [], "confirmed": True},),
    )
    _persist_doc_template(db_session, leader_client.user)
    url = f"/api/v1/projects/{project.id}/solutions/{item['id']}"
    exported = leader_client.post(url + "/export-sow", json={"version": item["version"]})
    assert exported.status_code == 200, exported.json
    version = db_session.scalar(select(ProjectDocumentVersion).where(
        ProjectDocumentVersion.id == exported.json["data"]["document_version_id"]))
    assert version is not None
    frozen = version.content_snapshot_json["solution"]
    design = frozen["design_markdown"]
    assert OPTIONS_HEADING in design
    assert OUT_OF_SCOPE_HEADING in design
    assert OUT_OF_SCOPE_TEXT in design
    assert frozen["acceptance_criteria"] == item["acceptance_criteria"]
