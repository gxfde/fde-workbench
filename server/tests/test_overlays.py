"""L5 任务 5：动态 PromptOverlay 两点共用装载静态钉（学习闭环 2.0 任务书 L53）。

钉面（任务书 L59 验收判据「两新表写面静态钉」的 overlay 侧＋注入点回归钉）：

1. **白名单派生钉**——``OVERLAY_PURPOSE_WHITELIST`` 恒等于
   ``prompt_registry`` 登记闭集（点号转下划线）减去公网面
   ``diagnostics_report``（评测集污染隔离＋公网写面纪律，v1 拍板「排除
   diagnostics.* 公网面」）；
2. **注入闸五件套①/②纯函数钉**——句式静态闸（第二人称＋祈使动词核心族，
   规范陈述词放行）与 n-gram 防洗稿比例；
3. **注入语义钉**——仅追加式（system 角色 content 追加 / 无 system 前插，
   浅拷贝不回写原列表）；
4. **装载软失败钉**——闭集外 purpose / 无应用上下文 / DB 故障 ⇒ 空列表
   零回归（既有指令源逐字节不变）；
5. **min_prompt_version 数字尾缀闸钉**——current<required 跳过、任一侧不可
   解析 fail-open；
6. **注入点源级钉**——``execute_ai_prompt`` 装载在指纹之后、降级分叉之前，
   全调用点（7 处）带 ``context_payload_json=overlay_payload``；
   ``complete_json`` 直连腿装载在指纹之后＋DSH 防双注入守卫，5 处 ``_audit``
   调用点透传；
7. **写面零触碰钉**——``ai/overlays.py`` 是纯读面，模块内零
   ``session.add`` / 零 INSERT（写面 ⊆ {release_channel 执行器, L5 测试}，
   任务书 L55；任务 7 落地三支执行器后由 AST 写面钉接管）。
"""

from __future__ import annotations

import ast
import pathlib
from pathlib import Path
from types import SimpleNamespace

from fde_api.ai.overlays import (
    OVERLAY_PURPOSE_WHITELIST,
    apply_overlays_to_messages,
    apply_overlays_to_system_prompt,
    load_overlays,
    ngram_overlap_ratio,
    purpose_allowed,
    validate_overlay_fragment,
    version_suffix,
)
from fde_api.ai.prompt_registry import PROMPT_REGISTRATIONS

SERVER_ROOT = Path(__file__).resolve().parents[1]


# ── 1. 白名单派生钉 ─────────────────────────────────────────────────────────


def test_whitelist_derives_from_registry_excluding_public_face():
    """派生而非硬编码：registry 登记闭集转下划线，公网面 diagnostics_report 剔除。"""
    derived = frozenset(
        reg.key.replace(".", "_") for reg in PROMPT_REGISTRATIONS
    ) - frozenset({"diagnostics_report"})
    assert OVERLAY_PURPOSE_WHITELIST == derived
    assert "diagnostics_report" not in OVERLAY_PURPOSE_WHITELIST
    assert purpose_allowed("diagnostics_report") is False


def test_intrinsics_purposes_allowed():
    for key in (
        "simulation_workbench",
        "simulation_improvement_draft",
        "quality_testcase_draft",
        "plans_delivery_plan_draft",
        "workflows_dag_draft",
        "dispatch_match_recommend",
    ):
        assert purpose_allowed(key) is True, key


def test_unknown_purpose_rejected():
    assert purpose_allowed("not_a_registered_purpose") is False
    assert purpose_allowed("") is False


# ── 2. 版本尾缀解析 ─────────────────────────────────────────────────────────


def test_version_suffix_numeric_tail():
    assert version_suffix("prompt-sim-v3") == 3
    assert version_suffix("prompt-sim-v10") == 10
    assert version_suffix(None) is None
    assert version_suffix("") is None
    assert version_suffix("no-digit-tag") is None


# ── 3. 注入闸五件套①：句式静态闸 ─────────────────────────────────────────


def test_validate_fragment_empty_and_length_gate():
    assert validate_overlay_fragment("") == "empty_fragment"
    assert validate_overlay_fragment("x" * 201) == "fragment_too_long"
    assert validate_overlay_fragment("x" * 200) is None


def test_validate_fragment_rejects_imperative_family():
    # 第二人称＋祈使动词核心族（中英双语）
    for bad in (
        "你务必核对数据后再提交。",
        "请确认你的理解。",
        "切勿虚构交付细节。",
        "严禁绕过人工门禁。",
        "Please do not fabricate citations.",
        "You must review the artifacts.",
        "Make sure the output is JSON.",
    ):
        assert validate_fragment_is_violation(bad), bad


def test_validate_fragment_allows_declarative_norms():
    # ★误伤修正回归钉：规范陈述词（必须/不得/不要/must/should）放行，
    # 祈使语义由核心族兜住，残余风险由五件套③审批面人工复核收口。
    assert validate_overlay_fragment("模型输出须保留引用编号，不得省略出处。") is None
    assert validate_overlay_fragment("数据不足时标记为 insufficient_data。") is None
    assert validate_overlay_fragment("Cite the artifact id in every claim.") is None


def validate_fragment_is_violation(fragment: str) -> bool:
    return validate_overlay_fragment(fragment) == "imperative_or_second_person"


# ── 4. 注入闸五件套②：n-gram 防洗稿 ──────────────────────────────────────


def test_ngram_self_and_disjoint():
    text = "交付物编号引用必须保留出处链"
    assert ngram_overlap_ratio(text, text, n=6) == 1.0
    assert ngram_overlap_ratio(text, "完全无关的参考语料" * 4, n=6) == 0.0
    # 短文本（<n）无 n-gram 可比 ⇒ 0.0（不编造比例）
    assert ngram_overlap_ratio("短", "参考语料", n=6) == 0.0


# ── 5. 注入语义（仅追加式） ────────────────────────────────────────────────


def test_apply_to_system_prompt_append_semantics():
    base = "你是 FDE 交付助手。"
    out = apply_overlays_to_system_prompt(base, ["条款A", "条款B"])
    assert out.startswith(base)
    assert out.endswith("条款A\n条款B")
    # 空 fragments ⇒ 原对象逐字节返回（零回归）
    assert apply_overlays_to_system_prompt(base, []) is base
    assert apply_overlays_to_system_prompt(None, []) is None


def test_apply_to_messages_append_without_mutation():
    system = {"role": "system", "content": "既有指令源"}
    user = {"role": "user", "content": "问题"}
    messages = [system, user]
    out = apply_overlays_to_messages(messages, ["条款A"])
    assert out is not messages
    assert messages[0]["content"] == "既有指令源"  # 原列表零改动
    assert out[0]["content"].startswith("既有指令源")
    assert out[0]["content"].endswith("条款A")
    assert out[1] is user
    # 无 system 行 ⇒ 前插（用同一引用列表验证浅拷贝不回写）
    passthrough = dict(user)
    out2 = apply_overlays_to_messages([passthrough], ["条款B"])
    assert out2[0]["role"] == "system"
    assert "条款B" in out2[0]["content"]
    assert out2[1] is passthrough  # 非 system 行原对象透传


# ── 6. 装载软失败＋版本闸（假 session 隔离 DB） ───────────────────────────


class _FakeResult:
    def __init__(self, rows: list):
        self._rows = rows

    def all(self) -> list:
        return list(self._rows)


class _FakeSession:
    """模拟「DB 侧已完成 where/order_by 过滤」的读面返回（装载函数只消费行序）。"""

    def __init__(self, rows: list | tuple = (), failure: Exception | None = None):
        self._rows = list(rows)
        self._failure = failure

    def scalars(self, stmt) -> _FakeResult:
        if self._failure is not None:
            raise self._failure
        return _FakeResult(self._rows)


def _overlay_row(
    row_id: str = "po-1",
    fragment: str = "条款A",
    sha: str = "a" * 64,
    min_prompt_version: str | None = None,
    status: str = "published",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        fragment=fragment,
        content_sha256=sha,
        min_prompt_version=min_prompt_version,
        status=status,
    )


def test_load_overlays_closed_set_outside_returns_empty():
    frags, payload = load_overlays("not_a_registered_purpose")
    assert frags == [] and payload is None


def test_load_overlays_no_app_context_soft_fail():
    # 无应用上下文且 session=None ⇒ 软失败空列表（不 raise）
    frags, payload = load_overlays("simulation_workbench")
    assert frags == [] and payload is None


def test_load_overlays_published_rows_with_payload():
    rows = [
        _overlay_row("po-1", "条款A", "a" * 64),
        _overlay_row("po-2", "条款B", "b" * 64),
    ]
    frags, payload = load_overlays("simulation_workbench", session=_FakeSession(rows))
    assert frags == ["条款A", "条款B"]
    assert payload == {
        "overlay_ids": ["po-1", "po-2"],
        "overlay_sha256": ["a" * 64, "b" * 64],
    }


def test_load_overlays_min_version_gate_numeric_tail():
    rows = [
        _overlay_row("po-1", "低版本条款", "a" * 64, min_prompt_version="prompt-v2"),
        _overlay_row("po-2", "不可解析版本条款", "b" * 64, min_prompt_version="weird"),
    ]
    # current v1 < required v2 ⇒ po-1 跳过；po-2 不可解析 fail-open 保留
    frags, payload = load_overlays(
        "simulation_workbench", "prompt-v1", session=_FakeSession(rows)
    )
    assert frags == ["不可解析版本条款"]
    assert payload["overlay_ids"] == ["po-2"]
    # current v10 ≥ required v2（数字尾缀比较，非字符串 v10<v2 错位）⇒ 保留
    frags2, _ = load_overlays(
        "simulation_workbench", "prompt-v10", session=_FakeSession(rows)
    )
    assert frags2 == ["低版本条款", "不可解析版本条款"]


def test_load_overlays_db_failure_soft_fail():
    session = _FakeSession(failure=RuntimeError("db down"))
    frags, payload = load_overlays("simulation_workbench", session=session)
    assert frags == [] and payload is None


# ── 7. 注入点源级钉（防未来轮次把装载挪走/漏传归因） ─────────────────────


def _read(rel: str) -> str:
    return (SERVER_ROOT / "src" / "fde_api" / rel).read_text(encoding="utf-8")


def test_execute_ai_prompt_wiring_source_nail():
    text = _read("control/ai_server_client.py")
    load_call = "load_overlays(purpose, prompt_version)"
    assert load_call in text
    # 装载点在指纹之后、降级分叉之前（防降级路径丢 overlay，P0-Ⅱ）
    fingerprint_at = text.index("fingerprint = compute_prompt_fingerprint(")
    load_at = text.index(load_call)
    fork_at = text.index("if not dsh_usable:")
    assert fingerprint_at < load_at < fork_at
    # execute 侧全部审计/降级调用点带 overlay 归因（7 处：预算闸 1＋降级 2＋_audit_execution 4）
    assert text.count("context_payload_json=overlay_payload") == 7
    # _degraded_direct_result 签名带 keyword（透传到其内 4 处 _audit_execution）
    assert "context_payload_json: dict[str, Any] | None = None" in text


def test_complete_json_direct_leg_wiring_source_nail():
    text = _read("ai/deepseek.py")
    load_call = "load_overlays(purpose, prompt_version)"
    assert load_call in text
    # DSH 防双注入守卫：DSH 分支经 structured_completion→execute_ai_prompt
    # 由那一侧装载一次，本腿不重复注入 messages（同一片段不得双重下发）
    assert "_dsh_branch" in text
    fingerprint_at = text.index("fingerprint = compute_prompt_fingerprint(")
    load_at = text.index(load_call)
    assert fingerprint_at < load_at
    # 直连腿 5 处 _audit 调用点透传归因
    assert text.count("context_payload_json=overlay_payload") == 5


def test_auditing_passthrough_source_nail():
    text = _read("ai/auditing.py")
    assert text.count("context_payload_json") >= 4  # 两函数签名＋插入体＋委托


def test_overlays_module_is_read_only_surface():
    """overlay 装载读面零写面：模块内禁止任何 DB 写操作（写面静态钉之 overlay 侧）。"""
    text = _read("ai/overlays.py")
    assert ".add(" not in text
    assert "INSERT INTO" not in text.upper()  # 列表 .insert() 非 DB 写面，精确匹配 SQL 写动词
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("flush", "commit"), "overlay 读面禁写库"
