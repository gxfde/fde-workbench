"""宿主代理回执落账（P2′① 约束 2/5/6；自 agents/service.py 拆出）。

拆分缘起：夜审修复 r5 迁移窗口（CR-045/048/053/059）给 agents/service.py
加回执写事务重校验后撞热点行数预算（test_source_size_budgets 1836）——
按 N1 补码轮先例把内聚的回执落账面拆成独立模块。

依赖形态：**顶层只依赖 adapter/models/extensions/zcode_contract**（单向）；
service 侧的 `_settings`/`_error`/`_verify_host_poll_token`/`_utcnow`/
`ARTIFACT_KINDS`/`FAILED_STATUSES` 一律**函数内惰性引用**——与
workflows/executor 拆分同款纪律：①不造顶层 import 环（architecture_purity
闸）；②保 monkeypatch `service._settings` 的测试语义（属性在调用时刻解析）。
对外名 `submit_host_receipt` 经 service 再导出——routes/tests 的
`svc.submit_host_receipt` 路径不变。
"""
from __future__ import annotations

from typing import Any

from fde_api.agents.adapter import AgentRunResult, ArtifactFile
from fde_api.agents.evidence_candidates import (
    evidence_kind_for_agent_run,
    register_agent_run_evidence_candidate,
)
from fde_api.agents.models import AgentArtifact, AgentRun
from fde_api.agents.workspace_files import is_unsafe_artifact_path
from fde_api.extensions import db
from fde_api.agents.zcode_contract import parse_json_summary


def submit_host_receipt(*, presented_token: str, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """宿主代理回执落账（P2′① 约束 2/5/6；幂等；H4 不自动重试）。

    与容器路径的关键差异：**产物原件在宿主磁盘**（红线：宿主工作区不入
    服务端），服务端不读文件算指纹——登记「宿主侧 sha256 + 路径」指针
    （约束 6 与红线同源）。终态语义与容器对齐：

    - ``exit_code == 0`` → completed（或零产物时如实 completed——宿主任务
      书是否要求 manifest 由宿主侧保证，``receipt_state`` 随载荷）；
    - ``exit_code != 0`` → failed；宿主报 timeout/budget_exceeded → 同名终态；
    - T2 评审门：solution 绑定场景当前不在宿主轮询载荷内（run 建时已无
      solution 上下文透传——首版宿主通道不接 solution 终审链，留 P1-1 后续），
      ``linked_solution_id=None``。
    - 幂等（CR-048 拍板 b 方案诚实化，2026-11-10）：终态后重复回执一律
      ``duplicate=True``——回执锚＝``host_receipt_at``，**载荷指纹比对未
      实现**（原「指纹不同 → 409」的承诺由本注记取代：自动指纹仲裁不做，
      冲突人工处置）；终态但缺回执锚 → 409 ``host_receipt_conflict``
      （人工介入）。
    - 宿主回执校验失败（invalid kind/unsafe path 等）不向宿主抛 422：
      状态机如实落 ``failed``（C-1 合同的可重试族不含外副作用），宿主侧
      收到 200 + ``failures`` 明细，重试/接管由人（H4）。
    """
    from fde_api.agents import service as _svc

    settings = _svc._settings()
    _svc._require_host_poll_enabled(settings)
    token_hash = _svc._verify_host_poll_token(settings, presented_token)

    allowed_keys = {"exit_code", "status", "summary", "artifacts", "token_cost", "duration_ms", "degraded", "degraded_reason"}
    if set(payload) - allowed_keys:
        raise _svc._error("invalid_request", "回执字段无效。")
    raw_summary = payload.get("summary")
    if not isinstance(raw_summary, dict):
        raise _svc._error("invalid_request", "summary 必填且为 --json 汇总对象。")

    with db.session() as session:
        run = session.get(AgentRun, run_id)
        if run is None:
            raise _svc._error("agent_run_not_found", "run 不存在。", 404, detail={"run_id": run_id})
        if run.execution_provider != "host_poll":
            raise _svc._error("host_receipt_rejected", "该 run 不属于宿主轮询通道。", 409, detail={"run_id": run_id})
        if run.host_token_hash is None:
            # 从未被领取：状态闸优先于令牌比对（信息最小暴露——不向未领取 run
            # 的提交方确认/否认任何令牌值）。
            raise _svc._error(
                "host_receipt_invalid_state",
                "该 run 未被领取或不在执行态。",
                409,
                detail={"run_id": run_id, "status": run.status},
            )
        if run.host_token_hash != token_hash:
            raise _svc._error("host_poll_forbidden", "回执令牌与领取不一致。", 403, detail={"run_id": run_id})
        if run.status in _svc.FAILED_STATUSES or run.status in ("completed", "succeeded_but_receipt_invalid"):
            if run.host_receipt_at is not None:
                return {"run_id": run_id, "status": run.status, "duplicate": True}
            raise _svc._error("host_receipt_conflict", "该 run 已终态且回执冲突，请人工介入。", 409, detail={"run_id": run_id})
        if run.status != "host_running":
            raise _svc._error(
                "host_receipt_invalid_state",
                "该 run 未被领取或不在执行态。",
                409,
                detail={"run_id": run_id, "status": run.status},
            )

    parsed = parse_json_summary(raw_summary)
    # QR-095（goal-crv r5 发现，goal-sprint r3 吸收）：exit_code 缺失/坏类型
    # 原缺省按 0＝「缺省即成功」——与容器面保守语义反向（宿主自报载荷是不
    # 可信面）。收口：非 int 一律 None；completed 终态**必须** int 0 支撑，
    # 缺失/非零的 completed 一律降 failed（fail-closed，人工按 failures
    # 处置）；timeout/budget_exceeded/failed 显式态不受影响（与 dev 直连
    # 同口径——timeout 路径 exit_code 本就为 None）。
    raw_exit = payload.get("exit_code")
    exit_code = raw_exit if isinstance(raw_exit, int) and not isinstance(raw_exit, bool) else None
    host_status = payload.get("status")
    if host_status not in ("completed", "timeout", "budget_exceeded", "failed"):
        host_status = "completed" if exit_code == 0 else "failed"
    elif host_status == "completed" and exit_code != 0:
        host_status = "failed"

    artifacts: list[ArtifactFile] = []
    host_digests: dict[str, str] = {}
    for item in payload.get("artifacts", []) or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        kind = item.get("kind")
        refs = item.get("source_refs")
        digest = item.get("sha256")
        if not isinstance(path, str) or not path or kind not in _svc.ARTIFACT_KINDS:
            continue
        if isinstance(digest, str) and len(digest) == 64:
            host_digests[path] = digest
        artifacts.append(
            ArtifactFile(
                path=path,
                kind=kind,
                source_refs=tuple(r for r in refs if isinstance(r, str)) if isinstance(refs, list) else (),
            )
        )

    token_cost = int(payload["token_cost"]) if isinstance(payload.get("token_cost"), int) and payload["token_cost"] >= 0 else parsed.billable_units
    result = AgentRunResult(
        status=host_status,
        exit_code=exit_code,
        token_cost=token_cost,
        duration_ms=int(payload["duration_ms"]) if isinstance(payload.get("duration_ms"), int) and payload["duration_ms"] >= 0 else 0,
        artifacts=tuple(artifacts),
        tool_calls=(),  # --json 无逐事件流（诚实缺失，与 dev 直连同口径）
        degraded=bool(payload.get("degraded")),
        degraded_reason=payload.get("degraded_reason") if isinstance(payload.get("degraded_reason"), str) else None,
    )

    # 回执时刻（幂等锚）+ 终态落账单事务；产物走宿主侧指纹直录（不读文件）
    now = _svc._utcnow()
    with db.session() as session, session.begin():
        # CR-048（拍板 b 方案）：读闸与写事务分离的 TOCTOU 收口——写事务内
        # 行锁重读后重校验状态；并发回执胜者已落终态时，败者如实 duplicate
        # （终态只落一次、产物行由 uq_agent_artifacts_run_storage_ref 兜底）。
        run_row = session.get(AgentRun, run_id, with_for_update=True)
        if run_row is None:
            raise _svc._error("agent_run_not_found", "run 不存在。", 404, detail={"run_id": run_id})
        if run_row.status in _svc.FAILED_STATUSES or run_row.status in ("completed", "succeeded_but_receipt_invalid"):
            if run_row.host_receipt_at is not None:
                return {"run_id": run_id, "status": run_row.status, "duplicate": True}
            raise _svc._error("host_receipt_conflict", "该 run 已终态且回执冲突，请人工介入。", 409, detail={"run_id": run_id})
        if run_row.status != "host_running":
            raise _svc._error(
                "host_receipt_invalid_state",
                "该 run 未被领取或不在执行态。",
                409,
                detail={"run_id": run_id, "status": run_row.status},
            )
        run_row.host_receipt_at = now
        if result.status == "completed":
            run_row.status = "completed"
            run_row.exit_code = result.exit_code
            run_row.token_cost = result.token_cost
            run_row.duration_ms = result.duration_ms
            for artifact in result.artifacts:
                digest = host_digests.get(artifact.path)
                if not digest:
                    # 指纹缺失/非法（非 64hex）：不落 AgentArtifact（红线：指纹
                    # 必须完整成对）——该校验失败已记入 failures 供人工处置。
                    continue
                if is_unsafe_artifact_path(artifact.path):
                    # QR-073（goal-crv r5 吸收）：unsafe 路径不登记指纹行——
                    # 宿主自报 path 是不可信面，防任意宿主文件伪装产物污染
                    # 证据链；该校验失败已记入 failures 供人工处置。
                    continue
                storage_ref = f"host:{run_id}/output/{artifact.path}"[:255]
                session.add(
                    AgentArtifact(
                        run_id=run_id,
                        kind=artifact.kind,
                        # 指针带 host: 前缀——与容器 storage_ref 语义区分
                        # （原件在宿主磁盘，服务端永不回读）。
                        storage_ref=storage_ref,
                        sha256=digest,
                        reviewed=False,
                        linked_solution_id=None,
                        derived_summary=None,  # 服务端无原件，可重建派生摘要不可算——诚实置空
                    )
                )
                # G-07：产物自动登记为**建议性证据候选**（captured_from=
                # agent_run:<run_id>）——与容器路径（artifact_persistence）同款。
                # 只登记不采纳：采纳仍走人工提交闸（gate_service.submit_gate_evidence），
                # 本登记不触碰清单项 claim_status 与门禁状态机（红线：AI 不代拍板）。
                # 仅 completed run 的产物登记——失败 run 的产物是「留痕」不是「候选」。
                register_agent_run_evidence_candidate(
                    session,
                    project_id=run_row.project_id,
                    run_id=run_id,
                    storage_ref=storage_ref,
                    content_sha256=digest,
                    kind=evidence_kind_for_agent_run(linked_solution_id=None),
                )
        elif result.status in _svc.FAILED_STATUSES:
            run_row.status = result.status
            run_row.exit_code = result.exit_code
            run_row.token_cost = result.token_cost
            run_row.duration_ms = result.duration_ms
        # 宿主侧产物校验（仓库内 C-1 同款规则，不读文件）：invalid kind/
        # unsafe path/缺 source_refs 只记 failures 不改终态——状态机诚实，
        # 人工按 failures 明细处置（H4）。
        failures: list[dict[str, Any]] = []
        for artifact in result.artifacts:
            problems: list[str] = []
            if artifact.kind not in _svc.ARTIFACT_KINDS:
                problems.append("invalid_kind")
            if not artifact.source_refs:
                problems.append("missing_source_refs")
            # QR-073（goal-crv r5 吸收）：盘符/反斜杠/根锚三形态并入 unsafe
            # 判定（单一真身 workspace_files.is_unsafe_artifact_path——宿主
            # 自报 path 恒为 POSIX 相对 output/ 文件名，含盘符/反斜杠即拒绝
            # 登记指纹，防任意宿主文件伪装产物污染证据链）。
            if is_unsafe_artifact_path(artifact.path):
                problems.append("unsafe_path")
            if artifact.path not in host_digests:
                problems.append("sha256_missing_in_receipt")
            if problems:
                failures.append({"path": artifact.path, "reasons": problems})

    return {"run_id": run_id, "status": result.status, "duplicate": False, "failures": failures}
