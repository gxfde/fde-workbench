"""D26 ontology MCP 工具桥（§9.1 分级 → integrations 项目级代理）。

工具参数 project_id/binding_id 定位项目绑定；本体版本与租户一律由服务端注入
（S-13 绑定 pinned_version_id + D10 project.org_id），Agent 不可指定或篡改
（§13 M4 条 1）；execution_id 为每次 AI 执行的可审计编号（§9.3 运行追溯——
代理层把调用方身份映射为 runtime requested_by，I4 审批分离在 runtime 强制）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from fde_api.control.service import ControlServiceError

_FALLBACK = "本次工具调用失败。"


def call_ontology_tool(
    session: Session, *, user: Any, name: str, arguments: dict[str, Any], execution_id: str
) -> Any:
    from fde_api.integrations import service as binding_service
    from fde_api.integrations.service import BindingError

    project_id = str(arguments.get("project_id", ""))
    binding_id = str(arguments.get("binding_id", ""))
    if not project_id or not binding_id:
        raise ControlServiceError("invalid_request", "project_id 与 binding_id 必填。", 400)
    try:
        if name == "ontology_logic_run":
            logic_key = str(arguments.get("logic_key", ""))
            if not logic_key:
                raise ControlServiceError("invalid_request", "logic_key 必填。", 400)
            return binding_service.run_binding_logic(
                actor=user,
                project_id=project_id,
                binding_id=binding_id,
                logic_key=logic_key,
                payload={"input": arguments.get("input") or {}},
            )
        if name == "ontology_action_propose":
            action_key = str(arguments.get("action_key", ""))
            if not action_key:
                raise ControlServiceError("invalid_request", "action_key 必填。", 400)
            return binding_service.propose_binding_action(
                actor=user,
                project_id=project_id,
                binding_id=binding_id,
                action_key=action_key,
                payload={"input": arguments.get("input") or {}},
            )
        if name == "ontology_action_execute":
            action_key = str(arguments.get("action_key", ""))
            request_id = str(arguments.get("request_id", ""))
            if not action_key or not request_id:
                raise ControlServiceError(
                    "invalid_request", "action_key 与 request_id 必填。", 400
                )
            return binding_service.execute_binding_action(
                actor=user,
                project_id=project_id,
                binding_id=binding_id,
                action_key=action_key,
                payload={"request_id": request_id},
            )
        if name == "ontology_dry_validate":
            # AF0-C1（api-spec 1.3.6-af0）：纯候选预检——零状态变更，本体与钉版
            # 由绑定服务端注入（S-13），调用方只带 proposed_json。
            proposed_json = arguments.get("proposed_json")
            if not isinstance(proposed_json, dict):
                raise ControlServiceError("invalid_request", "proposed_json 必须是 JSON 对象。", 400)
            return binding_service.dry_validate_binding_candidate(
                actor=user,
                project_id=project_id,
                binding_id=binding_id,
                payload={"proposed_json": proposed_json},
            )
        raise ControlServiceError("invalid_tool", "工具或参数无效。", 400)
    except BindingError as exc:
        raise ControlServiceError(
            str(exc.code or "ontology_error"), str(exc) or _FALLBACK, int(exc.status)
        ) from exc
