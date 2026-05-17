"""Snap stop sequences to OSM streets via the public OSRM demo router."""

from __future__ import annotations

import logging
from typing import Any

import requests

logger = logging.getLogger(__name__)

OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"
OSRM_CHUNK_SIZE = 25
OSRM_TIMEOUT = 45.0


def straight_path(stops: list[dict[str, Any]]) -> list[dict[str, float]]:
    return [{"lat": s["lat"], "lon": s["lon"]} for s in stops]


def _osrm_path(chunk: list[dict[str, Any]], session: requests.Session) -> list[dict[str, float]] | None:
    if len(chunk) < 2:
        return straight_path(chunk)

    coord_str = ";".join(f"{s['lon']},{s['lat']}" for s in chunk)
    url = f"{OSRM_ROUTE_URL}/{coord_str}"
    response = session.get(
        url,
        params={"overview": "full", "geometries": "geojson", "steps": "false"},
        timeout=OSRM_TIMEOUT,
        headers={"User-Agent": "IBB_bus/1.0 (Istanbul line map; local dev)"},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != "Ok" or not payload.get("routes"):
        return None

    coords = payload["routes"][0]["geometry"]["coordinates"]
    return [{"lat": lat, "lon": lon} for lon, lat in coords]


def snap_stops_to_streets(stops: list[dict[str, Any]]) -> tuple[list[dict[str, float]], str]:
    """
    Best-effort driving route through ordered stops (not official bus geometry).
    Returns (path, source) where source is 'osrm' or 'straight'.
    """
    if len(stops) < 2:
        return straight_path(stops), "straight"

    session = requests.Session()

    if len(stops) <= OSRM_CHUNK_SIZE:
        try:
            path = _osrm_path(stops, session)
            if path:
                return path, "osrm"
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.warning("OSRM route failed (%s stops): %s", len(stops), exc)
        return straight_path(stops), "straight"

    merged: list[dict[str, float]] = []
    step = OSRM_CHUNK_SIZE - 1
    used_osrm = False

    for start in range(0, len(stops) - 1, step):
        end = min(start + OSRM_CHUNK_SIZE, len(stops))
        chunk = stops[start:end]
        if len(chunk) < 2:
            break
        try:
            part = _osrm_path(chunk, session)
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            logger.warning("OSRM chunk failed: %s", exc)
            part = None

        if not part:
            part = straight_path(chunk)
        else:
            used_osrm = True

        if merged and part:
            part = part[1:]
        merged.extend(part)

    if not merged:
        return straight_path(stops), "straight"
    return merged, "osrm" if used_osrm else "straight"
