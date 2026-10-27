from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from aha.domain import (
    DETAIL_FIELDS,
    PRICING_FIELDS,
    ROLLUP_FIELDS,
    AppError,
    content_hash,
    decimal_text,
    record_key,
    row_fingerprint,
)
from aha.sources import TABLE_FIELDS, load_sqlite
from aha.sql_dump import load_sql_dump


def detail(**changes: Any) -> dict[str, Any]:
    return {
        "request_id": "r1",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "m",
        "request_model": None,
        "pricing_model": None,
        "input_tokens": 100,
        "output_tokens": 5,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 10,
        "input_token_semantics": 1,
        "input_cost_usd": "0.1",
        "output_cost_usd": "0.02",
        "cache_read_cost_usd": "0.03",
        "cache_creation_cost_usd": "0.04",
        "total_cost_usd": "0.19",
        "cost_multiplier": "1",
        "created_at": 1790866800,
        "session_id": "s1",
        "data_source": "codex_session",
        **changes,
    }


def rollup(**changes: Any) -> dict[str, Any]:
    return {
        "date": "2026-09-01",
        "provider_id": "_codex_session",
        "app_type": "codex",
        "model": "m",
        "request_model": "",
        "pricing_model": "",
        "request_count": 8,
        "input_tokens": 100,
        "output_tokens": 5,
        "cache_read_tokens": 40,
        "cache_creation_tokens": 10,
        "input_token_semantics": 2,
        "total_cost_usd": "1.23456789",
        **changes,
    }


def price(**changes: Any) -> dict[str, Any]:
    return {
        "model_id": "m",
        "display_name": "模型",
        "input_cost_per_million": "2",
        "output_cost_per_million": "3",
        "cache_read_cost_per_million": "0.1",
        "cache_creation_cost_per_million": "0",
        **changes,
    }


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return str(value)


def dump(
    details: list[dict[str, Any]] | None = None,
    rollups: list[dict[str, Any]] | None = None,
    pricing: list[dict[str, Any]] | None = None,
) -> bytes:
    parts = [
        "-- CC Switch backup\n-- user_version: 23\nPRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;"
    ]
    values = {
        "proxy_request_logs": details or [],
        "usage_daily_rollups": rollups or [],
        "model_pricing": pricing or [],
    }
    for table, fields in TABLE_FIELDS.items():
        parts.append(f'CREATE TABLE "{table}" (' + ",".join(f'"{f}" TEXT' for f in fields) + ");")
        if values[table]:
            parts.append(
                f'INSERT INTO "{table}" ('
                + ",".join(f'"{f}"' for f in fields)
                + ") VALUES\n"
                + ",\n".join(
                    "(" + ",".join(_literal(row[f]) for f in fields) + ")" for row in values[table]
                )
                + ";"
            )
    parts.append("COMMIT;")
    return "\n".join(parts).encode("utf-8")


def database(path: Path, rows: list[dict[str, Any]] | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version=23")
    for table, fields in TABLE_FIELDS.items():
        # No affinity lets these fixtures exercise actual integer/text distinctions.
        connection.execute(f'CREATE TABLE "{table}" (' + ",".join(f'"{f}"' for f in fields) + ")")
    for row in rows or []:
        connection.execute(
            "INSERT INTO proxy_request_logs VALUES (" + ",".join("?" for _ in DETAIL_FIELDS) + ")",
            [row[key] for key in DETAIL_FIELDS],
        )
    connection.execute(
        "INSERT INTO model_pricing VALUES (" + ",".join("?" for _ in PRICING_FIELDS) + ")",
        [price()[key] for key in PRICING_FIELDS],
    )
    connection.commit()
    return connection


class SqlDumpTests(unittest.TestCase):
    def test_literals_bom_multiline_and_private_configuration_projection(self) -> None:
        original = detail(request_id="r,';\n中文", model="m,';\n模型")
        raw = b"\xef\xbb\xbf" + dump([original], [rollup()], [price()])
        raw += b"\nINSERT INTO providers (id, secret) VALUES (1, 'PRIVATE_KEY');"
        with patch("sqlite3.connect", side_effect=AssertionError("SQL must never execute")):
            result = load_sql_dump(raw, r"C:\private\input.sql")
        self.assertEqual(result["details"][0]["request_id"], original["request_id"])
        self.assertEqual(result["details"][0]["model"], original["model"])
        self.assertEqual(result["source"]["name"], "input.sql")
        self.assertEqual(result["source"]["fingerprint"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(set(result["details"][0]), set(DETAIL_FIELDS))
        self.assertNotIn("PRIVATE_KEY", str(result))
        self.assertNotIn("private", str(result))

    def test_same_second_same_tokens_distinct_keys_are_preserved(self) -> None:
        result = load_sql_dump(dump([detail(), detail(request_id="r2")]), "x.sql")
        self.assertEqual(len(result["details"]), 2)
        self.assertNotEqual(record_key(result["details"][0]), record_key(result["details"][1]))

    def test_duplicate_detail_rollup_and_price_primary_keys_are_rejected(self) -> None:
        for rows in (
            ([detail(), detail()], [], []),
            ([], [rollup(), rollup()], []),
            ([detail()], [], [price(), price()]),
        ):
            with self.subTest(rows=len(rows[0])), self.assertRaises(AppError) as error:
                load_sql_dump(dump(*rows), "x.sql")
            self.assertEqual(error.exception.code, "duplicate_key")

    def test_side_effects_and_expressions_are_rejected_without_execution(self) -> None:
        raw = dump([detail(model="EXPRESSION")])
        expressions = (
            b"load_extension('private')",
            b"(SELECT 'm')",
            b"random()",
            b"'m'||'x'",
            b"X'1234'",
        )
        for expression in expressions:
            with self.subTest(expression=expression), self.assertRaises(AppError) as error:
                load_sql_dump(raw.replace(b"'EXPRESSION'", expression), "x.sql")
            self.assertEqual(error.exception.code, "invalid_sql")
            self.assertNotIn("private", error.exception.message)
        for command in (
            b"ATTACH DATABASE 'private.db' AS other;",
            b"SELECT load_extension('private');",
            b"UPDATE proxy_request_logs SET input_tokens=0;",
            b"DELETE FROM proxy_request_logs;",
            b"CREATE TRIGGER bad AFTER INSERT ON proxy_request_logs BEGIN SELECT 1; END;",
        ):
            with self.subTest(command=command), self.assertRaises(AppError):
                load_sql_dump(dump() + command, "x.sql")

    def test_valid_escaped_comment_markers_and_ignored_configuration_expressions(self) -> None:
        raw = dump([detail(model="m -- not comment /* ; */")])
        raw += (
            b"\nDELETE FROM sqlite_sequence;"
            b"\nINSERT INTO settings(k,v) VALUES ('key', dangerous());"
        )
        self.assertEqual(len(load_sql_dump(raw, "x.sql")["details"]), 1)

    def test_version_declarations_are_real_comments_or_literal_pragma(self) -> None:
        raw = dump([detail()])
        for modified in (
            raw.replace(b"user_version: 23", b"user_version: 24"),
            raw.replace(b"-- user_version: 23", b""),
            raw + b"\nPRAGMA user_version=22;",
            raw.replace(
                b"-- user_version: 23",
                b"INSERT INTO settings(k,v) VALUES ('x','-- user_version: 23');",
            ),
        ):
            with self.subTest(version=modified[:30]), self.assertRaises(AppError) as error:
                load_sql_dump(modified, "x.sql")
            self.assertEqual(error.exception.code, "unsupported_schema")
        result = load_sql_dump(
            raw.replace(b"-- user_version: 23", b"PRAGMA user_version=23;"), "x.sql"
        )
        self.assertEqual(result["schema_version"], 23)

    def test_missing_columns_malformed_values_and_truncation_fail(self) -> None:
        raw = dump([detail()])
        for invalid in (
            raw.replace(b'"input_token_semantics"', b'"wrong_semantics"'),
            raw.replace(b"'r1'", b"'unterminated"),
            raw.replace(b"VALUES\n(", b"VALUES\n(),("),
            raw.replace(b'"request_id",', b'"request_id","request_id",'),
        ):
            with self.subTest(prefix=invalid[:20]), self.assertRaises(AppError):
                load_sql_dump(invalid, "x.sql")

    def test_invalid_financial_token_and_timestamp_values_fail_closed(self) -> None:
        invalid_rows = [
            detail(total_cost_usd=value)
            for value in ("NaN", "Infinity", "-0.01", "1e10000", "1.2.3", None)
        ] + [
            detail(**{key: value})
            for key, value in (
                ("input_tokens", -1),
                ("output_tokens", "1.5"),
                ("cache_read_tokens", None),
                ("input_token_semantics", 3),
                ("created_at", -1),
                ("created_at", 253402300800),
                ("input_tokens", 2**64),
            )
        ]
        for row in invalid_rows:
            with self.subTest(row=row), self.assertRaises(AppError):
                load_sql_dump(dump([row]), "x.sql")
        for row in (rollup(date="2026-02-30"), rollup(request_count=-1)):
            with self.subTest(row=row), self.assertRaises(AppError):
                load_sql_dump(dump([], [row]), "x.sql")

    def test_irrelevant_app_and_proxy_rows_are_not_counted(self) -> None:
        result = load_sql_dump(
            dump(
                [
                    detail(),
                    detail(request_id="proxy", data_source="proxy", total_cost_usd="not-money"),
                    detail(request_id="claude", app_type="claude"),
                ],
                [rollup(), rollup(provider_id="other")],
                [price(), price(model_id="unused")],
            ),
            "x.sql",
        )
        self.assertEqual(len(result["details"]), 1)
        self.assertEqual(len(result["rollups"]), 1)
        self.assertEqual(len(result["pricing"]), 1)

    def test_decimal_exponent_is_preserved_without_binary_float(self) -> None:
        result = load_sql_dump(dump([detail(total_cost_usd="1.234567891234567891e-10")]), "x.sql")
        self.assertEqual(result["details"][0]["total_cost_usd"], "0.0000000001234567891234567891")
        with self.assertRaises(AppError):
            decimal_text(0.1)

    def test_size_and_encoding_limits(self) -> None:
        with patch("aha.sql_dump.MAX_SQL_BYTES", 4), self.assertRaises(AppError) as error:
            load_sql_dump(b"12345", "x.sql")
        self.assertEqual(error.exception.status, 413)
        with self.assertRaises(AppError) as error:
            load_sql_dump(b"\xff\xfe", "x.sql")
        self.assertEqual(error.exception.code, "invalid_sql_encoding")

    def test_empty_tables_are_a_valid_empty_source(self) -> None:
        result = load_sql_dump(dump(), "x.sql")
        self.assertEqual(result["details"], [])
        self.assertEqual(result["rollups"], [])


class SqliteSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name, "source.sqlite")

    def test_wal_snapshot_includes_committed_wal_and_does_not_modify_source(self) -> None:
        connection = database(self.path, [detail()])
        self.addCleanup(connection.close)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute(
            "INSERT INTO proxy_request_logs VALUES (" + ",".join("?" for _ in DETAIL_FIELDS) + ")",
            [detail(request_id="wal-only")[key] for key in DETAIL_FIELDS],
        )
        connection.execute("CREATE TABLE providers(secret TEXT)")
        connection.execute("INSERT INTO providers VALUES ('DO_NOT_RETAIN')")
        connection.commit()
        wal = Path(str(self.path) + "-wal")
        before = (
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            hashlib.sha256(wal.read_bytes()).hexdigest(),
        )
        result = load_sqlite(self.path)
        after = (
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            hashlib.sha256(wal.read_bytes()).hexdigest(),
        )
        self.assertEqual(before, after)
        self.assertEqual(len(result["details"]), 2)
        self.assertNotIn("DO_NOT_RETAIN", str(result))
        self.assertEqual(result["source"]["fingerprint_kind"], "allowed_projection_sha256")
        self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 23)
        self.assertEqual(
            result["source"]["fingerprint"],
            content_hash(
                {key: result[key] for key in ("schema_version", "details", "rollups", "pricing")}
            ),
        )

    def test_sqlite_and_sql_have_the_same_allowed_content(self) -> None:
        connection = database(self.path, [detail()])
        connection.close()
        left, right = (
            load_sqlite(self.path),
            load_sql_dump(dump([detail()], [], [price()]), "x.sql"),
        )
        for key in ("details", "rollups", "pricing"):
            self.assertEqual(left[key], right[key])

    def test_invalid_database_missing_table_version_and_float_money(self) -> None:
        for action in ("version", "table", "float"):
            with self.subTest(action=action):
                path = Path(self.temporary.name, action + ".sqlite")
                connection = database(path, [detail()])
                if action == "version":
                    connection.execute("PRAGMA user_version=24")
                elif action == "table":
                    connection.execute("DROP TABLE usage_daily_rollups")
                else:
                    connection.execute("UPDATE proxy_request_logs SET total_cost_usd=?", (0.1,))
                connection.commit()
                connection.close()
                with self.assertRaises(AppError):
                    load_sqlite(path)
        self.path.write_bytes(b"not a database PRIVATE")
        with self.assertRaises(AppError) as error:
            load_sqlite(self.path)
        self.assertNotIn("PRIVATE", error.exception.message)
        self.assertNotIn(self.temporary.name, error.exception.message)

    def test_missing_file_does_not_create_a_database(self) -> None:
        with self.assertRaises(AppError):
            load_sqlite(self.path)
        self.assertFalse(self.path.exists())

    def test_snapshot_timeout_aborts_without_fallback(self) -> None:
        connection = database(self.path, [detail()])
        connection.close()
        with patch("aha.sources.SNAPSHOT_TIMEOUT", -1), self.assertRaises(AppError) as error:
            load_sqlite(self.path)
        self.assertEqual(error.exception.code, "source_busy")


class SourceIdentityTests(unittest.TestCase):
    def test_content_fingerprint_ignores_assignments_but_tracks_saved_cost(self) -> None:
        row = detail()
        changed = {**row, "project_id": "new", "project_name": "新项目", "cwd": "/private"}
        self.assertEqual(row_fingerprint(row), row_fingerprint(changed))
        changed["total_cost_usd"] = "99"
        self.assertEqual(record_key(row), record_key(changed))
        self.assertNotEqual(row_fingerprint(row), row_fingerprint(changed))
        other = rollup(request_model="changed")
        self.assertNotEqual(record_key(rollup(), "rollup"), record_key(other, "rollup"))
        self.assertEqual(set(rollup()), set(ROLLUP_FIELDS))


if __name__ == "__main__":
    unittest.main()
