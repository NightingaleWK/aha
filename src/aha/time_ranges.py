"""One Beijing half-open range contract for queries and frozen evidence.

Intent is presentation metadata. Only the resolved integer-second bounds and
grain policy identify a selection; saving never resolves that intent again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from .domain import BEIJING, AppError, parse_date

PRESETS = {"today", "last_24h", "last_7d", "last_14d", "last_30d", "month", "all"}
_MINUTE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}\Z")
_SECOND = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\+08:00\Z")
_EPOCH = datetime(1970, 1, 1, 8, tzinfo=BEIJING)


def current_time() -> datetime:
    """Central clock seam; a new analysis captures it exactly once."""
    return datetime.now(BEIJING).replace(microsecond=0)


def epoch(value: datetime) -> int:
    return int((value - _EPOCH).total_seconds())


def at_epoch(value: int) -> datetime:
    # Arithmetic also supports pre-1970 dates on Windows, without OS time_t.
    return _EPOCH + timedelta(seconds=value)


def midnight(value: date) -> int:
    return epoch(datetime.combine(value, time.min, BEIJING))


def _invalid(message: str = "时间范围格式不正确，请重新选择。") -> AppError:
    return AppError("invalid_time_range", message)


def _parse(value: Any, *, minute: bool = False) -> datetime:
    if not isinstance(value, str) or not (_MINUTE if minute else _SECOND).fullmatch(value):
        raise _invalid()
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _invalid() from exc
    return result.replace(tzinfo=BEIJING) if minute else result


@dataclass(frozen=True)
class TimeRange:
    start_epoch: int
    end_exclusive_epoch: int
    precision: str
    intent: dict[str, Any]
    resolved_at: str | None

    @property
    def start_date(self) -> date:
        return at_epoch(self.start_epoch).date()

    @property
    def end_date(self) -> date:
        return at_epoch(self.end_exclusive_epoch - 1).date()

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "timezone": "Asia/Shanghai",
            "start_at": at_epoch(self.start_epoch).isoformat(timespec="seconds"),
            "end_before": at_epoch(self.end_exclusive_epoch).isoformat(timespec="seconds"),
            "precision": self.precision,
            "intent": dict(self.intent),
            "resolved_at": self.resolved_at,
            "rollup_policy": "full_days_only",
        }

    def identity(self) -> dict[str, Any]:
        return {
            "version": 1,
            "timezone": "Asia/Shanghai",
            "start_epoch": self.start_epoch,
            "end_exclusive_epoch": self.end_exclusive_epoch,
            "rollup_policy": "full_days_only",
        }

    def full_days(self) -> tuple[date, date] | None:
        first, last = self.start_date, self.end_date
        if self.start_epoch != midnight(first):
            if first == date.max:
                return None
            first += timedelta(days=1)
        if self.end_exclusive_epoch != midnight(last) + 86400:
            if last == date.min:
                return None
            last -= timedelta(days=1)
        return (first, last) if first <= last else None

    def partial_days(self) -> list[tuple[int, int, date]]:
        """At most two disjoint detail-only pieces, one for a single-day range."""
        first, last = self.start_date, self.end_date
        start, end = self.start_epoch, self.end_exclusive_epoch
        if first == last:
            return [] if start == midnight(first) and end == start + 86400 else [
                (start, end, first)
            ]
        result = []
        if start != midnight(first):
            result.append((start, midnight(first) + 86400, first))
        if end != midnight(last) + 86400:
            result.append((midnight(last), end, last))
        return result


def legacy_dates(start_date: str, end_date: str, *, resolved_at: str | None = None) -> TimeRange:
    first, last = parse_date(start_date), parse_date(end_date)
    if first > last:
        raise AppError("invalid_date_range", "开始日期不能晚于结束日期。")
    # Keep the old max-date summary boundary in integers. That legacy-only
    # analysis cannot export a version-1 ISO range or iterate overflowing rows.
    return TimeRange(midnight(first), midnight(last) + 86400, "day", {
        "kind": "legacy_dates", "start_date": start_date, "end_date": end_date,
    }, resolved_at)


def resolve(
    intent: Any, *, now: datetime, coverage: tuple[str, str] | None = None
) -> TimeRange:
    if not isinstance(intent, dict) or not isinstance(intent.get("follow_now"), bool):
        raise _invalid()
    follow = intent["follow_now"]
    try:
        captured = now.astimezone(BEIJING).replace(microsecond=0)
        resolved_at = captured.isoformat(timespec="seconds")
        kind = intent.get("kind")
        if kind == "preset":
            preset = intent.get("preset")
            if not isinstance(preset, str) or preset not in PRESETS:
                raise _invalid()
            allowed = {"kind", "preset", "follow_now"}
            if preset == "all":
                if follow or set(intent) != allowed:
                    raise _invalid()
                if coverage is None:
                    raise _invalid("暂无可查询日期，请先同步本地用量。")
                result = legacy_dates(*coverage, resolved_at=resolved_at)
                result = TimeRange(result.start_epoch, result.end_exclusive_epoch,
                                   "day", dict(intent), resolved_at)
            else:
                if not follow:
                    allowed.add("end_before")
                if set(intent) != allowed:
                    raise _invalid()
                end = epoch(captured) + 1 if follow else epoch(_parse(intent["end_before"]))
                anchor = at_epoch(end - 1).date()
                if preset == "last_24h":
                    start = end - 86400
                elif preset == "month":
                    start = midnight(anchor.replace(day=1))
                else:
                    count = 1 if preset == "today" else int(preset[5:-1])
                    start = midnight(anchor - timedelta(days=count - 1))
                result = TimeRange(start, end, "second", dict(intent), resolved_at)
        elif kind == "custom":
            allowed = {"kind", "start", "follow_now"} | (set() if follow else {"end"})
            if set(intent) != allowed:
                raise _invalid()
            start = epoch(_parse(intent["start"], minute=True))
            end = epoch(captured) + 1 if follow else epoch(_parse(intent["end"], minute=True)) + 60
            result = TimeRange(start, end, "second" if follow else "minute",
                               dict(intent), resolved_at)
        else:
            raise _invalid()
        if result.start_epoch >= result.end_exclusive_epoch:
            raise _invalid("开始时间不能晚于结束时间，请检查时间范围。")
        result.as_dict()  # Reject underflow/overflow before a query is created.
        return result
    except (OverflowError, ValueError, OSError, KeyError) as exc:
        raise _invalid("时间范围超出支持范围，请重新选择。") from exc


def from_analysis(analysis: dict[str, Any]) -> TimeRange:
    value = analysis.get("time_range")
    if value is None:
        return legacy_dates(analysis["start_date"], analysis["end_date"])
    if (
        not isinstance(value, dict)
        or type(value.get("version")) is not int
        or value["version"] != 1
        or value.get("timezone") != "Asia/Shanghai"
        or value.get("rollup_policy") != "full_days_only"
        or not isinstance(value.get("precision"), str)
        or value["precision"] not in {"day", "minute", "second"}
        or not isinstance(value.get("intent"), dict)
    ):
        raise _invalid()
    start, end = epoch(_parse(value.get("start_at"))), epoch(_parse(value.get("end_before")))
    if start >= end:
        raise _invalid()
    result = TimeRange(start, end, value["precision"], dict(value["intent"]),
                       value.get("resolved_at"))
    if result.start_date.isoformat() != analysis.get("start_date") or (
        result.end_date.isoformat() != analysis.get("end_date")
    ):
        raise _invalid("时间范围与日期依据不一致，请更新预览。")
    return result


def frozen_metadata(analysis: dict[str, Any]) -> dict[str, Any]:
    """Supplement legacy dates in memory; missing historical completeness stays unknown."""
    result = dict(analysis)
    if result.get("time_range") is None:
        try:
            result["time_range"] = from_analysis(result).as_dict()
        except OverflowError:
            pass  # Old extreme-date analyses retain their old export error.
    for key in ("time_coverage", "summary_complete", "pending_count"):
        result.setdefault(key, None)
    return result
