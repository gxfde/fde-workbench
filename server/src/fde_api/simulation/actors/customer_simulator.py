"""客户模拟器（G3）——受限状态机，**不编造**。

三条铁律（G1 §5.2）：
1. **事实集先行**：能说的内容只来自场景（``hidden.facts`` + ``visible``）；语言
   只是表达方式，**不得引入事实集外的实体**。
2. **命中才披露**：顾问问到点子上（探针关键词命中）才解锁对应事实；否则走
   **受控应答**（「不知道 / 要内部确认 / 反问」），**沉默本身就是信号**。
3. **不得主动给答案**：客户不会主动说出方案；只回答被问到的。

变体差异：
- ``vague``：信息直给度低（需要更多轮），答不上来时反问。
- ``complex``：额外冲突与变更事件；被忽视的事实会**主动升级**（escalate）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 受控非应答模板（按轮次确定性取用；**不含任何事实内容**）
NON_ANSWER_TEMPLATES = (
    "这个我得回去确认一下，{unknown_hint}。",
    "我们内部对这块说法不太一样，我一时不好回答。",
    "你说的这个我还真不清楚，得问下面的人。",
    "这块有点复杂，你想先了解哪一部分？",
    "这个我印象里好像不是这样，你从哪个系统看到的？",
)

# 升级（客户主动补充）模板
ESCALATION_TEMPLATE = "对了，有一点我要先说清楚：{text}"


@dataclass(frozen=True)
class CustomerReply:
    """客户的一轮应答。"""

    text: str
    persona: str
    disclosed: tuple[str, ...] = ()
    matched: bool = False
    escalated: bool = False
    unanswered: bool = False


@dataclass
class CustomerState:
    """客户模拟器的持久状态（落 ``simulation_actors.state_json``）。"""

    disclosed_fact_ids: list[str] = field(default_factory=list)
    probe_count: int = 0
    unanswered_count: int = 0
    ignored_counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "disclosed_fact_ids": list(self.disclosed_fact_ids),
            "probe_count": self.probe_count,
            "unanswered_count": self.unanswered_count,
            "ignored_counts": dict(self.ignored_counts),
        }

    @classmethod
    def from_json(cls, payload: dict[str, Any] | None) -> "CustomerState":
        payload = payload or {}
        disclosed = payload.get("disclosed_fact_ids")
        ignored = payload.get("ignored_counts")
        return cls(
            disclosed_fact_ids=[str(item) for item in disclosed] if isinstance(disclosed, list) else [],
            probe_count=int(payload.get("probe_count") or 0),
            unanswered_count=int(payload.get("unanswered_count") or 0),
            ignored_counts=(
                {str(k): int(v) for k, v in ignored.items()} if isinstance(ignored, dict) else {}
            ),
        )


class CustomerSimulator:
    """客户行为模拟：只按场景设定回答，逐步披露隐藏信息。"""

    def __init__(
        self,
        *,
        customer_view: dict[str, Any],
        state: CustomerState | None = None,
        escalate_after: int = 0,
    ) -> None:
        self._view = customer_view
        self._state = state or CustomerState()
        self._facts = self._extract_facts(customer_view)
        self._escalate_after = max(0, escalate_after)

    # -- 场景事实集 --------------------------------------------------------

    @staticmethod
    def _extract_facts(customer_view: dict[str, Any]) -> list[dict[str, Any]]:
        hidden = customer_view.get("hidden")
        facts = hidden.get("facts") if isinstance(hidden, dict) else None
        if not isinstance(facts, list):
            return []
        return [fact for fact in facts if isinstance(fact, dict) and fact.get("fact_id")]

    @property
    def state(self) -> CustomerState:
        return self._state

    @property
    def disclosed_facts(self) -> tuple[dict[str, Any], ...]:
        disclosed = set(self._state.disclosed_fact_ids)
        return tuple(fact for fact in self._facts if str(fact.get("fact_id")) in disclosed)

    # -- 应答 --------------------------------------------------------------

    def respond(
        self,
        question: str,
        *,
        allowed_stages: tuple[str, ...] = ("setup", "interview", "analysis", "design", "implementation", "late"),
    ) -> CustomerReply:
        """回答顾问的一问。

        ``allowed_stages`` 约束本阶段可披露的事实（阶段来自 ``disclosure_stage``），
        防止「还没到分析阶段就把结论说完了」。
        """
        self._state.probe_count += 1
        persona = self._persona()
        lowered = (question or "").lower()
        newly: list[dict[str, Any]] = []

        for fact in self._facts:
            fact_id = str(fact.get("fact_id"))
            if fact_id in self._state.disclosed_fact_ids:
                continue
            stage = str(fact.get("disclosure_stage") or "interview")
            if stage not in allowed_stages:
                continue
            keywords = [str(kw).lower() for kw in (fact.get("probe_keywords") or []) if str(kw).strip()]
            if keywords and any(keyword in lowered for keyword in keywords):
                newly.append(fact)

        if newly:
            texts = [str(fact.get("text") or "") for fact in newly]
            body = "；".join(texts)
            for fact in newly:
                fact_id = str(fact.get("fact_id"))
                self._state.disclosed_fact_ids.append(fact_id)
                self._state.ignored_counts.pop(fact_id, None)
            return CustomerReply(
                text=f"{persona}：这个情况我说一下——{body}。",
                persona=persona,
                disclosed=tuple(str(fact.get("fact_id")) for fact in newly),
                matched=True,
            )

        # 未命中：累计忽视次数，并在 complex 变体里主动升级
        escalated_fact: dict[str, Any] | None = None
        for fact in self._facts:
            fact_id = str(fact.get("fact_id"))
            if fact_id in self._state.disclosed_fact_ids:
                continue
            stage = str(fact.get("disclosure_stage") or "interview")
            if stage not in allowed_stages:
                continue
            self._state.ignored_counts[fact_id] = self._state.ignored_counts.get(fact_id, 0) + 1
            if (
                self._escalate_after
                and self._state.ignored_counts[fact_id] >= self._escalate_after
                and escalated_fact is None
            ):
                escalated_fact = fact

        if escalated_fact is not None:
            fact_id = str(escalated_fact.get("fact_id"))
            self._state.disclosed_fact_ids.append(fact_id)
            self._state.ignored_counts.pop(fact_id, None)
            return CustomerReply(
                text=f"{persona}：" + ESCALATION_TEMPLATE.format(text=escalated_fact.get("text")),
                persona=persona,
                disclosed=(fact_id,),
                matched=False,
                escalated=True,
            )

        self._state.unanswered_count += 1
        template = NON_ANSWER_TEMPLATES[
            (self._state.probe_count - 1) % len(NON_ANSWER_TEMPLATES)
        ]
        return CustomerReply(
            text=f"{persona}：" + template.format(unknown_hint="具体是哪块我也不确定"),
            persona=persona,
            matched=False,
            unanswered=True,
        )

    # -- 角色 --------------------------------------------------------------

    def _persona(self) -> str:
        profile = self._view.get("customer_profile")
        stakeholders = profile.get("stakeholders") if isinstance(profile, dict) else None
        if not isinstance(stakeholders, list) or not stakeholders:
            return "客户"
        index = (self._state.probe_count - 1) % len(stakeholders)
        return str(stakeholders[index])
