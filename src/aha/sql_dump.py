"""Interpret only literal CCS INSERT data; never execute a supplied SQL program."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from .domain import SCHEMA_VERSION, AppError, build_source_data, source_name
from .sources import TABLE_FIELDS

MAX_SQL_BYTES = 128 * 1024 * 1024
MAX_STATEMENT_ROWS = 1_000_000
_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", re.ASCII)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*", re.ASCII)
_VERSION_COMMENT = re.compile(r"\s*user_version\s*:\s*(\d+)\s*\Z", re.I)


def _invalid() -> AppError:
    return AppError(
        "invalid_sql", "SQL 备份格式不受支持或包含非常量用量数据；请重新从 CC Switch 导出。"
    )


def _statements(text: str, versions: set[int]) -> Iterator[str]:
    """Split outside strings/comments, including semicolons and newlines in values."""
    start = 0
    position = 0
    length = len(text)
    while position < length:
        char = text[position]
        if char in ("'", '"', "`", "["):
            end_quote = "]" if char == "[" else char
            position += 1
            while position < length:
                if text[position] == end_quote:
                    if (
                        end_quote != "]"
                        and position + 1 < length
                        and text[position + 1] == end_quote
                    ):
                        position += 2
                        continue
                    position += 1
                    break
                position += 1
            else:
                raise _invalid()
            continue
        if text.startswith("--", position):
            end = text.find("\n", position + 2)
            end = length if end < 0 else end
            match = _VERSION_COMMENT.fullmatch(text[position + 2 : end].strip())
            if match:
                versions.add(int(match.group(1)))
            position = end
            continue
        if text.startswith("/*", position):
            end = text.find("*/", position + 2)
            if end < 0:
                raise _invalid()
            position = end + 2
            continue
        if char == ";":
            yield text[start:position]
            start = position + 1
        position += 1
    # CCS emits terminators, but a final literal INSERT without one is harmless.
    if text[start:].strip():
        yield text[start:]


class _Lexer:
    def __init__(self, statement: str) -> None:
        self.text = statement
        self.position = 0
        self.pending: tuple[str, str] | None = None

    def peek(self) -> tuple[str, str]:
        if self.pending is None:
            self.pending = self._next()
        return self.pending

    def take(self) -> tuple[str, str]:
        token = self.peek()
        self.pending = None
        return token

    def expect(self, expected: str) -> None:
        kind, value = self.take()
        if value.upper() != expected or kind not in ("word", "symbol"):
            raise _invalid()

    def identifier(self) -> str:
        kind, value = self.take()
        if kind not in ("word", "identifier"):
            raise _invalid()
        return value.lower()

    def _next(self) -> tuple[str, str]:
        text = self.text
        length = len(text)
        while self.position < length:
            if text[self.position].isspace():
                self.position += 1
            elif text.startswith("--", self.position):
                end = text.find("\n", self.position + 2)
                self.position = length if end < 0 else end + 1
            elif text.startswith("/*", self.position):
                end = text.find("*/", self.position + 2)
                if end < 0:
                    raise _invalid()
                self.position = end + 2
            else:
                break
        if self.position >= length:
            return ("end", "")
        char = text[self.position]
        if char in ("'", '"', "`", "["):
            terminator = "]" if char == "[" else char
            self.position += 1
            parts: list[str] = []
            start = self.position
            while self.position < length:
                if text[self.position] == terminator:
                    parts.append(text[start : self.position])
                    self.position += 1
                    if (
                        terminator != "]"
                        and self.position < length
                        and text[self.position] == terminator
                    ):
                        parts.append(terminator)
                        self.position += 1
                        start = self.position
                        continue
                    return ("string" if char == "'" else "identifier", "".join(parts))
                self.position += 1
            raise _invalid()
        number = _NUMBER.match(text, self.position)
        if number:
            self.position = number.end()
            return ("number", number.group(0))
        identifier = _IDENTIFIER.match(text, self.position)
        if identifier:
            self.position = identifier.end()
            return ("word", identifier.group(0))
        self.position += 1
        return ("symbol", char)


def _declaration(lexer: _Lexer, columns: dict[str, set[str]]) -> None:
    """Inspect names only; defaults, checks, functions and DDL are never run."""
    if lexer.peek()[1].upper() != "TABLE":
        return
    lexer.take()
    if lexer.peek()[1].upper() == "IF":
        for keyword in ("IF", "NOT", "EXISTS"):
            lexer.expect(keyword)
    table = lexer.identifier()
    if table not in TABLE_FIELDS:
        return
    lexer.expect("(")
    depth = 1
    at_column = True
    names: set[str] = set()
    while depth:
        kind, value = lexer.take()
        if kind == "end":
            raise _invalid()
        if value == "(" and kind == "symbol":
            depth += 1
        elif value == ")" and kind == "symbol":
            depth -= 1
        elif value == "," and kind == "symbol" and depth == 1:
            at_column = True
        elif at_column and depth == 1:
            if kind not in ("word", "identifier"):
                raise _invalid()
            if value.upper() not in {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}:
                names.add(value.lower())
            at_column = False
    columns[table] = columns.get(table, set()) | names


def _insert(
    lexer: _Lexer,
    columns: dict[str, set[str]],
    sink: Callable[[str, dict[str, Any]], None],
    counts: dict[str, int],
) -> None:
    lexer.expect("INTO")
    table = lexer.identifier()
    if table not in TABLE_FIELDS:
        # A full CCS export contains private configuration; do not decode its values.
        return
    lexer.expect("(")
    fields: list[str] = []
    while True:
        field = lexer.identifier()
        if field in fields:
            raise _invalid()
        fields.append(field)
        token = lexer.take()
        if token == ("symbol", ")"):
            break
        if token != ("symbol", ","):
            raise _invalid()
    if not set(TABLE_FIELDS[table]).issubset(fields):
        raise AppError("incompatible_schema", "SQL 用量表缺少必要列，请重新导出完整备份。")
    columns[table] = columns.get(table, set()) | set(fields)
    lexer.expect("VALUES")
    while True:
        lexer.expect("(")
        values: list[Any] = []
        while True:
            kind, value = lexer.take()
            if kind in ("number", "string"):
                values.append(value)
            elif kind == "word" and value.upper() == "NULL":
                values.append(None)
            else:
                raise _invalid()
            token = lexer.take()
            if token == ("symbol", ")"):
                break
            if token != ("symbol", ","):
                raise _invalid()
        if len(values) != len(fields):
            raise _invalid()
        counts[table] += 1
        if counts[table] > MAX_STATEMENT_ROWS:
            raise AppError("source_too_large", "SQL 用量记录过多，请选择较小的备份。", 413)
        sink(table, dict(zip(fields, values, strict=True)))
        token = lexer.take()
        if token == ("end", ""):
            break
        if token != ("symbol", ","):
            raise _invalid()


def scan_sql_dump(
    data: bytes, name: str, sink: Callable[[str, dict[str, Any]], None]
) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise AppError("invalid_sql", "请读取 UTF-8 格式的 SQL 备份。")
    if len(data) > MAX_SQL_BYTES:
        raise AppError("source_too_large", "SQL 备份超过 128 MiB 限制。", 413)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AppError("invalid_sql_encoding", "SQL 备份必须使用 UTF-8 编码。") from exc
    versions: set[int] = set()
    columns: dict[str, set[str]] = {}
    counts = dict.fromkeys(TABLE_FIELDS, 0)
    for statement in _statements(text, versions):
        lexer = _Lexer(statement)
        kind, command = lexer.take()
        command = command.upper()
        if kind == "end":
            continue
        if kind != "word":
            raise _invalid()
        if command == "INSERT":
            _insert(lexer, columns, sink, counts)
        elif command == "CREATE":
            if lexer.peek()[1].upper() not in {"TABLE", "INDEX", "UNIQUE"}:
                raise _invalid()
            _declaration(lexer, columns)
        elif command == "PRAGMA":
            if lexer.identifier() == "user_version":
                lexer.expect("=")
                version_kind, version = lexer.take()
                if (
                    version_kind != "number"
                    or not version.isascii()
                    or not version.isdigit()
                    or lexer.take()[0] != "end"
                ):
                    raise _invalid()
                versions.add(int(version))
        elif command == "DELETE":
            lexer.expect("FROM")
            if lexer.identifier() != "sqlite_sequence" or lexer.take()[0] != "end":
                raise _invalid()
            # SQLite dumps reset this internal counter. It has no usage meaning.
        elif command not in {"BEGIN", "COMMIT", "END"}:
            # No UPDATE, ATTACH, SELECT, extension calls, triggers or SQL programs.
            raise _invalid()
    if versions != {SCHEMA_VERSION}:
        raise AppError("unsupported_schema", "SQL 未标明结构版本 23，或包含不一致的结构版本。")
    for table, required in TABLE_FIELDS.items():
        if not set(required).issubset(columns.get(table, set())):
            raise AppError(
                "incompatible_schema", "SQL 缺少必要表或列，请选择完整的 CC Switch 备份。"
            )
    return {
        "kind": "sql",
        "name": source_name(name),
        "fingerprint_kind": "original_file_sha256",
        "fingerprint": hashlib.sha256(data).hexdigest(),
        "observed_at": datetime.now(UTC).isoformat(),
    }


def load_sql_dump(data: bytes, name: str) -> dict[str, Any]:
    """Bounded fixture/convenience loader; the sync pipeline uses scan_sql_dump."""
    rows: dict[str, list[dict[str, Any]]] = {table: [] for table in TABLE_FIELDS}
    source = scan_sql_dump(data, name, lambda table, row: rows[table].append(row))
    return build_source_data(
        rows["proxy_request_logs"], rows["usage_daily_rollups"], rows["model_pricing"], source
    )
