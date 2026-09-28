import io

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.auth.tokens import issue_access_token
from fde_api.workbench.models import ModuleCatalog


def test_presurvey_draft_uses_database_session_factory(client, db_session, settings, monkeypatch):
    user = User(
        username="project.draft.admin",
        display_name="Project Draft Admin",
        role="admin",
        password_hash=hash_password("InitialPass!234"),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.add(ModuleCatalog(
        module_key="pre_diagnosis",
        name="预调研",
        description="整理预调研信息",
        sort_order=1,
        is_active=True,
    ))
    db_session.commit()

    def fake_analyze(_self, **kwargs):
        messages = kwargs["build_messages"]("企业：测试企业")
        assert "pre_diagnosis（预调研）" in messages[0]["content"]
        return {
            "project": {"name": "测试项目", "enterprise_name": "测试企业"},
            "modules": [{"module_key": "pre_diagnosis", "name": "预调研", "tasks": []}],
        }

    monkeypatch.setattr("fde_api.ai.project_draft.KimiFileClient.analyze_docx_json", fake_analyze)
    response = client.post(
        "/api/v1/ai/project-draft/presurvey",
        headers={"Authorization": f"Bearer {issue_access_token(user, settings)}"},
        data={"file": (io.BytesIO(b"synthetic-docx"), "presurvey.docx")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["data"]["project"]["name"] == "测试项目"
    assert response.json["data"]["modules"][0]["module_key"] == "pre_diagnosis"
