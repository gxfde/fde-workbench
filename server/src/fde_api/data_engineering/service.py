"""data_engineering 域服务（AF2-WP1 画像 + AF2-WP2 TransformPlan 计划面）：
权限 + 落库 + 审计编排面。

权限口径（沿 AF1 域惯例，ingest_service S-01）：项目不存在 **或无访问权**
一律 404（不泄露存在性）；画像/采样=项目授权内预览档（04 §4「资料导入、
候选生成、隔离预览可在项目授权和预算内运行」），member 级 can_view 即可，
不预支生产写授权。

写操作审计（§15）：画像创建落 ``operation_events``（引用与统计，不含样本
内容）。

TransformPlan 计划面（AF2-WP2）：只落**已通过静态校验**的计划——校验失败
⇒ 400 ``invalid_transform_plan`` 且零落库；无编译、无执行、无 I/O（编译
面归 WP3 design-first 门）。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.data_engineering.models import DataProfile, TransformPlan
from fde_api.data_engineering.profiling import ProfileError, profile_bytes
from fde_api.data_engineering.transform_plan import validate_plan
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


def _adapter_from_app():
    """本体 adapter 出口：flag 关 fail-closed 503（零出站调用，§15 红线）。"""
    from flask import current_app

    from fde_api.integrations.service import client_from_settings

    settings = current_app.config["SETTINGS"]
    if not getattr(settings, "ontology_enabled", False):
        raise _error("ontology_disabled", "本体运行时未启用。", 503)
    return client_from_settings()


def _fk_relation_candidates(tables: dict[str, Any]) -> list[dict[str, Any]]:
    """catalog 外键 = 关系候选硬证据（D5 ④）：status 恒 ``candidate``，无翻产
    通道（03 §77）；无外键的表不产生候选（同名列降级判断归画像消费面）。"""
    candidates: list[dict[str, Any]] = []
    for table_name in sorted(tables):
        for fk in tables[table_name].get("foreign_keys") or []:
            candidates.append(
                {
                    "left_table": table_name,
                    "right_table": str(fk["references_table"]),
                    "left_column": str(fk["column"]),
                    "right_column": str(fk["references_column"]),
                    "basis": "fk_catalog",
                    "status": "candidate",
                }
            )
    return candidates


def create_connector_profile(
    *,
    actor,
    project_id: str,
    ontology_id: str,
    version_id: str,
    data_source_key: str,
    org_id: str,
    adapter=None,
) -> dict[str, Any]:
    """连接器侧 DB 内省画像（AF2-WP1 第二批 / D5）：掩码出边界在 ontology-service
    连接器沙箱内完成（单一真身），本侧只透传统计 + 掩码样本落库，不二次脱敏。

    ``org_id`` 为本体运行时租户上下文（interim 显式传参；binding 集成后收窄为
    服务端从绑定解析——消费接线批）。画像行带快照锚四件（版本快照钉版本）。
    """
    session: Session = db.session()
    try:
        project = _require_project(session, actor, project_id)
        client = adapter if adapter is not None else _adapter_from_app()
        try:
            report = client.introspect_data_source(
                actor_id=str(actor.id),
                org_id=org_id,
                project_id=project_id,
                ontology_id=ontology_id,
                version_id=version_id,
                data_source_key=data_source_key,
            )
        except DataEngineeringError:
            raise
        except Exception as error:  # OntologyClient 异常族 → 显性映射（禁吞错，§14-4）
            raise _error("ontology_unavailable", "本体运行时内省调用失败。", 503) from error
        status = int(report.get("_status") or 0)
        if status == 404:
            raise _error("data_source_not_found", "数据源不在该版本快照中。", 404)
        if status == 422:
            raise _error("introspection_unsupported", "该数据源类型不支持内省。", 422)
        if status != 200:
            raise _error("ontology_unavailable", "本体运行时内省调用失败。", 503)

        tables = report.get("tables") or {}
        row = DataProfile(
            project_id=project.id,
            source_name=f"connector:{data_source_key}",
            input_sha256=str(report.get("snapshot_sha256") or ""),
            table_count=len(tables),
            source_kind="connector",
            ontology_id=ontology_id,
            ontology_version_id=version_id,
            snapshot_sha256=str(report.get("snapshot_sha256") or ""),
            data_source_key=data_source_key,
            tables_json=tables,
            relation_candidates_json=_fk_relation_candidates(tables),
            samples_json={
                name: t["row_sample"]
                for name, t in sorted(tables.items())
                if isinstance(t.get("row_sample"), dict)
            },
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
                "source_kind": row.source_kind,
                "source_name": row.source_name,
                "ontology_id": ontology_id,
                "ontology_version_id": version_id,
                "data_source_key": data_source_key,
                "snapshot_sha256": row.snapshot_sha256,
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


def create_transform_plan(*, actor, project_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """落一份已通过静态校验的转换计划（AF2-WP2 计划面）。

    校验失败 ⇒ 400 ``invalid_transform_plan``（detail 携带校验报告）且
    **零落库**；成功只落声明与校验报告（append-only，无生产态字段）。
    """
    session: Session = db.session()
    try:
        project = _require_project(session, actor, project_id)
        report = validate_plan(plan)
        if not report["valid"]:
            raise _error(
                "invalid_transform_plan",
                "转换计划未通过静态校验。",
                400,
                detail={"validation": report},
            )
        source = plan.get("source") or {}
        row = TransformPlan(
            project_id=project.id,
            plan_version=str(plan.get("plan_version") or ""),
            status="validated",
            source_profile_id=str(source.get("profile_id") or ""),
            source_table=str(source.get("table") or ""),
            plan_json=plan,
            validation_json=report,
            created_by_user_id=actor.id,
        )
        session.add(row)
        session.flush()
        record_event(
            session,
            actor,
            "transform_plan_created",
            project,
            {
                "plan_id": row.id,
                "plan_version": row.plan_version,
                "source_profile_id": row.source_profile_id,
                "source_table": row.source_table,
                "step_count": len(plan.get("steps") or []),
                "error_count": 0,
            },
        )
        session.commit()
        return row.snapshot()
    finally:
        session.close()


def list_transform_plans(*, actor, project_id: str) -> list[dict[str, Any]]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        rows = session.scalars(
            select(TransformPlan)
            .where(TransformPlan.project_id == project_id)
            .order_by(TransformPlan.created_at.desc())
        ).all()
        return [row.snapshot() for row in rows]
    finally:
        session.close()


def get_transform_plan(*, actor, project_id: str, plan_id: str) -> dict[str, Any]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        row = session.get(TransformPlan, plan_id)
        if row is None or row.project_id != project_id:
            raise _error("transform_plan_not_found", "转换计划不存在。", 404)
        return row.snapshot()
    finally:
        session.close()
