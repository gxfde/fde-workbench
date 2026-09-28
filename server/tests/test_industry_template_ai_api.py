from uuid import uuid4
import time

import pytest

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import ModuleCatalog
from test_industry_template_ai_draft import generated_payload


class FakeDeepSeek:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture
def ai_clients(client, app, db_session, settings):
    users = {}
    for role in ("admin", "project_lead"):
        user = User(
            username=f"{role}.ai",
            display_name=role,
            role=role,
            password_hash=hash_password("InitialPass!234"),
            must_change_password=False,
            is_active=True,
        )
        db_session.add(user)
        users[role] = user
    db_session.add_all(
        [ModuleCatalog(
            module_key="pre_diagnosis",
            name="预诊断",
            description="澄清目标",
            sort_order=1,
            is_active=True,
        ), ModuleCatalog(
            module_key="diagnosis",
            name="调研",
            description="开展调研",
            sort_order=2,
            is_active=True,
        )]
    )
    db_session.commit()
    return {
        role: {"Authorization": f"Bearer {issue_access_token(user, settings)}"}
        for role, user in users.items()
    }


def test_non_admin_cannot_use_industry_template_ai(client, ai_clients):
    response = client.post(
        "/api/v1/ai/industry-template/chat",
        headers=ai_clients["project_lead"],
        json={"messages": [{"role": "user", "content": "制造业"}]},
    )
    assert response.status_code == 403


def test_admin_chat_returns_validated_decision(client, app, ai_clients):
    app.extensions["fde_api_industry_deepseek"] = FakeDeepSeek(
        [
            {
                "status": "need_more_information",
                "message": "请补充目标",
                "known_information": {"industry": "制造业"},
                "missing_fields": ["business_goal"],
                "questions": ["最希望改善什么流程？"],
            }
        ]
    )
    response = client.post(
        "/api/v1/ai/industry-template/chat",
        headers=ai_clients["admin"],
        json={"messages": [{"role": "user", "content": "制造业"}]},
    )
    assert response.status_code == 200
    assert response.json["data"]["status"] == "need_more_information"
    assert response.json["data"]["questions"] == ["最希望改善什么流程？"]


def test_admin_chat_execution_exposes_live_status_and_result(client, app, ai_clients):
    app.extensions["fde_api_industry_deepseek"] = FakeDeepSeek([
        {
            "status": "ready_to_generate",
            "message": "信息已足够",
            "known_information": {"industry": "制造业"},
            "missing_fields": [],
            "questions": [],
        }
    ])
    started = client.post(
        "/api/v1/ai/executions",
        headers=ai_clients["admin"],
        json={
            "operation": "industry_template_chat",
            "payload": {"messages": [{"role": "user", "content": "制造业"}]},
        },
    )
    assert started.status_code == 202
    execution_id = started.json["data"]["id"]

    current = started
    for _attempt in range(50):
        current = client.get(
            f"/api/v1/ai/executions/{execution_id}?after=0",
            headers=ai_clients["admin"],
        )
        if current.json["data"]["status"] != "running":
            break
        time.sleep(0.02)

    assert current.status_code == 200
    assert current.json["data"]["status"] == "completed"
    assert current.json["data"]["result"]["status"] == "ready_to_generate"
    assert any(event["type"] == "stage_changed" for event in current.json["data"]["events"])


def test_admin_chat_repairs_harmless_model_shape_variations(client, app, ai_clients):
    app.extensions["fde_api_industry_deepseek"] = FakeDeepSeek(
        [{"status": "ready_to_generate", "message": "可以生成", "known_information": {"industry": "IoT"}, "extra_note": "ignore"}]
    )
    response = client.post(
        "/api/v1/ai/industry-template/chat",
        headers=ai_clients["admin"],
        json={"messages": [{"role": "user", "content": "IoT 行业，为客户做调研"}]},
    )
    assert response.status_code == 200
    assert response.json["data"]["status"] == "ready_to_generate"
    assert response.json["data"]["questions"] == []
    assert response.json["data"]["known_information"]["user_requirement"] == "IoT 行业，为客户做调研"


def test_admin_generation_creates_v1_draft(client, app, ai_clients):
    fake = FakeDeepSeek([generated_payload()])
    app.extensions["fde_api_industry_deepseek"] = fake
    response = client.post(
        "/api/v1/ai/industry-template/generate",
        headers=ai_clients["admin"],
        json={
            "generation_id": str(uuid4()),
            "messages": [{"role": "user", "content": "制造业，改善订单流程"}],
            "known_information": {"industry": "制造业"},
        },
    )
    assert response.status_code == 201
    assert response.json["data"]["status"] == "draft"
    assert response.json["data"]["version_number"] == 1


def test_admin_generation_supports_two_modules_without_research_forms(
    client, app, ai_clients
):
    payload = generated_payload()
    payload["research_definition"] = None
    payload["modules"].append({
        "module_key": "diagnosis",
        "name": "调研",
        "description": "",
        "sort_order": 2,
        "tasks": [{
            "task_key": "run_research",
            "name": "开展调研",
            "description": "",
            "duration_days": 2,
            "default_assignee_role": "fde_engineer",
            "sort_order": 1,
            "dependency_keys": ["collect_info"],
        }],
    })
    app.extensions["fde_api_industry_deepseek"] = FakeDeepSeek([payload])

    response = client.post(
        "/api/v1/ai/industry-template/generate",
        headers=ai_clients["admin"],
        json={
            "generation_id": str(uuid4()),
            "messages": [{"role": "user", "content": "只要预调研和调研模块，不生成调研表"}],
            "known_information": {"enterprise": "示例制造企业"},
        },
    )

    assert response.status_code == 201
    assert [item["module_key"] for item in response.json["data"]["modules"]] == [
        "pre_diagnosis", "diagnosis"
    ]


def test_cancelled_generation_does_not_call_deepseek(client, app, ai_clients):
    fake = FakeDeepSeek([generated_payload()])
    app.extensions["fde_api_industry_deepseek"] = fake
    generation_id = str(uuid4())
    cancelled = client.delete(
        f"/api/v1/ai/industry-template/generations/{generation_id}",
        headers=ai_clients["admin"],
    )
    assert cancelled.status_code == 200

    response = client.post(
        "/api/v1/ai/industry-template/generate",
        headers=ai_clients["admin"],
        json={
            "generation_id": generation_id,
            "messages": [{"role": "user", "content": "制造业"}],
            "known_information": {},
        },
    )
    assert response.status_code == 409
    assert response.json["error"]["code"] == "generation_cancelled"
    assert fake.calls == []
