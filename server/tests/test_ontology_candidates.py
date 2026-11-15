"""discovery 事实 → 本体候选构建器（WP4④ / D17）纯函数层单测。

不碰数据库：候选构建是纯函数（事实列表 + 原文正文 ⇒ 候选条目），故可直接钉住
「逐字引文还原」「人工审阅门槛」「跨抽取冲突」「未知项贯通」「KEY_RE/Payload 严格契约」五条规则。
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from fde_api.integrations.candidates import build_candidates

_KEY_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,79}")


def _fact(**overrides):
    base = {
        "id": "fact-1",
        "fact_type": "role",
        "classification": "customer_stated",
        "subject": "客户经理",
        "predicate": "负责",
        "object_value": "线索跟进",
        "confidence": 0.9,
        "source_ref": "interview_minutes:min-1",
        "source_locator": {"type": "line", "line": 2},
        "review_status": "accepted",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


SOURCE_TEXT = "第一行引子\n客户经理负责线索跟进\n第三行结束\n"


def test_accepted_fact_becomes_six_piece_candidate():
    build = build_candidates(
        facts=[_fact()], source_texts={"interview_minutes:min-1": SOURCE_TEXT}
    )

    assert len(build.items) == 1
    item = build.items[0]
    assert item["op"] == "create"
    assert item["entity_type"] == "object_types"
    assert _KEY_RE.fullmatch(item["entity_key"]) is not None
    assert "." not in item["entity_key"]
    payload = item["payload"]
    # ObjectTypePayload ConfigDict(extra="forbid") 禁止 status
    assert "status" not in payload
    # 六件套（captured_from 条目必含）
    assert payload["source_location"] == "interview_minutes:min-1#line=2&type=line"
    assert payload["evidence_quote"] == "客户经理负责线索跟进"
    assert payload["confidence"] == 0.9
    assert payload["fact_or_inference"] == "fact"
    assert payload["suggested_owner"] == "business_owner"
    assert build.skipped == []


def test_unreviewed_fact_is_not_pushed():
    build = build_candidates(
        facts=[_fact(review_status="pending")],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert build.items == []
    assert [entry["reason"] for entry in build.skipped] == ["not_accepted"]


def test_non_text_locator_is_skipped_not_fabricated():
    build = build_candidates(
        facts=[
            _fact(source_locator={"type": "transcript_segment", "start_ms": 0, "end_ms": 500})
        ],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert build.items == []
    assert build.skipped[0]["reason"] == "evidence_quote_not_restorable"


def test_missing_source_content_is_skipped():
    build = build_candidates(facts=[_fact()], source_texts={})

    assert build.items == []
    assert build.skipped[0]["reason"] == "source_content_unavailable"


def test_unmapped_fact_type_is_skipped():
    build = build_candidates(
        facts=[_fact(fact_type="pain_point")],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert build.items == []
    assert build.skipped[0]["reason"] == "fact_type_not_mapped_to_entity"


def test_conflicts_are_detected_across_extractions():
    other = _fact(id="fact-2", object_value="商机跟进")
    build = build_candidates(
        facts=[_fact(), other],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert len(build.items) == 2
    # 同 change-set 内 display_name 与 entity_key 均自动去重，避免撞 term_conflict / key 冲突
    assert build.items[0]["entity_key"] != build.items[1]["entity_key"]
    assert (
        build.items[0]["payload"]["display_name"]
        != build.items[1]["payload"]["display_name"]
    )
    assert build.items[0]["payload"]["conflicts"] == ["其他抽取取值：商机跟进"]
    assert build.items[1]["payload"]["conflicts"] == ["其他抽取取值：线索跟进"]


def test_unresolved_questions_are_collected():
    question = _fact(
        id="fact-3",
        classification="open_question",
        fact_type="open_question",
        subject="报价口径",
        predicate="是否含实施",
        review_status="needs_clarification",
    )
    build = build_candidates(
        facts=[_fact(), question],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert build.unresolved_questions == ["报价口径｜是否含实施"]
    assert build.items[0]["payload"]["unresolved_questions"] == ["报价口径｜是否含实施"]


def test_char_span_locator_restores_verbatim_slice():
    build = build_candidates(
        facts=[_fact(source_locator={"type": "char_span", "start": 6, "end": 15})],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert build.items[0]["payload"]["evidence_quote"] == "客户经理负责线索跟"


def test_process_and_system_map_to_object_types_while_metric_skips_in_m2():
    proc = _fact(id="f-proc", fact_type="process", subject="线索分配流程")
    metric = _fact(id="f-met", fact_type="metric", subject="转化率", object_value="30%")
    build = build_candidates(
        facts=[proc, metric],
        source_texts={"interview_minutes:min-1": SOURCE_TEXT},
    )

    assert len(build.items) == 1
    assert build.items[0]["entity_type"] == "object_types"
    assert _KEY_RE.fullmatch(build.items[0]["entity_key"]) is not None
    assert [s["reason"] for s in build.skipped] == ["fact_type_not_mapped_to_entity"]
