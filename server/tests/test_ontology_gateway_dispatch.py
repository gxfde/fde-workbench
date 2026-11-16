"""ontology_dry_validate 网关分派钉（AF1-WP1 第二批，AF0-C1）。

call_ontology_tool 直测：参数校验 400（binding 缺失由分派前置检查承担，
proposed_json 形状在网关面拦——不触 ensure_enabled/app 上下文）与分派到
binding_service（monkeypatch 假件，零出站）。
"""
from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.orm import Session

from fde_api.control import ontology_gateway
from fde_api.control.service import ControlServiceError

# 分派层直测：被测分支不触 session（分派前即校验/假件接管）——cast 钉形状。
_NO_SESSION = cast(Session, None)


class _User:
    id = "u-1"


def test_dry_validate_requires_candidate_list_payload() -> None:
    """AF1-WP1 收口批：proposed_json=候选条目数组（与 ChangeSet.proposed_json
    同形，api-spec 1.3.6-af0 实装语义；WP1 第二批误钉 JSON 对象——真服务
    端到端必 422，此处随实装对齐为 list 面）。"""
    with pytest.raises(ControlServiceError) as missing:
        ontology_gateway.call_ontology_tool(
            _NO_SESSION, user=_User(), name="ontology_dry_validate",
            arguments={"project_id": "p", "binding_id": "b"}, execution_id="e1",
        )
    assert missing.value.code == "invalid_request"
    with pytest.raises(ControlServiceError) as wrong_type:
        ontology_gateway.call_ontology_tool(
            _NO_SESSION, user=_User(), name="ontology_dry_validate",
            arguments={"project_id": "p", "binding_id": "b", "proposed_json": "nope"},
            execution_id="e1",
        )
    assert wrong_type.value.code == "invalid_request"
    with pytest.raises(ControlServiceError) as object_shape:
        ontology_gateway.call_ontology_tool(
            _NO_SESSION, user=_User(), name="ontology_dry_validate",
            arguments={"project_id": "p", "binding_id": "b", "proposed_json": {"objects": []}},
            execution_id="e1",
        )
    assert object_shape.value.code == "invalid_request"


def test_dry_validate_dispatches_to_binding_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_dry_validate(*, actor, project_id, binding_id, payload):
        captured.update(project_id=project_id, binding_id=binding_id, payload=payload)
        return {"verdict": "pass", "violations": []}

    from fde_api.integrations import service as binding_service
    monkeypatch.setattr(binding_service, "dry_validate_binding_candidate", fake_dry_validate)
    candidate_items: list[dict[str, object]] = [
        {
            "op": "create",
            "entity_type": "property_definitions",
            "entity_key": "equipment_serial_no",
            "payload": {
                "display_name": "设备序列号",
                "object_type_id": "equipment",
                "data_type": "string",
            },
        }
    ]
    out = ontology_gateway.call_ontology_tool(
        _NO_SESSION, user=_User(), name="ontology_dry_validate",
        arguments={
            "project_id": "p1", "binding_id": "b1", "proposed_json": candidate_items,
        },
        execution_id="e1",
    )
    assert out == {"verdict": "pass", "violations": []}
    assert captured == {
        "project_id": "p1",
        "binding_id": "b1",
        "payload": {"proposed_json": candidate_items},
    }


def test_call_tool_dispatches_dry_validate_through_ontology_bridge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """真闸钉：走 mcp_gateway.call_tool 全链（闭集校验/能力交集/execution_id
    强制/分派元组）——分派元组删名或 execution_id 缺失均转红。"""
    from fde_api.control import mcp_gateway, ontology_gateway

    captured: dict[str, object] = {}

    def fake_bridge(session, *, user, name, arguments, execution_id):
        captured.update(name=name, arguments=dict(arguments), execution_id=execution_id)
        return {"verdict": "pass", "violations": []}

    monkeypatch.setattr(ontology_gateway, "call_ontology_tool", fake_bridge)
    candidate_items: list[dict[str, object]] = [
        {
            "op": "create",
            "entity_type": "property_definitions",
            "entity_key": "equipment_serial_no",
            "payload": {
                "display_name": "设备序列号",
                "object_type_id": "equipment",
                "data_type": "string",
            },
        }
    ]
    out = mcp_gateway.call_tool(
        _NO_SESSION,
        user=_User(),
        claims={"execution_id": "e1"},
        allowed=["ontology.read"],
        name="ontology_dry_validate",
        arguments={
            "project_id": "p1", "binding_id": "b1", "proposed_json": candidate_items,
        },
    )
    assert out == {"verdict": "pass", "violations": []}
    assert captured == {
        "name": "ontology_dry_validate",
        "arguments": {
            "project_id": "p1", "binding_id": "b1", "proposed_json": candidate_items,
        },
        "execution_id": "e1",
    }
    with pytest.raises(ControlServiceError) as excinfo:
        mcp_gateway.call_tool(
            _NO_SESSION,
            user=_User(),
            claims={"execution_id": ""},
            allowed=["ontology.read"],
            name="ontology_dry_validate",
            arguments={"project_id": "p", "binding_id": "b", "proposed_json": {}},
        )
    assert excinfo.value.code == "invalid_request"
