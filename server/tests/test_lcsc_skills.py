"""No live storefront or model provider calls in automated tests."""
from unittest.mock import Mock

import pytest
from uuid import uuid4
from cryptography.fernet import Fernet

from fde_api.auth.models import User
from fde_api.auth.tokens import issue_access_token
from fde_api.control.lcsc_browser import _safe_url
from fde_api.control.chat_cost import estimate_chat_cost
from fde_api.control.lcsc_skills import _baseline_select, _cost, _jev_key, _jev_select, run_lcsc_skill
from fde_api.control.model_preferences import ModelPreference
from fde_api.control.service import ControlServiceError


@pytest.fixture(autouse=True)
def fake_default_judge(monkeypatch):
    judge = Mock(return_value=({"index": 0, "selection": "general_model"},
        {"input_tokens": 120, "output_tokens": 8}, "default-test-model", {"cny_estimate": "0.001"}, 30))
    monkeypatch.setattr("fde_api.control.lcsc_desktop.general_select", judge)
    return judge


def test_storefront_navigation_is_allowlisted():
    assert _safe_url("https://so.szlcsc.com/global.html?k=C8734")
    for candidate in ("http://www.szlcsc.com/", "https://evil.example/", "https://www.szlcsc.com.evil.example/", "file:///etc/passwd"):
        with pytest.raises(ControlServiceError):
            _safe_url(candidate)


def test_baseline_prefers_exact_model_without_jev():
    candidates = [{"title": "STM32F103CBT6"}, {"title": "STM32F103C8T6"}]
    assert _baseline_select("STM32F103C8T6", candidates)["index"] == 1
    assert _baseline_select("resistor", candidates)["selection"] == "site_rank"


def test_jev_uses_actual_choice_and_reported_usage(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    response = Mock()
    response.json.return_value = {"model": "jev-1.13.0", "answers": {"best_match": {
        "choice": "product_1", "confidence": 0.91, "probabilities": {"product_0": 0.09, "product_1": 0.91, "no_match": 0}}},
        "usage": {"input_tokens": 540, "output_tokens": 46}}
    post = Mock(return_value=response)
    monkeypatch.setattr("fde_api.control.lcsc_skills.requests.post", post)
    candidates = [{"title": "Other", "visible_text": "Other"}, {"title": "C8734", "visible_text": "C8734"}]
    selection, usage, model = _jev_select("C8734", candidates)
    assert selection["index"] == 1
    assert usage == {"input_tokens": 540, "output_tokens": 46}
    assert model == "jev-1.13.0"
    assert post.call_args.kwargs["json"]["questions"]["best_match"]["type"] == "choice"


def test_jev_never_silently_falls_back(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ControlServiceError) as error:
        _jev_select("C8734", [{"title": "C8734", "visible_text": "C8734"}])
    assert error.value.code == "jev_not_configured"


def test_cost_uses_real_tokens_and_dated_fx(monkeypatch):
    response = Mock()
    response.json.return_value = {"rates": {"CNY": 6.7}, "date": "2026-09-21"}
    monkeypatch.setattr("fde_api.control.lcsc_skills.requests.get", Mock(return_value=response))
    value = _cost({"input_tokens": 1_000_000, "output_tokens": 10})
    assert value["cny_estimate"] == "0.281400"
    assert value["fx_date"] == "2026-09-21"
    assert _cost({})["cny_estimate"] == "0"


def test_browser_run_is_durable_idempotent_and_private(app, client, db_session, settings, monkeypatch):
    user = User(username=f"lcsc-{uuid4().hex}", display_name="LCSC tester",
                password_hash="unused", role="viewer", is_active=True, must_change_password=False)
    other = User(username=f"lcsc-{uuid4().hex}", display_name="Other",
                 password_hash="unused", role="viewer", is_active=True, must_change_password=False)
    db_session.add_all([user, other])
    db_session.commit()
    browser = Mock(return_value=([{"title": "STM32F103C8T6", "url": "https://item.szlcsc.com/9243.html",
                                   "visible_text": "编号 C8734 1+ ￥9.89"}],
                                 [{"at_ms": 1, "action": "navigate", "detail": "打开立创商城"}],
                                 "https://so.szlcsc.com/global.html?k=STM32F103C8T6"))
    monkeypatch.setattr("fde_api.control.lcsc_skills.search_storefront", browser)
    with app.app_context():
        identifier = str(uuid4())
        first = run_lcsc_skill(user=user, execution_id=identifier, skill_key="lcsc-browser-baseline", query="STM32F103C8T6")
        repeated = run_lcsc_skill(user=user, execution_id=identifier, skill_key="lcsc-browser-baseline", query="STM32F103C8T6")
        assert first["id"] == repeated["id"]
        assert first["result"]["selected_product"]["title"] == "STM32F103C8T6"
        assert first["models"][0]["model"] == "default-test-model"
        assert first["usage"]["input_tokens"] == 120
        assert browser.call_count == 1
        own = client.get(f"/api/v1/ai/lcsc-runs/{first['id']}", headers={"Authorization": "Bearer " + issue_access_token(user, settings)})
        denied = client.get(f"/api/v1/ai/lcsc-runs/{first['id']}", headers={"Authorization": "Bearer " + issue_access_token(other, settings)})
        assert own.status_code == 200
        assert denied.status_code == 404


def test_direct_use_runs_both_versions_and_keeps_their_records_private(client, db_session, settings, monkeypatch):
    user = User(username=f"lcsc-{uuid4().hex}", display_name="Direct tester",
                password_hash="unused", role="viewer", is_active=True, must_change_password=False)
    other = User(username=f"lcsc-{uuid4().hex}", display_name="Other",
                 password_hash="unused", role="viewer", is_active=True, must_change_password=False)
    db_session.add_all([user, other])
    db_session.commit()
    monkeypatch.setattr("fde_api.control.lcsc_skills.search_storefront", Mock(return_value=([
        {"title": "STM32F103C8T6", "url": "https://item.szlcsc.com/9243.html", "visible_text": "编号 C8734"}],
        [{"at_ms": 1, "action": "navigate", "detail": "打开商城"}], "https://so.szlcsc.com/global.html?k=STM32F103C8T6")))
    jev = Mock(return_value=({"index": 0, "selection": "jev_choice", "confidence": 0.9},
                             {"input_tokens": 120, "output_tokens": 8}, "jev-1.13.0"))
    monkeypatch.setattr("fde_api.control.lcsc_skills._jev_select", jev)
    monkeypatch.setattr("fde_api.control.lcsc_skills._cost", lambda usage: {"cny_estimate": "0.001" if usage else "0"})
    headers = {"Authorization": "Bearer " + issue_access_token(user, settings)}
    for key in ("lcsc-browser-baseline", "lcsc-browser-jev"):
        response = client.post("/api/v1/ai/lcsc-runs", headers=headers,
                               json={"skill_key": key, "query": "STM32F103C8T6"})
        assert response.status_code == 200, response.json
        assert response.json["data"]["status"] == "succeeded"
        assert response.json["data"]["skill_key"] == key
    assert jev.call_count == 1
    items = client.get("/api/v1/ai/lcsc-runs", headers=headers).json["data"]["items"]
    assert {item["skill_key"] for item in items} == {"lcsc-browser-baseline", "lcsc-browser-jev"}
    other_headers = {"Authorization": "Bearer " + issue_access_token(other, settings)}
    assert client.get("/api/v1/ai/lcsc-runs", headers=other_headers).json["data"]["items"] == []
    assert client.post("/api/v1/ai/lcsc-runs", headers=headers, json={"query": "C8734"}).status_code == 400


def test_chat_cost_fails_closed_without_complete_provider_usage(monkeypatch):
    assert estimate_chat_cost({"complete": False, "calls": []})["cny_estimate"] is None
    assert estimate_chat_cost({"complete": True, "calls": [{"model": "unknown", "input_tokens": 20}]})["cny_estimate"] is None
    assert estimate_chat_cost({"complete": True, "calls": [{"model": "deepseek-flash", "input_tokens": 20,
        "output_tokens": 2, "cache_read_tokens": None, "cache_write_tokens": None}]})["cny_estimate"] is None


def test_jev_key_can_come_from_encrypted_personal_model_settings(app, db_session, monkeypatch):
    user = User(username=f"jev-{uuid4().hex}", display_name="Jev tester", password_hash="unused",
                role="viewer", is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.flush()
    cipher_key = Fernet.generate_key()
    app.config["MODEL_CREDENTIAL_KEY"] = cipher_key
    db_session.add(ModelPreference(scope="personal", owner_user_id=user.id, name="Jev", provider="typesafe",
        base_url="https://api.typesafe.ai/v1", model="jev-1.13.0", credential_ciphertext=Fernet(cipher_key).encrypt(b"private-test-key").decode(),
        is_default=False, supports_tools=False))
    db_session.add(ModelPreference(scope="public", owner_user_id=None, name="Shared Jev", provider="typesafe",
        base_url="https://api.typesafe.ai/v1", model="jev-1.13.0", credential_ciphertext=Fernet(cipher_key).encrypt(b"shared-test-key").decode(),
        is_default=False, supports_tools=False))
    db_session.commit()
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with app.app_context():
        assert _jev_key(user) == "private-test-key"


def test_unexpected_browser_error_is_recorded_without_details(app, db_session, monkeypatch):
    user = User(username=f"lcsc-{uuid4().hex}", display_name="LCSC tester", password_hash="unused",
                role="viewer", is_active=True, must_change_password=False)
    db_session.add(user)
    db_session.commit()
    monkeypatch.setattr("fde_api.control.lcsc_skills.search_storefront",
                        Mock(side_effect=RuntimeError("provider-secret-detail")))
    with app.app_context():
        run = run_lcsc_skill(user=user, execution_id=str(uuid4()), skill_key="lcsc-browser-baseline", query="C8734")
    assert run["status"] == "failed"
    assert run["error_code"] == "lcsc_unexpected_error"
    assert "provider-secret-detail" not in str(run)
