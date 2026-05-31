# Delay analysis methodology

This document defines how we measure bus delay in this project, what data we collect, and how to run the logger and analysis scripts.

## Definitions

| Term | Meaning |
|------|---------|
| **Scheduled time** | When a trip was supposed to reach a point. Phase 1 uses terminal departures (`DT` from `PlanlananSeferSaati`). Phase 2 will use per-stop GTFS `stop_times`. |
| **Observed time** | When the vehicle was first seen at a stop: the poll where `yakinDurakKodu` changed to that stop (stored in `stop_passage_events.detected_at`). |
| **Delay (minutes)** | `observed − scheduled`. Positive = late. |
| **On-time** | Within ±3 minutes of schedule (configurable in `examples/analyze_delays.py`). |

Mobiett “5 dk” style messages are **predictions**, not delay versus the published timetable.

## Data store

All static cache and observation data live in one SQLite file:

**`cache/iett.sqlite`** (gitignored via `cache/*.sqlite`)

| Area | Tables |
|------|--------|
| Static / API cache | `stops`, `lines`, `kv_cache`, `sync_meta` |
| Live observations | `vehicle_polls`, `stop_passage_events` |

The observation logger does not use separate files; it appends to the same database the web app and examples use.

## Observation schema

### `vehicle_polls`

One row per vehicle per line per poll (audit trail).

| Column | Type | Source |
|--------|------|--------|
| `polled_at` | TEXT (ISO8601) | Wall clock when the poll started |
| `line_code` | TEXT | CLI line, e.g. `15B` |
| `vehicle_id` | TEXT | `kapino` |
| `avl_time` | TEXT | `son_konum_zamani` |
| `nearest_stop` | INTEGER | `yakinDurakKodu` |
| `lat`, `lon` | REAL | `enlem`, `boylam` |
| `route_code` | TEXT | `guzergahkodu` |
| `direction_label` | TEXT | `yon` (free text) |
| `payload` | TEXT | Full JSON row |

Indexes: `(line_code, polled_at)`, `(vehicle_id, polled_at)`.

### `stop_passage_events`

Derived event: bus **reached** stop X at time T (nearest-stop code changed).

| Column | Type | Notes |
|--------|------|--------|
| `detected_at` | TEXT | `polled_at` of the poll where the change was seen |
| `line_code` | TEXT | |
| `vehicle_id` | TEXT | |
| `stop_code` | INTEGER | New `yakinDurakKodu` |
| `prev_stop_code` | INTEGER | Previous nearest stop |
| `stop_seq` | INTEGER | From `line_stops` when direction is known |
| `direction` | TEXT | `D` / `G` from `guzergahkodu` when parseable |
| `avl_time` | TEXT | Vehicle AVL timestamp at detection |
| `source` | TEXT | `yakin_durak_change` |

Unique: `(vehicle_id, stop_code, detected_at)`.

## Parallel observation logger

Run in a **second terminal** alongside the web app or other work. It polls each configured line once per minute (`GetHatOtoKonum_json`), writes `vehicle_polls`, and emits `stop_passage_events` when `yakinDurakKodu` changes.

```bash
# By line list
python examples/log_lines.py --lines 15B 19F --interval 60 --until 2026-05-18T22:00

# Or from observation_lines.txt (one code per line, # comments allowed)
python examples/log_lines.py --duration 4h
```

Options:

| Flag | Purpose |
|------|---------|
| `--lines` | Line codes to watch |
| `--lines-file` | Default `observation_lines.txt` in project root |
| `--interval` | Seconds between rounds (default 60) |
| `--until` | Stop at local ISO datetime |
| `--duration` | Run for a span (`4h`, `90m`, …) |
| `-v` | Debug logging |

On startup the logger prefetches `get_line_stops()` for each line so `stop_seq` can be filled on events.

**Error handling:** one line failing does not stop others. Rows are still stored when AVL is stale; analysis flags `stale_avl` when `polled_at − avl_time > 5` minutes.

**Not in v1:** delay calculation in the hot path, GTFS import, web UI for observations.

## Offline delay analysis

After collecting passages:

```bash
python examples/analyze_delays.py --line 15B --format table
python examples/analyze_delays.py --since 2026-05-18T08:00 --format json
python examples/analyze_delays.py --format csv > delays.csv
```

The script:

1. Reads `stop_passage_events` from SQLite.
2. Loads schedule from `kv_cache` / API (`get_line_schedule`).
3. Assigns each observation to the latest terminal `DT` trip at or before the event.
4. Estimates scheduled time at the stop: exact `DT` at terminals; elsewhere `trip_departure + (stop_seq − 1) × minutes_per_stop` (median headway–based default).

Use `--service-type` to filter `SSERVISTIPI`, `--minutes-per-stop` to override interpolation, `--refresh-schedule` to bypass schedule TTL.

## Limitations

| Topic | Limitation |
|-------|------------|
| **Nearest stop** | `yakinDurakKodu` is “closest” stop, not a confirmed arrival; GPS error and dwell between polls add noise. |
| **Poll interval** | 60 s polling can miss short stops or record a stop late. |
| **Schedule** | Phase 1 uses terminal departures only, not per-stop GTFS times. |
| **Trip matching** | Heuristic “last departure before event”; wrong trip assignment possible near layovers. |
| **Direction** | Parsed from `guzergahkodu` (`15B_G_D0` → `G`); missing on some AVL rows. |
| **Day type** | `SGUNTIPI` (C / I / P) is line-specific; analysis prefers `C` when present. |
| **Stale AVL** | Flagged in output; not dropped automatically. |

## Phase 2 (GTFS)

Import GTFS `stop_times` into SQLite (or join an external file), match `stop_code`, and set `schedule_source = gtfs_stop_time` in analysis output. Logger schema stays unchanged.

## Related code

| File | Role |
|------|------|
| `iett/store.py` | Schema + `insert_vehicle_polls`, `insert_stop_passage`, `fetch_passages` |
| `iett/observations.py` | `ObservationLogger` polling loop |
| `examples/log_lines.py` | CLI entrypoint |
| `examples/analyze_delays.py` | Delay table from passages + schedule |
