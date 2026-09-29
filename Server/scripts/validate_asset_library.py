"""Validate manifests and Unity dependencies in the external asset library."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_service import validate_asset_library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library-root", default="")
    args = parser.parse_args()

    kwargs = {}
    if args.library_root:
        kwargs["library_root"] = args.library_root

    result = validate_asset_library(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
