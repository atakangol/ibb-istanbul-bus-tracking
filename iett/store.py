"""SQLite cache and stop search for İETT static data."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "cache" / "iett.sqlite"

CACHE_TTL = timedelta(weeks=2)
SCHEDULE_CACHE_TTL = timedelta(weeks=1)

STOPS_ALL_DATASET = "stops_all"
LINES_ALL_DATASET = "lines_all"

LEGACY_STOPS_DIR = PROJECT_ROOT / "cache" / "stops"
LEGACY_LINES_DIR = PROJECT_ROOT / "cache" / "lines"
LEGACY_SCHEDULES_DIRS = (
    PROJECT_ROOT / "cache" / "line_schedules",
    PROJECT_ROOT / "line_schedules",
)
LINE_STOPS_SUFFIX = "__stops"

_TR_TRANSLATE = str.maketrans(
    {
        "ı": "i",
        "İ": "i",
        "ş": "s",
        "Ş": "s",
        "ğ": "g",
        "Ğ": "g",
        "ü": "u",
        "Ü": "u",
        "ö": "o",
        "Ö": "o",
        "ç": "c",
        "Ç": "c",
    }
)

_POINT_RE = re.compile(
    r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)",
    re.IGNORECASE,
)
_MAHALLE_RE = re.compile(r"(.+?)\s*MAHALLE", re.IGNORECASE)


def normalize_text(value: str) -> str:
    return value.translate(_TR_TRANSLATE).casefold().strip()


def _extract_mahalle_from_name(name: str) -> str:
    """Pull mahalle fragment from stop names like 'INÖNÜ MAHALLESİ'."""
    match = _MAHALLE_RE.search(name)
    if not match:
        return ""
    return match.group(0).strip()


def _mahalle_search_text(name: str, ilce: str) -> str:
    """Mahalle search text: ilçe (ILCEADI) plus mahalle wording from the stop name."""
    parts: list[str] = []
    if ilce.strip():
        parts.append(ilce.strip())
    fragment = _extract_mahalle_from_name(name)
    if fragment:
        parts.append(fragment)
    return " ".join(parts)


def _semt_search_text(syon: str) -> str:
    """Semt search text: SYON holds area names (Levent, Maslak, …)."""
    return syon.strip()


def _field_match_score(needle: str, haystack: str) -> float:
    """0.0 = no match, 1.0 = exact; higher = better overlap (prefix > substring)."""
    if not needle or not haystack:
        return 0.0
    if haystack == needle:
        return 1.0
    if haystack.startswith(needle):
        return 0.85 + 0.15 * (len(needle) / len(haystack))
    if needle in haystack:
        return 0.55 * (len(needle) / len(haystack))
    for token in haystack.split():
        if token == needle:
            return 0.8
        if token.startswith(needle):
            return 0.65 + 0.2 * (len(needle) / len(token))
    return 0.0


def _stop_search_score(
    needle: str,
    *,
    code: int,
    name_norm: str,
    mahalle_norm: str,
    semt_norm: str,
) -> float:
    if needle.isdigit() and code == int(needle):
        return 10_000.0
    name = _field_match_score(needle, name_norm)
    semt = _field_match_score(needle, semt_norm)
    mahalle = _field_match_score(needle, mahalle_norm)
    if name == 0.0 and semt == 0.0 and mahalle == 0.0:
        return 0.0
    # Stop name first, then semt (SYON), then mahalle (ilçe + mahalle in name).
    return name * 1_000 + semt * 120 + mahalle * 100


def _parse_point(coord: str | None) -> tuple[float | None, float | None]:
    if not coord:
        return None, None
    match = _POINT_RE.search(coord)
    if not match:
        return None, None
    return float(match.group(1)), float(match.group(2))


def _line_code(row: dict[str, Any]) -> str | None:
    for key in ("SHATKODU", "HATKODU", "KOD", "HatKodu", "hat_kodu"):
        raw = row.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


def _line_name(row: dict[str, Any]) -> str:
    for key in ("SHATADI", "HATADI", "ADI", "HAT_ADI", "HatAdi", "hat_adi"):
        raw = row.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return ""


def _line_search_score(
    needle: str,
    *,
    code: str,
    code_norm: str,
    name_norm: str,
) -> float:
    if needle == code_norm:
        return 10_000.0
    code_score = _field_match_score(needle, code_norm)
    name_score = _field_match_score(needle, name_norm)
    if code_score == 0.0 and name_score == 0.0:
        return 0.0
    return code_score * 1_000 + name_score * 100


def _stop_code(row: dict[str, Any]) -> int | None:
    raw = row.get("SDURAKKODU")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class IettStore:
    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        ttl: timedelta = CACHE_TTL,
        schedule_ttl: timedelta = SCHEDULE_CACHE_TTL,
    ) -> None:
        self.db_path = db_path
        self.ttl = ttl
        self.schedule_ttl = schedule_ttl
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self.import_legacy_json_caches()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_meta (
                    dataset TEXT PRIMARY KEY,
                    fetched_at TEXT NOT NULL,
                    ttl_days REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS stops (
                    code INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    district TEXT,
                    direction TEXT,
                    lon REAL,
                    lat REAL,
                    name_norm TEXT NOT NULL,
                    district_norm TEXT NOT NULL,
                    direction_norm TEXT NOT NULL,
                    mahalle_norm TEXT NOT NULL DEFAULT '',
                    semt_norm TEXT NOT NULL DEFAULT '',
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_stops_name_norm ON stops(name_norm);
                CREATE INDEX IF NOT EXISTS idx_stops_district_norm ON stops(district_norm);
                CREATE INDEX IF NOT EXISTS idx_stops_direction_norm ON stops(direction_norm);

                CREATE TABLE IF NOT EXISTS lines (
                    code TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    code_norm TEXT NOT NULL,
                    name_norm TEXT NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_lines_code_norm ON lines(code_norm);
                CREATE INDEX IF NOT EXISTS idx_lines_name_norm ON lines(name_norm);

                CREATE TABLE IF NOT EXISTS kv_cache (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vehicle_polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    polled_at TEXT NOT NULL,
                    line_code TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    avl_time TEXT,
                    nearest_stop INTEGER,
                    lat REAL,
                    lon REAL,
                    route_code TEXT,
                    direction_label TEXT,
                    payload TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_vehicle_polls_line_polled
                    ON vehicle_polls(line_code, polled_at);
                CREATE INDEX IF NOT EXISTS idx_vehicle_polls_vehicle_polled
                    ON vehicle_polls(vehicle_id, polled_at);

                CREATE TABLE IF NOT EXISTS stop_passage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detected_at TEXT NOT NULL,
                    line_code TEXT NOT NULL,
                    vehicle_id TEXT NOT NULL,
                    stop_code INTEGER NOT NULL,
                    prev_stop_code INTEGER,
                    stop_seq INTEGER,
                    direction TEXT,
                    avl_time TEXT,
                    source TEXT NOT NULL,
                    UNIQUE(vehicle_id, stop_code, detected_at)
                );

                CREATE INDEX IF NOT EXISTS idx_passages_line_detected
                    ON stop_passage_events(line_code, detected_at);
                CREATE INDEX IF NOT EXISTS idx_passages_vehicle_detected
                    ON stop_passage_events(vehicle_id, detected_at);
                """
            )
            self._migrate_locality_columns(conn)

    def _migrate_locality_columns(self, conn: sqlite3.Connection) -> None:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(stops)")}
        if "mahalle_norm" not in columns:
            conn.execute("ALTER TABLE stops ADD COLUMN mahalle_norm TEXT NOT NULL DEFAULT ''")
            conn.execute("ALTER TABLE stops ADD COLUMN semt_norm TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stops_mahalle_norm ON stops(mahalle_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_stops_semt_norm ON stops(semt_norm)")
        if "mahalle_norm" not in columns or conn.execute(
            "SELECT 1 FROM stops WHERE district != '' AND mahalle_norm = '' LIMIT 1"
        ).fetchone():
            self._reindex_locality_fields(conn)

    def _reindex_locality_fields(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute("SELECT code, name, district, direction FROM stops").fetchall()
        if not rows:
            return
        updates: list[tuple[str, str, str, str, int]] = []
        for row in rows:
            mahalle = normalize_text(_mahalle_search_text(row["name"], row["district"] or ""))
            semt = normalize_text(_semt_search_text(row["direction"] or ""))
            updates.append((mahalle, semt, mahalle, semt, int(row["code"])))
        conn.executemany(
            """
            UPDATE stops
            SET mahalle_norm = ?, semt_norm = ?,
                district_norm = ?, direction_norm = ?
            WHERE code = ?
            """,
            updates,
        )

    def is_sync_fresh(self, dataset: str, *, ttl: timedelta | None = None) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at, ttl_days FROM sync_meta WHERE dataset = ?",
                (dataset,),
            ).fetchone()
        if row is None:
            return False
        fetched_at = datetime.fromisoformat(row["fetched_at"])
        effective_ttl = ttl or timedelta(days=row["ttl_days"])
        return datetime.now() - fetched_at < effective_ttl

    def touch_sync(
        self,
        dataset: str,
        *,
        ttl: timedelta | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        effective_ttl = ttl or self._ttl_for_dataset(dataset)
        when = fetched_at or datetime.now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_meta (dataset, fetched_at, ttl_days)
                VALUES (?, ?, ?)
                ON CONFLICT(dataset) DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    ttl_days = excluded.ttl_days
                """,
                (dataset, when.isoformat(), effective_ttl.total_seconds() / 86400),
            )

    def invalidate_sync(self, dataset: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM sync_meta WHERE dataset = ?", (dataset,))

    def stops_index_fresh(self) -> bool:
        return self.is_sync_fresh(STOPS_ALL_DATASET)

    def stops_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM stops").fetchone()
        return int(row["n"]) if row else 0

    def lines_index_fresh(self) -> bool:
        return self.is_sync_fresh(LINES_ALL_DATASET)

    def lines_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM lines").fetchone()
        return int(row["n"]) if row else 0

    def lines_missing_names(self) -> bool:
        """True when the index exists but names were not populated (legacy rows)."""
        if self.lines_count() == 0:
            return False
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM lines WHERE name != '' LIMIT 1").fetchone()
        return row is None

    def upsert_lines(self, rows: list[dict[str, Any]]) -> None:
        records: list[tuple[Any, ...]] = []
        for row in rows:
            code = _line_code(row)
            if not code:
                continue
            name = _line_name(row)
            records.append(
                (
                    code,
                    name,
                    normalize_text(code),
                    normalize_text(name),
                    json.dumps(row, ensure_ascii=False),
                )
            )
        if not records:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO lines (code, name, code_norm, name_norm, payload)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    code_norm = excluded.code_norm,
                    name_norm = excluded.name_norm,
                    payload = excluded.payload
                """,
                records,
            )

    def search_lines(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        needle = normalize_text(query)
        if not needle:
            return []

        pattern = f"%{needle}%"
        fetch_limit = min(max(limit * 25, 100), 500)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT code, code_norm, name_norm, payload
                FROM lines
                WHERE code_norm LIKE ? OR name_norm LIKE ?
                LIMIT ?
                """,
                (pattern, pattern, fetch_limit),
            ).fetchall()

        scored: list[tuple[float, str]] = []
        for row in rows:
            score = _line_search_score(
                needle,
                code=row["code"],
                code_norm=row["code_norm"],
                name_norm=row["name_norm"],
            )
            if score > 0:
                scored.append((score, row["payload"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [json.loads(payload) for _, payload in scored[:limit]]

    def get_line_by_code(self, line_code: str) -> dict[str, Any] | None:
        code = line_code.strip()
        if not code:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM lines WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def upsert_stops(self, rows: list[dict[str, Any]]) -> None:
        records: list[tuple[Any, ...]] = []
        for row in rows:
            code = _stop_code(row)
            if code is None:
                continue
            name = str(row.get("SDURAKADI") or "")
            district = str(row.get("ILCEADI") or "")
            direction = str(row.get("SYON") or "")
            lon, lat = _parse_point(str(row.get("KOORDINAT") or ""))
            mahalle_norm = normalize_text(_mahalle_search_text(name, district))
            semt_norm = normalize_text(_semt_search_text(direction))
            records.append(
                (
                    code,
                    name,
                    district,
                    direction,
                    lon,
                    lat,
                    normalize_text(name),
                    mahalle_norm,
                    semt_norm,
                    mahalle_norm,
                    semt_norm,
                    json.dumps(row, ensure_ascii=False),
                )
            )
        if not records:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO stops (
                    code, name, district, direction, lon, lat,
                    name_norm, district_norm, direction_norm,
                    mahalle_norm, semt_norm, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET
                    name = excluded.name,
                    district = excluded.district,
                    direction = excluded.direction,
                    lon = excluded.lon,
                    lat = excluded.lat,
                    name_norm = excluded.name_norm,
                    district_norm = excluded.district_norm,
                    direction_norm = excluded.direction_norm,
                    mahalle_norm = excluded.mahalle_norm,
                    semt_norm = excluded.semt_norm,
                    payload = excluded.payload
                """,
                records,
            )

    def get_stop_by_code(self, stop_code: str) -> dict[str, Any] | None:
        try:
            code = int(stop_code.strip())
        except ValueError:
            return None
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM stops WHERE code = ?", (code,)).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])

    def get_all_stops(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM stops ORDER BY code").fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def search_stops(self, query: str, *, limit: int = 20) -> list[dict[str, Any]]:
        needle = normalize_text(query)
        if not needle:
            return []

        pattern = f"%{needle}%"
        fetch_limit = min(max(limit * 25, 100), 500)
        params: list[Any] = [pattern, pattern, pattern]
        sql = """
            SELECT code, name_norm, mahalle_norm, semt_norm, payload
            FROM stops
            WHERE name_norm LIKE ? OR mahalle_norm LIKE ? OR semt_norm LIKE ?
            LIMIT ?
        """
        params.append(fetch_limit)
        if needle.isdigit():
            sql = """
                SELECT code, name_norm, mahalle_norm, semt_norm, payload
                FROM stops
                WHERE code = ? OR name_norm LIKE ? OR mahalle_norm LIKE ? OR semt_norm LIKE ?
                LIMIT ?
            """
            params = [int(needle), pattern, pattern, pattern, fetch_limit]

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        scored: list[tuple[float, str]] = []
        for row in rows:
            score = _stop_search_score(
                needle,
                code=int(row["code"]),
                name_norm=row["name_norm"],
                mahalle_norm=row["mahalle_norm"],
                semt_norm=row["semt_norm"],
            )
            if score > 0:
                scored.append((score, row["payload"]))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [json.loads(payload) for _, payload in scored[:limit]]

    def _dataset_key(self, kind: str, code: str) -> str:
        text = code.strip() or "all"
        return f"{kind}:{text}"

    def _ttl_for_dataset(self, dataset: str) -> timedelta:
        if dataset.startswith("schedule:"):
            return self.schedule_ttl
        return self.ttl

    def get_kv(self, kind: str, code: str) -> list[dict[str, Any]] | None:
        dataset = self._dataset_key(kind, code)
        if not self.is_sync_fresh(dataset, ttl=self._ttl_for_dataset(dataset)):
            return None
        key = dataset
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM kv_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload"])
        if not isinstance(payload, list):
            raise ValueError(f"KV cache is not a list: {key}")
        return payload

    def set_kv(
        self,
        kind: str,
        code: str,
        data: list[dict[str, Any]],
        *,
        fetched_at: datetime | None = None,
    ) -> None:
        dataset = self._dataset_key(kind, code)
        key = dataset
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO kv_cache (key, payload) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET payload = excluded.payload
                """,
                (key, json.dumps(data, ensure_ascii=False)),
            )
        self.touch_sync(dataset, ttl=self._ttl_for_dataset(dataset), fetched_at=fetched_at)

    def import_legacy_json_caches(self) -> int:
        """One-time import of pre-SQLite JSON cache files (preserves file mtime as TTL)."""
        imported = 0
        imported += self._import_legacy_stop_files()
        imported += self._import_legacy_line_files()
        imported += self._import_legacy_line_stop_files()
        imported += self._import_legacy_schedule_files()
        return imported

    def _import_legacy_stop_files(self) -> int:
        if not LEGACY_STOPS_DIR.is_dir():
            return 0
        count = 0
        for path in LEGACY_STOPS_DIR.glob("*.json"):
            if path.name == "all.json":
                continue
            try:
                rows = self._read_json_list(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            if not rows:
                continue
            self.upsert_stops(rows)
            count += 1
        all_path = LEGACY_STOPS_DIR / "all.json"
        if all_path.is_file() and self.stops_count() == 0:
            try:
                rows = self._read_json_list(all_path)
                self.upsert_stops(rows)
                mtime = datetime.fromtimestamp(all_path.stat().st_mtime)
                if self._is_fresh_mtime(mtime, self.ttl):
                    self.touch_sync(STOPS_ALL_DATASET, fetched_at=mtime)
                count += 1
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        return count

    def _import_legacy_line_files(self) -> int:
        if not LEGACY_LINES_DIR.is_dir():
            return 0
        all_path = LEGACY_LINES_DIR / "all.json"
        if all_path.is_file() and self.lines_count() == 0:
            try:
                rows = self._read_json_list(all_path)
                self.upsert_lines(rows)
                mtime = datetime.fromtimestamp(all_path.stat().st_mtime)
                if self._is_fresh_mtime(mtime, self.ttl):
                    self.touch_sync(LINES_ALL_DATASET, fetched_at=mtime)
                return 1
            except (OSError, json.JSONDecodeError, ValueError):
                pass
        cached = self.get_kv("line", "")
        if cached and self.lines_count() == 0:
            self.upsert_lines(cached)
            return len(cached)
        return 0

    def _import_legacy_line_stop_files(self) -> int:
        if not LEGACY_LINES_DIR.is_dir():
            return 0
        count = 0
        for path in LEGACY_LINES_DIR.glob("*.json"):
            stem = path.stem
            if not stem.endswith(LINE_STOPS_SUFFIX):
                continue
            line_code = stem[: -len(LINE_STOPS_SUFFIX)]
            if self.get_kv("line_stops", line_code) is not None:
                continue
            try:
                rows = self._read_json_list(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if not self._is_fresh_mtime(mtime, self.ttl):
                continue
            self.set_kv("line_stops", line_code, rows, fetched_at=mtime)
            count += 1
        for path in LEGACY_LINES_DIR.glob("*.json"):
            stem = path.stem
            if stem.endswith(LINE_STOPS_SUFFIX):
                continue
            if self.get_kv("line", stem) is not None:
                continue
            try:
                rows = self._read_json_list(path)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            if not self._is_fresh_mtime(mtime, self.ttl):
                continue
            self.set_kv("line", stem, rows, fetched_at=mtime)
            count += 1
        return count

    def _import_legacy_schedule_files(self) -> int:
        count = 0
        seen: set[str] = set()
        for directory in LEGACY_SCHEDULES_DIRS:
            if not directory.is_dir():
                continue
            for path in directory.glob("*.json"):
                line_code = path.stem
                if line_code in seen:
                    continue
                seen.add(line_code)
                if self.get_kv("schedule", line_code) is not None:
                    continue
                try:
                    rows = self._read_json_list(path)
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
                if not self._is_fresh_mtime(mtime, self.schedule_ttl):
                    continue
                self.set_kv("schedule", line_code, rows, fetched_at=mtime)
                count += 1
        return count

    @staticmethod
    def _read_json_list(path: Path) -> list[dict[str, Any]]:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError(f"Cache file is not a list: {path}")
        return payload

    @staticmethod
    def _is_fresh_mtime(fetched_at: datetime, ttl: timedelta) -> bool:
        return datetime.now() - fetched_at < ttl

    def invalidate_kv(self, kind: str, code: str) -> None:
        dataset = self._dataset_key(kind, code)
        key = dataset
        with self._connect() as conn:
            conn.execute("DELETE FROM kv_cache WHERE key = ?", (key,))
        self.invalidate_sync(dataset)

    def insert_vehicle_polls(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        records = [
            (
                row["polled_at"],
                row["line_code"],
                row["vehicle_id"],
                row.get("avl_time"),
                row.get("nearest_stop"),
                row.get("lat"),
                row.get("lon"),
                row.get("route_code"),
                row.get("direction_label"),
                row["payload"],
            )
            for row in rows
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO vehicle_polls (
                    polled_at, line_code, vehicle_id, avl_time, nearest_stop,
                    lat, lon, route_code, direction_label, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                records,
            )
        return len(records)

    def insert_stop_passage(self, event: dict[str, Any]) -> bool:
        """Insert a passage event. Returns False if duplicate (unique constraint)."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO stop_passage_events (
                    detected_at, line_code, vehicle_id, stop_code, prev_stop_code,
                    stop_seq, direction, avl_time, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["detected_at"],
                    event["line_code"],
                    event["vehicle_id"],
                    event["stop_code"],
                    event.get("prev_stop_code"),
                    event.get("stop_seq"),
                    event.get("direction"),
                    event.get("avl_time"),
                    event.get("source", "yakin_durak_change"),
                ),
            )
            return cursor.rowcount > 0

    def fetch_passages(
        self,
        *,
        line_code: str | None = None,
        vehicle_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if line_code:
            clauses.append("line_code = ?")
            params.append(line_code.strip())
        if vehicle_id:
            clauses.append("vehicle_id = ?")
            params.append(vehicle_id.strip())
        if since:
            clauses.append("detected_at >= ?")
            params.append(since)
        if until:
            clauses.append("detected_at <= ?")
            params.append(until)

        sql = "SELECT * FROM stop_passage_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY detected_at"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def count_vehicle_polls(self, *, line_code: str | None = None) -> int:
        with self._connect() as conn:
            if line_code:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM vehicle_polls WHERE line_code = ?",
                    (line_code.strip(),),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM vehicle_polls").fetchone()
        return int(row["n"]) if row else 0

    def count_passages(self, *, line_code: str | None = None) -> int:
        with self._connect() as conn:
            if line_code:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM stop_passage_events WHERE line_code = ?",
                    (line_code.strip(),),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM stop_passage_events").fetchone()
        return int(row["n"]) if row else 0
