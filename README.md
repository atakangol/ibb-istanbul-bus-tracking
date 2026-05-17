# Istanbul bus tracking & delay analysis

Track public buses across the city using **İBB (Istanbul Metropolitan Municipality)** open data, and analyze **delays in near–real time** (vehicle positions vs schedules — exact pipelines TBD).

## Goals

- Ingest live or frequently updated bus locations and timetable references.
- Compute delay metrics (e.g. behind/ahead of schedule by stop or segment).
- Surface simple views or exports for monitoring and further analysis.

## Quick start (API)

Official İETT data is exposed as **SOAP** on `https://api.ibb.gov.tr/iett/…`. No API key is required for basic calls today.

```bash
pip install -r requirements.txt

# One stop
python examples/stop_lookup.py 113252

# Search stops by name, district, or direction (first run downloads all stops)
python examples/search_stops.py maslak

# Live buses on a line
python examples/live_line.py 15B

# Ordered stops on a line (both directions)
python examples/line_stops.py 15B
```

### Line map (browser)

OpenStreetMap view with up to three İETT lines (search, direction picker, stop-to-stop polylines):

```bash
pip install -r requirements.txt
uvicorn web.app:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). The first line search downloads the full line index from the API once (cached in SQLite).

Line geometry between stops is approximated on **OpenStreetMap streets** via the public [OSRM](https://project-osrm.org/) demo router (driving profile — not official İETT corridors). If routing fails, the map falls back to straight segments.

Optional credentials (if İBB provides them later): copy `.env.example` to `.env` and set `IETT_USERNAME` / `IETT_PASSWORD`.

### Main endpoints

| Use case | Service |
|----------|---------|
| Stops, lines, routes | `UlasimAnaVeri/HatDurakGuzergah.asmx` |
| Live vehicle positions | `FiloDurum/SeferGerceklesme.asmx` |
| Stop sequence per line | `ibb/ibb.asmx` (`DurakDetay_GYY`) |

Docs and dataset links: [data.ibb.gov.tr](https://data.ibb.gov.tr/en/dataset/?tags=%C4%B0ETT&res_format=API).

Programmatic access: `from iett import IettClient`.

Static stop and line data is cached in **`cache/iett.sqlite`** (SQLite) for **2 weeks** (schedules **1 week**). The first `search_stops` or `get_stop('')` call downloads all stops from the API once, then searches locally. Existing JSON under `cache/lines/`, `cache/line_schedules/`, or `line_schedules/` is imported automatically on startup (file age preserved). Live vehicle calls always hit the API. Pass `force_refresh=True` on cached methods, or `--refresh` on the example scripts, to bypass TTL.

## Status

Basic SOAP client and examples in place; delay analysis pipeline still TBD.
