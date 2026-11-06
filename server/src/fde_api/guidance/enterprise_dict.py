"""T-A2 企业名词典：仓库内种子文件为单一真源（闸②拍板）。

词典来源纪律（登记条目红线级约束）：
- 仓库内 `server/seeds/enterprise-names.txt` 只允许合成示例——真实企业名
  永不进 git 历史与远端（AGENTS.md 红线）。
- 现场真实词典经 `FDE_ENTERPRISE_DICT` 环境变量指向本地文件（执行面不触
  真相层的实现形态：真相层把提取物放到本地路径，工作台只读该路径）。
- CI 的 check-pseudonymization.sh 与本加载器读同一个种子文件，一致性由
  哨兵测试钉死（test_enterprise_dict_parity）。

失败语义（闸①拍板：分层）：
- 机制性异常（种子文件缺失 / 行格式不合规 / 环境变量文件缺失）→
  RedactionConfigError → 调用方 fail-closed 硬阻断入库。
- 疑似企业名（正则命中但词典未收录）→ 不阻断，返回待复核清单，由
  方案审核人 confirm 前复核。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

_SEEDS_DIR = Path(__file__).resolve().parents[3] / "seeds"
SEED_DICT_PATH = _SEEDS_DIR / "enterprise-names.txt"
EXTRA_DICT_ENV = "FDE_ENTERPRISE_DICT"

# 与 CI 黑名单提取同一码位区间（check-pseudonymization.sh:91 perl
# [\x{4E00}-\x{9FA5}]）：GNU grep 多字节区间跨 locale 不可移植，Python re
# 在 str 上按码位匹配，与 locale 无关。
ENTERPRISE_NAME_PATTERN = re.compile(r"[\u4e00-\u9fa5]{2,15}(?:公司|集团|厂)")

# 通用词白名单：正则固有会抓「技术公司」「制造公司」这类没有辨识度的组合，
# 它们既不是客户名、替换了反而破坏可读性——跳过替换、不进疑似清单。
# 维护口径：只收「去掉修饰词后无指代对象」的通用后缀组合；具体客户名
# （哪怕是通用词+地名的组合）应进词典而不是这里。
GENERIC_NAMES = frozenset({
    "技术公司", "制造公司", "制造厂", "生产厂", "加工厂",
    "有限公司", "有限责任公司", "股份公司", "集团公司", "控股公司",
    "总公司", "分公司", "子公司", "厂", "公司", "集团",
})


def is_generic_name(candidate: str) -> bool:
    """通用词判定：候选**以某个通用词结尾**且该通用词长度不小于候选一半。

    中文企业名没有空格边界，切出来的候选常把句子前缀带进来（「对方是一家
    技术公司」）。用「后缀通用词 + 长度占比」判定：通用词占候选一半以上即
    视为无辨识度的通用表述——不改替换、不进复核清单（哨兵②：通用词零改动）。
    「未登记示例厂」这类真实疑似名不会命中：通用后缀「厂」只占 1/6。
    """
    for generic in GENERIC_NAMES:
        if candidate.endswith(generic) and len(generic) * 2 >= len(candidate):
            return True
    return False


class RedactionConfigError(RuntimeError):
    """词典机制性故障（fail-closed 硬阻断入库，闸①拍板①层）。"""


def _parse_dict_file(path: Path, *, source: str) -> tuple[str, ...]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise RedactionConfigError(f"企业名词典文件缺失（{source}）：{path}") from error
    except OSError as error:
        raise RedactionConfigError(f"企业名词典文件不可读（{source}）：{path}") from error
    names: list[str] = []
    for line_no, line in enumerate(raw.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not ENTERPRISE_NAME_PATTERN.fullmatch(stripped):
            raise RedactionConfigError(
                f"企业名词典（{source}）第 {line_no} 行不是「中文2-15字+公司/集团/厂」结尾：{stripped[:40]}"
            )
        if stripped not in GENERIC_NAMES:
            names.append(stripped)
    return tuple(names)


@lru_cache(maxsize=1)
def _seed_names() -> tuple[str, ...]:
    return _parse_dict_file(SEED_DICT_PATH, source="seeds")


def _extra_names() -> tuple[str, ...]:
    """现场补充词典（环境变量指向本地文件）。缺失=只有种子；格式坏=fail-closed。"""
    extra_path = os.environ.get(EXTRA_DICT_ENV, "").strip()
    if not extra_path:
        return ()
    return _parse_dict_file(Path(extra_path), source=EXTRA_DICT_ENV)


def enterprise_names() -> tuple[str, ...]:
    """合并后的词典（种子 + 现场），按长度降序——长名优先替换防子串截断。"""
    merged = dict.fromkeys((*_seed_names(), *_extra_names()))
    return tuple(sorted(merged, key=len, reverse=True))


def reset_dict_cache() -> None:
    """测试专用：清掉 lru_cache，让环境变量改动生效。"""
    _seed_names.cache_clear()
