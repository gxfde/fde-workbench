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


def test_dry_validate_requires_object_payload() -> None:
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


def test_dry_validate_dispatches_to_binding_service(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_dry_validate(*, actor, project_id, binding_id, payload):
        captured.update(project_id=project_id, binding_id=binding_id, payload=payload)
        return {"verdict": "pass", "violations": []}

    from fde_api.integrations import service as binding_service
    monkeypatch.setattr(binding_service, "dry_validate_binding_candidate", fake_dry_validate)
    out = ontology_gateway.call_ontology_tool(
        _NO_SESSION, user=_User(), name="ontology_dry_validate",
        arguments={"project_id": "p1", "binding_id": "b1", "proposed_json": {"objects": []}},
        execution_id="e1",
    )
    assert out == {"verdict": "pass", "violations": []}
    assert captured == {
        "project_id": "p1",
        "binding_id": "b1",
        "payload": {"proposed_json": {"objects": []}},
    }


def test_dry_validate_registered_in_gateway_branch() -> None:
    """分派注册钉：dry_validate 与既有三件同走 ontology 桥（execution_id
    强制在 mcp_gateway.call_tool 层——删除注册即本测试转红）。"""
    assert "ontology_dry_validate" in (
        "ontology_logic_run", "ontology_action_propose",
        "ontology_action_execute", "ontology_dry_validate",
    )
    from fde_api.control import mcp_gateway
    assert "ontology_dry_validate" in mcp_gateway.TOOLS
    descriptor = mcp_gateway.TOOLS["ontology_dry_validate"]
    assert descriptor[1] == "ontology.read"  # capability
    assert descriptor[3] == "read"  # effect（零状态变更）
