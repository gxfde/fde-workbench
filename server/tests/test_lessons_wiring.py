# -*- coding: utf-8 -*-
"""agent 上下文知识片段接线测试与静态钉（L 线 L3 轮，2026-11-12）。

静态钉四组（钉 ``server/seeds/lessons.json`` 与 ``agents/lessons.py``）：
①种子 schema 闭集＋sha256 逐条一致（**改 text 必留 diff**）；②能力域闭集
（capability_tags ⊆ ``CAPABILITY_REQUIREMENTS`` 的 ``agent.*`` 键，persona
键不可作能力腿）；③答案字段词汇零命中（诊断卡判卷基准键族＋客户资料词
永不进种子——污染单向阀的 lessons 侧承载）；④接线行为（能力腿/行业过滤、
top-K 与单条截断、运行时软失败、渲染实例非空——设计稿 §5-L3 验收判据）。

种子内容纪律：只含抽象打法/判据，零案例答案、零客户资料、零未溯源数字；
来源＝SOP 现行产品已蒸馏资产（单一来源）。评测集展示面**不得**进本面——
生成器可见的知识库种子面属污染单向阀禁止域，既有污染隔离钉 N2/N3
机械拦截（2026-11-12 CI 实测拦截记录留痕，可推翻）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from fde_api.agents import lessons
from fde_api.control.access import CAPABILITY_REQUIREMENTS

SEED_PATH = Path(__file__).resolve().parents[1] / "seeds" / "lessons.json"

# 诊断卡判卷基准键族（污染单向阀：答案字段词汇零命中）＋客户资料词。
ANSWER_VOCAB = (
    "ground_truth",
    "problems_expected",
    "solution_direction",
    "fde_actions_expected",
    "must_not_hallucinate",
    "human_boundary",
    "真实姓名",
    "身份证",
    "微信号",
)


def _raw_seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 静态钉①②③：种子内容质量（CI 强制）
# ---------------------------------------------------------------------------


def test_seed_schema_closed_and_sha256_matches_text():
    raw = _raw_seed()
    assert raw.get("version") == "lessons-v1"
    entries = raw.get("entries")
    assert isinstance(entries, list) and 10 <= len(entries) <= 20
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids))
    for entry in entries:
        assert lessons.REQUIRED_ENTRY_KEYS.issubset(entry), entry.get("id")
        assert not (set(entry) - lessons.REQUIRED_ENTRY_KEYS - lessons.OPTIONAL_ENTRY_KEYS)
        # sha256 逐条一致：改 text 必留 diff（指纹钉）。
        assert entry["sha256"] == hashlib.sha256(entry["text"].encode("utf-8")).hexdigest(), entry["id"]
        assert entry["source_ref"].strip(), entry["id"]
        assert entry["text"].strip() and len(entry["text"]) <= 200, entry["id"]


def test_seed_capability_tags_in_closed_domain():
    agent_keys = {key for key in CAPABILITY_REQUIREMENTS if key.startswith("agent.")}
    for entry in _raw_seed()["entries"]:
        tags = entry["capability_tags"]
        assert isinstance(tags, list) and tags, entry["id"]
        for tag in tags:
            assert tag in agent_keys, f"{entry['id']}: {tag}"
            assert not tag.startswith("agent.persona."), entry["id"]


def test_seed_zero_answer_vocab_and_customer_words():
    raw_text = SEED_PATH.read_text(encoding="utf-8")
    for word in ANSWER_VOCAB:
        assert word not in raw_text, word


def test_load_entries_rejects_malformed(tmp_path):
    bad = tmp_path / "lessons.json"
    bad.write_text(json.dumps({"version": "lessons-v1", "entries": [{"id": "x"}]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        lessons.load_entries(bad)
    missing = tmp_path / "absent.json"
    with pytest.raises(SystemExit):
        lessons.load_entries(missing)


# ---------------------------------------------------------------------------
# 选择行为（纯函数，合成条目）
# ---------------------------------------------------------------------------


def _entries():
    return [
        {"id": "L1", "capability_tags": ["agent.module.solution"], "text": "方案甲" * 100, "industries": ["foreign_trade"]},
        {"id": "L2", "capability_tags": ["agent.module.presales"], "text": "售前乙", "industries": []},
        {"id": "L3", "capability_tags": ["agent.module.solution", "agent.quality_guard"], "text": "通用丙"},
        {"id": "L4", "capability_tags": ["agent.module.solution"], "text": "方案丁"},
    ]


def test_select_filters_by_capability_tier():
    picked = lessons.select_lessons(_entries(), capability_tier="agent.module.presales", top_k=5, max_chars=400)
    assert [row["id"] for row in picked] == ["L2"]
    picked = lessons.select_lessons(_entries(), capability_tier="agent.quality_guard", top_k=5, max_chars=400)
    assert [row["id"] for row in picked] == ["L3"]


def test_select_honors_industries_restriction():
    picked = lessons.select_lessons(
        _entries(), capability_tier="agent.module.solution", project_industry="legal_services", top_k=5, max_chars=400
    )
    # L1 限定 foreign_trade ⇒ 跳过；L3/L4 通用 ⇒ 注入。
    assert [row["id"] for row in picked] == ["L3", "L4"]
    picked = lessons.select_lessons(
        _entries(), capability_tier="agent.module.solution", project_industry="foreign_trade", top_k=5, max_chars=400
    )
    assert [row["id"] for row in picked] == ["L1", "L3", "L4"]


def test_select_top_k_and_max_chars_caps():
    picked = lessons.select_lessons(
        _entries(), capability_tier="agent.module.solution", project_industry="foreign_trade", top_k=2, max_chars=10
    )
    assert [row["id"] for row in picked] == ["L1", "L3"]
    assert all(len(row["text"]) <= 10 for row in picked)


# ---------------------------------------------------------------------------
# 接线（运行时软失败＋渲染实例）
# ---------------------------------------------------------------------------


def _settings(**overrides):
    # 键名＝config.Settings 字段名（L4 断点⑥修正：此前假键 fde_agent_lessons_*
    # 与 config 字段 agent_lessons_* 错配，掩盖了生产注入恒关的真缺陷）。
    base = {
        "agent_forbidden_terms": "",
        "agent_lessons_enabled": True,
        "agent_lessons_top_k": 3,
        "agent_lessons_max_chars": 400,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_snippets_disabled_returns_empty():
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    assert lessons.knowledge_snippets_for(
        project=project, agent=agent, settings=_settings(agent_lessons_enabled=False)
    ) == ()


def test_real_settings_injection_on_by_default_and_closable(app):
    """断点⑥验收钉（L4）：create_app 真实 Settings 下注入默认生效、可关。

    此前 lessons.py 读 ``fde_agent_lessons_*`` 而配置字段是 ``agent_lessons_*``
    ⇒ 生产注入恒关且任何「真实 Settings」测试都测不出（假 settings 掩盖）。
    本钉用 app 夹具的真实 SETTINGS 实例断言：默认开 ⇒ 非空；翻关 ⇒ 空。
    """
    settings = app.config["SETTINGS"]
    assert bool(settings.agent_lessons_enabled) is True
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    snippets = lessons.knowledge_snippets_for(project=project, agent=agent, settings=settings)
    assert snippets, "真实 Settings 下知识片段注入应为默认开启（断点⑥防复发）"
    closed = settings.model_copy(update={"agent_lessons_enabled": False})
    assert lessons.knowledge_snippets_for(project=project, agent=agent, settings=closed) == ()


def test_snippets_soft_fail_on_missing_or_broken_seed(tmp_path):
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    lessons.knowledge_snippets_for(project=project, agent=agent, settings=_settings())
    # 缺文件/形状坏 → 空元组（run 路径不炸；种子质量由 CI 静态钉拦截）。
    import unittest.mock as mock

    with mock.patch.object(lessons, "load_entries", side_effect=SystemExit("boom")):
        assert lessons.knowledge_snippets_for(project=project, agent=agent, settings=_settings()) == ()


def test_snippets_happy_path_reads_project_industry():
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot={"industry_name": "foreign_trade"})
    snippets = lessons.knowledge_snippets_for(project=project, agent=agent, settings=_settings())
    assert snippets and all("id" in row and "text" in row for row in snippets)


def test_render_context_knowledge_section_non_empty(monkeypatch):
    """验收判据：知识片段段非空渲染实例（设计稿 §5-L3）。"""
    from fde_api.agents import service as agent_service

    monkeypatch.setattr(agent_service, "_settings", lambda: _settings())
    project = SimpleNamespace(
        id="proj-lessons-smoke", project_code="P-LESSONS-SMOKE", template_snapshot=None
    )
    agent = SimpleNamespace(name="方案顾问", capability_tier="agent.module.solution")
    session = SimpleNamespace(scalar=lambda *a, **k: None)
    text, _refs = agent_service._render_context(session, project=project, agent=agent, solution=None)
    assert "## 知识片段" in text
    assert "（未检索到知识片段）" not in text
    # 方案腿条目在场（真实种子 → 真实渲染）。
    assert any(row["id"] in text for row in lessons.load_entries())


# ---------------------------------------------------------------------------
# 学习闭环 2.0 L5：动态 Lessons 装载层（agent_lessons published 行 DB 腿）
# ---------------------------------------------------------------------------


def _dyn_row(entry_id: str, *, status: str = "published", tags=None) -> SimpleNamespace:
    """合成 AgentLesson 行（只带 dynamic_published_entries 读面的属性面）。"""
    return SimpleNamespace(
        entry_id=entry_id,
        capability_tags=tags or ["agent.module.solution"],
        text=f"动态经验 {entry_id}" * 5,
        source_ref=f"improvement-proposal:{entry_id}",
        text_sha256="f" * 64,
        industries=None,
        status=status,
        created_at=None,
        id=f"row-{entry_id}",
    )


class _FakeScalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    """DB 腿替身：只暴露 dynamic_published_entries 用到的 .scalars()。"""

    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.query_count = 0

    def scalars(self, stmt):  # noqa: ARG002 - stmt 只验形状
        self.query_count += 1
        return _FakeScalars(self.rows)


def test_dynamic_published_entries_none_session_empty():
    """session=None（既有零回归路径）⇒ 动态腿读面空列表。"""
    assert lessons.dynamic_published_entries(None) == []


def test_dynamic_published_entries_soft_fail_on_broken_db_leg():
    """DB 腿故障（无 .scalars 属性 ⇒ AttributeError）软失败返 []，不炸 run 路径。"""
    assert lessons.dynamic_published_entries(SimpleNamespace()) == []


def test_dynamic_published_entries_maps_rows_like_seeds_schema():
    """published 行映射为与 seeds 同构 entry（capability_tags/text/source_ref/sha256）。"""
    session = _FakeSession([_dyn_row("LESS-DYN-001"), _dyn_row("LESS-DYN-002")])
    rows = lessons.dynamic_published_entries(session)
    assert [row["id"] for row in rows] == ["LESS-DYN-001", "LESS-DYN-002"]
    assert all(set(row) >= {"id", "capability_tags", "text", "source_ref", "sha256"} for row in rows)
    # 过滤（status=='published'）在 SQL WHERE 层，读面只映射；_FakeSession 不模拟
    # 真实 DB，故 status 过滤行为由「回滚行不在 rows ⇒ 不注入」钉（见下行测试）。


def test_dynamic_published_entries_industries_optional():
    """industries 为空 ⇒ 不写键（通用条目）；非空 ⇒ 原样带出（行业过滤腿生效）。"""
    session = _FakeSession([_dyn_row("LESS-DYN-003")])
    row = lessons.dynamic_published_entries(session)[0]
    assert "industries" not in row
    tagged = _dyn_row("LESS-DYN-004")
    tagged.industries = ["foreign_trade"]
    row2 = lessons.dynamic_published_entries(_FakeSession([tagged]))[0]
    assert row2["industries"] == ["foreign_trade"]


def test_knowledge_snippets_dynamic_union_seeds_first(tmp_path, monkeypatch):
    """seeds 底座 ∪ published 动态行：top_k 竞争 seeds 优先、动态腿追加在后。"""
    import unittest.mock as mock

    seed_rows = [
        {"id": f"S-{i}", "capability_tags": ["agent.module.solution"], "text": f"种子甲{i}",
         "source_ref": "seed", "sha256": "e" * 64, "industries": []}
        for i in range(10)
    ]
    dynamic = _dyn_row("LESS-DYN-001")
    session = _FakeSession([dynamic])
    with mock.patch.object(lessons, "load_entries", return_value=tuple(seed_rows)):
        picked = lessons.knowledge_snippets_for(
            project=SimpleNamespace(template_snapshot=None),
            agent=SimpleNamespace(capability_tier="agent.module.solution"),
            settings=_settings(agent_lessons_top_k=11),
            session=session,
        )
    ids = [row["id"] for row in picked]
    # seeds 10 条在前（底座优先），动态行第 11 位追加；top_k=11 全收。
    assert ids == [f"S-{i}" for i in range(10)] + ["LESS-DYN-001"]
    assert session.query_count == 1


def test_knowledge_snippets_dynamic_hot_effect_and_rollback(tmp_path, monkeypatch):
    """热生效/回滚行为钉：同进程内两次装载间 DB 腿变了 ⇒ 注入面立变（零模块级缓存）。"""
    import unittest.mock as mock

    seed_rows = [
        {"id": f"S-{i}", "capability_tags": ["agent.module.solution"], "text": f"种子甲{i}",
         "source_ref": "seed", "sha256": "e" * 64, "industries": []}
        for i in range(2)
    ]
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    with mock.patch.object(lessons, "load_entries", return_value=tuple(seed_rows)):
        # 发布 ⇒ 下一 run 立即可见（published 行在场）。
        live = _FakeSession([_dyn_row("LESS-DYN-001")])
        ids_live = [row["id"] for row in lessons.knowledge_snippets_for(
            project=project, agent=agent, settings=_settings(agent_lessons_top_k=10), session=live)]
        assert "LESS-DYN-001" in ids_live
        # 回滚（published→retired 行从读面消失）⇒ 立即不见，同进程无需重启。
        rolled_back = _FakeSession([])
        ids_rolled = [row["id"] for row in lessons.knowledge_snippets_for(
            project=project, agent=agent, settings=_settings(agent_lessons_top_k=10), session=rolled_back)]
        assert "LESS-DYN-001" not in ids_rolled
        assert ids_rolled == [f"S-{i}" for i in range(2)]


def test_knowledge_snippets_session_none_behavior_byte_identical(tmp_path, monkeypatch):
    """零回归：session=None 只走静态 seeds（动态腿不读、不查 DB），行为逐字节不变。"""
    import unittest.mock as mock

    seed_rows = [
        {"id": f"S-{i}", "capability_tags": ["agent.module.solution"], "text": f"种子甲{i}",
         "source_ref": "seed", "sha256": "e" * 64, "industries": []}
        for i in range(2)
    ]
    with mock.patch.object(lessons, "load_entries", return_value=tuple(seed_rows)), \
         mock.patch.object(lessons, "dynamic_published_entries") as dyn_spy:
        picked = lessons.knowledge_snippets_for(
            project=SimpleNamespace(template_snapshot=None),
            agent=SimpleNamespace(capability_tier="agent.module.solution"),
            settings=_settings(agent_lessons_top_k=2),
        )
    assert [row["id"] for row in picked] == ["S-0", "S-1"]
    dyn_spy.assert_not_called()


# ---------------------------------------------------------------------------
# seed 压制消解（收尾轮 R4）：published 动态行保底 1 席
# v1 局限＝seeds 恒在前 top_k 竞争中挤掉动态经验——学习闭环整条链的价值
# （真实交付反哺注入）被静态底座压制。修＝动态行保底 1 席，无动态行零变化。
# ---------------------------------------------------------------------------


def _fake_session(rows):
    """dynamic_published_entries 只用 session.scalars(...).all()——假会话直返行。"""
    return SimpleNamespace(scalars=lambda *a, **k: SimpleNamespace(all=lambda: rows))


def _dyn_lesson_row(entry_id="LESS-DYN-R4", tier="agent.module.solution"):
    return SimpleNamespace(
        entry_id=entry_id,
        capability_tags=[tier],
        text="动态经验：交付前先核对回款凭证清单。",
        source_ref="PROP-R4TEST",
        text_sha256="a" * 64,
        industries=None,
    )


def _seed_entries(count: int) -> list[dict]:
    return [
        {"id": f"LESS-SOP-R4-{i}", "capability_tags": ["agent.module.solution"], "text": f"SOP-{i}"}
        for i in range(count)
    ]


def test_dynamic_lesson_gets_reserved_slot_when_seeds_fill_top_k(monkeypatch):
    """seeds 占满 top_k ⇒ 匹配的 published 动态行保底 1 席（seeds 让出末席）。"""
    monkeypatch.setattr(lessons, "load_entries", lambda **kwargs: _seed_entries(3))
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    session = _fake_session([_dyn_lesson_row()])
    picked = lessons.knowledge_snippets_for(
        project=project, agent=agent, settings=_settings(), session=session
    )
    ids = [row["id"] for row in picked]
    assert ids == ["LESS-SOP-R4-0", "LESS-SOP-R4-1", "LESS-DYN-R4"]
    assert len(ids) == 3


def test_no_dynamic_rows_keeps_seed_selection_byte_identical(monkeypatch):
    """无匹配动态行 ⇒ 纯 seeds 选择（逐字节零行为变化——既有路径零回归）。"""
    seeds = _seed_entries(4)
    monkeypatch.setattr(lessons, "load_entries", lambda **kwargs: seeds)
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    picked = lessons.knowledge_snippets_for(
        project=project, agent=agent, settings=_settings()
    )
    assert picked == tuple(
        lessons.select_lessons(
            seeds,
            capability_tier="agent.module.solution",
            project_industry=None,
            top_k=3,
            max_chars=400,
        )
    )


def test_dynamic_rows_fill_remaining_slots_when_seeds_scarce(monkeypatch):
    """seeds 稀缺 ⇒ 动态行按序补足剩余席位（不止保底 1 席）。"""
    monkeypatch.setattr(lessons, "load_entries", lambda **kwargs: _seed_entries(1))
    agent = SimpleNamespace(capability_tier="agent.module.solution")
    project = SimpleNamespace(template_snapshot=None)
    session = _fake_session([_dyn_lesson_row("LESS-DYN-R4-A"), _dyn_lesson_row("LESS-DYN-R4-B")])
    picked = lessons.knowledge_snippets_for(
        project=project, agent=agent, settings=_settings(), session=session
    )
    ids = [row["id"] for row in picked]
    assert ids == ["LESS-SOP-R4-0", "LESS-DYN-R4-A", "LESS-DYN-R4-B"]
