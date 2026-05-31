"""Copy observation rows from the Pi SQLite file into cache/iett.sqlite."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PI_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PI_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from iett.store import DEFAULT_DB_PATH, IettStore

DEFAULT_PI_DB = PI_ROOT / "data" / "iett_pi.sqlite"

POLL_COLUMNS = (
    "polled_at",
    "line_code",
    "vehicle_id",
    "avl_time",
    "nearest_stop",
    "lat",
    "lon",
    "route_code",
    "direction_label",
    "payload",
)

PASSAGE_COLUMNS = (
    "detected_at",
    "line_code",
    "vehicle_id",
    "stop_code",
    "prev_stop_code",
    "stop_seq",
    "direction",
    "avl_time",
    "source",
)


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, table: str) -> int:
    if not _table_exists(conn, table):
        return 0
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0]) if row else 0


def merge(pi_db: Path, main_db: Path) -> tuple[int, int, int, int]:
    """Returns (polls_copied, polls_skipped, passages_copied, passages_skipped)."""
    if not pi_db.is_file():
        raise FileNotFoundError(f"Pi database not found: {pi_db}")

    IettStore(db_path=main_db)

    pi_conn = sqlite3.connect(pi_db)
    main_conn = sqlite3.connect(main_db)

    polls_copied = polls_skipped = 0
    passages_copied = passages_skipped = 0

    try:
        if _table_exists(pi_conn, "vehicle_polls"):
            cols = ", ".join(POLL_COLUMNS)
            placeholders = ", ".join("?" for _ in POLL_COLUMNS)
            rows = pi_conn.execute(
                f"SELECT {cols} FROM vehicle_polls ORDER BY id"
            ).fetchall()
            for row in rows:
                try:
                    main_conn.execute(
                        f"""
                        INSERT INTO vehicle_polls ({cols})
                        VALUES ({placeholders})
                        """,
                        row,
                    )
                    polls_copied += 1
                except sqlite3.Error:
                    polls_skipped += 1

        if _table_exists(pi_conn, "stop_passage_events"):
            cols = ", ".join(PASSAGE_COLUMNS)
            placeholders = ", ".join("?" for _ in PASSAGE_COLUMNS)
            rows = pi_conn.execute(
                f"SELECT {cols} FROM stop_passage_events ORDER BY id"
            ).fetchall()
            for row in rows:
                cursor = main_conn.execute(
                    f"""
                    INSERT OR IGNORE INTO stop_passage_events ({cols})
                    VALUES ({placeholders})
                    """,
                    row,
                )
                if cursor.rowcount:
                    passages_copied += 1
                else:
                    passages_skipped += 1

        main_conn.commit()
    finally:
        pi_conn.close()
        main_conn.close()

    return polls_copied, polls_skipped, passages_copied, passages_skipped


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge Pi observation tables into the main project SQLite DB"
    )
    parser.add_argument(
        "--pi-db",
        type=Path,
        default=DEFAULT_PI_DB,
        help="Source Pi SQLite file",
    )
    parser.add_argument(
        "--main-db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Destination main SQLite file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show row counts only; do not copy",
    )
    args = parser.parse_args()

    if not args.pi_db.is_file():
        print(f"Pi database not found: {args.pi_db}")
        sys.exit(1)

    pi_conn = sqlite3.connect(args.pi_db)
    pi_polls = _count(pi_conn, "vehicle_polls")
    pi_passages = _count(pi_conn, "stop_passage_events")
    pi_conn.close()

    print(f"Pi DB:   {args.pi_db.resolve()}")
    print(f"  vehicle_polls:       {pi_polls}")
    print(f"  stop_passage_events: {pi_passages}")
    print(f"Main DB: {args.main_db.resolve()}")

    if args.dry_run:
        return

    copied = merge(args.pi_db, args.main_db)
    print(
        f"\nMerged: {copied[0]} polls copied ({copied[1]} skipped), "
        f"{copied[2]} passages copied ({copied[3]} duplicates skipped)"
    )
    print("Run examples/analyze_delays.py on the main DB when ready.")


if __name__ == "__main__":
    main()
