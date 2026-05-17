"""FastAPI app: İETT line map API and static UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from iett import IettClient
from iett.geo import line_stop_latlng
from iett.routing import snap_stops_to_streets
from iett.store import _line_code, _line_name

STATIC_DIR = Path(__file__).resolve().parent / "static"
VALID_DIRECTIONS = frozenset({"D", "G"})

app = FastAPI(title="İBB Bus Line Map")
client = IettClient()


def _line_summary(row: dict[str, Any]) -> dict[str, str]:
    return {"code": _line_code(row) or "", "name": _line_name(row)}


def _line_display_name(line_code: str) -> str:
    row = client.store.get_line_by_code(line_code)
    if row:
        name = _line_name(row)
        if name:
            return name
    schedule = client.get_line_schedule(line_code)
    if schedule:
        name = str(schedule[0].get("HATADI") or "").strip()
        if name:
            return name
    return ""


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/lines/search")
def search_lines(
    q: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=50),
) -> list[dict[str, str]]:
    query = q.strip()
    if not query:
        return []
    rows = client.search_lines(query, limit=limit)
    seen: set[str] = set()
    results: list[dict[str, str]] = []
    for row in rows:
        summary = _line_summary(row)
        code = summary["code"]
        if not code or code in seen:
            continue
        seen.add(code)
        results.append(summary)
    return results


@app.get("/api/lines/{line_code}/route")
def line_route(
    line_code: str,
    direction: str = Query("D"),
) -> dict[str, Any]:
    code = line_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="Line code required")
    yon = direction.strip().upper()
    if yon not in VALID_DIRECTIONS:
        raise HTTPException(status_code=400, detail="direction must be D or G")

    rows = client.get_line_stops(code)
    filtered = [r for r in rows if str(r.get("YON", "")).upper() == yon]
    filtered.sort(key=lambda r: int(str(r.get("SIRANO") or "0")))

    stops: list[dict[str, Any]] = []
    for row in filtered:
        coords = line_stop_latlng(row)
        if coords is None:
            continue
        lat, lon = coords
        stops.append(
            {
                "order": int(str(row.get("SIRANO") or "0")),
                "code": str(row.get("DURAKKODU") or ""),
                "name": str(row.get("DURAKADI") or ""),
                "lat": lat,
                "lon": lon,
            }
        )

    if not stops:
        raise HTTPException(
            status_code=404,
            detail=f"No stops for line {code} direction {yon}",
        )

    path, path_source = snap_stops_to_streets(stops)

    return {
        "code": code,
        "direction": yon,
        "name": _line_display_name(code),
        "stops": stops,
        "path": path,
        "path_source": path_source,
    }


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
