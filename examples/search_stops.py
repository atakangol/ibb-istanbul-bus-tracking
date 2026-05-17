"""Search stops by name, mahalle, or semt."""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Search İETT stops by text")
    parser.add_argument("query", help="Stop name, mahalle, semt (SYON), or stop code")
    parser.add_argument("--limit", type=int, default=20, help="Max results")
    parser.add_argument("--refresh", action="store_true", help="Re-download all stops from API")
    parser.add_argument("--json", action="store_true", help="Print raw JSON")
    args = parser.parse_args()

    client = IettClient()
    rows = client.search_stops(args.query, limit=args.limit, force_refresh=args.refresh)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
        return

    if not rows:
        print("No matches.")
        return

    for row in rows:
        code = row.get("SDURAKKODU", "")
        name = row.get("SDURAKADI", "")
        mahalle = row.get("ILCEADI", "")
        semt = row.get("SYON", "")
        print(f"{code:>8}  {name:<24}  {mahalle:<16}  {semt}")


if __name__ == "__main__":
    main()
