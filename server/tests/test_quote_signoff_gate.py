"""W2-2 签字闸回归钉：正式对外报价单出口（export_quote_offer）。

红线（SKILL-03:43 / v2:54）：AI/系统起草的对外报价稿必须经人逐条核对并
签字后才可发出。本文件钉住服务端落点：

1. claims 未全 accepted → 409 signoff_required，且**不留任何导出事件**
   （拒了就是拒了，不能留下"未签先发"的痕迹让台账误读为已签发）；
2. 全空 field_claims（total=0）同样拒（防"零字段报价"绕过全称量词校验）；
3. 全 accepted 放行：返回对外版 HTML——公式价**整列不存在**（非折叠：
   连 details/summary 标签都不允许出现，客户侧点开也不可见）、无内部
   水印与底稿出处；内部系数值（integration_factor 等小数）不出现在正文；
4. 放行即落 quote_offer_exported 事件（OperationEvent，actor 留痕）；
   render_quote_draft 内部草稿路径行为不变（公式价折叠仍在）。

服务级直调（同 test_quote_numerical_guards 模式），无 HTTP 层。
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fde_api.auth.models import User
from fde_api.auth.passwords import hash_password
from fde_api.projects.quote_service import (
    CLAIMABLE_FIELDS,
    QuoteServiceError,
    create_quote,
    export_quote_offer,
    render_quote_draft,
)
from fde_api.workbench.models import (
    IndustryTemplate,
    IndustryTemplateVersion,
    OperationEvent,
    Project,
)
from conftest import INITIAL_PASSWORD


def _seed_project(db_session: Session) -> tuple[Project, User]:
    leader = User(
        username=f"signoff.lead.{uuid4().hex[:8]}",
        display_name="对外签字官",
        role="admin",
        password_hash=hash_password(INITIAL_PASSWORD),
        must_change_password=False,
        is_active=True,
    )
    db_session.add(leader)
    db_session.flush()
    template = IndustryTemplate(name="签字闸模板", industry_name="制造")
    version = IndustryTemplateVersion(
        template=template,
        name=template.name,
        industry_name=template.industry_name,
        description="",
        version_number=1,
        status="published",
        published_by=leader,
    )
    db_session.add_all([template, version])
    db_session.flush()
    project = Project(
        project_code=f"SG-{uuid4().hex[:8]}",
        name="签字闸项目",
        enterprise_code=f"签字闸企业·制造·{uuid4().hex[:8]}",
        leader=leader,
        source_template_version=version,
        template_snapshot={},
        research_snapshot={},
        planned_start_date=date(2026, 11, 16),
    )
    db_session.add(project)
    db_session.commit()
    return project, leader


def _accepted_quote(db_session: Session, project: Project, actor: User):
    """create_quote 合法路径建报价，再把全部 claimable 字段推进到 accepted。"""
    data = create_quote(
        actor=actor,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "25",
            "hourly_rate": 150,
            "anchor_mode": "steady",
        },
    )
    quote_key = data["quote_key"]
    claims = dict(data["field_claims"])
    assert set(claims) == set(CLAIMABLE_FIELDS)
    assert all(v == "estimated" for v in claims.values())
    # 直改 claims 模拟"人已逐条核对签字"（claim 单调前进的终态；服务级测试
    # 不再走 11 次 HTTP claim 前进——单调性已由既有用例钉住）。
    from fde_api.workbench.models import Quote

    quote = db_session.scalar(
        select(Quote).where(
            Quote.project_id == project.id, Quote.quote_key == quote_key
        )
    )
    assert quote is not None, "create_quote 刚建出的报价必须可查"
    quote.field_claims = {field: "accepted" for field in CLAIMABLE_FIELDS}
    db_session.commit()
    return quote_key


def _export_events(db_session: Session, project: Project) -> list[OperationEvent]:
    return list(
        db_session.scalars(
            select(OperationEvent).where(
                OperationEvent.project_id == project.id,
                OperationEvent.event_type == "quote_offer_exported",
            )
        )
    )


def test_export_rejected_when_claims_not_all_accepted(db_session):
    """未全 accepted → 409 signoff_required，且不留导出事件。"""
    project, leader = _seed_project(db_session)
    create_quote(
        actor=leader,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "25",
            "hourly_rate": 150,
            "anchor_mode": "steady",
        },
    )
    with pytest.raises(QuoteServiceError) as excinfo:
        export_quote_offer(actor=leader, project_id=project.id, quote_key="Q-001")
    assert excinfo.value.status == 409
    assert excinfo.value.code == "signoff_required"
    # 可辨断言：消息必须指明缺口（否则与其他 409 混淆）
    assert "逐条核对" in excinfo.value.message
    db_session.expire_all()
    assert _export_events(db_session, project) == []


def test_export_rejected_when_claims_empty(db_session):
    """全空 field_claims（total=0）同样拒——防零字段报价绕过全称校验。"""
    project, leader = _seed_project(db_session)
    data = create_quote(
        actor=leader,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "25",
            "hourly_rate": 150,
            "anchor_mode": "steady",
        },
    )
    from fde_api.workbench.models import Quote

    quote = db_session.scalar(
        select(Quote).where(
            Quote.project_id == project.id, Quote.quote_key == data["quote_key"]
        )
    )
    assert quote is not None, "create_quote 刚建出的报价必须可查"
    quote.field_claims = {}
    db_session.commit()
    with pytest.raises(QuoteServiceError) as excinfo:
        export_quote_offer(actor=leader, project_id=project.id, quote_key=data["quote_key"])
    assert excinfo.value.status == 409
    assert excinfo.value.code == "signoff_required"
    assert _export_events(db_session, project) == []


def test_export_renders_external_html_and_records_event(db_session):
    """全 accepted 放行：对外版无公式价列/无内部水印/无底稿出处；事件留痕。"""
    project, leader = _seed_project(db_session)
    quote_key = _accepted_quote(db_session, project, leader)

    result = export_quote_offer(actor=leader, project_id=project.id, quote_key=quote_key)
    html = result["html"]
    assert result["external"] is True

    # 对外版红线断言：公式价整列不存在——连 details/summary（折叠容器）都不可见
    assert "<details" not in html
    assert "内部测算" not in html
    # 内部水印与底稿出处（对内溯源文字）不外泄
    assert "内部草稿" not in html
    assert "v2.4.6" not in html
    assert "对内底稿" not in html
    # 锚点分支字母（内部口径词）不出现在表行（对外用"备注"列表述）
    assert "<td>A</td>" not in html
    assert "<td>B</td>" not in html
    # 建议区间与档位仍可见（对外信息本体）
    assert "建议报价区间" in html
    assert "轻量" in html
    # 正式版抬头与签字语义提示
    assert "报价单" in html
    assert "逐项核对" in html

    # 事件留痕：恰好一条，actor 正确，changes 不含金额
    events = _export_events(db_session, project)
    assert len(events) == 1
    assert events[0].actor_user_id == leader.id
    changes = events[0].changes or {}
    assert changes.get("quote_key") == quote_key
    assert changes.get("claims_accepted") == len(CLAIMABLE_FIELDS)
    assert "final_amount" not in changes
    assert "formula_price" not in changes

    # 二次导出：闸已开，仍放行（幂等放行、再留一条痕——签发审计链完整）
    export_quote_offer(actor=leader, project_id=project.id, quote_key=quote_key)
    assert len(_export_events(db_session, project)) == 2


def test_internal_draft_keeps_collapsed_formula(db_session):
    """内部草稿路径行为不变（W1-1 口径）：公式价折叠容器仍在、水印仍在。"""
    project, leader = _seed_project(db_session)
    create_quote(
        actor=leader,
        project_id=project.id,
        payload={
            "tier": "light",
            "ideal_hours": "25",
            "hourly_rate": 150,
            "anchor_mode": "steady",
        },
    )
    data = render_quote_draft(actor=leader, project_id=project.id, quote_key="Q-001")
    html = data["html"]
    assert "<details" in html
    assert "内部测算" in html
    assert "内部草稿" in html
    # 不落导出事件（草稿预览不是签发）
    assert _export_events(db_session, project) == []
