"""V3 T-O1：术语表 ontology_terms/aliases（设计 ontology-registry-v1 §2.2，验收 §5 用例 3/4）。

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
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from test_document_drafts_api import _persist_project

from conftest import INITIAL_PASSWORD
from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.control.api_catalog import CATALOG
from fde_api.ontology.models import OntologyTerm, OntologyTermAlias
from fde_api.ontology.service import (
    OntologyServiceError,
    confirm_term,
    create_term,
    merge_terms,
    serialize_term,
)
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
