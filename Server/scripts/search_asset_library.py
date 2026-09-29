"""Search the external Unity asset library from a terminal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_service import search_asset_library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--category", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--index-dir", default="")
    args = parser.parse_args()

    kwargs = {
        "query": args.query,
        "category": args.category,
        "top_k": args.top_k,
    }
    if args.index_dir:
        kwargs["index_dir"] = args.index_dir
    result = search_asset_library(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
