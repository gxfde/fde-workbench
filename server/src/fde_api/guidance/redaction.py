from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fde_api.guidance.docx_extract import ExtractedBlock, ExtractedPresurvey
from fde_api.guidance.enterprise_dict import (
    enterprise_names,
    is_generic_name,
)


class SensitiveCredentialDetected(ValueError):
    pass


_CREDENTIAL = re.compile(
    r"(?:密码|口令|密钥|secret|api[_ -]?key|access[_ -]?token|token)\s*[:：=]?\s*"
    r"(?:sk-|ak-|bearer\s+)?[A-Za-z0-9_./+=-]{12,}", re.IGNORECASE
)
_EMAIL = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)(?:0\d{2,3}[- ]?)?\d{7,8}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")

# 疑似企业名：正则命中但词典未收录、也不在通用词白名单——闸①第②层，
# 不阻断，记入待复核清单由方案审核人 confirm 前复核。
_SUSPECT = re.compile(r"[\u4e00-\u9fa5]{2,15}(?:公司|集团|厂)")
# 候选的前缀剥离：中文没有词边界，正则会把句子前缀一起吞进候选（「另有未登记
# 示例厂」）。按常见前置词/动词逐级剥离，剥到最短仍保留 2 字以上才算候选。
_PREFIX_NOUNS = (
    "另有", "还有", "以及", "其中", "目前", "当前", "已经", "曾经", "对方",
    "他们", "我们", "贵司", "我司", "该", "此", "这", "那", "是", "为", "与",
    "和", "及", "或", "在", "由", "向", "从", "对", "把", "被", "给", "让",
    "拜访了", "拜访", "走访了", "走访", "接洽了", "接洽", "接触了", "接触",
    "包括", "如", "到", "去", "见", "约了", "约",
)


def _trim_candidate(candidate: str) -> str:
    """剥掉候选里的句子前缀，返回最短的合理企业名候选。"""
    changed = True
    while changed and len(candidate) > 2:
        changed = False
        for prefix in _PREFIX_NOUNS:
            if candidate.startswith(prefix) and len(candidate) - len(prefix) >= 2:
                candidate = candidate[len(prefix):]
                changed = True
                break
    return candidate


@dataclass(frozen=True, slots=True)
class SuspectName:
    name: str
    occurrences: int


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """redact_text 的完整结果：替换后文本 + 待复核清单。

    backward-compat：直接把实例当字符串用会 TypeError——调用方必须显式取
    .text（设计如此：替换是否发生是审计要点，不允许无感知吞掉）。
    """

    text: str
    suspects: tuple[SuspectName, ...]
    replaced: tuple[str, ...]

    def __str__(self) -> str:
        return self.text


def _alias(project_code: str) -> str:
    """正文里的替换目标代号。

    enterprise_code 是三段式「客户A·行业·城市」，塞进正文读起来是
    「与客户A·制造业·苏州签订框架」——代号落在第一段，后两段是行业与城市，
    语义上不属于「企业名」。取第一段（客户A）；取不到回退「客户代号」。
    """
    if not project_code:
        return "客户代号"
    head = project_code.split("·")[0].strip()
    return head or "客户代号"


def redact_text_detailed(
    value: str,
    *,
    project_code: str = "",
    mask_pii: bool = True,
) -> RedactionResult:
    """分层失败语义（闸①拍板）的完整实现。

    第①层 fail-closed：凭据正则命中（既有行为）、词典机制性异常
    （RedactionConfigError 原样上抛，调用方阻断入库）。
    第②层放行+复核：疑似企业名替换为代号并记入 suspects——注意疑似
    （正则命中）与词典命中在这里合并处理：词典命中的替换是确定性的，
    疑似命中的替换同样确定性（统一替换成 project_code 或通用占位），
    两者都进复核清单，语义是「这些名字被换过，请人工确认替换是否恰当」。
    """
    if _CREDENTIAL.search(value):
        raise SensitiveCredentialDetected("文档中疑似包含密码、密钥或令牌，请移除后重试。")

    names = enterprise_names()  # RedactionConfigError 在这里上抛（fail-closed）
    text = value
    alias = _alias(project_code)
    replaced: list[str] = []
    for name in names:
        if name in text:
            text = text.replace(name, alias)
            replaced.append(name)

    # 疑似层（闸①第②层）：正则命中、词典未收录、且不是通用词——**同样替换**
    # （否则真实名仍留在库里，红线失守），替换后记入复核清单交人工确认替换
    # 是否恰当。通用词（哨兵②）零改动、不进清单。
    suspects: dict[str, int] = {}
    for match in _SUSPECT.findall(text):
        candidate = _trim_candidate(match)
        if candidate in replaced or is_generic_name(candidate):
            continue
        if candidate in text:
            text = text.replace(candidate, alias)
            suspects[candidate] = suspects.get(candidate, 0) + 1

    if mask_pii:
        value = _EMAIL.sub("[邮箱已脱敏]", text)
        value = _MOBILE.sub("[手机号已脱敏]", value)
        value = _ID_CARD.sub("[证件号已脱敏]", value)
        value = _LANDLINE.sub("[电话已脱敏]", value)
    else:
        value = text
    return RedactionResult(
        text=value,
        suspects=tuple(SuspectName(name=k, occurrences=v) for k, v in suspects.items()),
        replaced=tuple(dict.fromkeys(replaced)),
    )


def redact_text(value: str) -> str:
    """既有签名保持不变（contacts 脱敏 + 企业名替换，文本返回）。

    企业名替换在本实现里是「尽力而为」：词典机制性异常在这里同样 fail-closed
    上抛（redact_text 的既有调用方——ai_context 渲染——本就要求 fail-closed）。
    需要复核清单的调用方走 redact_text_detailed。
    """
    return redact_text_detailed(value).text


# ---------------------------------------------------------------------------
# QR-133（goal-crv-fix2 批 G，拍板 #6A 指纹化复核清单）：redaction_review 事件
# 账零真名——确证命中名只存 sha256 指纹（复核 UI 经词典反解显示），未确证疑似
# 名不入事件账只留聚合计数（复核人看草稿原文判定）。红线「数据库只存代号」
# 字面全守；复核功能保留。写入侧单一真身（guidance/translator 四锚共用）。
# ---------------------------------------------------------------------------

_REDACTION_HASH_DOMAIN = "fde-redaction-v1"


def redaction_name_hash(name: str) -> str:
    """复核条目指纹（域分隔 sha256）：事件账与读面反解共用同一真身。"""
    import hashlib

    return hashlib.sha256(f"{_REDACTION_HASH_DOMAIN}:{name}".encode("utf-8")).hexdigest()


def fingerprint_review_entries(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """旧形状（name/occurrences/matched_dict）→ 事件账新形状（零真名）。

    返回（指纹化条目列表, 疑似名聚合计数）：
    - matched_dict=True（词典确证命中）→ ``{"name_hash", "occurrences", "matched_dict": True}``；
    - matched_dict=False（疑似）→ 不逐条入账，名字出现次数并入 suspect_count。
    """
    fingerprinted: list[dict[str, Any]] = []
    suspect_count = 0
    for item in entries:
        occurrences = int(item.get("occurrences", 1) or 0)
        if item.get("matched_dict"):
            fingerprinted.append(
                {
                    "name_hash": redaction_name_hash(str(item.get("name", ""))),
                    "occurrences": occurrences,
                    "matched_dict": True,
                }
            )
        else:
            suspect_count += occurrences
    return fingerprinted, suspect_count


def fingerprint_review_payload(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """复核账存储形状（盲审追批，拍板 #6A 同族扩线）：单数组含两类项——

    - 指纹条目 ``{"name_hash", "occurrences", "matched_dict": True}``（确证命中）；
    - 哨兵聚合项 ``{"suspect_count": N}``（疑似名不逐条入账，殿后一条）。

    与 guidance 读面投影（``_review_projection``）完全同形状：桌面一处守卫
    复用三面（guidance / transcripts / discovery）。零真名红线不变。
    """
    fingerprinted, suspect_count = fingerprint_review_entries(entries)
    payload = list(fingerprinted)
    if suspect_count:
        payload.append({"suspect_count": suspect_count})
    return payload


def resolve_redaction_display(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """读面反解：指纹 → 词典词目原文（仅显示，不落库）。

    词典命中 → ``name`` 为词目原文；词典故障或指纹未命中（词典已更新删词）
    → ``name=None``（UI 显示指纹前 8 位占位，诚实缺失）。软失败不抛——
    读面（get_analysis/confirm/adopt 投影）不得因词典机制故障 500。
    """
    if not entries:
        return []
    try:
        digest_to_name = {redaction_name_hash(n): n for n in enterprise_names()}
    except Exception:  # noqa: BLE001 - 读面软失败（词典故障不阻断复核投影）
        digest_to_name = {}
    out: list[dict[str, Any]] = []
    for item in entries:
        row = dict(item)
        row["name"] = digest_to_name.get(str(item.get("name_hash", "")))
        out.append(row)
    return out


def redact_presurvey(extracted: ExtractedPresurvey, *, project_code: str = "") -> tuple[ExtractedPresurvey, tuple[SuspectName, ...], tuple[str, ...]]:
    """presurvey 抽取块的脱敏 + 企业名替换，返回（替换后, 疑似清单, 已替换清单）。"""
    blocks: list[ExtractedBlock] = []
    all_suspects: dict[str, int] = {}
    all_replaced: list[str] = []
    for block in extracted.blocks:
        result = redact_text_detailed(block.text, project_code=project_code)
        blocks.append(ExtractedBlock(block.source_ref, result.text))
        for suspect in result.suspects:
            all_suspects[suspect.name] = all_suspects.get(suspect.name, 0) + suspect.occurrences
        all_replaced.extend(result.replaced)
    return (
        ExtractedPresurvey(tuple(blocks)),
        tuple(SuspectName(name=k, occurrences=v) for k, v in sorted(all_suspects.items(), key=lambda kv: (-kv[1], kv[0]))),
        tuple(dict.fromkeys(all_replaced)),
    )


def redact_draft_payload(
    draft: dict, *, project_code: str = "", sink: list[dict]
) -> dict:
    """guidance 契约草稿的落库前企业名兜底替换（AI 只产草稿，草稿也不带真名入库）。

    - 文本字段（customer_vision / current_phase_objective / executive_summary）
      直接替换；
    - ai_schema.LIST_FIELDS 各项为 list[dict]，对其中每个 str 值替换；
    - evidence 只处理其 value 里的 str 值（键是内部 ref 结构不碰）。
    替换命中以 {"name", "occurrences": 1, "matched_dict": True} 追加进 sink。
    词典机制性异常（RedactionConfigError）原样上抛——调用方 fail-closed。

    预调研（guidance/jobs.py）与翻译器（translator/jobs.py）共用：两条 AI 入
    口产出的都是同一形状的 guidance 草稿，兜底层语义必须单一权威。
    """
    from fde_api.guidance.ai_schema import LIST_FIELDS  # 函数内导入防 ai_schema↔redaction 装载序耦合

    names = enterprise_names()
    if not names:
        return draft

    def replace_str(value: str) -> str:
        hits: list[str] = []
        text = value
        for name in names:
            if name in text:
                text = text.replace(name, project_code or "客户代号")
                hits.append(name)
        if hits:
            sink.extend({"name": h, "occurrences": 1, "matched_dict": True} for h in hits)
        return text

    out = dict(draft)
    for key in ("customer_vision", "current_phase_objective", "executive_summary"):
        out[key] = replace_str(out.get(key, "") or "")
    for field in LIST_FIELDS:
        items = out.get(field)
        if isinstance(items, list):
            out[field] = [
                {k: replace_str(v) if isinstance(v, str) else v for k, v in item.items()}
                if isinstance(item, dict) else item
                for item in items
            ]
    evidence = out.get("evidence")
    if isinstance(evidence, dict):
        out["evidence"] = {k: replace_str(v) if isinstance(v, str) else v for k, v in evidence.items()}
    return out
