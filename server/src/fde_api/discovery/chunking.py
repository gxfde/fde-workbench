"""大纪要分段抽取的切片规划与行号回基（V31-P1b）。

实测（MiniMax-M3.1-Flash，2026-11-09 somwyn 试点偏离复盘）：
供应商 completion **硬顶 16,384 tokens**，``reasoning_content`` 与 ``content``
共享同一份预算；10K 字符纪要一次成抽必被截断（JSON 断在半路，
``finish_reason=length``）。把预算 ×2 预留只会让模型思考更长——实测 32,768
预算下同一篇纪要 **>900s 未返回**（超时），既没换来正文空间也没换来成功率。

可行的解法不是「加预算」，而是**把活拆小**：按行切片分批抽取，每批的
输出体量落在供应商硬顶之内，再按行号回基合并成一份整批输出。

本模块是纯函数切片器（无 IO、无模型调用），行号口径：

- ``TranscriptChunk.start_line`` 是该片首行在**全文**中的绝对行号（1 起）；
- 模型看到的是片内正文，它回报的行号是**片内**行号（1 起）；
- 回基公式：``absolute = chunk.start_line + reported_line - 1``。
"""

from __future__ import annotations

from dataclasses import dataclass

# 切片上限：单片行数 / 单片字符数（均含片内正文，不含任何外部框架文字）。
# 取值依据是「单片输出体量必须落在供应商 completion 硬顶内」——2026-11-09
# 实测（MiniMax-M3.1-Flash，硬顶 16,384 tokens）：25 行/片典型用量 8,343
# tokens（余量充足）；40 行/片典型 13,105–13,728（余量薄，**实测有批次触顶**）；
# 60 行/片必截断。故取 25 行，并把残余方差交给**自适应二分**兜底
# （被截断的片自动一分为二再抽，见 split_chunk）。
DEFAULT_MAX_LINES = 25
DEFAULT_MAX_CHARS = 1600


@dataclass(frozen=True)
class TranscriptChunk:
    """一段连续正文切片。"""

    index: int
    text: str
    start_line: int  # 全文绝对行号（1 起，含）
    end_line: int    # 全文绝对行号（1 起，含）

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1

    def rebase_line(self, reported_line: int) -> int:
        """片内行号 → 全文绝对行号。"""
        return self.start_line + reported_line - 1


def plan_chunks(
    content: str,
    *,
    max_lines: int = DEFAULT_MAX_LINES,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[TranscriptChunk]:
    """按行把正文切成连续片（不丢行、不重排、不改字）。

    - 每片至多 ``max_lines`` 行、至多 ``max_chars`` 字符（近似计，含换行）；
    - 单行本身超 ``max_chars`` 时独占一片（不切开单行——行号口径不能破）；
    - 空正文返回空片列表（调用方按「无内容」处理）。
    """
    if max_lines <= 0 or max_chars <= 0:
        raise ValueError("切片上限必须为正数")
    if not content.strip():
        return []
    lines = content.split("\n")
    chunks: list[TranscriptChunk] = []
    buffer: list[str] = []
    size = 0
    start_line = 1

    for offset, line in enumerate(lines):
        line_size = len(line) + 1  # +1 记换行
        if buffer and (len(buffer) >= max_lines or size + line_size > max_chars):
            chunks.append(
                TranscriptChunk(
                    index=len(chunks),
                    text="\n".join(buffer),
                    start_line=start_line,
                    end_line=start_line + len(buffer) - 1,
                )
            )
            start_line = offset + 1
            buffer = []
            size = 0
        buffer.append(line)
        size += line_size
    if buffer:
        chunks.append(
            TranscriptChunk(
                index=len(chunks),
                text="\n".join(buffer),
                start_line=start_line,
                end_line=start_line + len(buffer) - 1,
            )
        )
    return chunks


def split_chunk(chunk: TranscriptChunk) -> tuple[TranscriptChunk, TranscriptChunk] | None:
    """把一片按行一分为二（自适应降片长用）。

    返回 ``None`` 表示不能再分（单行片）——此时只能诚实失败，不切碎单行
    （行号口径不能破）。两片的行号区间连续且不重叠。
    """
    lines = chunk.text.split("\n")
    if len(lines) < 2:
        return None
    half = len(lines) // 2
    left = TranscriptChunk(
        index=chunk.index,
        text="\n".join(lines[:half]),
        start_line=chunk.start_line,
        end_line=chunk.start_line + half - 1,
    )
    right = TranscriptChunk(
        index=chunk.index,
        text="\n".join(lines[half:]),
        start_line=chunk.start_line + half,
        end_line=chunk.end_line,
    )
    return left, right
