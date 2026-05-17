"""Look up one stop by code."""

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from iett import IettClient


def main() -> None:
    parser = argparse.ArgumentParser(description="İETT stop lookup")
    parser.add_argument("stop_code", default="113252", nargs="?", help="Stop code")
    args = parser.parse_args()

    rows = IettClient().get_stop(args.stop_code)
    print(json.dumps(rows, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
