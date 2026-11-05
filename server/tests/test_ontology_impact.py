"""V3 T-I1：本体变更影响分析（设计 ontology-registry-v1 §5 用例 6；验收 O-6）。

引用合同 = 名字域纽带（服务层 impact_of_term 模块 docstring）：
- 生效名字域 = 血缘（根 + 并入来源）内规范名 ∪ 别名——merge_terms 把来源
  规范名转写为保留行别名、来源自有别名留在来源行（别名→merged→canonical
  链可解析），名字域闭包 = 全部可解析到同一概念的名字。
- subjects：ProjectResearchSubject.name 精确命中名字域（「一个名字一个概念」
  的读侧兑现；子串/大小写变体不算命中——纽带是唯一性不是相似度）。
- links：端点命中主体的邻接边（引用主体改名，边语义随动——设计「引用该
  term 的 links」）。
- forms：命中主体名下的表单（含现行修订状态；无修订为 None）。
- gates：门禁清单是 gates.json 冻结模板文本（template_hash 钉死，T-G2），
  无术语名表面——backlog 目标句的 gates 一词按验收权威 O-6 落为三面
  （偏差回写 backlog T-I1 实施记录，不发明方法论层没有的引用）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from test_document_drafts_api import _persist_project
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    _create_project,
    _subject_payload,
    admin_client,
    authorized_client_factory,
    leader_client,
    published_template,
)

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.api_catalog import CATALOG
from fde_api.ontology.models import OntologyTermAlias
from fde_api.ontology.service import (
    OntologyServiceError,
    create_term,
    impact_of_term,
    merge_terms,
)
from fde_api.research.models import (
    ProjectResearchForm,
    ProjectResearchFormRevision,
    ProjectResearchSubject,
    ProjectResearchSubjectLink,
)


def _actor(db_session, *, name: str) -> User:
    user = User(
        username=f"impact.{name}.{uuid4().hex[:8]}",
        display_name=name,
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _subject_row(db_session, project_id: str, *, subject_key: str, name: str):
    row = ProjectResearchSubject(
        project_id=project_id,
        subject_key=subject_key,
        name=name,
        subject_type="role",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _link_row(db_session, project_id: str, *, source, target, link_type: str):
    row = ProjectResearchSubjectLink(
        project_id=project_id,
        source_subject_id=source.id,
        target_subject_id=target.id,
        link_type=link_type,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _form_row(
    db_session,
    project_id: str,
    *,
    subject,
    form_key: str,
    name: str,
    revision_status: str | None = None,
):
    form = ProjectResearchForm(
        project_id=project_id, subject_id=subject.id, form_key=form_key, name=name
    )
    db_session.add(form)
    db_session.flush()
    if revision_status is not None:
        revision = ProjectResearchFormRevision(
            form_id=form.id, revision_number=1, status=revision_status
        )
        db_session.add(revision)
        db_session.flush()
        form.current_revision_id = revision.id
        db_session.flush()
    return form


def _membership_fixture(db_session):
    """保 留 行「会员」（+别名「会员单位」）+ 并入行「VIP客户」（+自有别名
    「大客户」）：merge 后名字域 = {会员, 会员单位, VIP客户, 大客户}。"""
    actor = _actor(db_session, name="fixture")
    project = _persist_project(db_session, actor, code=f"ONTO-IMP-{uuid4().hex[:6]}")
    kept = create_term(
        db_session,
        project_id=project.id,
        term="会员",
        definition="享受会员权益的客户群。",
        term_type="entity",
        actor=actor,
        initial_status="confirmed",
    )
    db_session.add(
        OntologyTermAlias(
            project_id=project.id,
            term_id=kept.id,
            alias="会员单位",
            created_by_user_id=actor.id,
        )
    )
    source = create_term(
        db_session,
        project_id=project.id,
        term="VIP客户",
        definition="高价值客户分群。",
        actor=actor,
        initial_status="confirmed",
    )
    db_session.add(
        OntologyTermAlias(
            project_id=project.id,
            term_id=source.id,
            alias="大客户",
            created_by_user_id=actor.id,
        )
    )
    db_session.commit()
    merge_terms(db_session, source_id=source.id, target_id=kept.id, actor=actor)
    db_session.commit()
    return actor, project, kept, source


def test_impact_resolves_name_domain_and_all_facets(db_session) -> None:
    """O-6：impact_of_term 返回引用它的 subjects/links/forms——名字域全命中
    （规范名/保留行别名/转写来源名/来源自有别名），子串不命中。"""
    actor, project, kept, source = _membership_fixture(db_session)

    s_kept = _subject_row(db_session, project.id, subject_key="kept", name="会员")
    s_alias = _subject_row(db_session, project.id, subject_key="alias", name="会员单位")
    s_transferred = _subject_row(
        db_session, project.id, subject_key="vip", name="VIP客户"
    )
    s_own_alias = _subject_row(
        db_session, project.id, subject_key="vip-alias", name="大客户"
    )
    s_substring = _subject_row(
        db_session, project.id, subject_key="substring", name="会员体系"
    )
    s_other = _subject_row(db_session, project.id, subject_key="other", name="供应链")
    _link_row(
        db_session,
        project.id,
        source=s_kept,
        target=s_other,
        link_type="opportunity_role",
    )
    _link_row(
        db_session,
        project.id,
        source=s_other,
        target=s_transferred,
        link_type="opportunity_process",
    )
    # 未命中主体之间的边不进影响面
    _link_row(
        db_session,
        project.id,
        source=s_substring,
        target=s_other,
        link_type="opportunity_role",
    )
    _form_row(
        db_session,
        project.id,
        subject=s_kept,
        form_key="interview",
        name="访谈表",
        revision_status="confirmed",
    )
    _form_row(
        db_session,
        project.id,
        subject=s_own_alias,
        form_key="baseline",
        name="基线表",
    )
    _form_row(
        db_session, project.id, subject=s_other, form_key="hidden", name="对照表"
    )
    db_session.commit()

    report = impact_of_term(db_session, project_id=project.id, term_id=kept.id)

    assert report["term"]["id"] == kept.id
    assert report["resolved"]["canonical_term_id"] == kept.id
    assert set(report["resolved"]["lineage_term_ids"]) == {kept.id, source.id}
    assert set(report["resolved"]["names"]) == {"会员", "会员单位", "VIP客户", "大客户"}
    via = {name: entry["via"] for name, entry in report["resolved"]["names"].items()}
    assert via == {
        "会员": "term",
        "会员单位": "alias",
        "VIP客户": "alias",
        "大客户": "alias",
    }
    owners = {
        name: entry["term_id"] for name, entry in report["resolved"]["names"].items()
    }
    assert owners["会员"] == kept.id and owners["会员单位"] == kept.id
    assert owners["VIP客户"] == kept.id  # 转写来源名归保留行
    assert owners["大客户"] == source.id  # 来源自有别名留在来源行

    matched = {row["name"]: row for row in report["subjects"]}
    assert set(matched) == {"会员", "会员单位", "VIP客户", "大客户"}
    assert matched["会员"]["matched_via"] == "term"
    assert matched["会员"]["matched_term_id"] == kept.id
    assert matched["大客户"]["matched_via"] == "alias"
    assert matched["大客户"]["matched_term_id"] == source.id
    assert matched["VIP客户"]["subject_type"] == "role"
    assert matched["会员"]["merged_into_subject_id"] is None
    assert {row["id"] for row in report["subjects"]} == {
        s_kept.id,
        s_alias.id,
        s_transferred.id,
        s_own_alias.id,
    }

    assert {
        (
            row["source_subject_name"],
            row["target_subject_name"],
            row["link_type"],
        )
        for row in report["links"]
    } == {
        ("会员", "供应链", "opportunity_role"),
        ("供应链", "VIP客户", "opportunity_process"),
    }
    assert all(
        row["source_subject_name"] is not None
        and row["target_subject_name"] is not None
        for row in report["links"]
    )

    assert {
        (row["form_key"], row["subject_name"], row["current_revision_status"])
        for row in report["forms"]
    } == {
        ("interview", "会员", "confirmed"),
        ("baseline", "大客户", None),
    }
    assert report["counts"] == {"subjects": 4, "links": 2, "forms": 2}


def test_impact_of_merged_row_resolves_to_canonical(db_session) -> None:
    """对并入行发起查询 = 查其存活概念的影响面（请求行原样，血缘解析到根）。"""
    actor, project, kept, source = _membership_fixture(db_session)
    _subject_row(db_session, project.id, subject_key="by-name", name="VIP客户")
    db_session.commit()

    report = impact_of_term(db_session, project_id=project.id, term_id=source.id)

    assert report["term"]["id"] == source.id
    assert report["term"]["status"] == "merged"
    assert report["resolved"]["canonical_term_id"] == kept.id
    assert set(report["resolved"]["names"]) == {"会员", "会员单位", "VIP客户", "大客户"}
    assert [row["name"] for row in report["subjects"]] == ["VIP客户"]
    # 转写来源名归保留行（merge_terms 别名转写）——名字现由保留行持有
    assert report["subjects"][0]["matched_via"] == "alias"
    assert report["subjects"][0]["matched_term_id"] == kept.id
    assert report["counts"] == {"subjects": 1, "links": 0, "forms": 0}


def test_impact_rejects_unknown_and_cross_project_term(db_session) -> None:
    actor = _actor(db_session, name="notfound")
    project = _persist_project(db_session, actor, code=f"ONTO-NF-{uuid4().hex[:6]}")
    other = _persist_project(db_session, actor, code=f"ONTO-NF2-{uuid4().hex[:6]}")
    theirs = create_term(
        db_session,
        project_id=other.id,
        term="他项术语",
        definition="别项目的概念。",
        actor=actor,
    )
    db_session.commit()

    with pytest.raises(OntologyServiceError) as missing:
        impact_of_term(db_session, project_id=project.id, term_id=str(uuid4()))
    assert missing.value.code == "term_not_found"
    assert missing.value.status == 404

    with pytest.raises(OntologyServiceError) as foreign:
        impact_of_term(db_session, project_id=project.id, term_id=theirs.id)
    assert foreign.value.code == "term_not_found"


def test_impact_without_references_returns_empty_facets(db_session) -> None:
    actor = _actor(db_session, name="empty")
    project = _persist_project(db_session, actor, code=f"ONTO-EMP-{uuid4().hex[:6]}")
    term = create_term(
        db_session,
        project_id=project.id,
        term="回款凭证",
        definition="客户回款的银行凭证指针。",
        actor=actor,
        initial_status="confirmed",
    )
    db_session.commit()

    report = impact_of_term(db_session, project_id=project.id, term_id=term.id)

    assert report["term"]["term"] == "回款凭证"
    assert report["resolved"]["canonical_term_id"] == term.id
    assert report["resolved"]["lineage_term_ids"] == [term.id]
    assert report["resolved"]["names"] == {
        "回款凭证": {"term_id": term.id, "via": "term"}
    }
    assert report["subjects"] == [] and report["links"] == []
    assert report["forms"] == []
    assert report["counts"] == {"subjects": 0, "links": 0, "forms": 0}


def test_impact_http_surface_and_access_control(
    admin_client, published_template, leader_client, authorized_client_factory, db_session
) -> None:
    """GET /ontology/terms/<id>/impact（can_view）：引用主体命中；外人 403、
    未知术语/项目 404。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    subjects_url = f"/api/v1/projects/{project_id}/research/subjects"
    root = next(
        item
        for item in admin_client.get(subjects_url).json["data"]["items"]
        if item["subject_type"] == "project"
    )
    role = admin_client.post(
        subjects_url, json=_subject_payload("role", subject_key="planner")
    )
    assert role.status_code == 201, role.get_data(as_text=True)

    term = create_term(
        db_session,
        project_id=project_id,
        term=root["name"],
        definition="项目主体本体。",
        actor=admin_client.user,
        initial_status="confirmed",
    )
    db_session.commit()
    impact_url = f"/api/v1/projects/{project_id}/ontology/terms/{term.id}/impact"

    listing = leader_client.get(impact_url)
    assert listing.status_code == 200, listing.get_data(as_text=True)
    data = listing.json["data"]
    assert data["term"]["id"] == term.id
    assert [row["name"] for row in data["subjects"]] == [root["name"]]
    assert data["subjects"][0]["matched_via"] == "term"
    assert data["counts"] == {"subjects": 1, "links": 0, "forms": 0}

    outsider = authorized_client_factory("fde_engineer")
    assert outsider.get(impact_url).status_code == 403

    missing = leader_client.get(
        f"/api/v1/projects/{project_id}/ontology/terms/{uuid4()}/impact"
    )
    assert missing.status_code == 404
    assert missing.json["error"]["code"] == "term_not_found"

    assert (
        leader_client.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000000"
            f"/ontology/terms/{term.id}/impact"
        ).status_code
        == 404
    )


def test_impact_route_never_in_catalog() -> None:
    """红线钉子：影响分析是人工评审读面，永不进 api_catalog（沿 T-O3 纪律，
    本体治理面 AI 不可直达）。"""
    paths = {str(entry["path"]) for entry in CATALOG.values()}
    assert not any("/ontology/terms" in path for path in paths)
    assert not any("ontology" in key for key in CATALOG)
