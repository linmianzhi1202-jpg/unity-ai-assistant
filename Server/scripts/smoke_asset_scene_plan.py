"""Call the new scene-plan MCP tool against the connected Unity editor."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastmcp import FastMCP
from services.tools.asset_library_tools import register_asset_library_tools


async def run(intent: str) -> None:
    mcp = FastMCP("asset-scene-smoke")
    register_asset_library_tools(mcp)
    result = await mcp.call_tool(
        "preview_asset_scene_plan",
        {"intent": intent, "max_assets": 20},
    )
    payload = getattr(result, "structured_content", None)
    if payload is None:
        payload = result.data if hasattr(result, "data") else str(result)
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("intent")
    args = parser.parse_args()
    asyncio.run(run(args.intent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
