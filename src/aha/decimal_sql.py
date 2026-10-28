"""Exact SQLite aggregates; money never passes through REAL or int64 SUM."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol, cast

USAGE_TOTAL_FIELDS = (
    "record_count", "unpriced_count", "fresh_input_tokens", "output_tokens",
    "cache_read_tokens", "cache_creation_tokens", "total_tokens", "total_cost_usd",
)


class DecimalSum:
    def __init__(self) -> None:
        self.coefficient = 0
        self.exponent = 0

    def step(self, value: Any) -> None:
        if value is None:
            return
        text = str(value)
        integral, point, fractional = text.partition(".")
        if integral.lstrip("+-").isdigit() and (not point or fractional.isdigit()):
            # Normalized ledger values are fixed-point text. Parse its exact
            # coefficient directly rather than reconstructing a Decimal tuple
            # and joining every digit for every aggregate row.
            coefficient = int(integral + fractional)
            exponent = -len(fractional)
        else:
            number = Decimal(text)
            if not number.is_finite():
                raise ValueError("nonfinite decimal")
            parts = number.as_tuple()
            exponent = int(parts.exponent)
            coefficient = int("".join(map(str, parts.digits)) or "0")
            if parts.sign:
                coefficient = -coefficient
        if exponent < self.exponent:
            self.coefficient *= 10 ** (self.exponent - exponent)
            self.exponent = exponent
        self.coefficient += coefficient * 10 ** (exponent - self.exponent)

    def finalize(self) -> str:
        if not self.coefficient:
            return "0"
        sign = "-" if self.coefficient < 0 else ""
        digits = str(abs(self.coefficient))
        if self.exponent >= 0:
            return sign + digits + "0" * self.exponent
        digits = digits.zfill(1 - self.exponent)
        result = sign + digits[: self.exponent] + "." + digits[self.exponent :]
        return result.rstrip("0").rstrip(".")


class IntegerSum:
    def __init__(self) -> None:
        self.value = 0

    def step(self, value: Any) -> None:
        if value is not None:
            self.value += int(value)

    def finalize(self) -> str:
        return str(self.value)


class UsageTotals:
    """Sum the seven integer metrics and cost with one SQLite callback per row."""

    def __init__(self) -> None:
        self.counts = [0] * (len(USAGE_TOTAL_FIELDS) - 1)
        self.cost = DecimalSum()

    def step(self, *values: Any) -> None:
        for index in range(len(self.counts)):
            if values[index] is not None:
                self.counts[index] += int(values[index])
        self.cost.step(values[-1])

    def values(self) -> list[str]:
        return [*(str(value) for value in self.counts), self.cost.finalize()]

    def finalize(self) -> str:
        # Return TEXT so integer totals may exceed SQLite's signed int64 range.
        return json.dumps(self.values())


class UsageGroups:
    """Keep six bounded summary groups without a SQLite sorter over all daily rows."""

    def __init__(self) -> None:
        self.groups: dict[tuple[str, str], tuple[int, UsageTotals]] = {}

    def step(self, state: str, kind: str, count: int, *values: Any) -> None:
        if state not in {"available", "claimed", "pending"} or kind not in {"detail", "rollup"}:
            raise ValueError("invalid aggregate group")
        key = (state, kind)
        row_count, totals = self.groups.get(key, (0, None))
        if totals is None:
            totals = UsageTotals()
        totals.step(*values)
        self.groups[key] = (row_count + count, totals)

    def finalize(self) -> str:
        return json.dumps([
            {"state": state, "kind": kind, "row_count": count,
             **dict(zip(USAGE_TOTAL_FIELDS, totals.values(), strict=True))}
            for (state, kind), (count, totals) in self.groups.items()
        ])


class _TextAggregate(Protocol):
    def finalize(self) -> str: ...


def register(connection: sqlite3.Connection) -> None:
    # typeshed currently narrows finalize() to int, although SQLite explicitly
    # supports TEXT results. This adapter bridges that stub, not domain validation.
    create_text_aggregate = cast(
        Callable[[str, int, Callable[[], _TextAggregate]], None], connection.create_aggregate
    )
    create_text_aggregate("decimal_sum", 1, DecimalSum)
    create_text_aggregate("integer_sum", 1, IntegerSum)
    create_text_aggregate("bigint_sum", 1, IntegerSum)
    create_text_aggregate("usage_totals", len(USAGE_TOTAL_FIELDS), UsageTotals)
    create_text_aggregate("usage_groups", len(USAGE_TOTAL_FIELDS) + 3, UsageGroups)
