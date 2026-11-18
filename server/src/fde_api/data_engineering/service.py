"""data_engineering 域服务（AF2-WP1）：画像编排面——权限 + 落库 + 审计。

权限口径（沿 AF1 域惯例，ingest_service S-01）：项目不存在 **或无访问权**
一律 404（不泄露存在性）；画像/采样=项目授权内预览档（04 §4「资料导入、
候选生成、隔离预览可在项目授权和预算内运行」），member 级 can_view 即可，
不预支生产写授权。

写操作审计（§15）：画像创建落 ``operation_events``（引用与统计，不含样本
内容）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.data_engineering.models import DataProfile
from fde_api.data_engineering.profiling import ProfileError, profile_bytes
from fde_api.extensions import db
from fde_api.projects.events import record_event


class DataEngineeringError(Exception):
    def __init__(self, code: str, message: str, status: int, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.detail = detail or {}


def _error(code: str, message: str, status: int = 400, detail: dict[str, Any] | None = None) -> DataEngineeringError:
    return DataEngineeringError(code, message, status, detail)


def _require_project(session: Session, actor, project_id: str):
    """项目加载 + S-01 口径：不存在或无 can_view 都 404（不泄露存在性）。"""
    from fde_api.projects.permissions import project_access
    from fde_api.workbench.models import Project

    project = session.get(Project, project_id)
    access_ok = project is not None and project_access(actor, project).can_view
    if not access_ok:
        raise _error("project_not_found", "项目不存在。", 404)
    return project


def create_profile(*, actor, project_id: str, filename: str, data: bytes) -> dict[str, Any]:
    session: Session = db.session()
    try:
        project = _require_project(session, actor, project_id)

        try:
            report = profile_bytes(filename=filename, data=data)
        except ProfileError as error:
            code = str(error.args[0]) if error.args else "profile_failed"
            message = str(error.args[1]) if len(error.args) > 1 else str(error)
            raise _error(code, message, 400) from error

        row = DataProfile(
            project_id=project.id,
            source_name=report["source_name"],
            input_sha256=report["input_sha256"],
            truncated=report["truncated"],
            table_count=len(report["tables"]),
            tables_json=report["tables"],
            relation_candidates_json=report["relation_candidates"],
            samples_json=report["samples"],
            created_by_user_id=actor.id,
        )
        session.add(row)
        session.flush()
        record_event(
            session,
            actor,
            "data_profile_created",
            project,
            {
                "profile_id": row.id,
                "source_name": row.source_name,
                "input_sha256": row.input_sha256,
                "table_count": row.table_count,
            },
        )
        session.commit()
        return row.snapshot()
    finally:
        session.close()


def list_profiles(*, actor, project_id: str) -> list[dict[str, Any]]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        rows = session.scalars(
            select(DataProfile)
            .where(DataProfile.project_id == project_id)
            .order_by(DataProfile.created_at.desc())
        ).all()
        return [row.snapshot() for row in rows]
    finally:
        session.close()


def get_profile(*, actor, project_id: str, profile_id: str) -> dict[str, Any]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        row = session.get(DataProfile, profile_id)
        if row is None or row.project_id != project_id:
            raise _error("profile_not_found", "画像报告不存在。", 404)
        return row.snapshot()
    finally:
        session.close()
