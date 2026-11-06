"""#8 两级注入（readBefore → references 组）：消费面两层接线专项钉。

契约载体＝`docs/architecture/技能结构化契约-v1.md` §2.6 `references` 组：
- 第一级（选技能前）：`skill_list` 列表面带 `when_to_use` 摘要
  （取自 `use_boundaries.when_to_use`；未填该组不带此键——缺省＝不误导）。
- 第二级（读正文前）：`skill_read` 首页（offset=0）带 `required_reading` /
  `authoritative_sources` 引用清单；**续页不带**（同一正文的延续，重复是噪音）；
  引用是仓库内相对路径，不携带内容、不产生新读取权限。

四条边界：
1. 良构才出——类型不符（非 str / 非 list[str]）或缺省一律不带键，不猜不放宽；
2. 计数语义不变——首页带引用**不**改变 T-S2「仅首读计一次」；
3. 引用不注入正文——`instructions` 片段不含引用内容（AI 自行用既有只读工具读）；
4. 语义锚——`fde-package-verify` 的「README 冲突以 README 为准」手写规则是
   `authoritative_sources` 的最小实例（回填后经 `skill_read` 可读出）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.mcp_gateway import TOOLS, call_tool
from fde_api.control.models import SkillDefinition, SkillVersion

from test_gates_api import AuthorizedClient


def _make_user(db_session, *, role: str = "viewer") -> User:
    user = User(
        username=f"readbf.{uuid4().hex[:8]}",
        display_name="readbefore user",
        role=role,
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_skill(db_session, *, owner: User, manifest: dict, instructions: str) -> SkillDefinition:
    skill = SkillDefinition(
        scope="personal",
        namespace_key="default",
        owner_user_id=owner.id,
        skill_key=f"rb-{uuid4().hex[:8]}",
        name="两级注入测试技能",
        description="references 组用例",
        status="published",
        current_version_number=1,
        created_by_user_id=owner.id,
    )
    db_session.add(skill)
    db_session.flush()
    db_session.add(SkillVersion(
        skill_id=skill.id,
        version_number=1,
        instructions_text=instructions,
        manifest_json=manifest,
        required_capabilities=[],
        content_sha256="b" * 64,
        created_by_user_id=owner.id,
    ))
    # HTTP/MCP 调用按 app context 另起 session：fixture 数据必须提交才可见。
    db_session.commit()
    return skill


@pytest.fixture
def viewer(client, db_session, settings):
    user = _make_user(db_session, role="viewer")
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _call(db_session, viewer, name: str, arguments: dict) -> dict:
    user = db_session.scalar(select(User).where(User.id == viewer.user.id))
    result = call_tool(db_session, user=user, claims={"execution_id": None}, allowed=set(),
                       name=name, arguments=arguments)
    db_session.rollback()  # 消费计数微事务已自提交；回滚清掉本测测试的残留状态
    return result


def test_skill_list_first_level_carries_when_to_use(viewer, db_session):
    """第一级：skill_list 带 when_to_use 摘要；未填组的技能不带该键。"""
    plain = _make_skill(db_session, owner=viewer.user,
                        manifest={"version": "1.0.0", "source": "fde-workbench", "read_only": True},
                        instructions="无契约组。")
    tagged = _make_skill(db_session, owner=viewer.user,
                         manifest={"version": "1.0.0", "source": "fde-workbench", "read_only": True,
                                   "use_boundaries": {"when_to_use": "用户要采集集成桥快照时",
                                                      "when_not_to_use": "与桥无关的排查"},
                                   },
                         instructions="带触发条件。")
    result = _call(db_session, viewer, "skill_list", {})
    items = {item["id"]: item for item in result["items"]}
    assert "when_to_use" not in items[plain.id]
    assert items[tagged.id]["when_to_use"] == "用户要采集集成桥快照时"


def test_skill_read_first_page_carries_references(viewer, db_session):
    """第二级：首页带 required_reading/authoritative_sources；引用不进正文。"""
    skill = _make_skill(db_session, owner=viewer.user,
                        manifest={"version": "1.0.0", "source": "fde-workbench", "read_only": True,
                                  "references": {"required_reading": ["README.md"],
                                                 "authoritative_sources": ["AGENTS.md", "CHANGELOG.md"]}},
                        instructions="正文内容，不含引用文件本身。")
    result = _call(db_session, viewer, "skill_read", {"skill_id": skill.id})
    assert result["required_reading"] == ["README.md"]
    assert result["authoritative_sources"] == ["AGENTS.md", "CHANGELOG.md"]
    # 引用不注入正文
    assert "README.md" not in result["instructions"]


def test_skill_read_continuation_page_omits_references(viewer, db_session):
    """续页（offset>0）不带引用清单——同一正文的延续，重复是噪音。"""
    skill = _make_skill(db_session, owner=viewer.user,
                        manifest={"version": "1.0.0", "source": "fde-workbench", "read_only": True,
                                  "references": {"required_reading": ["README.md"]}},
                        instructions="x" * 40)
    second = _call(db_session, viewer, "skill_read", {"skill_id": skill.id, "offset": 16})
    assert second["offset"] == 16
    assert "required_reading" not in second


def test_malformed_reference_values_are_dropped(viewer, db_session):
    """良构才出：类型不符（非 list[str]）或缺省一律不带键——不猜不放宽。"""
    skill = _make_skill(db_session, owner=viewer.user,
                        manifest={"version": "1.0.0", "source": "fde-workbench", "read_only": True,
                                  "references": {"required_reading": "README.md",  # 非 list
                                                 "authoritative_sources": [123, ""],  # 非全非空 str
                                                 }},
                        instructions="坏引用。")
    result = _call(db_session, viewer, "skill_read", {"skill_id": skill.id})
    assert "required_reading" not in result
    assert "authoritative_sources" not in result


def test_tools_schema_unchanged_and_zero_new_permissions():
    """静态钉：两级注入不扩工具参数面（skill_list/skill_read schema 不变）——
    引用不携带内容、不产生新读取权限；消费方仍走既有只读工具。"""
    assert set(TOOLS["skill_list"][2]) == set()
    assert set(TOOLS["skill_read"][2]) == {"skill_id", "offset"}
