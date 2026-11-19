"""冻结断言文法的解析与求值（`_ae-tasks-v1.md` §5 逐字实现）。

**纪律**（05:41「评分器只消费落盘记录，不改断言」）：
- 本模块**只读**断言文本，**不改写、不放宽、不跳过**任何一条；
- 文法不合的表达式抛 ``AssertionSyntaxError``——评分器据此**判 FAIL 并登记**，
  绝不静默通过（证据缺失＝不通过）；
- 缺失路径以 ``MISSING`` 哨兵参与比较，恒为 False；``not <缺失>`` 亦为 False
  （无法证明其否定——「查不到」不等于「通过」）。

文法（`_ae-tasks-v1.md` §5 逐字）::

    expr    := clause ((" and " | " or " ) clause)*
    clause  := operand op operand
             | "len(" path ")" op operand
             | "not " operand
    operand := path | literal | "len(" path ")"
    path    := ident ( "." ident | "[" int "]" )*
    op      := "==" | "!=" | ">=" | "<=" | ">" | "<"
    literal := string | number | true | false | null
    ident   := [A-Za-z_][A-Za-z0-9_]*

根作用域（`_ae-tasks-v1.md` §4 观测包络）：``attempts.<first|replay2|replay3>``
（契约字段）、``task.total_cost_usd``（评分器派生）、``task.external_state.<key>``
（harness 观测）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

__all__ = [
    "AssertionSyntaxError",
    "MISSING",
    "evaluate_all",
    "evaluate_assertion",
    "parse_assertion",
]


class AssertionSyntaxError(ValueError):
    """断言文本不符合冻结文法（→ 评分器判 FAIL 并登记，不静默跳过）。"""


class _Missing:
    """缺失哨兵：证据缺失＝不可判＝不通过。"""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _Missing()


# ---- 文法元素 ----------------------------------------------------------------


@dataclass(frozen=True)
class _Path:
    segments: tuple[tuple[str, Any], ...]  # ("key", name) | ("index", int)


@dataclass(frozen=True)
class _Literal:
    value: Any


@dataclass(frozen=True)
class _Len:
    path: _Path


@dataclass(frozen=True)
class _Compare:
    left: Any
    op: str
    right: Any


@dataclass(frozen=True)
class _Not:
    operand: Any


@dataclass(frozen=True)
class _BoolOp:
    op: str
    left: Any
    right: Any


# ---- 词法 --------------------------------------------------------------------


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_OPS = ("==", "!=", ">=", "<=", ">", "<")
_KEYWORDS = {"and", "or", "not", "true", "false", "null", "len"}


@dataclass(frozen=True)
class _Token:
    kind: str  # ident | number | string | op | punct | keyword | end
    value: Any
    pos: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == '"':
            j = i + 1
            buf: list[str] = []
            while True:
                if j >= n:
                    raise AssertionSyntaxError(f"字符串未闭合：{text!r}")
                c = text[j]
                if c == "\\":
                    if j + 1 >= n:
                        raise AssertionSyntaxError(f"转义未闭合：{text!r}")
                    buf.append(text[j + 1])
                    j += 2
                    continue
                if c == '"':
                    break
                buf.append(c)
                j += 1
            tokens.append(_Token("string", "".join(buf), i))
            i = j + 1
            continue
        matched_op = next((op for op in _OPS if text.startswith(op, i)), None)
        if matched_op is not None:
            tokens.append(_Token("op", matched_op, i))
            i += len(matched_op)
            continue
        if ch in "().[]":
            tokens.append(_Token("punct", ch, i))
            i += 1
            continue
        m = _IDENT_RE.match(text, i)
        if m:
            word = m.group(0)
            tokens.append(_Token("keyword" if word in _KEYWORDS else "ident", word, i))
            i = m.end()
            continue
        m = _NUMBER_RE.match(text, i)
        if m:
            raw = m.group(0)
            tokens.append(_Token("number", float(raw) if "." in raw else int(raw), i))
            i = m.end()
            continue
        raise AssertionSyntaxError(f"无法识别的字符 {ch!r}（位置 {i}）：{text!r}")
    tokens.append(_Token("end", None, n))
    return tokens


# ---- 语法 --------------------------------------------------------------------


class _Parser:
    def __init__(self, text: str) -> None:
        self._text = text
        self._tokens = _tokenize(text)
        self._index = 0

    # -- token helpers --

    @property
    def _current(self) -> _Token:
        return self._tokens[self._index]

    def _advance(self) -> _Token:
        token = self._tokens[self._index]
        self._index += 1
        return token

    def _expect_punct(self, char: str) -> None:
        token = self._current
        if token.kind != "punct" or token.value != char:
            raise AssertionSyntaxError(f"期望 {char!r}（位置 {token.pos}）：{self._text!r}")
        self._advance()

    def _expect_keyword(self, word: str) -> None:
        token = self._current
        if token.kind != "keyword" or token.value != word:
            raise AssertionSyntaxError(f"期望 {word!r}（位置 {token.pos}）：{self._text!r}")
        self._advance()

    # -- grammar --

    def parse(self) -> Any:
        node = self._parse_expr()
        token = self._current
        if token.kind != "end":
            raise AssertionSyntaxError(f"表达式尾部有多余内容（位置 {token.pos}）：{self._text!r}")
        return node

    def _parse_expr(self) -> Any:
        node = self._parse_clause()
        while self._current.kind == "keyword" and self._current.value in ("and", "or"):
            op = self._advance().value
            right = self._parse_clause()
            node = _BoolOp(op, node, right)
        return node

    def _parse_clause(self) -> Any:
        if self._current.kind == "keyword" and self._current.value == "not":
            self._advance()
            return _Not(self._parse_operand())
        left = self._parse_operand()
        token = self._current
        if token.kind != "op":
            raise AssertionSyntaxError(f"期望比较算子（位置 {token.pos}）：{self._text!r}")
        self._advance()
        right = self._parse_operand()
        return _Compare(left, token.value, right)

    def _parse_operand(self) -> Any:
        token = self._current
        if token.kind == "keyword" and token.value == "len":
            self._advance()
            self._expect_punct("(")
            path = self._parse_path()
            self._expect_punct(")")
            return _Len(path)
        if token.kind == "string":
            self._advance()
            return _Literal(token.value)
        if token.kind == "number":
            self._advance()
            return _Literal(token.value)
        if token.kind == "keyword" and token.value in ("true", "false"):
            self._advance()
            return _Literal(token.value == "true")
        if token.kind == "keyword" and token.value == "null":
            self._advance()
            return _Literal(None)
        if token.kind == "ident":
            return self._parse_path()
        raise AssertionSyntaxError(f"期望操作数（位置 {token.pos}）：{self._text!r}")

    def _parse_path(self) -> _Path:
        token = self._current
        if token.kind != "ident":
            raise AssertionSyntaxError(f"期望路径标识符（位置 {token.pos}）：{self._text!r}")
        self._advance()
        segments: list[tuple[str, Any]] = [("key", token.value)]
        while True:
            token = self._current
            if token.kind == "punct" and token.value == ".":
                self._advance()
                name = self._current
                if name.kind != "ident":
                    raise AssertionSyntaxError(f"期望路径段标识符（位置 {name.pos}）：{self._text!r}")
                self._advance()
                segments.append(("key", name.value))
                continue
            if token.kind == "punct" and token.value == "[":
                self._advance()
                number = self._current
                if number.kind != "number" or not isinstance(number.value, int):
                    raise AssertionSyntaxError(f"期望整数下标（位置 {number.pos}）：{self._text!r}")
                self._advance()
                self._expect_punct("]")
                segments.append(("index", number.value))
                continue
            break
        return _Path(tuple(segments))


def parse_assertion(text: str) -> Any:
    """解析一条断言文本（文法不合即抛 ``AssertionSyntaxError``）。"""
    if not isinstance(text, str) or not text.strip():
        raise AssertionSyntaxError(f"断言文本须为非空字符串：{text!r}")
    return _Parser(text).parse()


# ---- 求值 --------------------------------------------------------------------


def _resolve(path: _Path, scope: dict[str, Any]) -> Any:
    current: Any = scope
    for kind, key in path.segments:
        if kind == "key":
            if not isinstance(current, dict) or key not in current:
                return MISSING
            current = current[key]
            continue
        if not isinstance(current, list) or not (-len(current) <= key < len(current)):
            return MISSING
        current = current[key]
    return current


def _operand_value(node: Any, scope: dict[str, Any]) -> Any:
    if isinstance(node, _Path):
        return _resolve(node, scope)
    if isinstance(node, _Literal):
        return node.value
    if isinstance(node, _Len):
        target = _resolve(node.path, scope)
        if target is MISSING:
            return MISSING
        if isinstance(target, (str, list, tuple, dict)):
            return len(target)
        return MISSING
    raise AssertionSyntaxError(f"未知操作数节点：{node!r}")


def _strict_equal(left: Any, right: Any) -> bool:
    """相等判定（bool 与数字不互等——避免 ``1 == True`` 造成假通过）。"""
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if type(left) is not type(right):
        return False
    return bool(left == right)


def _compare(op: str, left: Any, right: Any) -> bool:
    if left is MISSING or right is MISSING:
        return False
    if op == "==":
        return _strict_equal(left, right)
    if op == "!=":
        return not _strict_equal(left, right)
    try:
        if op == ">=":
            return bool(left >= right)
        if op == "<=":
            return bool(left <= right)
        if op == ">":
            return bool(left > right)
        if op == "<":
            return bool(left < right)
    except TypeError:
        return False
    raise AssertionSyntaxError(f"未知比较算子：{op!r}")


def _evaluate(node: Any, scope: dict[str, Any]) -> bool:
    if isinstance(node, _Compare):
        return _compare(node.op, _operand_value(node.left, scope), _operand_value(node.right, scope))
    if isinstance(node, _Not):
        value = _operand_value(node.operand, scope)
        if value is MISSING:
            return False
        return not bool(value)
    if isinstance(node, _BoolOp):
        left = _evaluate(node.left, scope)
        if node.op == "and":
            return left and _evaluate(node.right, scope)
        return left or _evaluate(node.right, scope)
    raise AssertionSyntaxError(f"未知断言节点：{node!r}")


def evaluate_assertion(expression: str, scope: dict[str, Any]) -> bool:
    """求值一条断言；文法不合抛 ``AssertionSyntaxError``（由评分器登记为 FAIL）。"""
    return _evaluate(parse_assertion(expression), scope)


def evaluate_all(expressions: list[str], scope: dict[str, Any]) -> list[bool]:
    """逐条求值；文法不合的条目登记为 **False**（不静默跳过、不中断整轮）。"""
    results: list[bool] = []
    for expression in expressions:
        try:
            results.append(evaluate_assertion(expression, scope))
        except AssertionSyntaxError:
            results.append(False)
    return results
