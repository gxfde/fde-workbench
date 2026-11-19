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

import csv
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.data_engineering.masking import mask_transform_output
from fde_api.data_engineering.models import MASKED_OUTPUT_KEY, DataProfile, TransformPlan, TransformRun
from fde_api.data_engineering.profiling import ProfileError, profile_bytes
from fde_api.data_engineering.transform_executor import execute_plan
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


def submit_transform_run(
    *,
    actor,
    project_id: str,
    plan_id: str,
    input_ref: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    """提交一次隔离执行（AF2-WP3，17 号 v1.0；甲案=worker 固定算子）。

    幂等重放：同 ``idempotency_key`` 返回既有 run（不重复执行）。执行闸链
    （17 号 §4.1）：S-01 项目权限 → 计划归属 → **纵深再校验 validate_plan**
    （计划=不可信候选）→ 输入快照锚（files 版本 available）→ **同源校验**
（§2.2：画像与快照指纹一致，不一致＝``snapshot_mismatch`` 拒绝）→ 解析（truncated
    ＝输入超上限，诚实 budget_exhausted 不静默截断）→ ``execute_plan`` 纯函数
    → 落库+审计。产物 append-only；账本零行值原文。
    """
    session: Session = db.session()
    try:
        project = _require_project(session, actor, project_id)

        replay = session.scalars(
            select(TransformRun).where(TransformRun.idempotency_key == idempotency_key)
        ).first()
        if replay is not None:
            if replay.project_id != project_id:
                raise _error("transform_run_not_found", "执行记录不存在。", 404)
            return replay.snapshot()

        plan_row = session.get(TransformPlan, plan_id)
        if plan_row is None or plan_row.project_id != project_id:
            raise _error("transform_plan_not_found", "转换计划不存在。", 404)

        # 纵深闸（§4.1）：落库计划执行前强制再过静态校验
        report = validate_plan(plan_row.plan_json)
        if not report["valid"]:
            raise _error(
                "invalid_transform_plan",
                "转换计划未通过静态校验。",
                400,
                detail={"validation": report},
            )

        kind = str((input_ref or {}).get("kind") or "")
        ref_id = str((input_ref or {}).get("file_version_id") or "").strip()
        if kind != "file_version" or not ref_id:
            raise _error("invalid_request", "input 须为 {kind: file_version, file_version_id}。", 400)
        version = _load_available_file_version(session, project_id, ref_id)
        # 同源校验（17 号 §2.2）：计划来源画像须与执行输入快照一致——画像缺失
        # ＝404 存在性隐藏（沿项目域惯例）；source_kind 二态不符或逐字节指纹
        # 不一致＝snapshot_mismatch 拒绝执行（快照漂移防线，零执行零落库）
        profile_row = session.get(DataProfile, plan_row.source_profile_id)
        if profile_row is None or profile_row.project_id != project.id:
            raise _error("transform_profile_not_found", "计划来源画像不存在。", 404)
        if profile_row.source_kind != "file" or (version.sha256 or "") != profile_row.input_sha256:
            raise _error(
                "snapshot_mismatch",
                "输入快照与计划来源画像不同源（指纹不一致或通道不符），拒绝执行。",
                400,
            )
        try:
            tables, truncated, parse_error_rows, source_row_count = _read_tables_from_version(
                session, version, plan_row.source_table,
            )
        except (ProfileError, UnicodeError, csv.Error):
            tables, truncated, parse_error_rows, source_row_count = {}, False, None, None
        if truncated or parse_error_rows != 0:
            # 不在部分输入上执行算子或出具质量结论。
            result: dict[str, Any] = {
                "status": "budget_exhausted" if truncated else "failed",
                "failure_reason": "max_input_rows" if truncated else "input_parse_errors",
                "conservation": {
                    "input_rows": None if truncated else source_row_count,
                    "output_rows": 0,
                    "rejected_rows": 0,
                    "overflow_count": 0,
                    "ok": None,
                },
            }
        else:
            result = execute_plan(plan_row.plan_json, tables)
        result["conservation"]["input_integrity"] = {
            "parse_error_rows": parse_error_rows,
            "truncated": truncated,
        }
        if result["status"] in ("failed", "budget_exhausted"):
            result["conservation"]["ok"] = None

        # 产物元数据与掩码层使用同一份声明投影。
        output_columns = plan_row.plan_json["output"]["columns"] if result["status"] == "succeeded" else []

        anchor = {
            "kind": "file_version",
            "file_version_id": version.id,
            "file_sha256": version.sha256 or "",
            "storage_key": version.storage_key,
            MASKED_OUTPUT_KEY: True,
        }
        output_rows = mask_transform_output(
            plan_row.plan_json, tables, result.get("output_rows") or [],
            report["dependency_graph"]["topological_order"],
        )
        run = TransformRun(
            project_id=project.id,
            plan_id=plan_row.id,
            plan_version=plan_row.plan_version,
            idempotency_key=idempotency_key,
            status=str(result["status"]),
            failure_reason=result.get("failure_reason"),
            input_anchor_json=anchor,
            output_rows_json=output_rows,
            output_row_count=int(result.get("output_row_count") or 0),
            output_columns_json=output_columns,
            reject_ledger_json=result.get("reject_ledger") or [],
            rejected_row_count=int(result.get("rejected_row_count") or 0),
            overflow_count=int(result.get("overflow_count") or 0),
            quality_report_json=result.get("quality_report") or {},
            lineage_json=result.get("lineage") or [],
            conservation_json=result.get("conservation") or {},
            created_by_user_id=actor.id,
        )
        session.add(run)
        session.flush()
        record_event(
            session,
            actor,
            "transform_run_submitted",
            project,
            {
                "run_id": run.id,
                "plan_id": plan_row.id,
                "status": run.status,
                "input_rows": (run.conservation_json or {}).get("input_rows"),
                "output_row_count": run.output_row_count,
                "rejected_row_count": run.rejected_row_count,
                "file_version_id": version.id,
            },
        )
        session.commit()
        return run.snapshot()
    finally:
        session.close()


def _load_available_file_version(session: Session, project_id: str, version_id: str):
    """files 版本锚加载：不存在=404；非 available（quarantined/deprecated 等）=400。"""
    from fde_api.files.models import ProjectFileVersion

    version = session.get(ProjectFileVersion, version_id)
    if version is None or version.project_file.project_id != project_id:
        raise _error("file_version_not_found", "输入文件版本不存在。", 404)
    if version.status != "available":
        raise _error("file_version_unavailable", "输入文件版本不可用（未通过可用状态闸）。", 400)
    return version


def _read_tables_from_version(
    session: Session, version, source_table: str,
) -> tuple[dict[str, list[dict[str, Any]]], bool, int | None, int | None]:
    """storage 读字节 → 解析为表行集（worker 域内直读，零行值出域）。

    解析复用画像底座（``_parse_csv``/``_parse_xlsx``）；任一表 ``truncated``
    ＝输入超画像解析上限 → 上层诚实 ``budget_exhausted``（17 号 §2.4 非静默
    截断）。
    """
    from fde_api.data_engineering.profiling import _parse_csv, _parse_xlsx
    from fde_api.extensions import object_storage
    from fde_api.storage.layout import current_layout, open_read_stream

    # M4 batch4 存储闸合规：读路径经布局翻译助手（回落序 legacy/dual_write/read_new/retired）
    with open_read_stream(
        object_storage.current, session, version.storage_key, layout=current_layout()
    ) as stream:
        data = stream.read()
    suffix = str(version.original_filename or "").lower().rsplit(".", 1)[-1]
    if suffix == "csv":
        parsed = _parse_csv(data, str(version.project_file.display_name or "table").rsplit(".", 1)[0], strict=True)
    elif suffix in ("xlsx", "xlsm"):
        parsed = _parse_xlsx(data)
    else:
        raise _error("unsupported_input_type", "输入文件类型不支持执行（仅 csv/xlsx）。", 400)
    tables = {table["name"]: list(table["rows"]) for table in parsed}
    truncated = any(table["truncated"] for table in parsed)
    parse_error_rows = sum(int(table["error_rows"]) for table in parsed)
    source_row_count = next(
        (int(table["row_count"]) + int(table["error_rows"]) for table in parsed if table["name"] == source_table),
        0,
    )
    return tables, truncated, parse_error_rows, source_row_count


def list_transform_runs(*, actor, project_id: str) -> list[dict[str, Any]]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        rows = session.scalars(
            select(TransformRun)
            .where(TransformRun.project_id == project_id)
            .order_by(TransformRun.created_at.desc())
        ).all()
        return [row.snapshot() for row in rows]
    finally:
        session.close()


def get_transform_run(*, actor, project_id: str, run_id: str) -> dict[str, Any]:
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        row = session.get(TransformRun, run_id)
        if row is None or row.project_id != project_id:
            raise _error("transform_run_not_found", "执行记录不存在。", 404)
        return row.snapshot()
    finally:
        session.close()


# ---- AF2-WP4 呈现面：四读面（run 落库件的只读派生视图，零落库零状态变更） ----

_PREVIEW_NOTE = (
    "样本预览用于早期检查（04 §3.2）；完整数据断言必须基于全量统计件"
    "（守恒/拒绝账本/质量报告），不能只用样本预览代替。"
)

_DIFF_NOTE = (
    "按弱守恒口径对照输入、产出和拒绝计数。join many_to_one 可合法展开产出行（17 号 §3.4）。"
    "按拒绝原因汇总已登记细目，超限拒绝仅计入 overflow；质量计数来自执行报告。"
)


def _load_run_or_404(session: Session, project_id: str, run_id: str) -> TransformRun:
    row = session.get(TransformRun, run_id)
    if row is None or row.project_id != project_id:
        raise _error("transform_run_not_found", "执行记录不存在。", 404)
    return row


def preview_transform_run(*, actor, project_id: str, run_id: str, limit: int) -> dict[str, Any]:
    """产物行集受控样本窗口（WP4 预览面）：limit 封顶由路由层执行；
    ``truncated``＝样本窗口小于落库产物行集。预览＝早期检查，样本性质随
    ``note`` 显式声明。"""
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        run = _load_run_or_404(session, project_id, run_id)
        sample_available = run.status == "succeeded" and run.input_anchor_json.get(MASKED_OUTPUT_KEY) is True
        rows = (run.output_rows_json or []) if sample_available else []
        sample = rows[:limit]
        return {
            "run_id": run.id,
            "status": run.status,
            "output_columns": run.output_columns_json or [],
            "total_row_count": run.output_row_count,
            "sample_available": sample_available,
            "sample_row_count": len(sample),
            "truncated": len(sample) < len(rows),
            "rows": sample,
            "note": _PREVIEW_NOTE,
        }
    finally:
        session.close()


def _conservation_verdict(run: TransformRun) -> bool | None:
    if run.status == "internal_inconsistency":
        return False
    if run.status != "succeeded" or not run.input_verified:
        return None
    verdict = (run.conservation_json or {}).get("ok")
    return verdict if isinstance(verdict, bool) else None


def diff_transform_run(*, actor, project_id: str, run_id: str) -> dict[str, Any]:
    """行数去向对照（WP4 差异面）：弱守恒口径下产出/拒绝/溢出三类去向，
    拒绝按 reason 分组；质量条目（``quality_*``＝保留行违规记录，非拒绝）
    单列 ``quality_flags`` 不与拒绝混淆（17 号 §3.3 两类账本条目的呈现区分）。"""
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        run = _load_run_or_404(session, project_id, run_id)
        conservation = run.conservation_json or {}
        rejected_by_reason: dict[str, int] = {}
        quality_flags: dict[str, int] = {}
        ledger = run.reject_ledger_json or []
        for entry in ledger:
            reason = str(entry.get("reason"))
            if not reason.startswith("quality_"):
                rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        for assertion in (run.quality_report_json or {}).values():
            violations = int(assertion.get("violations") or 0)
            if violations:
                reason = f"quality_{assertion['kind']}"
                quality_flags[reason] = quality_flags.get(reason, 0) + violations
        sample = ledger[:20]
        return {
            "run_id": run.id,
            "status": run.status,
            "input_rows": conservation.get("input_rows"),
            "input_integrity": conservation.get("input_integrity"),
            "failure_reason": run.failure_reason,
            "output_rows": run.output_row_count,
            "rejected_rows": run.rejected_row_count,
            "overflow_count": run.overflow_count,
            "destinations": {
                "output": run.output_row_count,
                "rejected_by_reason": rejected_by_reason,
                "quality_flags": quality_flags,
                "overflow": run.overflow_count,
            },
            "conservation_ok": _conservation_verdict(run),
            "ledger_sample": sample,
            "ledger_sample_truncated": len(sample) < len(ledger),
            "note": _DIFF_NOTE,
        }
    finally:
        session.close()


def lineage_transform_run(*, actor, project_id: str, run_id: str) -> dict[str, Any]:
    """两级血缘拼装（WP4 血缘呈现，17 号 §3.5）：计划静态 DAG
    （``validation_json.dependency_graph``）+ 执行级 per-step 统计
    （``lineage_json``）；执行步序与拓扑序不一致＝``steps_alignment`` false
    如实呈现（不静默）。"""
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        run = _load_run_or_404(session, project_id, run_id)
        plan_row = session.get(TransformPlan, run.plan_id)
        if plan_row is None or plan_row.project_id != project_id:
            raise _error("transform_run_not_found", "执行记录不存在。", 404)
        graph = (plan_row.validation_json or {}).get("dependency_graph") or {}
        topological_order = [str(node) for node in graph.get("topological_order") or []]
        executed_steps = [str(node.get("step_id")) for node in run.lineage_json or []]
        return {
            "run_id": run.id,
            "status": run.status,
            "plan_id": run.plan_id,
            "plan_version": run.plan_version,
            "plan_dag": {
                "nodes": [str(node) for node in graph.get("nodes") or []],
                "edges": graph.get("edges") or [],
                "topological_order": topological_order,
            },
            "execution_steps": run.lineage_json or [],
            "steps_alignment": executed_steps == topological_order,
            "final": {
                "output_row_count": run.output_row_count,
                "rejected_row_count": run.rejected_row_count,
                "overflow_count": run.overflow_count,
                "conservation_ok": _conservation_verdict(run),
            },
        }
    finally:
        session.close()


def quality_feedback_transform_run(*, actor, project_id: str, run_id: str) -> dict[str, Any]:
    """质量断言结构化反馈（WP4 反馈面，Agent/工程台可消费）：逐断言
    verdict + 违反计数；**零行值原文**——只含统计与定位类别（04 §3.2/
    17 号 §3.3），反馈面不给修正建议（防「丢坏行让通过率好看」的捷径诱导）。"""
    session: Session = db.session()
    try:
        _require_project(session, actor, project_id)
        run = _load_run_or_404(session, project_id, run_id)
        plan = session.get(TransformPlan, run.plan_id)
        if plan is None or plan.project_id != project_id:
            raise _error("transform_run_not_found", "执行记录不存在。", 404)
        graph = (plan.validation_json or {}).get("dependency_graph") or {}
        execution_steps = run.lineage_json or []
        complete = (
            run.status == "succeeded" and run.input_verified
            and [step["step_id"] for step in execution_steps] == graph.get("topological_order")
        )
        report = run.quality_report_json or {}
        assertions = []
        rejected_before = 0
        for step in execution_steps:
            step_id = step["step_id"]
            if step["op"] != "assert_quality" or step_id not in report:
                rejected_before += step.get("rejected_rows") or 0
                continue
            item = report[step_id]
            violations = int(item.get("violations") or 0)
            evaluated_rows = step.get("input_rows")
            if not complete:
                verdict = "incomplete"
            elif not evaluated_rows:
                verdict = "not_evaluated"
            elif violations:
                verdict = "fail"
            else:
                verdict = "incomplete" if rejected_before else "pass"
            assertions.append({
                "step_id": step_id,
                "kind": str(item.get("kind")),
                "column": str(item.get("column")),
                "evaluated_rows": evaluated_rows,
                "rejected_before": rejected_before,
                "violations": violations,
                "verdict": verdict,
            })
        failed = sum(1 for assertion in assertions if assertion["verdict"] == "fail") if complete else None
        return {
            "run_id": run.id,
            "status": run.status,
            "complete": complete,
            "input_row_count": (run.conservation_json or {}).get("input_rows") if run.input_verified else None,
            "overall": {
                "assertions_run": len(assertions),
                "assertions_failed": failed,
                "total_violations": sum(assertion["violations"] for assertion in assertions),
            },
            "assertions": assertions,
            "row_value_discipline": "反馈件零行值原文：仅断言统计与定位类别（04 §3.2 / 17 号 §3.3）。",
        }
    finally:
        session.close()
