"""List ordered stops for a line (both directions, SQLite cache)."""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Stops on an İETT line")
    parser.add_argument("line", nargs="?", default="15B", help="Line code")
    parser.add_argument("--limit", type=int, default=8, help="Rows to print per direction")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and refetch")
    args = parser.parse_args()

    stops = IettClient().get_line_stops(args.line, force_refresh=args.refresh)
    by_direction: dict[str, list] = {}
    for row in stops:
        by_direction.setdefault(row.get("YON", "?"), []).append(row)

    for direction, rows in sorted(by_direction.items()):
        print(f"\nDirection {direction} ({len(rows)} stops)")
        sample = [
            {
                "order": r.get("SIRANO"),
                "code": r.get("DURAKKODU"),
                "name": r.get("DURAKADI"),
                "lat": r.get("YKOORDINATI"),
                "lon": r.get("XKOORDINATI"),
            }
            for r in rows[: args.limit]
        ]
        print(json.dumps(sample, indent=2, ensure_ascii=False))
        if len(rows) > args.limit:
            print(f"… {len(rows) - args.limit} more stops")


if __name__ == "__main__":
    main()
