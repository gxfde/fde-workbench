"""台账同步钉（演进方向评估 v1.1 §七 P1-1 机械闸落地，2026-11-07）。

守两条「人工漏登/漏回写不再静默」的纪律，均为纯文本对账、零 DB：

1. ``test_backlog_ta_headline_matches_implementation``
   守「实施状态唯一权威列」的**标题行一致性**：``v3-backlog.md`` 任一
   ``### T-xx`` 条目，只要其正文里存在「#### ✅ …实施轮/核销轮/补齐轮/
   实施记录」子节（或正文写明「已实施并合并」），标题行就必须携带
   DONE/已实施/已合并语义——否则红并列出全部 stale 标题行。T-A5..T-A8
   4 条曾长期挂 PROPOSED（正文各有 ✅ 子节），T-A2/A3/A4 复测同款；
   #173/#176/#179 三轮「补账」均未触碰标题行——本钉让 D3 类形式遗留
   「漂移即红」，不再依赖人记得（#186 路由清单 CI 同步钉同型）。

2. ``test_changelog_ledger_round_share_stays_bounded``
   守「台账消耗型轮次占比 ≤ 20%」（评估报告 P0-3 降级改写后的可执行
   版）：对最近 N（默认 20）个 CHANGELOG 版本节做轮次性质分类——
   ①**台账消耗型**：零代码/纯文档且非机械闸/非口径裁决（补账、登记、
   状态回写、漂移校正…）——持续吞噬产能（D4/R2 分子）；
   ②**机械闸建设型**：零代码但落了「漂移即红/对账断言/新增环红」类
   机械钉或新增测试（#186/#183⑤⑨ 先例）——以零业务代码换长期减负；
   ③**实施型**：功能/修复/测试增量正常轮（含纯文档拍板回写轮：
   拍板回写本身推进决策状态，非台账搬运）。
   分类只看**节级**关键词命中（纯函数 ``classify_changelog_section``，
   供后续轮复用），不猜意图；占比超阈即红并打印分类明细。阈值与锚定
   分子（fork/main ``a139aba`` 前最近 20 节实测 ledger=3，15%）：允许
   再落 1 条台账轮（4/20=20% 恰在界），第 2 条即 25% 转红——
   意在「挤出台账消耗轮」，而非追溯历史。

变异验证（四连，见 PR 描述）：M1 标题行回退 PROPOSED→断言 1 红抓
T-A3（正向）；M2 连插两条纯补账节→5/20=25% 红（阈值边界：4/20=20%
仍绿，第 2 条转红）；M3 架构评估修复轮删全部机械钉词→分类从
mechanical_nail 翻为 ledger（机械闸词确为分类依据）；M4 洁癖收尾轮
正文深埋台账词（「状态未回写」家族），删标题词不翻转（分类看全节，
防标题伪装）。
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"
_BACKLOG = _REPO_ROOT / "docs" / "implementation" / "v3-backlog.md"

# 演进方向评估 v1.1 §2.3 固定正则（行级 13 词）——分类器的「零代码轮」判据底座
ZERO_CODE_PATTERNS = (
    "零代码零迁移零路由",
    "纯文档",
    "纯测试轮",
    "零业务代码",
    "本轮仅立项",
    "口径全不动",
    "零生产行为变更",
    "登记轮",
    "评估报告",
    "状态轮报告",
    "补账",
    "漂移校正",
    "逐行复测",
)
# 「台账消耗型」再判据：在零代码底座上，正文是状态搬运/补账/登记/校正而非机械闸
LEDGER_PATTERNS = (
    "补账",
    "登记轮",
    "状态轮报告",
    "漂移校正",
    "逐行复测",
    "口径全现测吻合",
    "核销",
    "拍板回写",
    "回写",
    "台账收口",
    "驳回销号",
)
# 「机械闸建设型」判据：零代码/纯测试但落了机械钉（对账、漂移即红、环冻结…）
MECHANICAL_NAIL_PATTERNS = (
    "漂移即红",
    "对账断言",
    "新增环红",
    "环冻结",
    "机械闸",
    "机械钉",
    "机械强制",
    "静态钉",
    "CI 同步钉",
)
# 实施型轮的显式信号（测试/功能增量、新增 NEW 文件、路由/迁移/桌面变更）
DELIVERY_SIGNALS = (
    "pytest +",
    "vitest +",
    "+1 pytest",
    "NEW `",
    "路由 3",
    "零迁移零路由；server 变更",
    "桌面变更",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_changelog_sections(text: str) -> list[str]:
    """按 ``## [`` 切 CHANGELOG 为节（含标题行自身），顺序=文件顺序（最新在前）。"""
    raw = text.split("\n## [")
    sections: list[str] = []
    for i, chunk in enumerate(raw):
        if i == 0:
            # 首段是文件头（# Changelog 说明），跳过；但若首段本身以 ## [ 开头
            # （split 的边界情况）则保留。
            if chunk.lstrip().startswith("## [") or chunk.startswith("## ["):
                sections.append(chunk if chunk.startswith("## [") else "## [" + chunk)
            continue
        sections.append("## [" + chunk)
    return sections


def classify_changelog_section(section_text: str) -> str:
    """单节轮次性质三分类（纯函数，供台账占比钉与后续轮复用）。

    返回 ``delivery``（实施型）/ ``mechanical_nail``（机械闸建设型）/
    ``ledger``（台账消耗型）。判据序：先实施信号，再机械闸词，再台账词，
    最后零代码底座兜底（零代码且无任何其他信号 ⇒ 按台账消耗计——
    「既没交付又没减负的零代码轮」正是 D4/R2 要挤出的对象）。
    """
    blob = section_text
    zero_code = any(p in blob for p in ZERO_CODE_PATTERNS)
    if not zero_code:
        return "delivery"
    if any(p in blob for p in DELIVERY_SIGNALS) and not any(p in blob for p in LEDGER_PATTERNS):
        return "delivery"
    if any(p in blob for p in MECHANICAL_NAIL_PATTERNS):
        # 机械闸建设：零代码/纯测试 + 机械钉词（#186 节含「机械闸」「漂移即红」）
        return "mechanical_nail"
    if any(p in blob for p in LEDGER_PATTERNS):
        return "ledger"
    # 零代码底座兜底：无实施信号、无机械钉、无台账词 ⇒ 台账消耗
    return "ledger"


def test_backlog_ta_headline_matches_implementation() -> None:
    """backlog ``### T-xx`` 标题行状态语义必须与正文实施子节一致（D3 漂移即红）。"""
    import re

    text = _read(_BACKLOG)
    headings = [
        (m.group(1), m.start())
        for m in re.finditer(r"^### (T-[A-Za-z]+\d+)[^\n]*$", text, re.M)
    ]
    assert headings, "v3-backlog.md 里一个 ### T-xx 标题都没找到——解析器失效"

    stale: list[str] = []
    for tid, pos in headings:
        # 块边界＝下一条任意二级/三级标题（T- 条目的自界内容；用「下一条 T-
        # 标题」会把末位条目（如 T-Z1）后整段借鉴清单的 ✅ 行误吞进来）。
        boundary = re.compile(r"^#{2,3} ", re.M).search(text, pos + 1)
        block = text[pos : boundary.start() if boundary else len(text)]
        headline = block.splitlines()[0]
        # 正文已实施的两个信号：✅ 实施类子节，或正文明写「已实施并合并」
        impl_subsection = re.search(
            r"^#### ✅ .*(实施轮|核销轮|补齐轮|实施记录|补齐轮)", block, re.M
        )
        impl_inline = "已实施并合并" in block or ("**已实施**" in block)
        headline_done = any(
            kw in headline for kw in ("DONE", "已实施", "已合并", "已兑现")
        )
        if (impl_subsection or impl_inline) and not headline_done:
            stale.append(f"{tid}: {headline.strip()}")

    assert not stale, (
        "backlog 标题行状态落后于正文实施子节（D3 形式遗留，机械闸转红）：\n"
        + "\n".join(stale)
        + "\n处置：标题行状态改为 DONE（核销）或「已实施并合并」语义——"
        "正文 ✅ 子节已在，标题行是实施状态唯一权威列（架构评估提示词 §一）。"
    )


def test_changelog_ledger_round_share_stays_bounded() -> None:
    """最近 20 个 CHANGELOG 版本节中「台账消耗型」占比 ≤ 20%（D4/R2 可执行版）。"""
    sections = split_changelog_sections(_read(_CHANGELOG))
    assert len(sections) >= 20, f"CHANGELOG 节数不足 20（实测 {len(sections)}）——钉失效条件"
    recent = sections[:20]
    buckets: dict[str, list[str]] = {"delivery": [], "mechanical_nail": [], "ledger": []}
    for sec in recent:
        title = sec.splitlines()[0][:60]
        buckets[classify_changelog_section(sec)].append(title)

    ledger_n = len(buckets["ledger"])
    share = ledger_n / len(recent)
    detail = "\n".join(
        f"  [{kind}] {n} 节: " + " | ".join(t[:34] for t in titles[:8])
        for kind, titles in buckets.items()
        for n in [len(titles)]
        if titles
    )
    assert share <= 0.20, (
        f"最近 20 个 CHANGELOG 节里「台账消耗型」占 {ledger_n}/20 = {share:.0%}，"
        f"超过 20% 上限（演进方向评估 v1.1 §七 P1-1）。\n"
        f"分类明细：\n{detail}\n"
        "处置：补账/登记/状态回写并入随轮 PR（AGENTS「工作流与陷阱」DoD），"
        "不再落独立台账轮；机械闸建设型（漂移即红/对账断言/环冻结）不受此限。"
    )
