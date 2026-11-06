"""只读技能中心（B#32 A 面）：浏览面只读、源限定权威库、零写入零执行。

借鉴登记 B#32「Skill 固定目录 + 按需加载 + 只读技能中心」——**取内容域、弃
文件目录形态**：我方技能的权威已在 DB（`skill_definitions` / `skill_versions`，
含 `content_sha256` 与不可变版本行），并非「固定目录里的 SKILL.md 文件包」。
若另起文件系统 provider，就会出现**两个权威**（DB 版本行 vs 磁盘文件），漂移
不可测。故本面**只读 DB 权威**，不引入文件目录、不引依赖（⇒ 无供应链闸）。

**权限边界（照抄 #32 语义，不扩大）**：
- 只列**当前调用者有权看到**的技能：公共已发布技能 + 本人个人技能
  （与既有 `mcp_gateway._skills` 同尺：`scope=public` 或 `owner_user_id=当前用户`，
  且状态为 `published`——draft/in_review 未过发布闸不外泄）。
- **不枚举**用户／全局技能目录、**不枚举**客户项目、**不执行**技能、
  **不修改**任何项目数据——本模块无写路径（无 session.commit）。
- 正文按**版本**读取（`current_version_number` 对应的不可变版本行），
  返回体带 `content_sha256` 供下载方校验（与 `skill_read` 同一指纹口径）。
- **不消费计数**：`skill_read` 读出指南才计一次消费（T-S2 语义）；本面是
  治理浏览面（人看目录、下载文件），不是 AI 消费面，故不写
  `skill_used_*` 事件——否则浏览一次就虚增一条「已消费」记录。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select

from fde_api.auth.models import User
from fde_api.control.models import SkillDefinition, SkillVersion
from fde_api.extensions import db


# 列表面每页上限（有界返回，不做无限分页）
SKILL_CENTER_PAGE_SIZE = 200
# 正文下载的字节上限（技能指南正文应远小于此；超限拒绝而非截断）
SKILL_CENTER_MAX_BODY_BYTES = 512_000


def _visible_skills(session, user: User) -> list[tuple[SkillDefinition, SkillVersion]]:
    """当前用户可见的已发布技能 + 其当前版本（权限面与 `mcp_gateway._skills` 同尺）。

    只读：status=published（draft/in_review 未过发布闸不外泄）、scope=public
    或本人所有；排序稳定（scope → name → id）便于前端与测试比对。
    """
    rows = session.execute(
        select(SkillDefinition, SkillVersion)
        .join(
            SkillVersion,
            (SkillVersion.skill_id == SkillDefinition.id)
            & (SkillVersion.version_number == SkillDefinition.current_version_number),
        )
        .where(
            SkillDefinition.status == "published",
            or_(
                SkillDefinition.scope == "public",
                SkillDefinition.owner_user_id == user.id,
            ),
        )
        .order_by(SkillDefinition.scope, SkillDefinition.name, SkillDefinition.id)
    )
    return [(skill, version) for skill, version in rows]


def list_skill_center(*, user: User, scope: str | None = None) -> dict[str, Any]:
    """技能中心列表面：元信息 + 正文长度 + 指纹，不含正文本体。

    `scope` 可选过滤（`public` / `personal`）；非法值不报错，按未知即空处理
    并如实返回空列表——不猜、不放宽。
    """
    session = db.session()
    pairs = _visible_skills(session, user)
    if scope in {"public", "personal"}:
        pairs = [(skill, version) for skill, version in pairs if skill.scope == scope]
    elif scope not in (None, ""):
        pairs = []
    items = [
        {
            "id": skill.id,
            "scope": skill.scope,
            "key": skill.skill_key,
            "name": skill.name,
            "description": skill.description,
            "current_version": version.version_number,
            "content_sha256": version.content_sha256,
            "body_characters": len(version.instructions_text),
            "required_capabilities": list(version.required_capabilities or []),
            "manifest": dict(version.manifest_json or {}),
        }
        for skill, version in pairs[:SKILL_CENTER_PAGE_SIZE]
    ]
    return {
        "items": items,
        "total": len(pairs),
        "truncated": len(pairs) > SKILL_CENTER_PAGE_SIZE,
        # 边界声明：只读浏览面，不消费计数（AI 消费面是 skill_read）。
        "consumption_counted": False,
    }


def get_skill_document(*, user: User, skill_id: str) -> dict[str, Any]:
    """技能正文面：返回当前版本正文 + 指纹 + 建议下载文件名（UTF-8 文本）。

    权限同列表面：不可见即 404（不区分「不存在」与「无权」，避免探测）。
    """
    session = db.session()
    row = next(
        (
            (skill, version)
            for skill, version in _visible_skills(session, user)
            if skill.id == skill_id
        ),
        None,
    )
    if row is None:
        from fde_api.control.service import ControlServiceError

        raise ControlServiceError("skill_not_found", "技能不存在或无权查看。", 404)
    skill, version = row
    body = version.instructions_text
    if len(body.encode("utf-8")) > SKILL_CENTER_MAX_BODY_BYTES:
        from fde_api.control.service import ControlServiceError

        raise ControlServiceError(
            "skill_too_large", "技能正文过大，请通过 skill_read 分页读取。", 409
        )
    return {
        "id": skill.id,
        "scope": skill.scope,
        "key": skill.skill_key,
        "name": skill.name,
        "current_version": version.version_number,
        "content_sha256": version.content_sha256,
        "body": body,
        "body_characters": len(body),
        # 建议下载文件名：技能 key + .md（UTF-8），不含路径分隔符
        "download_filename": f"{skill.skill_key}.md",
        "read_only": True,
    }
