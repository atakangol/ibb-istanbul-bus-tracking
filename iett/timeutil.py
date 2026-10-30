"""Istanbul wall-clock helpers.

İETT schedules and AVL timestamps are Istanbul local time, so every timestamp we
store or compare is naive Istanbul time, regardless of the host's time zone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment,misc]
    ZoneInfoNotFoundError = Exception  # type: ignore[assignment,misc]


def _load_istanbul_tz() -> tzinfo:
    if ZoneInfo is not None:
        try:
            return ZoneInfo("Europe/Istanbul")
        except ZoneInfoNotFoundError:
            pass
    # Windows without the tzdata package has no IANA database; Turkey has been
    # permanently UTC+3 since 2016.
    return timezone(timedelta(hours=3), "+03")


ISTANBUL_TZ = _load_istanbul_tz()


def now_istanbul() -> datetime:
    """Current Istanbul wall-clock time as a naive datetime."""
    return datetime.now(ISTANBUL_TZ).replace(tzinfo=None)


def to_istanbul(value: datetime) -> datetime:
    """Convert to naive Istanbul time. Naive inputs are assumed to be Istanbul already."""
    if value.tzinfo is None:
        return value
    return value.astimezone(ISTANBUL_TZ).replace(tzinfo=None)


def parse_istanbul(text: str) -> datetime:
    """Parse ISO8601 (``Z`` and offsets allowed) into naive Istanbul time."""
    value = text.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return to_istanbul(datetime.fromisoformat(value))
