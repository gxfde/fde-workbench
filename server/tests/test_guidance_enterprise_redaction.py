"""T-A2 企业名词典与替换层的哨兵自测（借鉴总览 B#11：没自测过的校验器等于没有校验器）。

四条哨兵（登记条目验收口径）：
1. 注入合成企业名断言确实被替换；
2. 误替换钉死——「技术公司」类通用词零改动、不进复核清单；
3. 词典一致性——替换器种子与 CI 黑名单扫描读同一个文件（闸②拍板的物理基础）；
4. 测试数据只用合成 fixture，真实客户资料不可作测试素材（AGENTS.md 红线）。

失败语义分层（闸①拍板）也在此钉住：机制性异常 fail-closed、疑似放行+复核。
"""

from __future__ import annotations

import pytest

from fde_api.guidance import redaction
from fde_api.guidance.enterprise_dict import (
    EXTRA_DICT_ENV,
    SEED_DICT_PATH,
    RedactionConfigError,
    enterprise_names,
    reset_dict_cache,
)
from fde_api.guidance.redaction import (
    RedactionResult,
    SensitiveCredentialDetected,
    redact_presurvey,
    redact_text,
    redact_text_detailed,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(EXTRA_DICT_ENV, raising=False)
    reset_dict_cache()
    yield
    reset_dict_cache()


# ---------- 哨兵①：合成企业名必须被替换 ----------

def test_seed_enterprise_names_are_replaced_with_project_alias():
    assert "黑名单示例控股公司" in enterprise_names()
    result = redact_text_detailed("与黑名单示例控股公司签订框架协议", project_code="客户A·制造业·苏州")
    assert "黑名单示例控股公司" not in result.text
    # 替换目标是 enterprise_code 首段（客户A）——三段式代号的后两段是行业与
    # 城市，塞进正文读起来像「与客户A·制造业·苏州签订」，语义不对。
    assert "客户A·制造业·苏州" not in result.text
    assert "客户A" in result.text
    assert result.replaced == ("黑名单示例控股公司",)


def test_redact_text_plain_signature_also_replaces():
    text = redact_text("调研对象：合成测试集团 联系人 13800138000")
    assert "合成测试集团" not in text
    assert "13800138000" not in text


def test_longest_name_replaced_first_to_avoid_substring_truncation(monkeypatch):
    monkeypatch.setattr(redaction, "enterprise_names", lambda: ("示例制造有限公司", "制造有限公司"))
    result = redact_text_detailed("走访示例制造有限公司", project_code="客户A")
    assert result.text == "走访客户A"
    assert result.replaced == ("示例制造有限公司",)


# ---------- 哨兵②：误替换钉死 ----------

def test_generic_words_untouched_and_not_suspects():
    result = redact_text_detailed("对方是一家技术公司，主营制造公司咨询；隔壁是制造厂。")
    assert result.text == "对方是一家技术公司，主营制造公司咨询；隔壁是制造厂。"
    assert result.suspects == ()
    assert result.replaced == ()


def test_prefix_is_trimmed_from_suspect_candidate():
    """中文无词边界，正则会把句子前缀吞进候选（「拜访了未登记示例厂」）。
    候选必须剥到最短合理企业名，否则复核清单里会出现整句。"""
    result = redact_text_detailed("拜访了未登记示例厂洽谈合作", project_code="客户A")
    names = [s.name for s in result.suspects]
    assert names == ["未登记示例厂"]


# ---------- 疑似层：正则命中但词典未收录 ----------

def test_unknown_enterprise_name_is_replaced_and_flagged_for_review():
    # 闸①第②层语义：疑似名（正则命中、词典未收录）**同样替换**——不替换就
    # 等于让真实名留在库里，红线失守；替换后记入复核清单交人工确认。
    result = redact_text_detailed("拜访了未登记示例厂洽谈合作", project_code="客户A")
    assert "未登记示例厂" not in result.text
    assert "客户A" in result.text
    assert any(s.name == "未登记示例厂" for s in result.suspects)


# ---------- 闸①第①层：机制性异常 fail-closed ----------

def test_missing_seed_file_raises_config_error(monkeypatch):
    monkeypatch.setattr(redaction, "enterprise_names", lambda: (_ for _ in ()).throw(RedactionConfigError("种子缺失")))
    with pytest.raises(RedactionConfigError):
        redact_text("任何文本")


def test_extra_dict_env_bad_format_is_fail_closed(monkeypatch, tmp_path):
    bad = tmp_path / "bad-dict.txt"
    bad.write_text("这不是企业名\n", encoding="utf-8")
    monkeypatch.setenv(EXTRA_DICT_ENV, str(bad))
    reset_dict_cache()
    with pytest.raises(RedactionConfigError):
        enterprise_names()
    with pytest.raises(RedactionConfigError):
        redact_text("任何文本")


def test_extra_dict_env_valid_file_merges(monkeypatch, tmp_path):
    extra = tmp_path / "extra-dict.txt"
    extra.write_text("# 注释行\n现场补充集团\n", encoding="utf-8")
    monkeypatch.setenv(EXTRA_DICT_ENV, str(extra))
    reset_dict_cache()
    assert "现场补充集团" in enterprise_names()


# ---------- 凭据红线保持 ----------

def test_blocks_api_keys_still():
    with pytest.raises(SensitiveCredentialDetected):
        redact_text("接口密钥：example-api-key-not-real-123456")


# ---------- redact_presurvey 聚合 ----------

def test_redact_presurvey_aggregates_suspects_and_replacements():
    from fde_api.guidance.docx_extract import ExtractedBlock, ExtractedPresurvey

    extracted = ExtractedPresurvey((
        ExtractedBlock("paragraph-1", "客户：合成测试集团 联系电话 13800138000"),
        ExtractedBlock("table-1-row-1-cell-1", "竞争对手：未登记示例厂"),
    ))
    redacted, suspects, replaced = redact_presurvey(extracted, project_code="客户A")
    texts = [b.text for b in redacted.blocks]
    assert all("合成测试集团" not in t for t in texts)
    assert all("13800138000" not in t for t in texts)
    assert "客户A" in texts[0]
    assert any(s.name == "未登记示例厂" for s in suspects)
    assert replaced == ("合成测试集团",)


# ---------- 哨兵③：词典一致性（CI 与替换器同一文件）----------

def test_seed_dict_names_match_ci_blacklist_fixture():
    """闸②拍板的物理基础：CI 黑名单（synthetic fixture）三个名字必须都在
    替换器种子里——两处名单漂移时本测试红，防止「CI 扫的」与「替换的」
    变成两套词典。"""
    # SEED_DICT_PATH = server/seeds/enterprise-names.txt → 仓库根 = parents[2]
    repo_root = SEED_DICT_PATH.parents[2]
    fixture = repo_root / ".github" / "ci-assets" / "synthetic-leads-blacklist.txt"
    fixture_names = {
        line.strip()
        for line in fixture.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    assert fixture_names, "CI fixture 为空 = 扫描失效"
    assert fixture_names <= set(enterprise_names())


# ---------- RedactionResult 契约 ----------

def test_redaction_result_str_returns_text():
    result = redact_text_detailed("普通文本")
    assert isinstance(result, RedactionResult)
    assert str(result) == "普通文本"
