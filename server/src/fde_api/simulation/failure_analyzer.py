"""失败分析与根因归因（G5，G1 §10.1/§10.2）。

**纯函数**：输入评估结论（+ Trace），输出失败发现与根因候选。不碰数据库。

归因纪律：
- 失败现象 → 候选根因（分类表 + 判据映射）；
- 每个根因候选**必须附证据引用**（无证据即不成立）；
- 置信度三档：`confirmed`（判据直接命中）/ `likely`（相关判据但间接）/
  `hypothesis`（仅分类相符，无直接证据）；
- **只有 `confirmed` 根因可生成改进提案**——`hypothesis` 进人工复核队列。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 失败分类（G1 §10.1；十类，码稳定可断言）
FAILURE_CATEGORIES: dict[str, dict[str, str]] = {
    "FA-01": {
        "title": "未发现客户真实需求",
        "root_cause": "访谈追问不足",
        "target_kind": "prompt",
        "target_scope": "interview",
    },
    "FA-02": {
        "title": "错误理解生产流程",
        "root_cause": "领域知识不足",
        "target_kind": "ontology",
        "target_scope": "domain",
    },
    "FA-03": {
        "title": "方案过度复杂",
        "root_cause": "缺少成本约束",
        "target_kind": "rule",
        "target_scope": "solution",
    },
    "FA-04": {
        "title": "Workflow 节点设计错误",
        "root_cause": "任务拆解能力不足",
        "target_kind": "workflow_template",
        "target_scope": "workflow",
    },
    "FA-05": {
        "title": "工具调用失败",
        "root_cause": "接口或权限问题",
        "target_kind": "tool",
        "target_scope": "tool",
    },
    "FA-06": {
        "title": "交付证据不足",
        "root_cause": "验收标准不明确",
        "target_kind": "rule",
        "target_scope": "acceptance",
    },
    "FA-07": {
        "title": "频繁重复执行",
        "root_cause": "幂等设计不足",
        "target_kind": "workflow_template",
        "target_scope": "workflow",
    },
    "FA-08": {
        "title": "客户约束被忽略",
        "root_cause": "约束未纳入方案检查",
        "target_kind": "rule",
        "target_scope": "solution",
    },
    "FA-09": {
        "title": "权限边界被试探",
        "root_cause": "权限前置检查缺失",
        "target_kind": "rule",
        "target_scope": "permission",
    },
    "FA-10": {
        "title": "成本失控",
        "root_cause": "无预算约束",
        "target_kind": "rule",
        "target_scope": "cost",
    },
}

# 判据 → 失败分类（直接命中 ⇒ confirmed）
CRITERION_TO_FAILURE: dict[str, str] = {
    "D1-01": "FA-01",
    "D1-02": "FA-01",
    "D2-01": "FA-02",
    "D2-02": "FA-02",
    "D3-02": "FA-03",
    "D4-01": "FA-04",
    "D4-02": "FA-04",
    "D4-03": "FA-04",
    "D5-01": "FA-05",
    "D6-01": "FA-06",
    "D6-02": "FA-06",
    "D6-03": "FA-06",
    "D5-03": "FA-07",
    "D7-02": "FA-08",
}

# 硬性失败 → 失败分类
HARD_FAILURE_TO_FAILURE: dict[str, str] = {
    "HF-01": "FA-09",
    "HF-02": "FA-06",
    "HF-03": "FA-04",
    "HF-04": "FA-06",
    "HF-05": "FA-09",
    "HF-07": "FA-08",
}


@dataclass(frozen=True)
class RootCause:
    """根因候选。"""

    code: str
    title: str
    confidence: str
    analysis: str
    evidence_refs: tuple[dict[str, Any], ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "confidence": self.confidence,
            "analysis": self.analysis,
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
        }


@dataclass(frozen=True)
class Finding:
    """一条失败发现。"""

    code: str
    title: str
    severity: str
    dimension: str
    description: str
    evidence_refs: tuple[dict[str, Any], ...]
    root_causes: tuple[RootCause, ...]
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def confirmed_root(self) -> RootCause | None:
        for cause in self.root_causes:
            if cause.confidence == "confirmed":
                return cause
        return None

    def to_json(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity,
            "dimension": self.dimension,
            "description": self.description,
            "evidence_refs": [dict(ref) for ref in self.evidence_refs],
            "root_causes": [cause.to_json() for cause in self.root_causes],
            "detail": dict(self.detail),
        }


def _severity(score: float, threshold: float) -> str:
    if score <= 0.0:
        return "high"
    if score < threshold:
        return "medium"
    return "low"


def analyze_failures(
    *,
    evaluation: dict[str, Any],
    traces: list[dict[str, Any]] | None = None,
    failure_threshold: float = 0.6,
) -> list[Finding]:
    """由评估结论产出失败发现与根因。

    ``evaluation`` 是 L-A 层的 ``scores`` + ``hard_failures``（G1 §9.6 结构）。
    """
    traces = traces or []
    findings: list[Finding] = []

    criteria = (evaluation.get("scores") or {}).get("criteria") or []
    by_key = {str(item.get("key")): item for item in criteria if isinstance(item, dict)}

    # ---- 1. 硬性失败 → 直接失败发现（confirmed） -----------------------
    for failure in evaluation.get("hard_failures") or []:
        code = str(failure.get("code") or "")
        mapped = HARD_FAILURE_TO_FAILURE.get(code)
        if not mapped:
            continue
        meta = FAILURE_CATEGORIES[mapped]
        findings.append(
            Finding(
                code=mapped,
                title=meta["title"],
                severity="high",
                dimension="hard_failure",
                description=f"{code} {failure.get('title')}：{meta['title']}",
                evidence_refs=tuple(
                    dict(ref) for ref in (failure.get("evidence_refs") or [])
                ),
                root_causes=(
                    RootCause(
                        code=meta["root_cause"],
                        title=meta["root_cause"],
                        confidence="confirmed",
                        analysis=f"硬性失败 {code} 直接命中「{meta['title']}」。",
                        evidence_refs=tuple(
                            dict(ref) for ref in (failure.get("evidence_refs") or [])
                        ),
                    ),
                ),
                detail={"hard_failure": code},
            )
        )

    # ---- 2. 低分判据 → 失败发现（confirmed / likely） ------------------
    for key, item in by_key.items():
        mapped = CRITERION_TO_FAILURE.get(key)
        if not mapped:
            continue
        score = float(item.get("score") or 0.0)
        if score >= failure_threshold:
            continue
        meta = FAILURE_CATEGORIES[mapped]
        evidence = tuple(dict(ref) for ref in (item.get("evidence_refs") or []))
        confidence = "confirmed" if evidence else "hypothesis"
        findings.append(
            Finding(
                code=mapped,
                title=meta["title"],
                severity=_severity(score, failure_threshold),
                dimension=str(item.get("dimension") or ""),
                description=(
                    f"判据 {key}「{item.get('title')}」得分 {score:.2f} "
                    f"（阈值 {failure_threshold}）⇒ {meta['title']}"
                ),
                evidence_refs=evidence,
                root_causes=(
                    RootCause(
                        code=meta["root_cause"],
                        title=meta["root_cause"],
                        confidence=confidence,
                        analysis=(
                            f"判据 {key} 未达标，且该判据直接对应「{meta['title']}」"
                            f"⇒ 根因指向「{meta['root_cause']}」。"
                            if evidence
                            else f"仅分类相符、无直接证据 ⇒ 待人工确认「{meta['root_cause']}」。"
                        ),
                        evidence_refs=evidence,
                    ),
                ),
                detail={"criterion": key, "score": score},
            )
        )

    # ---- 3. 工具失败 → FA-05（likely） --------------------------------
    tool_errors = [
        call
        for trace in traces
        for call in (trace.get("tool_call") or [{}])
        if isinstance(call, dict) and call.get("reason")
    ]
    if tool_errors:
        meta = FAILURE_CATEGORIES["FA-05"]
        findings.append(
            Finding(
                code="FA-05",
                title=meta["title"],
                severity="high",
                dimension="D5",
                description=f"模拟环境出现 {len(tool_errors)} 次工具异常调用。",
                evidence_refs=tuple(
                    {"kind": "tool_call", "tool": str(call.get("tool")), "reason": str(call.get("reason"))}
                    for call in tool_errors
                ),
                root_causes=(
                    RootCause(
                        code=meta["root_cause"],
                        title=meta["root_cause"],
                        confidence="likely",
                        analysis="工具异常来自执行面（接口/权限），不指向访谈或方案能力。",
                        evidence_refs=tuple(
                            {"kind": "tool_call", "tool": str(call.get("tool"))}
                            for call in tool_errors
                        ),
                    ),
                ),
                detail={"tool_error_count": len(tool_errors)},
            )
        )

    # 去重：同一失败分类只留**最严重**的一条
    best: dict[str, Finding] = {}
    order = {"high": 0, "medium": 1, "low": 2}
    for finding in findings:
        current = best.get(finding.code)
        if current is None or order[finding.severity] < order[current.severity]:
            best[finding.code] = finding
    return list(best.values())
