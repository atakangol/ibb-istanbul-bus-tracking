"""Raspberry Pi observation logger — separate SQLite, runs until stopped."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PI_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PI_ROOT.parent
sys.path.insert(0, str(PROJECT_ROOT))

from iett.client import IettClient
from iett.observations import ObservationLogger
from iett.store import IettStore

DEFAULT_DB = PI_ROOT / "data" / "iett_pi.sqlite"
DEFAULT_LINES_FILE = PI_ROOT / "observation_lines.txt"


def _load_lines(args: argparse.Namespace) -> list[str]:
    if args.lines:
        return args.lines
    if args.lines_file.is_file():
        lines = [
            line.strip()
            for line in args.lines_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if lines:
            return lines
    raise SystemExit(
        f"Provide --lines or add line codes to {args.lines_file}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Pi logger: poll İETT lines every minute into a dedicated SQLite file. "
            "Runs until Ctrl+C or SIGTERM."
        )
    )
    parser.add_argument(
        "--lines",
        nargs="+",
        help="Line codes to observe (e.g. 15B 19F)",
    )
    parser.add_argument(
        "--lines-file",
        type=Path,
        default=DEFAULT_LINES_FILE,
        help=f"Lines list file (default: {DEFAULT_LINES_FILE.name})",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB,
        help=f"SQLite path for Pi observations (default: {DEFAULT_DB.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between poll rounds (default: 60)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("pi.logger")

    args.db.parent.mkdir(parents=True, exist_ok=True)
    store = IettStore(db_path=args.db)
    client = IettClient(store=store)
    lines = _load_lines(args)

    log.info("Pi DB: %s", args.db.resolve())
    log.info("Lines: %s", ", ".join(lines))
    log.info("Interval: %.0fs — press Ctrl+C to stop", args.interval)

    observer = ObservationLogger(
        lines,
        client=client,
        store=store,
        interval_seconds=args.interval,
    )
    try:
        observer.run_until(deadline=None)
    except KeyboardInterrupt:
        log.info("Stopped.")
        print("\nStopped.")


if __name__ == "__main__":
    main()
