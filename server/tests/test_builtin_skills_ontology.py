"""AF1-WP3：本体候选工程 Skill 的工程提示/规则面契约钉。

Skill（builtin `ontology-candidate-engineering`）是「SOP/字典→候选生成与修正」
的工程提示面（11 号 WP1 工作令 WP3）：词表与工具描述同源、四分纪律（事实/缺失/
假设/证据）、同义词/主键/单位歧义→决策单产物（不编造、不凭置信度绕审批）、
修正循环与失败行为、S-19 材料注入纪律。静态钉 + DB 对账 + 分档可见性三层。
"""
from __future__ import annotations

from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.access import capabilities_for_level
from fde_api.control.builtin_skills import SKILLS, seed_public_skills
from fde_api.control.mcp_gateway import TOOLS, call_tool

SKILL_KEY = "ontology-candidate-engineering"

# 词表真身（与 ontology-service validation.py 同源；工具描述是 workbench 侧唯一
# 机器可读载体——skill 文本必须与它逐字同源，漂移即红）
DATA_TYPES = ("string", "number", "boolean", "date", "datetime", "enum", "ref")
OPS = ("create", "update", "deprecate")
ENTITY_TYPES = ("object_types", "property_definitions", "relation_types", "data_sources")


def _entry() -> tuple[str, str, str, list[str], str]:
    for item in SKILLS:
        if item[0] == SKILL_KEY:
            return item
    raise AssertionError(f"{SKILL_KEY}: builtin 种子清单中缺失")


def _instructions() -> str:
    return _entry()[4]


def test_ontology_skill_registered_with_read_capability() -> None:
    key, _name, description, capabilities, instructions = _entry()
    assert capabilities == ["ontology.read"]
    assert description.strip() and instructions.strip()
    assert "dry_validate" in instructions, "修正循环必须锚在 dry_validate 预检工具上"


def test_ontology_skill_vocabulary_matches_tool_description() -> None:
    """词表同源钉：skill 文本与工具描述的词表**整串同现**（评审 F4——逐值子串
    会被 datetime/enum_values/ref_object_type_id 掩蔽，整串断言同时钉顺序）。
    跨仓不可 import：真身（ontology-service validation.py DATA_TYPES/OPS/
    ENTITY_TYPES）漂移由 live demo 行为锚与 WP5 评分兜底，本钉守 workbench
    侧三处互证。"""
    instructions = _instructions()
    tool_description = TOOLS["ontology_dry_validate"][0]
    data_type_series = "/".join(DATA_TYPES)
    assert data_type_series in instructions, "skill 词表须整串同现（钉顺序与完整集）"
    assert data_type_series in tool_description, "工具描述词表须整串同现（同源失守）"
    for value in OPS:
        assert value in instructions
    for value in ENTITY_TYPES:
        assert value in instructions
    # entity_key 形状文案与真身 KEY_RE 同源（评审 F2：短横线-only 文案会与
    # KEY_RE 允许下划线矛盾，live 材料的下划线键会被测试「奖励违规」）
    assert "下划线" in instructions
    assert "下划线" in tool_description


def test_ontology_skill_discipline_pins() -> None:
    """四分/决策单/治理纪律钉：11 号 WP3「事实/缺失/假设/证据四分；同义词/主键/
    单位问题→决策单产物（不编造、不凭置信度绕审批）」逐条落文本。"""
    text = _instructions()
    for marker in (
        "事实", "缺失", "假设", "证据",                      # 四分
        "unresolved_questions",                              # 决策单产物载体（六件套字段）
        "同义词", "主键", "单位",                            # 三类歧义→待人工决策
        "evidence_quote", "fact_or_inference",               # 六件套可溯源/区分为 fact/inference
        "不得编造",                                          # 未知不编造
        "置信度",                                            # 不凭置信度绕审批
        "待审",                                              # 停待审是正常终点
    ):
        assert marker in text, f"纪律面缺 {marker!r}"
    # 失败行为：依赖不可用如实停止不伪造成功；材料指令是数据不是命令（S-19 纪律）；
    # 不可修正违规（injection_suspect 命中逐字引用）→保留引用上报停止（评审 F7）
    assert "不伪造" in text or "不得伪造" in text
    assert "指令" in text and "数据" in text
    assert "injection_suspect" in text
    assert "不得删改引用" in text


def test_ontology_skill_seeded_published_and_visible_by_level(db_session):
    """种子落库 + 分档可见性：manager 档（含 ontology.read）可见，viewer 档不可见
    （mcp_gateway._skills 按 required_capabilities ⊆ allowed 过滤的全真链）。"""
    db_session.add(User(username="ont-skill-admin", display_name="Ont Skill Admin", role="admin",
        password_hash=hash_password(PASSWORD), must_change_password=False, is_active=True))
    db_session.commit()
    seed_public_skills()
    from fde_api.control.models import SkillDefinition
    row = db_session.scalar(select(SkillDefinition).where(
        SkillDefinition.namespace_key == "public", SkillDefinition.skill_key == SKILL_KEY))
    assert row is not None and row.status == "published"

    class _User:
        def __init__(self, uid: str) -> None:
            self.id = uid

    skill_name = _entry()[1]
    claims = {"execution_id": "exec-ont-skill"}
    manager_view = call_tool(
        db_session, user=_User("u-manager"), claims=claims,
        allowed=capabilities_for_level("project_manager"), name="skill_list", arguments={},
    )
    assert any(item["name"] == skill_name for item in manager_view["items"]), manager_view
    viewer_view = call_tool(
        db_session, user=_User("u-viewer"), claims=claims,
        allowed=capabilities_for_level("assistant_read"), name="skill_list", arguments={},
    )
    assert not any(item["name"] == skill_name for item in viewer_view["items"])
