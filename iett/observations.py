"""Poll live line positions and record stop passage events."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from .client import IettClient
from .store import IettStore

logger = logging.getLogger(__name__)

SOURCE_YAKIN_DURAK_CHANGE = "yakin_durak_change"


def route_direction(route_code: str | None) -> str | None:
    """Extract D/G from guzergah codes like ``15B_G_D0``."""
    if not route_code:
        return None
    parts = route_code.strip().split("_")
    if len(parts) >= 2 and parts[1] in ("D", "G"):
        return parts[1]
    return None


def _parse_nearest_stop(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _parse_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def build_stop_seq_index(stops: list[dict[str, Any]]) -> dict[tuple[str, int], int]:
    """Map (direction, stop_code) to sequence number from line stop rows."""
    index: dict[tuple[str, int], int] = {}
    for row in stops:
        direction = str(row.get("YON") or "").strip()
        raw_code = row.get("DURAKKODU")
        raw_seq = row.get("SIRANO")
        if not direction or raw_code is None or raw_seq is None:
            continue
        try:
            stop_code = int(raw_code)
            stop_seq = int(raw_seq)
        except (TypeError, ValueError):
            continue
        index[(direction, stop_code)] = stop_seq
    return index


class ObservationLogger:
    """Minute poller: AVL snapshots plus stop passage events on nearest-stop change."""

    def __init__(
        self,
        lines: list[str],
        *,
        client: IettClient | None = None,
        store: IettStore | None = None,
        interval_seconds: float = 60.0,
    ) -> None:
        self.lines = [line.strip() for line in lines if line.strip()]
        if not self.lines:
            raise ValueError("At least one line code is required")
        self.client = client or IettClient()
        self.store = store or self.client.store
        self.interval_seconds = interval_seconds
        self._last_nearest: dict[str, int | None] = {}
        self._stop_seq_by_line: dict[str, dict[tuple[str, int], int]] = {}

    def prefetch_line_stops(self) -> None:
        for line in self.lines:
            stops = self.client.get_line_stops(line)
            self._stop_seq_by_line[line] = build_stop_seq_index(stops)
            logger.info("Cached %s stops for line %s", len(stops), line)

    def run_until(self, deadline: datetime | None = None) -> None:
        """Poll until *deadline* or keyboard interrupt."""
        self.prefetch_line_stops()
        logger.info(
            "Observation logger started for %s (interval %.0fs)",
            ", ".join(self.lines),
            self.interval_seconds,
        )
        while True:
            if deadline is not None and datetime.now() >= deadline:
                logger.info("Reached --until deadline")
                break
            polled_at = datetime.now()
            self._poll_round(polled_at)
            if deadline is not None and datetime.now() >= deadline:
                break
            time.sleep(self.interval_seconds)

    def _poll_round(self, polled_at: datetime) -> None:
        polled_iso = polled_at.isoformat(timespec="seconds")
        for line in self.lines:
            try:
                vehicles = self.client.get_line_vehicles(line)
            except Exception:
                logger.warning("Failed to poll line %s", line, exc_info=True)
                continue
            poll_rows: list[dict[str, Any]] = []
            for vehicle in vehicles:
                poll_row, event = self._process_vehicle(
                    line, vehicle, polled_at=polled_iso
                )
                poll_rows.append(poll_row)
                if event is not None:
                    inserted = self.store.insert_stop_passage(event)
                    if inserted:
                        logger.debug(
                            "Passage %s %s -> stop %s",
                            line,
                            event["vehicle_id"],
                            event["stop_code"],
                        )
            if poll_rows:
                self.store.insert_vehicle_polls(poll_rows)
            logger.info(
                "Polled %s at %s: %s vehicles, %s polls total",
                line,
                polled_iso,
                len(vehicles),
                self.store.count_vehicle_polls(line_code=line),
            )

    def _process_vehicle(
        self,
        line_code: str,
        vehicle: dict[str, Any],
        *,
        polled_at: str,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        vehicle_id = str(vehicle.get("kapino") or "").strip()
        nearest = _parse_nearest_stop(vehicle.get("yakinDurakKodu"))
        route_code = str(vehicle.get("guzergahkodu") or "") or None
        direction = route_direction(route_code)
        avl_time = str(vehicle.get("son_konum_zamani") or "") or None

        poll_row = {
            "polled_at": polled_at,
            "line_code": line_code,
            "vehicle_id": vehicle_id or "?",
            "avl_time": avl_time,
            "nearest_stop": nearest,
            "lat": _parse_float(vehicle.get("enlem")),
            "lon": _parse_float(vehicle.get("boylam")),
            "route_code": route_code,
            "direction_label": str(vehicle.get("yon") or "") or None,
            "payload": json.dumps(vehicle, ensure_ascii=False),
        }

        event: dict[str, Any] | None = None
        if vehicle_id and nearest is not None:
            prev = self._last_nearest.get(vehicle_id)
            if prev is not None and prev != nearest:
                stop_seq = None
                if direction:
                    stop_seq = self._stop_seq_by_line.get(line_code, {}).get(
                        (direction, nearest)
                    )
                event = {
                    "detected_at": polled_at,
                    "line_code": line_code,
                    "vehicle_id": vehicle_id,
                    "stop_code": nearest,
                    "prev_stop_code": prev,
                    "stop_seq": stop_seq,
                    "direction": direction,
                    "avl_time": avl_time,
                    "source": SOURCE_YAKIN_DURAK_CHANGE,
                }
            self._last_nearest[vehicle_id] = nearest

        return poll_row, event
