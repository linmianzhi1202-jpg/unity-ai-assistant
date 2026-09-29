"""Build the dedicated ChromaDB index for external Unity assets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_service import index_asset_library


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--library-root", default="")
    parser.add_argument("--index-dir", default="")
    parser.add_argument(
        "--embedding",
        choices=("local-hash", "bge-m3"),
        default="bge-m3",
        help="local-hash is fast/offline; bge-m3 may download several GB",
    )
    parser.add_argument(
        "--no-shadow",
        action="store_true",
        help="Build directly into the active collection instead of a shadow collection.",
    )
    parser.add_argument(
        "--no-activate",
        action="store_true",
        help="Evaluate the candidate collection without switching the active index.",
    )
    parser.add_argument("--evaluation-limit", type=int, default=50)
    args = parser.parse_args()

    kwargs = {
        "rebuild": args.rebuild,
        "embedding_provider": args.embedding,
        "progress": lambda message: print(message, flush=True),
        "shadow": not args.no_shadow,
        "activate": not args.no_activate,
        "evaluation_limit": max(1, args.evaluation_limit),
    }
    if args.library_root:
        kwargs["library_root"] = args.library_root
    if args.index_dir:
        kwargs["index_dir"] = args.index_dir

    print(
        f"Building Unity asset library with embedding={args.embedding}",
        flush=True,
    )
    if args.embedding == "bge-m3":
        print(
            "Using the local bge-m3 cache when available; no cloud API is used.",
            flush=True,
        )
    result = index_asset_library(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
