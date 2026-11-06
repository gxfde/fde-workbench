"""只读技能中心（B#32 A 面）：权限面只读、源限定权威库、不消费计数。

钉住四条边界（照抄 #32 语义，不扩大）：
1. **只列有权可见的已发布技能**：公共已发布 + 本人个人已发布；他人个人技能
   与未过发布闸的 draft/in_review 一律不可见。
2. **只读**：无写路径——不执行技能、不修改项目数据。
3. **不消费计数**：浏览不写 `skill_used_*` 事件（AI 消费面是 `skill_read`）。
4. **指纹口径一致**：正文面返回的 `content_sha256` 与 DB 版本行一致（可校验）。

另钉：不可见/不存在一律 404（不区分「不存在」与「无权」，避免探测）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from conftest import INITIAL_PASSWORD as PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.control.models import SkillDefinition, SkillVersion
from fde_api.workbench.models import OperationEvent

from test_gates_api import AuthorizedClient


def _make_user(db_session, *, role: str = "viewer", username: str | None = None) -> User:
    user = User(
        username=username or f"skillcenter.{uuid4().hex[:8]}",
        display_name="SkillCenter user",
        role=role,
        password_hash=hash_password(PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _make_skill(
    db_session,
    *,
    owner: User | None,
    scope: str,
    status: str = "published",
    key: str | None = None,
    instructions: str = "只做只读浏览。",
) -> SkillDefinition:
    skill = SkillDefinition(
        scope=scope,
        namespace_key="default",
        owner_user_id=owner.id if owner else None,
        skill_key=key or f"skill-{uuid4().hex[:8]}",
        name="技能中心测试技能",
        description="只读技能中心用例",
        status=status,
        current_version_number=1,
        created_by_user_id=(owner.id if owner else _system_user_id(db_session)),
    )
    db_session.add(skill)
    db_session.flush()
    version = SkillVersion(
        skill_id=skill.id,
        version_number=1,
        instructions_text=instructions,
        manifest_json={"entrypoint": "SKILL.md", "format": "markdown"},
        required_capabilities=[],
        content_sha256="a" * 64,
        created_by_user_id=skill.created_by_user_id,
    )
    db_session.add(version)
    db_session.flush()
    # 必须提交：HTTP 路由在请求期另起 session（scoped_session 按 app context
    # 分域），未提交的 fixture 数据在请求侧不可见 ⇒ 列表会是空集。
    db_session.commit()
    return skill


def _system_user_id(db_session) -> str:
    row = db_session.scalar(select(User).where(User.role == "admin").limit(1))
    if row is None:
        row = _make_user(db_session, role="admin")
    return row.id


@pytest.fixture
def viewer(client, db_session, settings):
    user = _make_user(db_session, role="viewer")
    db_session.commit()
    return AuthorizedClient(
        client, user, {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
    )


def _get(client, path: str):
    return client.get(path)


def test_skill_center_lists_only_visible_published_skills(viewer, db_session):
    """公共已发布 + 本人个人已发布可见；他人个人技能与 draft 不可见。"""
    me = db_session.scalar(select(User).where(User.username == viewer.user.username))
    other = _make_user(db_session, role="viewer")

    public = _make_skill(db_session, owner=None, scope="public")
    mine = _make_skill(db_session, owner=me, scope="personal")
    theirs = _make_skill(db_session, owner=other, scope="personal")
    draft = _make_skill(db_session, owner=None, scope="public", status="draft")
    db_session.commit()

    response = _get(viewer, "/api/v1/skills")
    assert response.status_code == 200
    payload = response.get_json()["data"]
    ids = {item["id"] for item in payload["items"]}
    assert public.id in ids
    assert mine.id in ids
    assert theirs.id not in ids
    assert draft.id not in ids
    # 只读浏览面不消费计数
    assert payload["consumption_counted"] is False


def test_skill_center_document_returns_body_and_fingerprint(viewer, db_session):
    """正文面返回当前版本正文 + 与 DB 一致的指纹 + 建议下载文件名。"""
    me = db_session.scalar(select(User).where(User.username == viewer.user.username))
    skill = _make_skill(db_session, owner=me, scope="personal", instructions="正文内容：只读浏览。")
    db_session.flush()

    response = _get(viewer, f"/api/v1/skills/{skill.id}/document")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["body"] == "正文内容：只读浏览。"
    assert data["content_sha256"] == "a" * 64
    assert data["download_filename"] == f"{skill.skill_key}.md"
    assert data["read_only"] is True


def test_skill_center_document_of_invisible_skill_is_404(viewer, db_session):
    """他人个人技能与不存在技能一律 404（不区分「不存在」与「无权」）。"""
    other = _make_user(db_session, role="viewer")
    theirs = _make_skill(db_session, owner=other, scope="personal")
    db_session.flush()

    assert _get(viewer, f"/api/v1/skills/{theirs.id}/document").status_code == 404
    assert _get(viewer, f"/api/v1/skills/{uuid4().hex}/document").status_code == 404


def test_skill_center_scope_filter(viewer, db_session):
    """scope 过滤：public/personal 精确过滤；非法值按空处理（不猜不放宽）。"""
    me = db_session.scalar(select(User).where(User.username == viewer.user.username))
    _make_skill(db_session, owner=None, scope="public")
    _make_skill(db_session, owner=me, scope="personal")
    db_session.flush()

    public_items = _get(viewer, "/api/v1/skills?scope=public").get_json()["data"]["items"]
    assert public_items and all(item["scope"] == "public" for item in public_items)

    personal_items = _get(viewer, "/api/v1/skills?scope=personal").get_json()["data"]["items"]
    assert personal_items and all(item["scope"] == "personal" for item in personal_items)

    bogus = _get(viewer, "/api/v1/skills?scope=bogus").get_json()["data"]
    assert bogus["items"] == []


def test_skill_center_browsing_writes_no_operation_event(viewer, db_session):
    """只读面零写入：浏览技能不产生任何操作事件（不写 skill_used_*）。"""
    me = db_session.scalar(select(User).where(User.username == viewer.user.username))
    skill = _make_skill(db_session, owner=me, scope="personal")
    db_session.flush()

    before = len(list(db_session.scalars(select(OperationEvent))))
    assert _get(viewer, "/api/v1/skills").status_code == 200
    assert _get(viewer, f"/api/v1/skills/{skill.id}/document").status_code == 200
    db_session.expire_all()
    after = len(list(db_session.scalars(select(OperationEvent))))
    assert after == before
