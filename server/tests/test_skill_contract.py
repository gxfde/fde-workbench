"""B#37 技能自洽校验（标准库+pytest，零新依赖）——契约=docs/architecture/技能结构化契约-v1.md（B#36）。

四钉（静态三 + DB 对账一）：
① 仓库 runbook（.agents/skills/*/SKILL.md）front matter 契约：
   name=目录名（fde- 前缀）/description 下限/已知契约点路径键良构/正文非空；
② builtin_skills.SKILLS 种子清单静态契约：形状/键唯一/能力 ⊆ CAPABILITY_REQUIREMENTS/
   LEGACY 升级指纹键 ⊆ 现役键；
③ 种子 manifest 构造规则独立复算钉（version 分档/source/read_only 推导）+ 键空间闭合；
④ 种子清单 ↔ DB 行对账：seed_public_skills 端到端——全量落库逐位一致、首轮恰一版、
   幂等二轮零新建零版本增殖；read_only×effects.write_actions 契约自洽律在库上复核。

存量 4 个 runbook 与内置种子 manifest 均不回填（契约 §5 非目标）；未知键不拒绝
（不设 additionalProperties:false），只校验已知键良构性。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.access import CAPABILITY_REQUIREMENTS
from fde_api.control.builtin_skills import (
    LEGACY_SKILLS,
    SKILLS,
    _LCSC_V1,
    _SOLUTION_SKILLS,
    seed_public_skills,
)
from fde_api.control.models import SkillDefinition, SkillVersion

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK_DIR = REPO_ROOT / ".agents" / "skills"

# 契约 v1（B#36）五组语义——组键空间闭合枚举，防自带种子/DB 行漂移进契约外键。
CONTRACT_GROUPS: dict[str, dict[str, type]] = {
    "use_boundaries": {"when_to_use": str, "when_not_to_use": str},
    "effects": {"write_actions": bool, "external_side_effects": list},
    "evidence": {"artifacts_as_pointers": bool, "evidence_gates": list},
    "verification": {"verified_scenarios": list, "unverified_note": str},
    "failure_behavior": {"failure_reporting": str, "degrade_policy": str},
    # 2.6 references 必读引用组（#8 两级注入载体，2026-11-06 扩组）：引用是仓库内
    # 相对路径清单；消费方用既有只读工具自行读取，引用不携带内容、不产生新权限。
    "references": {"required_reading": list, "authoritative_sources": list},
}
BASE_MANIFEST_KEYS = {"version", "source", "read_only"}
GATE_IDS = {f"G{i}" for i in range(1, 10)}
RUNBOOK_KEY = re.compile(r"^fde-[a-z0-9-]+$")
SEED_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,99}$")


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md 必须以 --- 开头的 front matter"
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            fields: dict[str, str] = {}
            for line in lines[1:index]:
                if not line.strip():
                    continue
                key, sep, value = line.partition(":")
                assert sep, f"front matter 行缺少冒号分隔: {line!r}"
                fields[key.strip()] = value.strip()
            return fields, "\n".join(lines[index + 1:])
    raise AssertionError("front matter 未闭合（缺收尾 ---）")


def _assert_flat_contract_key_well_formed(flat_key: str, value: str) -> None:
    group, sep, sub = flat_key.partition(".")
    assert sep and group in CONTRACT_GROUPS, f"未知契约点路径组键: {flat_key}"
    spec = CONTRACT_GROUPS[group]
    assert sub in spec, f"未知契约子键: {flat_key}"
    expected = spec[sub]
    if expected is bool:
        assert value in ("true", "false"), f"{flat_key} 须为 true/false 字面量"
    elif expected is list:
        parsed: Any = json.loads(value)
        assert isinstance(parsed, list), f"{flat_key} 须为 JSON 数组字面量"
        assert all(isinstance(item, str) for item in parsed), f"{flat_key} 须为字符串数组"
        if sub == "evidence_gates":
            assert set(parsed) <= GATE_IDS, f"{flat_key} 门禁编号须 ⊆ G1–G9"
    else:
        assert value, f"{flat_key} 不得为空"


def test_repo_runbooks_follow_front_matter_contract():
    runbooks = sorted(RUNBOOK_DIR.glob("*/SKILL.md"))
    assert runbooks, ".agents/skills/ runbook 集合意外消失"
    for path in runbooks:
        fields, body = _parse_front_matter(path.read_text(encoding="utf-8"))
        assert RUNBOOK_KEY.fullmatch(path.parent.name), f"{path}: 目录名须为 fde- 前缀小写连字符"
        assert fields.get("name") == path.parent.name, f"{path}: name 须等于目录名"
        assert len(fields.get("description", "")) >= 40, f"{path}: description 过短（契约下限 40 字符）"
        for key, value in fields.items():
            if "." in key:
                _assert_flat_contract_key_well_formed(key, value)
        assert body.strip(), f"{path}: front matter 之后必须有非空正文"


def test_builtin_seed_list_static_contract():
    keys = [item[0] for item in SKILLS]
    assert len(keys) == len(set(keys)), "种子 skill_key 重复"
    for key, name, description, capabilities, instructions in SKILLS:
        assert SEED_KEY.fullmatch(key), f"{key}: skill_key 形状违例"
        assert name.strip() and description.strip() and instructions.strip(), f"{key}: 文本字段不得为空"
        assert isinstance(capabilities, list), f"{key}: capabilities 须为列表"
        assert len(set(capabilities)) == len(capabilities), f"{key}: capabilities 重复"
        outside = set(capabilities) - set(CAPABILITY_REQUIREMENTS)
        assert not outside, f"{key}: 域外能力 {outside}"
    assert {item[0] for item in LEGACY_SKILLS} <= set(keys), "LEGACY 升级指纹键必须仍在现役清单"


def _expected_seed_manifest(key: str, capabilities: list[str]) -> dict[str, Any]:
    """独立复算种子 manifest 构造规则（与 seed_public_skills 同式）——src 侧漂移即红。"""
    version = "1.2.0" if key in _SOLUTION_SKILLS else "1.1.4" if key in _LCSC_V1 else "1.0.0"
    return {"version": version, "source": "fde-workbench", "read_only": "workbench.write" not in capabilities}


def test_builtin_seed_manifest_rule_pinned():
    allowed = BASE_MANIFEST_KEYS | set(CONTRACT_GROUPS)
    for key, _name, _description, capabilities, _instructions in SKILLS:
        manifest = _expected_seed_manifest(key, capabilities)
        assert set(manifest) <= allowed, f"{key}: 种子 manifest 键漂移出契约键空间"
        assert manifest["read_only"] == ("workbench.write" not in capabilities), f"{key}: read_only 推导违例"
    # 版本分档口径钉：三类互不混淆（solution 腿 / lcsc 腿 / 其余基线）
    assert _expected_seed_manifest("delivery-scope-documents", ["project.read"])["version"] == "1.2.0"
    assert _expected_seed_manifest("lcsc-browser-baseline", [])["version"] == "1.1.4"
    assert _expected_seed_manifest("workbench-help", [])["version"] == "1.0.0"


def test_seed_public_skills_reconciles_seed_list_with_db_rows(db_session):
    db_session.add(User(username="seedadmin.b37", display_name="B37 Seed Admin", role="admin",
        password_hash=hash_password(PASSWORD), must_change_password=False, is_active=True))
    db_session.commit()

    created = seed_public_skills()
    assert created == len(SKILLS), "全新库首轮应全量建种"

    def _definition(key: str) -> SkillDefinition:
        row = db_session.scalar(select(SkillDefinition).where(
            SkillDefinition.namespace_key == "public", SkillDefinition.skill_key == key))
        assert row is not None, f"{key}: 未落库"
        return row

    for key, name, _description, capabilities, instructions in SKILLS:
        row = _definition(key)
        assert row.status == "published", f"{key}: 种子须直落 published"
        assert row.name == name
        version = db_session.scalar(select(SkillVersion).where(
            SkillVersion.skill_id == row.id, SkillVersion.version_number == row.current_version_number))
        assert version is not None, f"{key}: 无现行版本行"
        assert version.instructions_text == instructions, f"{key}: instructions 与种子不一致"
        assert version.required_capabilities == capabilities, f"{key}: capabilities 与种子不一致"
        assert version.manifest_json == _expected_seed_manifest(key, capabilities), f"{key}: manifest 与构造规则不一致"
        effects = version.manifest_json.get("effects")
        if isinstance(effects, dict) and "write_actions" in effects:
            # 契约自洽律（契约 §2.2）：read_only 与 effects.write_actions 并存时必须互补
            assert version.manifest_json["read_only"] == (not effects["write_actions"]), f"{key}: 契约自洽律违例"
        assert len(db_session.scalars(select(SkillVersion.id).where(SkillVersion.skill_id == row.id)).all()) == 1, \
            f"{key}: 首轮应恰一版"

    # 幂等对账：二轮零新建（管理员未编辑 ⇒ 不入升级集合）、版本行不增殖
    assert seed_public_skills() == 0
    for key, *_rest in SKILLS:
        row = _definition(key)
        assert len(db_session.scalars(select(SkillVersion.id).where(SkillVersion.skill_id == row.id)).all()) == 1, \
            f"{key}: 二轮后版本行增殖"
