"""Print live buses on a given line."""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Live İETT vehicles on a line")
    parser.add_argument("line", nargs="?", default="15B", help="Line code, e.g. 15B")
    args = parser.parse_args()

    client = IettClient()
    vehicles = client.get_line_vehicles(args.line)
    print(f"Line {args.line}: {len(vehicles)} vehicles\n")
    print(json.dumps(vehicles[:5], indent=2, ensure_ascii=False))
    if len(vehicles) > 5:
        print(f"\n… and {len(vehicles) - 5} more")


if __name__ == "__main__":
    main()
