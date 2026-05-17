"""Coordinate helpers for İETT line stop rows."""

from __future__ import annotations

from typing import Any


def line_stop_latlng(row: dict[str, Any]) -> tuple[float, float] | None:
    """Return (lat, lon) from a line stop row, or None if invalid."""
    try:
        lat = float(row.get("YKOORDINATI") or "")
        lon = float(row.get("XKOORDINATI") or "")
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon
