"""Parallel observation logger: poll configured lines every minute."""

from __future__ import annotations

import argparse
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett.observations import ObservationLogger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LINES_FILE = PROJECT_ROOT / "observation_lines.txt"

_DURATION_RE = re.compile(
    r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>h|m|s|hours?|minutes?|seconds?)$",
    re.IGNORECASE,
)


def _parse_until(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid --until datetime: {value}") from exc


def _parse_duration(value: str) -> timedelta:
    match = _DURATION_RE.match(value.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"Invalid --duration: {value}")
    amount = float(match.group("value"))
    unit = match.group("unit").lower()[0]
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "m":
        return timedelta(minutes=amount)
    return timedelta(seconds=amount)


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
    raise SystemExit("Provide --lines or a non-empty observation_lines.txt")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Poll İETT line AVL every minute and log passages to SQLite"
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
        help=f"Optional lines list file (default: {DEFAULT_LINES_FILE.name})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=60.0,
        help="Seconds between poll rounds (default: 60)",
    )
    parser.add_argument(
        "--until",
        type=_parse_until,
        help="Stop at this local datetime (ISO8601, e.g. 2026-05-18T22:00)",
    )
    parser.add_argument(
        "--duration",
        type=_parse_duration,
        help="Run for a duration from now (e.g. 4h, 90m)",
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

    if args.until and args.duration:
        parser.error("Use only one of --until or --duration")

    deadline = args.until
    if args.duration:
        deadline = datetime.now() + args.duration

    lines = _load_lines(args)
    logger = ObservationLogger(lines, interval_seconds=args.interval)
    try:
        logger.run_until(deadline)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
