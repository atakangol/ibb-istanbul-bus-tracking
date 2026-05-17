"""Show posted departure times for a line (SQLite cache, one week TTL)."""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Posted schedule for an İETT line")
    parser.add_argument("line", nargs="?", default="15B", help="Line code")
    parser.add_argument("--limit", type=int, default=12, help="Rows to print per group")
    parser.add_argument("--refresh", action="store_true", help="Ignore cache and refetch")
    args = parser.parse_args()

    rows = IettClient().get_line_schedule(args.line, force_refresh=args.refresh)
    by_key: dict[tuple[str, str, str], list] = {}
    for row in rows:
        key = (row.get("SYON", "?"), row.get("SGUNTIPI", "?"), row.get("SSERVISTIPI", "?"))
        by_key.setdefault(key, []).append(row)

    print(f"Line {args.line}: {len(rows)} departures")
    for (direction, day_type, service_type), group in sorted(by_key.items()):
        print(f"\nDirection {direction}, day {day_type}, service {service_type} ({len(group)} trips)")
        sample = [
            {
                "time": r.get("DT"),
                "route": r.get("SGUZERAH"),
                "sign": r.get("GUZERGAH_ISARETI"),
            }
            for r in sorted(group, key=lambda r: r.get("DT", ""))[: args.limit]
        ]
        print(json.dumps(sample, indent=2, ensure_ascii=False))
        if len(group) > args.limit:
            print(f"… {len(group) - args.limit} more")


if __name__ == "__main__":
    main()
