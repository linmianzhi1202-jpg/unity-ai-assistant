"""Preview or apply semantic placement profiles to existing asset manifests."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_service import (
    DEFAULT_LIBRARY_ROOT,
    build_placement_profile,
)


def _manifest_paths(root: Path) -> list[Path]:
    paths = set(root.rglob("asset.json"))
    paths.update(root.rglob("*.asset.json"))
    return sorted(paths, key=lambda path: path.as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--library-root", default=str(DEFAULT_LIBRARY_ROOT))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    root = Path(args.library_root).resolve()
    changed: list[dict[str, str]] = []
    unchanged = 0
    roles: Counter[str] = Counter()
    surfaces: Counter[str] = Counter()
    for path in _manifest_paths(root):
        data = json.loads(path.read_text(encoding="utf-8"))
        current = data.get("placementProfile", {})
        profile = build_placement_profile(data, current)
        roles[str(profile.get("placementRole", ""))] += 1
        if profile.get("surfaceType"):
            surfaces[str(profile["surfaceType"])] += 1
        updated = dict(data)
        updated["schemaVersion"] = max(3, int(data.get("schemaVersion", 1) or 1))
        updated["placementProfile"] = profile
        if updated == data:
            unchanged += 1
            continue
        changed.append(
            {
                "asset_id": str(data.get("id", "")),
                "path": str(path),
                "placement_role": str(profile.get("placementRole", "")),
                "surface_type": str(profile.get("surfaceType", "")),
            }
        )
        if args.apply:
            temp = path.with_suffix(path.suffix + ".tmp")
            temp.write_text(
                json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp.replace(path)

    report = {
        "success": True,
        "status": "applied" if args.apply else "preview",
        "library_root": str(root),
        "manifest_count": len(changed) + unchanged,
        "changed_count": len(changed),
        "unchanged_count": unchanged,
        "role_counts": dict(sorted(roles.items())),
        "surface_counts": dict(sorted(surfaces.items())),
        "changes": changed,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
