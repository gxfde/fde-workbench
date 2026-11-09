"""模型评估层的提示词构造（V3.2 G9 接线轮）。

沿用仓库既有范式：``system`` 段固定角色与纪律，``user`` 段只放**本次评估所需
的结构化材料**（Rubric / 期望结果 / 交付产物正文 / 过程摘要）。

**三条纪律**（写进 system 段，也是模型的硬约束）：
1. **只评不判终局**——模型给分项与证据，**终局结论由规则层（L-A）判定**；模型
   不得宣称「通过/硬性失败」。
2. **证据强制**——每条评分必须引用交付正文里的**原文片段**；无引用的评分会被
   契约层丢弃（宁缺毋滥）。
3. **不评未交付的**——不得依据 Rubric 之外的标准加减分；不得虚构未见的产物。
"""
from __future__ import annotations

import json
from typing import Any, Iterator

SYSTEM_PROMPT = """你是 FDE 交付质量的独立评估员。

你只做一件事：按给定的评分基准（Rubric）给**分项评分 + 证据引用**。

纪律：
1. 只按 Rubric 评分，不引入 Rubric 之外的标准，不因「看起来不错」加分。
2. 每条评分必须引用交付正文里的原文片段作为证据；无法引用原文的条目不要给分。
3. 你不判定最终通过与否，也不判定硬性失败——那些由确定性规则层负责。
4. 只依据提供的材料判断；材料没写的，就是没有。不要推测交付方「可能做了什么」。

输出格式（唯一允许的形状，G9 真机实测补充：不给形状模型会回显 Rubric 桶键）——
单个 JSON 对象，顶层键**只有** `criteria` 与 `summary`：
```json
{"criteria": [
    {"key": "MI-1", "dimension": "D1", "title": "<判据短名>", "score": 0.7,
     "verdict": "pass",
     "evidence_refs": [{"kind": "quote", "text": "<交付正文原文片段，≤600 字>"}],
     "reason": "<一句话理由>"}
  ],
 "summary": "<一句话总评>"}
```
- `key`：自拟唯一短名（must_identify 第 n 条建议 `MI-n`、must_avoid → `MA-n`、must_produce → `MP-n`）；
- `dimension`：只准取 D1–D7——D1 访谈与需求识别 / D2 业务流程与本体建模 /
  D3 解决方案质量 / D4 任务拆解与 Workflow 设计 / D5 实施质量 /
  D6 测试、验收与证据 / D7 成本、风险与沟通；
- `verdict`：只准 `pass` / `partial` / `fail`；`score` 在 0–1；
- **禁止**把 `must_identify` / `must_avoid` / `must_produce` 作为输出键——
  它们是输入材料（Rubric 桶），不是输出格式；
- 没有原文证据的判据**不要输出**（会被整条丢弃）。"""

# 交付正文最多带入的字符数（超长截断，避免超上下文与烧 token）。
# G9b 真机实测：真实面一次运行有 5–7 份产物，全量 6000 字/份会让 provider
# 读超时——模型层是**咨询性第二意见**（不判终局），3000 字摘录足够定性。
MAX_ARTIFACT_CHARS = 3000
MAX_TRACE_ITEMS = 24


def _clip(text: str, limit: int = MAX_ARTIFACT_CHARS) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…（已截断）"


def _iter_artifact_blocks(artifacts: dict[str, Any]) -> Iterator[tuple[str, str]]:
    """遍历产物正文块（G9b 真机实测修正：评估器实际传入**相位键控**集合）。

    - 相位键控（``{"analysis": {...}, "design": {...}, ...}``）：真实面相位体内
      ``artifacts`` 是产物条目列表（含 ``text`` 摘录）；mock 面相位体是结构化
      字段——同样序列化进正文（模型评估的就是交付内容本身）。
    - 顶层 ``artifacts`` 列表：测试注入形态，向后兼容。
    """
    top = artifacts.get("artifacts") if isinstance(artifacts, dict) else None
    if isinstance(top, list):
        for index, entry in enumerate(top, start=1):
            if isinstance(entry, dict):
                yield (
                    str(entry.get("name") or f"artifact-{index}"),
                    str(entry.get("text") or ""),
                )
    for phase in ("analysis", "design", "implementation", "validation"):
        body = artifacts.get(phase)
        if not isinstance(body, dict):
            continue
        entries = body.get("artifacts")
        if isinstance(entries, list) and entries:
            for entry in entries:
                if isinstance(entry, dict):
                    name = str(entry.get("name") or entry.get("pointer") or phase)
                    yield (f"{phase}/{name}", str(entry.get("text") or ""))
            continue
        rest = {
            key: value
            for key, value in body.items()
            if key not in ("artifacts", "tool_calls", "evidence_count")
        }
        if rest:
            yield (
                f"{phase}（结构化交付）",
                json.dumps(rest, ensure_ascii=False)[:MAX_ARTIFACT_CHARS],
            )


def build_evaluation_messages(
    *,
    judge_view: dict[str, Any],
    artifacts: dict[str, Any],
    traces: list[dict[str, Any]] | None = None,
    rubric_version: str = "rubric-v1",
) -> list[dict[str, str]]:
    """构造模型评估的 messages（system + user）。

    ``judge_view`` 是评分侧视图（含 reference/rubric）——**只有评估器能装载它**。
    """
    reference = judge_view.get("reference") if isinstance(judge_view, dict) else None
    reference = reference if isinstance(reference, dict) else {}
    rubric = reference.get("rubric") if isinstance(reference, dict) else None
    rubric = rubric if isinstance(rubric, dict) else {}

    blocks: list[str] = []
    blocks.append("## 评分基准（Rubric）")
    blocks.append(f"规则版本：{rubric_version}")
    for label, key in (
        ("必须识别（must_identify）", "must_identify"),
        ("必须避免（must_avoid）", "must_avoid"),
        ("必须产出（must_produce）", "must_produce"),
    ):
        items = [str(item) for item in (rubric.get(key) or [])]
        blocks.append(f"{label}：")
        if items:
            blocks.extend(f"- {item}" for item in items)
        else:
            blocks.append("- （未提供）")

    outcomes = [str(item) for item in (reference.get("expected_outcomes") or [])]
    criteria = [str(item) for item in (reference.get("acceptance_criteria") or [])]
    if outcomes:
        blocks.append("## 期望结果")
        blocks.extend(f"- {item}" for item in outcomes)
    if criteria:
        blocks.append("## 验收标准")
        blocks.extend(f"- {item}" for item in criteria)

    blocks.append("## 交付正文（按产物逐条）")
    wrote_any = False
    for index, (name, text) in enumerate(_iter_artifact_blocks(artifacts), start=1):
        wrote_any = True
        blocks.append(f"### 产物 {index}：{name}")
        blocks.append(_clip(text) if text else "（无正文）")
    if not wrote_any:
        blocks.append("（本次交付没有产物正文）")

    if traces:
        blocks.append("## 过程摘要")
        for trace in traces[:MAX_TRACE_ITEMS]:
            event = str(trace.get("event_type") or "")
            phase = str(trace.get("phase") or "")
            raw_payload = trace.get("payload")
            payload = raw_payload if isinstance(raw_payload, dict) else {}
            detail = {
                key: value
                for key, value in payload.items()
                if key not in ("artifact", "text")
            }
            blocks.append(f"- [{phase}] {event} {detail}")

    user = "\n".join(blocks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
