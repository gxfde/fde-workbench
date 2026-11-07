"""T-B1 产物派生摘要（goal-tb tb2）：可从原件重建的派生，绝不复制原件进库。

B#6《状态归属与对账》§1 不变量「引用方永不复制真相，只持指针」：diff /
test_results 的原件本体留在 storage_ref（项目工作目录），库内只存
storage_ref + sha256 + 本模块派生的结构化摘要。摘要不可解析时如实落
零计数（不发明数字、不猜格式）——可重建性由测试钉住（同一原件二次
派生逐位一致）。
"""

from __future__ import annotations

import re

_MAX_PARSE_BYTES = 2 * 1024 * 1024

_COUNTABLE_TOKENS = re.compile(r"(\d+) (passed|failed|errors?|skipped)\b")
_DIFF_FILE_LINE = re.compile(r"^diff --git a/(.+?) b/(.+?)$")


def derive_artifact_summary(kind: str, content: bytes) -> dict[str, int] | None:
    """从产物原件内容派生结构化摘要；非 diff/test_results 种类返回 None。"""
    if kind not in ("diff", "test_results"):
        return None
    text = content[:_MAX_PARSE_BYTES].decode("utf-8", errors="replace")
    if kind == "diff":
        return _summarize_diff(text)
    return _summarize_test_output(text)


def _summarize_diff(text: str) -> dict[str, int]:
    files: set[str] = set()
    additions = 0
    deletions = 0
    for line in text.splitlines():
        file_match = _DIFF_FILE_LINE.match(line)
        if file_match:
            files.add(file_match.group(2))
        elif line.startswith("+++") or line.startswith("---"):
            continue  # 文件头行，不是增删行
        elif line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return {"files_changed": len(files), "additions": additions, "deletions": deletions}


def _summarize_test_output(text: str) -> dict[str, int]:
    """计数器口径：全文扫描「N passed/failed/errors/skipped」token 累加。

    对 pytest 终局行（``=== 3 failed, 12 passed, 2 skipped ===``）与逐条
    输出都成立；同一 token 多次出现按出现次数累加（pytest 终局行恰好
    一次一 token；自由格式输出宁多计不漏计——摘要可从原件复核）。
    """
    counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    for match in _COUNTABLE_TOKENS.finditer(text):
        count, label = int(match.group(1)), match.group(2)
        key = "errors" if label.startswith("error") else label
        counts[key] += count
    return counts
