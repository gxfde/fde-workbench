"""V3 T-O1：术语表 ontology_terms/aliases（设计 ontology-registry-v1 §2.2，验收 §5 用例 3/4）
+ V3 T-O2：关系/对象类型注册表 ontology_relation_types（§2.3，验收 §5 用例 7）。

T-O1：
- 唯一约束：同项目同名 409 term_exists（服务层预检，并发撞墙由保存点读回
  赢家）；名字被既有别名占用同样 409（一个名字一个概念）；跨项目同名互不干扰。
- 状态机：draft→confirmed 拍板（confirmed_by/at、version 递增）；confirmed
  不可重复确认/原地改（409 term_immutable，用例 3——服务层无 definition 编辑
  路径，修订走 T-O3 change_set 新版本）；终态不能再确认。
- 合并保留来源（用例 4）：source→merged 指向 target、target 转写获得 source
  规范名为别名、曾并入 source 的行重指 target（链一跳化）、逐项
  OperationEvent；重复合并/终态目标/跨项目/并入自身一律 409。
- DB 约束：merged 无 canonical 被 CHECK 拒；非法 term_type/status 被 CHECK 拒；
  别名同项目唯一（DB 层）。
- 零路由钉子：ontology 术语面不进 api_catalog（AI 候选只进 change_set，T-O3）。

T-O2：
- 注册表把「关系类型白名单硬编码 2 种」「对象类型 CheckConstraint 硬编码」
  （审计附录 D ②③）的扩展面变成可登记；内置两类关系类型的端点约束是存量
  语义（冻结），注册表不得覆盖内置码（409 duplicate_code）。
- ∪ 接入：_validate_link 改为「内置优先 + 注册表」——内置码的方向校验不被
  放开（backlog 风险条）；注册类型按端点约束放行/拒绝；retired 类型禁新边
  （409 link_type_retired）、存量边只读；未知类型仍 422。
- 作用域：project_id=NULL 是全局类型（仅 admin 可建），项目内类型遮蔽同名
  全局类型；同作用域同 (kind, code) 唯一。
- 红线钉子：类型注册面是人工路径，不进 api_catalog（AI 候选走 change_set，
  T-O3）。
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from test_document_drafts_api import _persist_project
from test_research_subjects_api import (  # noqa: F401  (pytest fixture)
    AuthorizedClient,
    _create_project,
    _project_payload,
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
from fde_api.ontology.models import OntologyRelationType, OntologyTerm, OntologyTermAlias
from fde_api.ontology.service import (
    BUILTIN_LINK_TYPE_CODES,
    BUILTIN_SUBJECT_TYPE_CODES,
    OntologyServiceError,
    confirm_term,
    create_term,
    find_relation_type,
    list_relation_types,
    merge_terms,
    register_relation_type,
    retire_relation_type,
    serialize_relation_type,
    serialize_term,
)
from fde_api.research.models import SUBJECT_TYPES
from fde_api.research.subject_service import LINK_SUBJECT_TYPES
from fde_api.workbench.models import OperationEvent


def _actor(db_session, *, name: str) -> User:
    user = User(
        username=f"onto.{name}.{uuid4().hex[:8]}",
        display_name=name,
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    return user


def _term_rows(db_session, project_id: str) -> list[OntologyTerm]:
    return list(
        db_session.scalars(
            select(OntologyTerm)
            .where(OntologyTerm.project_id == project_id)
            .order_by(OntologyTerm.created_at.asc(), OntologyTerm.id.asc())
        )
    )


def _alias_names(db_session, project_id: str) -> set[str]:
    return set(
        db_session.scalars(
            select(OntologyTermAlias.alias).where(
                OntologyTermAlias.project_id == project_id
            )
        )
    )


def _events(db_session, project_id: str) -> list[OperationEvent]:
    return list(
        db_session.scalars(
            select(OperationEvent)
            .where(
                OperationEvent.project_id == project_id,
                OperationEvent.event_type == "ontology_term_merged",
            )
            .order_by(OperationEvent.occurred_at.asc(), OperationEvent.id.asc())
        )
    )


def test_term_lifecycle_and_confirmed_immutability(db_session) -> None:
    actor = _actor(db_session, name="lifecycle")
    project = _persist_project(db_session, actor, code=f"ONTO-LC-{uuid4().hex[:6]}")

    draft = create_term(
        db_session,
        project_id=project.id,
        term="  回款凭证  ",
        definition="客户回款的银行凭证扫描件指针。",
        term_type="entity",
        actor=actor,
    )
    db_session.commit()
    assert draft.term == "回款凭证" and draft.status == "draft"
    assert draft.term_type == "entity" and draft.version == 1
    assert draft.created_by_user_id == actor.id
    assert draft.confirmed_by_user_id is None and draft.confirmed_at is None

    confirmed = confirm_term(db_session, term_id=draft.id, actor=actor)
    db_session.commit()
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_by_user_id == actor.id
    assert confirmed.confirmed_at is not None
    assert confirmed.version == 2
    assert serialize_term(confirmed)["confirmed_at"] is not None

    # 用例 3：confirmed 不可原地改——重确认 409；服务层不提供 definition 编辑路径
    with pytest.raises(OntologyServiceError) as immutable:
        confirm_term(db_session, term_id=draft.id, actor=actor)
    assert immutable.value.code == "term_immutable"
    assert immutable.value.status == 409

    # 终态不能再确认（merged 行见合并用例；这里直接落一行终态验证守卫）
    other = create_term(
        db_session,
        project_id=project.id,
        term="验收单",
        definition="客户签署的验收文件。",
        actor=actor,
    )
    other.status = "superseded"
    db_session.commit()
    with pytest.raises(OntologyServiceError) as transition:
        confirm_term(db_session, term_id=other.id, actor=actor)
    assert transition.value.code == "invalid_transition"


def test_term_input_normalization_rejects_invalid(db_session) -> None:
    actor = _actor(db_session, name="normalize")
    project = _persist_project(db_session, actor, code=f"ONTO-NF-{uuid4().hex[:6]}")

    for bad_term in ("   ", "x" * 121):
        with pytest.raises(OntologyServiceError) as invalid:
            create_term(
                db_session,
                project_id=project.id,
                term=bad_term,
                definition="d",
                actor=actor,
            )
        assert invalid.value.code == "invalid_request"
        assert invalid.value.status == 400
        assert "term" in invalid.value.message

    with pytest.raises(OntologyServiceError) as blank_definition:
        create_term(
            db_session,
            project_id=project.id,
            term="指标",
            definition="   ",
            actor=actor,
        )
    assert blank_definition.value.code == "invalid_request"
    assert "definition" in blank_definition.value.message

    with pytest.raises(OntologyServiceError) as bad_type:
        create_term(
            db_session,
            project_id=project.id,
            term="指标",
            definition="d",
            term_type="relation",
            actor=actor,
        )
    assert bad_type.value.code == "invalid_request"

    with pytest.raises(OntologyServiceError) as bad_status:
        create_term(
            db_session,
            project_id=project.id,
            term="指标",
            definition="d",
            actor=actor,
            initial_status="published",
        )
    assert bad_status.value.code == "invalid_request"


def test_same_project_term_uniqueness_and_alias_collision(db_session) -> None:
    actor = _actor(db_session, name="unique")
    project = _persist_project(db_session, actor, code=f"ONTO-UQ-{uuid4().hex[:6]}")
    other = _persist_project(db_session, actor, code=f"ONTO-UQ2-{uuid4().hex[:6]}")

    kept = create_term(
        db_session,
        project_id=project.id,
        term="交付包",
        definition="一次交付的物量集合。",
        actor=actor,
    )
    merged = create_term(
        db_session,
        project_id=project.id,
        term="交付物量",
        definition="同「交付包」。",
        actor=actor,
    )
    db_session.commit()

    # 同项目同名 → 409（服务层预检）
    with pytest.raises(OntologyServiceError) as dup:
        create_term(
            db_session,
            project_id=project.id,
            term="交付包",
            definition="重复名。",
            actor=actor,
        )
    assert dup.value.code == "term_exists" and dup.value.status == 409

    # 合并后「交付物量」成为 kept 的别名：另立同名术语 → 409（别名占用）
    merge_terms(db_session, source_id=merged.id, target_id=kept.id, actor=actor)
    db_session.commit()
    with pytest.raises(OntologyServiceError) as alias_conflict:
        create_term(
            db_session,
            project_id=project.id,
            term="交付物量",
            definition="别名占用。",
            actor=actor,
        )
    assert alias_conflict.value.code == "term_exists"
    assert "别名" in alias_conflict.value.message

    # 跨项目同名互不干扰
    other_term = create_term(
        db_session,
        project_id=other.id,
        term="交付包",
        definition="另一个项目的同名术语。",
        actor=actor,
    )
    db_session.commit()
    assert other_term.project_id == other.id
    assert len(_term_rows(db_session, project.id)) == 2


def test_merge_preserves_provenance(db_session) -> None:
    """用例 4：合并保留来源 + 链一跳化 + 逐项 OperationEvent。"""
    actor = _actor(db_session, name="merge")
    project = _persist_project(db_session, actor, code=f"ONTO-MG-{uuid4().hex[:6]}")

    kept = create_term(
        db_session,
        project_id=project.id,
        term="交付包",
        definition="一次交付的物量集合。",
        actor=actor,
        initial_status="confirmed",
    )
    middle = create_term(
        db_session,
        project_id=project.id,
        term="交付物量",
        definition="同「交付包」的别名口径。",
        actor=actor,
        initial_status="confirmed",
    )
    leaf = create_term(
        db_session,
        project_id=project.id,
        term="交付物清单",
        definition="口径三。",
        actor=actor,
    )
    db_session.commit()
    kept_version = kept.version

    # 第一跳：leaf 并入 middle（target 允许 draft）
    first = merge_terms(db_session, source_id=leaf.id, target_id=middle.id, actor=actor)
    db_session.commit()
    assert leaf.status == "merged" and leaf.canonical_term_id == middle.id
    assert first["aliases_added"] == ["交付物清单"]
    assert _alias_names(db_session, project.id) == {"交付物清单"}

    # 第二跳：middle 并入 kept —— leaf 重指 kept（链一跳化），kept 获 middle 名为别名
    second = merge_terms(db_session, source_id=middle.id, target_id=kept.id, actor=actor)
    db_session.commit()
    assert middle.status == "merged" and middle.canonical_term_id == kept.id
    assert leaf.canonical_term_id == kept.id  # 重指向，不出现 merged→merged→…链
    assert second["aliases_added"] == ["交付物量"]
    assert _alias_names(db_session, project.id) == {"交付物清单", "交付物量"}
    assert kept.version == kept_version + 1  # 合并 target 版本递增（第一跳 target 是 middle）
    assert kept.definition == "一次交付的物量集合。"  # 合并不改写保留行定义
    # 合并保留来源：被并行仍可读，canonical 链一跳可解析
    rows = {row.id: row for row in _term_rows(db_session, project.id)}
    assert rows[leaf.id].status == "merged"

    # 逐项 OperationEvent（occurred_at+id 定序，T-W5 教训）
    events = _events(db_session, project.id)
    assert [event.target_id for event in events] == [leaf.id, middle.id]
    assert events[0].changes["canonical_term_id"] == middle.id
    assert events[1].changes["canonical_term_id"] == kept.id
    assert events[1].changes["repointed"] == 1
    assert events[1].changes["canonical_term"] == "交付包"

    # 409 族：重复合并 / 合并目标已并 / 被并源再并 / 并入自身 / 跨项目
    with pytest.raises(OntologyServiceError) as repeat:
        merge_terms(db_session, source_id=middle.id, target_id=kept.id, actor=actor)
    assert repeat.value.code == "term_already_merged"
    with pytest.raises(OntologyServiceError) as dead_target:
        merge_terms(db_session, source_id=kept.id, target_id=middle.id, actor=actor)
    assert dead_target.value.code == "merge_target_invalid"
    with pytest.raises(OntologyServiceError) as dead_source:
        merge_terms(db_session, source_id=leaf.id, target_id=kept.id, actor=actor)
    assert dead_source.value.code == "term_already_merged"
    with pytest.raises(OntologyServiceError) as self_merge:
        merge_terms(db_session, source_id=kept.id, target_id=kept.id, actor=actor)
    assert self_merge.value.code == "merge_invalid"
    other = _persist_project(db_session, actor, code=f"ONTO-MG2-{uuid4().hex[:6]}")
    foreign = create_term(
        db_session,
        project_id=other.id,
        term="外部术语",
        definition="别的项目。",
        actor=actor,
    )
    db_session.commit()
    with pytest.raises(OntologyServiceError) as cross:
        merge_terms(db_session, source_id=foreign.id, target_id=kept.id, actor=actor)
    assert cross.value.code == "merge_cross_project"


def test_alias_db_uniqueness(db_session) -> None:
    actor = _actor(db_session, name="alias")
    project = _persist_project(db_session, actor, code=f"ONTO-AL-{uuid4().hex[:6]}")
    kept = create_term(
        db_session,
        project_id=project.id,
        term="回款凭证",
        definition="客户回款的银行凭证。",
        actor=actor,
    )
    db_session.commit()
    db_session.add(
        OntologyTermAlias(
            project_id=project.id, term_id=kept.id, alias="回款单", created_by_user_id=actor.id
        )
    )
    db_session.commit()
    # 同项目重复别名被 UNIQUE 拒（DB 层口径）
    with pytest.raises(IntegrityError, match="uq_ontology_term_aliases_project_alias"):
        db_session.add(
            OntologyTermAlias(project_id=project.id, term_id=kept.id, alias="回款单")
        )
        db_session.flush()
    db_session.rollback()


def test_db_constraints_reject_invalid_states(db_session) -> None:
    actor = _actor(db_session, name="constraints")
    project = _persist_project(db_session, actor, code=f"ONTO-CR-{uuid4().hex[:6]}")

    # merged 无 canonical 被 CHECK 拒
    with pytest.raises(IntegrityError, match="ck_ontology_terms_merged_canonical"):
        db_session.add(
            OntologyTerm(
                project_id=project.id,
                term="孤儿合并",
                definition="merged 但无指向。",
                status="merged",
            )
        )
        db_session.flush()
    db_session.rollback()

    # 非法 term_type / status 被 CHECK 拒
    with pytest.raises(IntegrityError, match="ck_ontology_terms_term_type"):
        db_session.add(
            OntologyTerm(
                project_id=project.id, term="坏种类", definition="d", term_type="relation"
            )
        )
        db_session.flush()
    db_session.rollback()
    with pytest.raises(IntegrityError, match="ck_ontology_terms_status"):
        db_session.add(
            OntologyTerm(
                project_id=project.id, term="坏状态", definition="d", status="published"
            )
        )
        db_session.flush()
    db_session.rollback()


def test_ontology_write_paths_never_in_catalog() -> None:
    """红线钉子：AI 候选只进 change_set（T-O3），术语治理面不进 api_catalog。"""
    assert not any("ontology" in key for key in CATALOG)
    assert not any("/ontology" in str(entry["path"]) for entry in CATALOG.values())


# ---------------------------------------------------------------------------
# V3 T-O2：关系/对象类型注册表（设计 ontology-registry-v1 §2.3，验收 §5 用例 7）
# ---------------------------------------------------------------------------


def _register_type(db_session, project_id, actor, **overrides):
    payload = {
        "kind": "link_type",
        "code": "opportunity_risk",
        "allowed_source_types": ["opportunity"],
        "allowed_target_types": ["role"],
    }
    payload.update(overrides)
    return register_relation_type(db_session, project_id=project_id, actor=actor, **payload)


def test_relation_type_registration_validates_input_and_guards_duplicates(db_session) -> None:
    """注册表是受控面：内置码不可覆盖、同作用域不可重复、端点约束必须合法。"""
    actor = _actor(db_session, name="type-register")
    project = _persist_project(db_session, actor, code=f"ONTO-TY-{uuid4().hex[:6]}")

    row = _register_type(db_session, project.id, actor)
    db_session.commit()
    assert row.kind == "link_type" and row.code == "opportunity_risk"
    assert row.status == "active" and row.version == 1
    assert row.project_id == project.id
    assert row.allowed_source_types == ["opportunity"]
    assert row.allowed_target_types == ["role"]
    assert serialize_relation_type(row)["scope"] == "project"

    # 同作用域同 (kind, code) 不可重复
    with pytest.raises(OntologyServiceError) as duplicate:
        _register_type(db_session, project.id, actor)
    assert duplicate.value.code == "duplicate_code"
    assert duplicate.value.status == 409

    # 内置码不可被注册表覆盖（存量语义冻结）
    with pytest.raises(OntologyServiceError) as builtin_link:
        _register_type(
            db_session,
            project.id,
            actor,
            code="opportunity_role",
            allowed_source_types=["role"],
            allowed_target_types=["opportunity"],
        )
    assert builtin_link.value.code == "duplicate_code"
    with pytest.raises(OntologyServiceError) as builtin_subject:
        register_relation_type(
            db_session,
            project_id=project.id,
            actor=actor,
            kind="subject_type",
            code="role",
        )
    assert builtin_subject.value.code == "duplicate_code"

    # 输入校验：kind / code
    for bad_kind in ("relation", "", None):
        with pytest.raises(OntologyServiceError) as invalid_kind:
            register_relation_type(
                db_session,
                project_id=project.id,
                actor=actor,
                kind=bad_kind,
                code="x_edge",
            )
        assert invalid_kind.value.code == "invalid_request"
    for bad_code in ("Bad-Code", "9lead", "", "x" * 61):
        with pytest.raises(OntologyServiceError) as invalid_code:
            _register_type(db_session, project.id, actor, code=bad_code)
        assert invalid_code.value.code == "invalid_request"

    # 关系类型必须声明端点约束；对象类型不得声明端点约束
    with pytest.raises(OntologyServiceError) as no_endpoints:
        _register_type(
            db_session,
            project.id,
            actor,
            code="no_endpoints",
            allowed_source_types=[],
            allowed_target_types=[],
        )
    assert no_endpoints.value.code == "invalid_request"
    with pytest.raises(OntologyServiceError) as subject_endpoints:
        register_relation_type(
            db_session,
            project_id=project.id,
            actor=actor,
            kind="subject_type",
            code="system",
            allowed_source_types=["opportunity"],
        )
    assert subject_endpoints.value.code == "invalid_request"

    # 端点引用未登记的对象类型 → 400（先登记对象类型再登记关系类型）
    with pytest.raises(OntologyServiceError) as unknown_endpoint:
        _register_type(
            db_session,
            project.id,
            actor,
            code="ghost_edge",
            allowed_source_types=["opportunity"],
            allowed_target_types=["system"],
        )
    assert unknown_endpoint.value.code == "invalid_request"

    subject_row = register_relation_type(
        db_session,
        project_id=project.id,
        actor=actor,
        kind="subject_type",
        code="system",
    )
    db_session.commit()
    assert subject_row.status == "active"
    edge = _register_type(
        db_session,
        project.id,
        actor,
        code="system_edge",
        allowed_source_types=["opportunity"],
        allowed_target_types=["system"],
    )
    db_session.commit()
    assert edge.allowed_target_types == ["system"]


def test_global_scope_and_project_shadowing(db_session) -> None:
    """全局类型对所有项目生效；项目内类型遮蔽同名全局类型（端点约束可按项目定制）。"""
    actor = _actor(db_session, name="type-global")
    project = _persist_project(db_session, actor, code=f"ONTO-GL-{uuid4().hex[:6]}")
    other = _persist_project(db_session, actor, code=f"ONTO-GO-{uuid4().hex[:6]}")

    global_row = register_relation_type(
        db_session,
        project_id=None,
        actor=actor,
        kind="link_type",
        code="global_edge",
        allowed_source_types=["opportunity"],
        allowed_target_types=["role"],
    )
    db_session.commit()
    assert global_row.project_id is None
    assert serialize_relation_type(global_row)["scope"] == "global"

    scoped_row = register_relation_type(
        db_session,
        project_id=project.id,
        actor=actor,
        kind="link_type",
        code="global_edge",
        allowed_source_types=["opportunity"],
        allowed_target_types=["process"],
    )
    db_session.commit()
    assert scoped_row.project_id == project.id

    resolved = find_relation_type(
        db_session, project_id=project.id, kind="link_type", code="global_edge"
    )
    assert resolved is not None and resolved.id == scoped_row.id
    resolved_other = find_relation_type(
        db_session, project_id=other.id, kind="link_type", code="global_edge"
    )
    assert resolved_other is not None and resolved_other.id == global_row.id

    items = list_relation_types(db_session, project_id=project.id)
    assert [item.code for item in items].count("global_edge") == 1
    assert items[0].id == scoped_row.id
    other_items = list_relation_types(db_session, project_id=other.id)
    assert [item.id for item in other_items] == [global_row.id]


def test_builtin_types_are_frozen_and_pinned(db_session) -> None:
    """内置集合不得漂移；内置码不可注册——∪ 语义因此无法放开内置方向校验。"""
    actor = _actor(db_session, name="type-builtin")
    project = _persist_project(db_session, actor, code=f"ONTO-BI-{uuid4().hex[:6]}")

    # 漂移钉子：注册表的保留名单必须与 research 模块的内置集合一致
    assert set(SUBJECT_TYPES) == set(BUILTIN_SUBJECT_TYPE_CODES)
    assert set(LINK_SUBJECT_TYPES) == set(BUILTIN_LINK_TYPE_CODES)

    with pytest.raises(OntologyServiceError) as builtin:
        _register_type(
            db_session,
            project.id,
            actor,
            code="opportunity_role",
            allowed_source_types=["role"],
            allowed_target_types=["opportunity"],
        )
    assert builtin.value.code == "duplicate_code"


def test_relation_type_db_constraints_reject_invalid_states(db_session) -> None:
    """DB 层兜底：非法 kind/status、关系类型缺端点约束、端点非数组一律被拒。"""
    actor = _actor(db_session, name="type-db")
    project = _persist_project(db_session, actor, code=f"ONTO-DB-{uuid4().hex[:6]}")
    db_session.commit()

    with pytest.raises(IntegrityError, match="ck_ontology_relation_types_kind"):
        db_session.add(
            OntologyRelationType(
                project_id=project.id, kind="relation", code="bad_kind"
            )
        )
        db_session.flush()
    db_session.rollback()
    with pytest.raises(IntegrityError, match="ck_ontology_relation_types_status"):
        db_session.add(
            OntologyRelationType(
                project_id=project.id,
                kind="link_type",
                code="bad_status",
                allowed_source_types=["opportunity"],
                allowed_target_types=["role"],
                status="published",
            )
        )
        db_session.flush()
    db_session.rollback()
    with pytest.raises(IntegrityError, match="ck_ontology_relation_types_link_endpoints"):
        db_session.add(
            OntologyRelationType(
                project_id=project.id,
                kind="link_type",
                code="no_endpoints",
                allowed_source_types=[],
                allowed_target_types=[],
            )
        )
        db_session.flush()
    db_session.rollback()
    with pytest.raises(IntegrityError, match="ck_ontology_relation_types_endpoints_json"):
        db_session.execute(
            text(
                "INSERT INTO ontology_relation_types "
                "(id, project_id, kind, code, allowed_source_types, allowed_target_types, "
                "status, created_at, updated_at) "
                "VALUES (:id, :project_id, 'link_type', 'bad_json', '{\"a\": 1}', '[]', "
                "'active', now(), now())"
            ),
            {"id": str(uuid4()), "project_id": project.id},
        )
        db_session.flush()
    db_session.rollback()


def test_relation_type_http_surface_and_link_lifecycle(
    admin_client, published_template, leader_client, authorized_client_factory
) -> None:
    """用例 7：注册新 link_type→建边成功；retired 后建边 409、存量边可读。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    registry_url = f"/api/v1/projects/{project_id}/ontology/relation-types"
    subjects_url = f"/api/v1/projects/{project_id}/research/subjects"

    def _root_subject():
        items = admin_client.get(subjects_url).json["data"]["items"]
        return next(item for item in items if item["subject_type"] == "project")

    root = _root_subject()
    role = admin_client.post(subjects_url, json=_subject_payload("role", subject_key="planner"))
    assert role.status_code == 201, role.get_data(as_text=True)
    role_id = role.json["data"]["id"]

    # 未登记的类型不可建边（既有行为不变）
    unknown = admin_client.post(
        f"{subjects_url}/{root['id']}/links",
        json={
            "version": _root_subject()["version"],
            "target_subject_id": role_id,
            "link_type": "project_role",
        },
    )
    assert unknown.status_code == 422, unknown.get_data(as_text=True)
    assert unknown.json["error"]["code"] == "invalid_research_subject_link"

    # 登记类型（can_manage）
    registered = admin_client.post(
        registry_url,
        json={
            "kind": "link_type",
            "code": "project_role",
            "label": "项目到岗位",
            "allowed_source_types": ["project"],
            "allowed_target_types": ["role"],
        },
    )
    assert registered.status_code == 201, registered.get_data(as_text=True)
    row = registered.json["data"]["relation_type"]
    assert row["scope"] == "project" and row["status"] == "active"
    assert row["allowed_target_types"] == ["role"]

    # 列表（can_view）可见；外人不可见
    listing = admin_client.get(registry_url)
    assert listing.status_code == 200
    assert any(item["code"] == "project_role" for item in listing.json["data"]["items"])
    outsider = authorized_client_factory("fde_engineer")
    assert outsider.get(registry_url).status_code == 403
    assert (
        outsider.post(
            registry_url,
            json={"kind": "link_type", "code": "x", "allowed_source_types": ["project"],
                  "allowed_target_types": ["role"]},
        ).status_code
        == 403
    )
    assert admin_client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/ontology/relation-types").status_code == 404

    # 建边成功（方向符合端点约束）
    linked = admin_client.post(
        f"{subjects_url}/{root['id']}/links",
        json={
            "version": _root_subject()["version"],
            "target_subject_id": role_id,
            "link_type": "project_role",
        },
    )
    assert linked.status_code == 201, linked.get_data(as_text=True)

    # 反向被拒（端点约束方向）
    reverse = admin_client.post(
        f"{subjects_url}/{role_id}/links",
        json={
            "version": 1,
            "target_subject_id": root["id"],
            "link_type": "project_role",
        },
    )
    assert reverse.status_code == 422, reverse.get_data(as_text=True)
    assert reverse.json["error"]["code"] == "invalid_research_subject_link"

    # 停用类型：禁新边
    retired = admin_client.post(f"{registry_url}/{row['id']}/retire")
    assert retired.status_code == 200, retired.get_data(as_text=True)
    assert retired.json["data"]["relation_type"]["status"] == "retired"

    blocked = admin_client.post(
        f"{subjects_url}/{root['id']}/links",
        json={
            "version": _root_subject()["version"],
            "target_subject_id": role_id,
            "link_type": "project_role",
        },
    )
    assert blocked.status_code == 409, blocked.get_data(as_text=True)
    assert blocked.json["error"]["code"] == "link_type_retired"

    # 存量边只读（停用不影响既有边）
    root_after = _root_subject()
    assert [link["link_type"] for link in root_after["links"]] == ["project_role"]


def test_relation_type_routes_never_in_catalog() -> None:
    """红线钉子：类型登记是人工路径，永不进 api_catalog（AI 候选走 change_set）。"""
    paths = {str(entry["path"]) for entry in CATALOG.values()}
    assert not any("/ontology/relation-types" in path for path in paths)
    assert not any("ontology" in key for key in CATALOG)


def test_global_type_registration_and_retirement_are_admin_only(
    admin_client, published_template, leader_client
) -> None:
    """全局类型对所有项目生效——登记与停用都必须是管理员动作。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    registry_url = f"/api/v1/projects/{project['id']}/ontology/relation-types"
    payload = {
        "kind": "link_type",
        "code": "admin_global_edge",
        "scope": "global",
        "allowed_source_types": ["project"],
        "allowed_target_types": ["role"],
    }

    # 项目负责人（can_manage）不能登记全局类型
    denied = leader_client.post(registry_url, json=payload)
    assert denied.status_code == 403, denied.get_data(as_text=True)

    registered = admin_client.post(registry_url, json=payload)
    assert registered.status_code == 201, registered.get_data(as_text=True)
    row = registered.json["data"]["relation_type"]
    assert row["scope"] == "global" and row["project_id"] is None

    # 列表里可见（全局类型对项目生效）
    listing = admin_client.get(registry_url)
    assert any(item["id"] == row["id"] for item in listing.json["data"]["items"])

    # 项目负责人不能停用全局类型（否则任一项目管理员都能影响别的项目）
    assert leader_client.post(f"{registry_url}/{row['id']}/retire").status_code == 403
    retired = admin_client.post(f"{registry_url}/{row['id']}/retire")
    assert retired.status_code == 200, retired.get_data(as_text=True)
    assert retired.json["data"]["relation_type"]["status"] == "retired"
