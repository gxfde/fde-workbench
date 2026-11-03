"""V3 T-O1：术语表 ontology_terms/aliases（设计 ontology-registry-v1 §2.2，验收 §5 用例 3/4）
+ V3 T-O2：关系/对象类型注册表 ontology_relation_types（§2.3，验收 §5 用例 7）
+ V3 T-O3：变更集 ontology_change_sets（§2.4，验收 §5 用例 1/2/3）。

T-O1：
- 唯一约束：同项目同名 409 term_exists（服务层预检，并发撞墙由保存点读回
  赢家）；名字被既有别名占用同样 409（一个名字一个概念）；跨项目同名互不干扰。
- 状态机：draft→confirmed 拍板（confirmed_by/at、version 递增）；confirmed
  不可重复确认/原地改（409 term_immutable，用例 3——服务层无 definition 编辑
  路径，修订走 T-O3 change_set）；终态不能再确认。
- 合并保留来源（用例 4）：source→merged 指向 target、target 转写获得 source
  规范名为别名、曾并入 source 的行重指 target（链一跳化）、逐项
  OperationEvent；重复合并/终态目标/跨项目/并入自身一律 409。
- DB 约束：merged 无 canonical 被 CHECK 拒；非法 term_type/status 被 CHECK 拒；
  别名同项目唯一（DB 层）。

T-O2：
- 注册表把「关系类型白名单硬编码 2 种」「对象类型 CheckConstraint 硬编码」
  （审计附录 D ②③）的扩展面变成可登记；内置两类关系类型的端点约束是存量
  语义（冻结），注册表不得覆盖内置码（409 duplicate_code）。
- ∪ 接入：_validate_link 改为「内置优先 + 注册表」——内置码的方向校验不被
  放开（backlog 风险条）；注册类型按端点约束放行/拒绝；retired 类型禁新边
  （409 link_type_retired）、存量边只读；未知类型仍 422。
- 作用域：project_id=NULL 是全局类型（仅 admin 可建），项目内类型遮蔽同名
  全局类型；同作用域同 (kind, code) 唯一。

T-O3：
- AI 候选唯一入口（用例 1）：propose 只写变更集行（confirm 前 terms 无行）；
  captured_from 标来源、仅服务层原语可写（HTTP 人工路径拒收该字段）。
- 状态机：draft→submit(in_review，算 base 指纹)→confirm（复核指纹 + 单事务
  逐项物化，全成全败）/ reject（留 reason）；验收分离：拍板人 ≠ 提交人（403）。
- base_conflict（并发防护）：submit 与 confirm 复核共用同一采集器——既有行被
  并发改写或占位名凭空出现/消失都算漂移（409 base_conflict，不物化）。
- 物化语义：create_term 直落 confirmed；update_term 同名=原行受控改写（旧定义
  随事件留档）、改名=新行 confirmed+原行 superseded+原名转别名；merge_terms
  走 T-O1 原语（保留来源）；register_relation_type 只登记项目内类型。
- 人工面（不进 api_catalog 红线钉子）：GET terms（?q= 名/别名检索）、change-set
  propose/list/detail/submit/confirm/reject；跨项目 404/403（用例 2）。
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
from fde_api.ontology.models import (
    OntologyChangeSet,
    OntologyRelationType,
    OntologyTerm,
    OntologyTermAlias,
)
from fde_api.ontology.service import (
    BUILTIN_LINK_TYPE_CODES,
    BUILTIN_SUBJECT_TYPE_CODES,
    OntologyServiceError,
    confirm_change_set,
    confirm_term,
    create_term,
    find_relation_type,
    list_relation_types,
    merge_terms,
    propose_change_set,
    register_relation_type,
    reject_change_set,
    retire_relation_type,
    serialize_relation_type,
    serialize_term,
    submit_change_set,
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


# ---------------------------------------------------------------------------
# V3 T-O3：变更集（AI 候选唯一入口；验收 §5 用例 1/2/3）
# ---------------------------------------------------------------------------


def _propose(db_session, actor, project_id, items, **overrides):
    return propose_change_set(
        db_session,
        project_id=project_id,
        actor=actor,
        title=overrides.pop("title", "术语候选"),
        proposed_json=items,
        **overrides,
    )


def test_change_set_propose_validates_payload_schema(db_session) -> None:
    """propose 形状/值级校验：未知动作、设计列有但本轮未开放的动作、缺必填、
    未知字段、空载荷、超批量、merge 自并、空标题——全部 400 且不落行。"""
    actor = _actor(db_session, name="cs-schema")
    project = _persist_project(db_session, actor, code=f"ONTO-CS-{uuid4().hex[:6]}")

    good = [
        {"action": "create_term", "term": "回款凭证", "definition": "银行回款凭证指针。"}
    ]

    with pytest.raises(OntologyServiceError) as empty:
        _propose(db_session, actor, project.id, [])
    assert empty.value.code == "payload_schema"

    with pytest.raises(OntologyServiceError) as unknown_action:
        _propose(db_session, actor, project.id, [{"action": "drop_database"}])
    assert unknown_action.value.code == "payload_schema"

    # 设计 §2.4 列有、T-O3 不开放：create_subject / link_subjects
    with pytest.raises(OntologyServiceError) as deferred:
        _propose(
            db_session, actor, project.id, [{"action": "create_subject", "subject_key": "x"}]
        )
    assert deferred.value.code == "payload_schema"
    assert "本轮未开放" in deferred.value.message

    with pytest.raises(OntologyServiceError) as missing:
        _propose(db_session, actor, project.id, [{"action": "create_term", "term": "x"}])
    assert missing.value.code == "payload_schema"
    assert "definition" in missing.value.message

    with pytest.raises(OntologyServiceError) as unknown_field:
        _propose(
            db_session,
            actor,
            project.id,
            [{"action": "create_term", "term": "x", "definition": "y", "hax": 1}],
        )
    assert unknown_field.value.code == "payload_schema"
    assert "hax" in unknown_field.value.message

    from fde_api.ontology.service import CHANGE_SET_MAX_ITEMS

    with pytest.raises(OntologyServiceError) as overflow:
        _propose(
            db_session,
            actor,
            project.id,
            [
                {"action": "create_term", "term": f"术语{i}", "definition": "x"}
                for i in range(CHANGE_SET_MAX_ITEMS + 1)
            ],
        )
    assert overflow.value.code == "payload_schema"

    with pytest.raises(OntologyServiceError) as self_merge:
        _propose(
            db_session,
            actor,
            project.id,
            [{"action": "merge_terms", "source_term": "同名", "target_term": "同名"}],
        )
    assert self_merge.value.code == "payload_schema"

    with pytest.raises(OntologyServiceError) as bad_title:
        propose_change_set(
            db_session, project_id=project.id, actor=actor,
            title="   ", proposed_json=good,
        )
    assert bad_title.value.code == "invalid_request"

    # 合法 propose：只写变更集行，术语表零行（用例 1 的服务层半面）
    row = _propose(
        db_session,
        actor,
        project.id,
        good
        + [
            {
                "action": "register_relation_type",
                "kind": "link_type",
                "code": "proj_dept",
                "allowed_source_types": ["project"],
                "allowed_target_types": ["department"],
            },
        ],
        description="AI 预审候选",
    )
    db_session.commit()
    assert row.status == "draft" and row.base_snapshot_sha256 is None
    assert row.diff_summary == "新建术语 1 · 登记类型 1"
    # 载荷归一化落库（term_type 缺省补齐 generic）
    assert row.proposed_json[0]["term_type"] == "generic"
    assert len(_term_rows(db_session, project.id)) == 0


def test_change_set_state_machine_and_http_surface(
    admin_client, published_template, leader_client, authorized_client_factory, db_session
) -> None:
    """人工评审面全链路：propose(draft)→submit(in_review+指纹)→confirm(拍板物化)
    / reject(留 reason)；验收分离（拍板人≠提交人 403）；重复确认 409 not_in_review；
    跨项目 404/403（用例 2）；?status= 过滤；confirmed 事件携带逐项结果。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    base_url = f"/api/v1/projects/{project_id}/ontology"
    cs_url = f"{base_url}/change-sets"
    terms_url = f"{base_url}/terms"
    payload = {
        "title": "引入回款凭证术语",
        "description": "AI 预审候选，请评审。",
        "proposed_json": [
            {
                "action": "create_term",
                "term": "回款凭证",
                "definition": "客户回款的银行凭证指针。",
                "term_type": "entity",
            }
        ],
    }

    # 用例 1：confirm 前 terms 表无行
    proposed = leader_client.post(cs_url, json=payload)
    assert proposed.status_code == 201, proposed.get_data(as_text=True)
    cs = proposed.json["data"]["change_set"]
    assert cs["status"] == "draft" and cs["base_snapshot_sha256"] is None
    assert cs["diff_summary"] == "新建术语 1"
    assert leader_client.get(terms_url).json["data"]["items"] == []

    # captured_from 是 AI 通道字段，人工路径拒收
    hijack = leader_client.post(cs_url, json={**payload, "captured_from": "agent_run:abc"})
    assert hijack.status_code == 400
    assert hijack.json["error"]["code"] == "invalid_request"

    # 清单 + 详情（can_view）；?status= 过滤；坏状态 400
    listing = leader_client.get(cs_url)
    assert listing.status_code == 200
    assert any(item["id"] == cs["id"] for item in listing.json["data"]["items"])
    detail = leader_client.get(f"{cs_url}/{cs['id']}")
    assert detail.status_code == 200
    assert detail.json["data"]["change_set"]["proposed_json"][0]["term"] == "回款凭证"
    assert any(
        item["id"] == cs["id"]
        for item in leader_client.get(f"{cs_url}?status=draft").json["data"]["items"]
    )
    assert leader_client.get(f"{cs_url}?status=confirmed").json["data"]["items"] == []
    assert leader_client.get(f"{cs_url}?status=審核中").status_code == 400

    # 外人不可见（用例 2）；未知项目 404
    outsider = authorized_client_factory("fde_engineer")
    assert outsider.get(cs_url).status_code == 403
    assert outsider.post(cs_url, json=payload).status_code == 403
    missing_project = "/api/v1/projects/00000000-0000-0000-0000-000000000000/ontology/change-sets"
    assert admin_client.get(missing_project).status_code == 404
    assert admin_client.get(f"{missing_project}/{cs['id']}").status_code == 404

    # 跨项目：另一项目的变更集 id 在本项目路由下不可见（404，不泄露存在性）
    other_leader = authorized_client_factory("project_lead")
    other_project = _create_project(admin_client, published_template, other_leader.user)
    other_cs_url = f"/api/v1/projects/{other_project['id']}/ontology/change-sets"
    cross = other_leader.get(f"{other_cs_url}/{cs['id']}")
    assert cross.status_code == 404
    assert cross.json["error"]["code"] == "change_set_not_found"

    # 提交评审：draft → in_review，算出 base 指纹
    submitted = leader_client.post(f"{cs_url}/{cs['id']}/submit")
    assert submitted.status_code == 200, submitted.get_data(as_text=True)
    in_review = submitted.json["data"]["change_set"]
    assert in_review["status"] == "in_review"
    assert in_review["base_snapshot_sha256"]
    assert in_review["submitted_by_user_id"] == leader_client.user.id
    # draft 已消耗：重复 submit 409
    again = leader_client.post(f"{cs_url}/{cs['id']}/submit")
    assert again.status_code == 409
    assert again.json["error"]["code"] == "invalid_transition"

    # 验收分离：提交人不能自己拍板
    self_confirm = leader_client.post(f"{cs_url}/{cs['id']}/confirm")
    assert self_confirm.status_code == 403, self_confirm.get_data(as_text=True)
    assert self_confirm.json["error"]["code"] == "change_set_decider_conflict"

    # 管理员拍板：单事务逐项物化，术语直落 confirmed
    confirmed = admin_client.post(f"{cs_url}/{cs['id']}/confirm")
    assert confirmed.status_code == 200, confirmed.get_data(as_text=True)
    data = confirmed.json["data"]
    assert data["change_set"]["status"] == "confirmed"
    assert data["change_set"]["confirmed_by_user_id"] == admin_client.user.id
    assert data["results"][0]["action"] == "create_term"
    assert data["results"][0]["status"] == "created"
    assert data["results"][0]["term"] == "回款凭证"
    terms = leader_client.get(terms_url).json["data"]["items"]
    assert len(terms) == 1 and terms[0]["term"] == "回款凭证"
    assert terms[0]["status"] == "confirmed"

    # 重复确认 409 not_in_review
    replay = admin_client.post(f"{cs_url}/{cs['id']}/confirm")
    assert replay.status_code == 409
    assert replay.json["error"]["code"] == "not_in_review"

    # confirmed 事件携带逐项结果
    events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project_id,
                OperationEvent.event_type == "ontology_change_set_confirmed",
            )
        )
    )
    db_session.rollback()
    assert len(events) == 1
    assert events[0].changes["item_count"] == 1
    assert events[0].changes["results"][0]["term"] == "回款凭证"

    # 否决流：admin 提出+提交，leader 否决（拍板人≠提交人）留 reason
    proposed2 = admin_client.post(
        cs_url,
        json={
            "title": "重复候选",
            "proposed_json": [
                {"action": "create_term", "term": "交付物量", "definition": "同「交付包」。"}
            ],
        },
    )
    assert proposed2.status_code == 201, proposed2.get_data(as_text=True)
    cs2 = proposed2.json["data"]["change_set"]
    assert admin_client.post(f"{cs_url}/{cs2['id']}/submit").status_code == 200
    # 否决无 reason 400（先于成功否决验证，集合仍可否决）
    assert leader_client.post(f"{cs_url}/{cs2['id']}/reject", json={}).status_code == 400
    rejected = leader_client.post(
        f"{cs_url}/{cs2['id']}/reject", json={"reason": "与既有术语重复，请走合并。"}
    )
    assert rejected.status_code == 200, rejected.get_data(as_text=True)
    assert rejected.json["data"]["change_set"]["status"] == "rejected"
    assert rejected.json["data"]["change_set"]["rejected_reason"] == "与既有术语重复，请走合并。"
    # 终态再否决 409
    assert (
        leader_client.post(f"{cs_url}/{cs2['id']}/reject", json={"reason": "再否一次"}).status_code
        == 409
    )
    # 已 confirmed 的集合不可否决
    assert (
        leader_client.post(f"{cs_url}/{cs['id']}/reject", json={"reason": "迟了"}).status_code == 409
    )
    # 否决同样验收分离：leader 提交的集合 leader 不能自己否决
    proposed3 = leader_client.post(cs_url, json=payload)
    cs3 = proposed3.json["data"]["change_set"]
    leader_client.post(f"{cs_url}/{cs3['id']}/submit")
    self_reject = leader_client.post(f"{cs_url}/{cs3['id']}/reject", json={"reason": "自己撤"})
    assert self_reject.status_code == 403
    assert self_reject.json["error"]["code"] == "change_set_decider_conflict"


def test_change_set_base_conflict_on_concurrent_drift(
    admin_client, published_template, leader_client
) -> None:
    """base 指纹并发防护：既有行被并发改写 / 占位名被并发占用，confirm 一律
    409 base_conflict 且零物化（集合停在 in_review）。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    cs_url = f"/api/v1/projects/{project_id}/ontology/change-sets"

    def _propose_and_submit(items, *, proposer, title="并发防护用例") -> str:
        proposed = proposer.post(cs_url, json={"title": title, "proposed_json": items})
        assert proposed.status_code == 201, proposed.get_data(as_text=True)
        cs_id = proposed.json["data"]["change_set"]["id"]
        assert proposer.post(f"{cs_url}/{cs_id}/submit").status_code == 200
        return cs_id

    def _confirm(cs_id, *, confirmer):
        return confirmer.post(f"{cs_url}/{cs_id}/confirm")

    def _create_item(term, definition="占位定义。"):
        return {"action": "create_term", "term": term, "definition": definition, "term_type": "entity"}

    # 种子：确认「回款凭证」
    seed_id = _propose_and_submit(
        [_create_item("回款凭证")], proposer=admin_client, title="种子候选"
    )
    assert _confirm(seed_id, confirmer=leader_client).status_code == 200

    # 漂移①：stale 先按旧定义取指纹，fresh 抢先改掉定义，stale 再拍板 → base_conflict
    stale_id = _propose_and_submit(
        [{"action": "update_term", "term": "回款凭证", "definition": "迟到的修订。"}],
        proposer=leader_client,
        title="修订候选",
    )
    fresh_id = _propose_and_submit(
        [{"action": "update_term", "term": "回款凭证", "definition": "抢先修订的定义。"}],
        proposer=admin_client,
        title="抢先修订",
    )
    fresh = _confirm(fresh_id, confirmer=leader_client)
    assert fresh.status_code == 200, fresh.get_data(as_text=True)
    stale = _confirm(stale_id, confirmer=admin_client)
    assert stale.status_code == 409, stale.get_data(as_text=True)
    assert stale.json["error"]["code"] == "base_conflict"
    # 零物化：变更集仍停在 in_review，定义保持抢先版
    detail = admin_client.get(f"{cs_url}/{stale_id}").json["data"]["change_set"]
    assert detail["status"] == "in_review"
    terms = admin_client.get(f"/api/v1/projects/{project_id}/ontology/terms").json["data"]["items"]
    target = next(row for row in terms if row["term"] == "回款凭证")
    assert target["definition"] == "抢先修订的定义。"

    # 漂移②：create_term 的占位名被另一变更集抢注
    ghost_id = _propose_and_submit(
        [_create_item("交付物量")], proposer=leader_client, title="占位候选"
    )
    squatter_id = _propose_and_submit(
        [_create_item("交付物量", "先到先得。")],
        proposer=admin_client,
        title="抢注候选",
    )
    squatter = _confirm(squatter_id, confirmer=leader_client)
    assert squatter.status_code == 200, squatter.get_data(as_text=True)
    ghost = _confirm(ghost_id, confirmer=admin_client)
    assert ghost.status_code == 409
    assert ghost.json["error"]["code"] == "base_conflict"
    assert admin_client.get(f"{cs_url}/{ghost_id}").json["data"]["change_set"]["status"] == "in_review"


def test_change_set_item_failure_rolls_back_whole_set(
    admin_client, published_template, leader_client
) -> None:
    """单事务全成全败：第 2 项物化失败（端点引用未登记对象类型）→ 整体回滚，
    第 1 项的术语也不落行，变更集停在 in_review 且错误点名项次。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    cs_url = f"/api/v1/projects/{project_id}/ontology/change-sets"
    payload = {
        "title": "第二项会失败的候选",
        "proposed_json": [
            {"action": "create_term", "term": "影子术语", "definition": "不该落行。"},
            {
                "action": "register_relation_type",
                "kind": "link_type",
                "code": "ghost_edge",
                "allowed_source_types": ["project"],
                "allowed_target_types": ["ghost_type"],
            },
        ],
    }
    proposed = leader_client.post(cs_url, json=payload)
    assert proposed.status_code == 201, proposed.get_data(as_text=True)
    cs_id = proposed.json["data"]["change_set"]["id"]
    assert leader_client.post(f"{cs_url}/{cs_id}/submit").status_code == 200

    confirmed = admin_client.post(f"{cs_url}/{cs_id}/confirm")
    assert confirmed.status_code == 400, confirmed.get_data(as_text=True)
    assert confirmed.json["error"]["code"] == "change_set_item_failed"
    assert "第 2 项" in confirmed.json["error"]["message"]

    terms = admin_client.get(f"/api/v1/projects/{project_id}/ontology/terms").json["data"]["items"]
    assert terms == []  # 第 1 项一并回滚
    types = admin_client.get(
        f"/api/v1/projects/{project_id}/ontology/relation-types"
    ).json["data"]["items"]
    assert types == []
    assert admin_client.get(f"{cs_url}/{cs_id}").json["data"]["change_set"]["status"] == "in_review"


def test_change_set_update_term_in_place_and_rename_supersede(db_session) -> None:
    """修订语义裁决：同名=原行受控改写（旧定义随事件留档）；改名=新行 confirmed
    + 原行 superseded 指 canonical + 原名转别名；终态行不能修订。"""
    author = _actor(db_session, name="cs-update-a")
    approver = _actor(db_session, name="cs-update-b")
    project = _persist_project(db_session, author, code=f"ONTO-UP-{uuid4().hex[:6]}")

    seed = create_term(
        db_session,
        project_id=project.id,
        term="交付包",
        definition="旧定义。",
        term_type="entity",
        actor=author,
        initial_status="confirmed",
    )
    db_session.commit()

    # 同名修订（in-place）
    cs1 = _propose(
        db_session,
        author,
        project.id,
        [
            {
                "action": "update_term",
                "term": "交付包",
                "definition": "新口径定义。",
                "term_type": "entity",
            },
        ],
    )
    submit_change_set(db_session, row=cs1, actor=author)
    db_session.commit()
    outcome = confirm_change_set(db_session, row=cs1, actor=approver)
    db_session.commit()
    db_session.refresh(seed)
    assert seed.id == outcome["results"][0]["term_id"]  # 原行原地修订
    assert seed.definition == "新口径定义。" and seed.status == "confirmed"
    assert seed.version == 2  # 创建（直落 confirmed，version=1）+ 受控修订 +1
    assert outcome["results"][0]["before"] == {"definition": "旧定义。", "term_type": "entity"}
    assert outcome["results"][0]["after"]["definition"] == "新口径定义。"

    # 改名修订（行级取代：superseded + canonical + 原名转别名）
    cs2 = _propose(
        db_session,
        author,
        project.id,
        [
            {
                "action": "update_term",
                "term": "交付包",
                "new_term": "交付物集合",
                "definition": "改名并修订。",
            },
        ],
    )
    submit_change_set(db_session, row=cs2, actor=author)
    db_session.commit()
    outcome2 = confirm_change_set(db_session, row=cs2, actor=approver)
    db_session.commit()
    result = outcome2["results"][0]
    assert result["status"] == "superseded" and result["old_term"] == "交付包"
    assert result["new_term"] == "交付物集合"
    db_session.refresh(seed)
    assert seed.status == "superseded" and seed.canonical_term_id == result["new_term_id"]
    rows = _term_rows(db_session, project.id)
    by_name = {row.term: row for row in rows}
    assert by_name["交付物集合"].status == "confirmed"
    assert by_name["交付包"].status == "superseded"  # 原行保留为历史
    assert "交付包" in _alias_names(db_session, project.id)  # 原名转别名

    # 终态行（superseded）不能修订——物化失败整体回滚
    cs3 = _propose(
        db_session,
        author,
        project.id,
        [{"action": "update_term", "term": "交付包", "definition": "再改一次。"}],
    )
    submit_change_set(db_session, row=cs3, actor=author)
    db_session.commit()
    with pytest.raises(OntologyServiceError) as failure:
        confirm_change_set(db_session, row=cs3, actor=approver)
    assert failure.value.code == "change_set_item_failed"
    db_session.rollback()


def test_change_set_captured_from_ai_channel(db_session) -> None:
    """AI 候选通道（用例 1 全程）：captured_from 只在服务层原语可写；confirm 前
    terms 零行，confirm 后直落 confirmed。"""
    author = _actor(db_session, name="cs-ai-a")
    approver = _actor(db_session, name="cs-ai-b")
    project = _persist_project(db_session, author, code=f"ONTO-AI-{uuid4().hex[:6]}")

    row = propose_change_set(
        db_session,
        project_id=project.id,
        actor=author,
        title="AI 抽取候选：回款凭证",
        proposed_json=[
            {"action": "create_term", "term": "回款凭证", "definition": "银行回款凭证指针。"}
        ],
        captured_from="agent_run:11111111-1111-4111-8111-111111111111",
    )
    db_session.commit()
    assert row.captured_from == "agent_run:11111111-1111-4111-8111-111111111111"
    assert len(_term_rows(db_session, project.id)) == 0  # confirm 前不物化

    submit_change_set(db_session, row=row, actor=author)
    confirm_change_set(db_session, row=row, actor=approver)
    db_session.commit()
    rows = _term_rows(db_session, project.id)
    assert [item.term for item in rows] == ["回款凭证"]
    assert rows[0].status == "confirmed"


def test_change_set_merge_terms_and_register_type_materialization(db_session) -> None:
    """merge_terms 走 T-O1 原语（保留来源+逐项事件）；register_relation_type 落
    项目内类型并可立即解析；confirm 事件逐项结果齐备。"""
    author = _actor(db_session, name="cs-mix-a")
    approver = _actor(db_session, name="cs-mix-b")
    project = _persist_project(db_session, author, code=f"ONTO-MX-{uuid4().hex[:6]}")

    for name, definition in (("交付物量", "同交付包。"), ("交付包", "一次交付的物量集合。")):
        create_term(
            db_session,
            project_id=project.id,
            term=name,
            definition=definition,
            actor=author,
            initial_status="confirmed",
        )
    db_session.commit()

    row = _propose(
        db_session,
        author,
        project.id,
        [
            {"action": "merge_terms", "source_term": "交付物量", "target_term": "交付包"},
            {
                "action": "register_relation_type",
                "kind": "link_type",
                "code": "pkg_dept",
                "label": "包到部门",
                "allowed_source_types": ["project"],
                "allowed_target_types": ["department"],
            },
        ],
    )
    submit_change_set(db_session, row=row, actor=author)
    db_session.commit()
    outcome = confirm_change_set(db_session, row=row, actor=approver)
    db_session.commit()

    results = outcome["results"]
    assert results[0]["action"] == "merge_terms" and results[0]["status"] == "merged"
    assert results[1]["action"] == "register_relation_type"
    assert results[1]["status"] == "registered"
    merged = {item.term: item for item in _term_rows(db_session, project.id)}
    assert merged["交付物量"].status == "merged"
    assert merged["交付物量"].canonical_term_id == merged["交付包"].id
    assert "交付物量" in _alias_names(db_session, project.id)
    registered = find_relation_type(
        db_session, project_id=project.id, kind="link_type", code="pkg_dept"
    )
    assert registered is not None and registered.project_id == project.id
    # merge 原语的 term 级事件仍在（溯源），叠 change-set 级事件（不同粒度不互斥）
    assert len(_events(db_session, project.id)) == 1
    cs_events = list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project.id,
                OperationEvent.event_type == "ontology_change_set_confirmed",
            )
        )
    )
    db_session.rollback()
    assert len(cs_events) == 1 and cs_events[0].changes["item_count"] == 2


def test_terms_get_surface_and_q_filter(
    admin_client, published_template, leader_client, authorized_client_factory, db_session
) -> None:
    """术语只读面（§4 GET /ontology/terms?q=）：别名命中返回属主行；外人 403。"""
    project = _create_project(admin_client, published_template, leader_client.user)
    project_id = project["id"]
    terms_url = f"/api/v1/projects/{project_id}/ontology/terms"
    author = admin_client.user

    create_term(
        db_session,
        project_id=project_id,
        term="回款凭证",
        definition="客户回款的银行凭证指针。",
        actor=author,
        initial_status="confirmed",
    )
    kept = create_term(
        db_session,
        project_id=project_id,
        term="交付包",
        definition="一次交付的物量集合。",
        actor=author,
        initial_status="confirmed",
    )
    db_session.add(
        OntologyTermAlias(
            project_id=project_id,
            term_id=kept.id,
            alias="交付物量",
            created_by_user_id=author.id,
        )
    )
    db_session.commit()

    listing = leader_client.get(terms_url)
    assert listing.status_code == 200
    items = {row["term"]: row for row in listing.json["data"]["items"]}
    assert set(items) == {"回款凭证", "交付包"}
    assert items["交付包"]["aliases"] == ["交付物量"]
    assert items["回款凭证"]["aliases"] == []

    # ?q= 命中规范名或别名（别名返回属主行）
    hit_alias = leader_client.get(f"{terms_url}?q=交付物量")
    assert [row["term"] for row in hit_alias.json["data"]["items"]] == ["交付包"]
    hit_term = leader_client.get(f"{terms_url}?q=回款")
    assert [row["term"] for row in hit_term.json["data"]["items"]] == ["回款凭证"]
    miss = leader_client.get(f"{terms_url}?q=不存在")
    assert miss.json["data"]["items"] == []

    outsider = authorized_client_factory("fde_engineer")
    assert outsider.get(terms_url).status_code == 403
    assert (
        admin_client.get(
            "/api/v1/projects/00000000-0000-0000-0000-000000000000/ontology/terms"
        ).status_code
        == 404
    )


def test_change_set_routes_never_in_catalog() -> None:
    """红线钉子：术语面与变更集面都是人工评审路径，永不进 api_catalog
    （AI 只经服务层原语产候选，拍板必须真人——同 signoff 纪律）。"""
    paths = {str(entry["path"]) for entry in CATALOG.values()}
    assert not any("/ontology/change-sets" in path for path in paths)
    assert not any("/ontology/terms" in path for path in paths)
    assert not any("/ontology/relation-types" in path for path in paths)
    assert not any("ontology" in key for key in CATALOG)
