"""Compute delay minutes from logged stop passages vs posted terminal schedule."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient
from iett.observations import build_stop_seq_index, route_direction
from iett.store import IettStore

# PlanlananSeferSaati SGUNTIPI values vary by line (commonly C / I / P).
_PREFERRED_DAY_TYPE = "C"

DEFAULT_MINUTES_PER_STOP = 2.0
ON_TIME_THRESHOLD_MIN = 3.0
STALE_AVL_MINUTES = 5.0


def _parse_dt(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _parse_avl_time(value: str | None, *, on_date: date) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        parsed = datetime.strptime(text, "%H:%M:%S").time()
        return datetime.combine(on_date, parsed)
    except ValueError:
        return None


def _parse_schedule_time(value: str, *, on_date: date) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt).time()
            return datetime.combine(on_date, parsed)
        except ValueError:
            continue
    return None


def _terminal_stop_codes(
    stop_index: dict[tuple[str, int], int],
) -> dict[str, set[int]]:
    """First sequence number per direction → terminal stop codes."""
    min_seq: dict[str, int] = {}
    for (direction, _), stop_seq in stop_index.items():
        current = min_seq.get(direction)
        if current is None or stop_seq < current:
            min_seq[direction] = stop_seq
    terminals: dict[str, set[int]] = {}
    for (direction, stop_code), stop_seq in stop_index.items():
        if stop_seq == min_seq.get(direction):
            terminals.setdefault(direction, set()).add(stop_code)
    return terminals


def _filter_schedule(
    schedule: list[dict[str, Any]],
    *,
    direction: str | None,
    day_type: str | None,
    service_type: str | None,
) -> list[dict[str, Any]]:
    rows = schedule
    if direction:
        rows = [r for r in rows if str(r.get("SYON") or "") == direction]
    if day_type:
        filtered = [r for r in rows if str(r.get("SGUNTIPI") or "") == day_type]
        if filtered:
            rows = filtered
    if service_type:
        rows = [r for r in rows if str(r.get("SSERVISTIPI") or "") == service_type]
    return rows


def _schedule_day_type(schedule: list[dict[str, Any]], *, direction: str | None) -> str | None:
    rows = schedule
    if direction:
        rows = [r for r in rows if str(r.get("SYON") or "") == direction]
    types = {str(r.get("SGUNTIPI") or "") for r in rows} - {""}
    if _PREFERRED_DAY_TYPE in types:
        return _PREFERRED_DAY_TYPE
    return sorted(types)[0] if len(types) == 1 else None


def _trip_departures(
    schedule_rows: list[dict[str, Any]],
    *,
    on_date: date,
) -> list[datetime]:
    departures: list[datetime] = []
    for row in schedule_rows:
        dt = _parse_schedule_time(str(row.get("DT") or ""), on_date=on_date)
        if dt is not None:
            departures.append(dt)
    departures.sort()
    return departures


def _assign_trip_departure(
    observed: datetime,
    departures: list[datetime],
    *,
    max_late_hours: float = 4.0,
) -> datetime | None:
    if not departures:
        return None
    latest = None
    for departure in departures:
        if departure <= observed:
            latest = departure
        else:
            break
    if latest is None:
        return None
    if observed - latest > timedelta(hours=max_late_hours):
        return None
    return latest


def _scheduled_at_stop(
    trip_departure: datetime,
    *,
    stop_seq: int | None,
    minutes_per_stop: float,
) -> datetime:
    offset = max((stop_seq or 1) - 1, 0) * minutes_per_stop
    return trip_departure + timedelta(minutes=offset)


def _minutes_per_stop(schedule_rows: list[dict[str, Any]], *, stop_count: int) -> float:
    departures = [
        _parse_schedule_time(str(row.get("DT") or ""), on_date=date.today())
        for row in schedule_rows
    ]
    departures = [d for d in departures if d is not None]
    departures.sort()
    if len(departures) < 2 or stop_count < 2:
        return DEFAULT_MINUTES_PER_STOP
    gaps = [
        (departures[i + 1] - departures[i]).total_seconds() / 60.0
        for i in range(len(departures) - 1)
    ]
    gaps = [g for g in gaps if 0 < g < 180]
    if not gaps:
        return DEFAULT_MINUTES_PER_STOP
    median_gap = sorted(gaps)[len(gaps) // 2]
    return max(median_gap / max(stop_count - 1, 1), 0.5)


def analyze_passages(
    passages: list[dict[str, Any]],
    *,
    schedule: list[dict[str, Any]],
    stop_index: dict[tuple[str, int], int],
    service_type: str | None = None,
    minutes_per_stop: float | None = None,
) -> list[dict[str, Any]]:
    terminals = _terminal_stop_codes(stop_index)
    stop_count = len(set(stop_index.values())) or 1
    results: list[dict[str, Any]] = []

    for passage in passages:
        detected = _parse_dt(passage["detected_at"])
        on_date = detected.date()
        direction = passage.get("direction")
        if not direction:
            direction = route_direction(passage.get("route_code"))
        day_type = _schedule_day_type(schedule, direction=direction)

        schedule_rows = _filter_schedule(
            schedule,
            direction=direction,
            day_type=day_type,
            service_type=service_type,
        )
        if minutes_per_stop is None:
            effective_mps = _minutes_per_stop(schedule_rows, stop_count=stop_count)
        else:
            effective_mps = minutes_per_stop

        departures = _trip_departures(schedule_rows, on_date=on_date)
        trip_start = _assign_trip_departure(detected, departures)
        stop_code = int(passage["stop_code"])
        stop_seq = passage.get("stop_seq")
        if stop_seq is None and direction:
            stop_seq = stop_index.get((direction, stop_code))

        schedule_source = "terminal_dt_interpolated"
        if (
            direction
            and stop_code in terminals.get(direction, set())
            and trip_start is not None
        ):
            schedule_source = "terminal_dt"

        scheduled_at = None
        delay_min: float | None = None
        if trip_start is not None:
            scheduled_at = _scheduled_at_stop(
                trip_start,
                stop_seq=int(stop_seq) if stop_seq is not None else None,
                minutes_per_stop=effective_mps,
            )
            delay_min = (detected - scheduled_at).total_seconds() / 60.0

        avl_dt = _parse_avl_time(passage.get("avl_time"), on_date=on_date)
        stale_avl = False
        if avl_dt is not None:
            stale_avl = (detected - avl_dt).total_seconds() > STALE_AVL_MINUTES * 60

        on_time = (
            delay_min is not None and abs(delay_min) <= ON_TIME_THRESHOLD_MIN
        )

        results.append(
            {
                "detected_at": passage["detected_at"],
                "line_code": passage["line_code"],
                "vehicle_id": passage["vehicle_id"],
                "stop_code": stop_code,
                "stop_seq": stop_seq,
                "direction": direction,
                "observed_at": detected.isoformat(timespec="seconds"),
                "scheduled_at": (
                    scheduled_at.isoformat(timespec="seconds") if scheduled_at else None
                ),
                "delay_minutes": round(delay_min, 1) if delay_min is not None else None,
                "on_time": on_time if delay_min is not None else None,
                "schedule_source": schedule_source if scheduled_at else None,
                "trip_departure": (
                    trip_start.isoformat(timespec="seconds") if trip_start else None
                ),
                "minutes_per_stop": round(effective_mps, 2),
                "day_type": day_type,
                "stale_avl": stale_avl,
                "source": passage.get("source"),
            }
        )

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze delays from observation SQLite data")
    parser.add_argument("--line", help="Filter to one line code")
    parser.add_argument("--since", help="Passages on/after ISO datetime")
    parser.add_argument("--until", help="Passages on/before ISO datetime")
    parser.add_argument(
        "--service-type",
        help="Filter schedule rows (SSERVISTIPI), e.g. ÖHO",
    )
    parser.add_argument(
        "--minutes-per-stop",
        type=float,
        help="Override per-stop offset for non-terminal stops",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Max passage rows to analyze",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "csv"),
        default="table",
        help="Output format",
    )
    parser.add_argument(
        "--refresh-schedule",
        action="store_true",
        help="Refetch schedule from API before analysis",
    )
    args = parser.parse_args()

    store = IettStore()
    passages = store.fetch_passages(
        line_code=args.line,
        since=args.since,
        until=args.until,
        limit=args.limit,
    )
    if not passages:
        print("No stop_passage_events found for the given filters.")
        return

    client = IettClient(store=store)
    lines = sorted({p["line_code"] for p in passages})
    schedules: dict[str, list[dict[str, Any]]] = {}
    stop_indexes: dict[str, dict[tuple[str, int], int]] = {}
    for line in lines:
        schedules[line] = client.get_line_schedule(
            line, force_refresh=args.refresh_schedule
        )
        stops = client.get_line_stops(line)
        stop_indexes[line] = build_stop_seq_index(stops)

    rows: list[dict[str, Any]] = []
    for passage in passages:
        line = passage["line_code"]
        rows.extend(
            analyze_passages(
                [passage],
                schedule=schedules[line],
                stop_index=stop_indexes[line],
                service_type=args.service_type,
                minutes_per_stop=args.minutes_per_stop,
            )
        )

    if args.format == "json":
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if args.format == "csv":
        fieldnames = list(rows[0].keys()) if rows else []
        writer = csv.DictWriter(sys.stdout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return

    print(f"Analyzed {len(rows)} passage(s)\n")
    for row in rows:
        delay = row["delay_minutes"]
        delay_text = f"{delay:+.1f} min" if delay is not None else "n/a"
        print(
            f"{row['detected_at']}  {row['line_code']}  {row['vehicle_id']}  "
            f"stop {row['stop_code']} (seq {row['stop_seq']})  "
            f"delay {delay_text}  [{row.get('schedule_source')}]"
        )


if __name__ == "__main__":
    main()
