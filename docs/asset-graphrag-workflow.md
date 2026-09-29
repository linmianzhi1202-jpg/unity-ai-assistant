# Unity Asset Hybrid GraphRAG Workflow

The asset library uses four local layers:

1. ChromaDB hybrid retrieval with `bge-m3`, lexical matching, metadata filters,
   confidence, and optional graph expansion.
2. A deterministic `asset_graph.json` for variants, compatible assets, bundles,
   placement relations, and scene recipes.
3. A centralized `manual_relations.json` overlay for curated cross-bundle
   knowledge and spatial constraints.
4. Unity-side scene analysis and transactional batch placement.

It does not use the Unity API or game-code LightRAG stores.

## Build And Evaluate

Run the full model build yourself so progress remains visible:

```powershell
.\.venv\Scripts\python.exe Server\scripts\index_asset_library.py --rebuild --embedding bge-m3
```

The command builds `unity_asset_library_bge_m3_v2`, evaluates it, and only then
updates `Server/data/asset_library/chroma_db/active_index.json`. The old
collection remains available for rollback.

Run the persistent acceptance benchmark (50 search, 20 relation, and 10 scene
plan cases):

```powershell
.\.venv\Scripts\python.exe Server\scripts\benchmark_asset_library.py
```

Reports are written to
`Server/data/asset_library/benchmark_reports/<timestamp>.json` and
`latest.json`. The command exits nonzero when a quality or latency gate fails.
Use `--no-vector --quick` to validate deterministic reranking without rebuilding
the vector index.

Rebuild the deterministic graph without rebuilding vectors:

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; import sys; sys.path.insert(0, str(Path('Server/src').resolve())); from services.asset_graph_service import build_asset_graph; print(build_asset_graph())"
```

## MCP Flow

Single asset:

1. `search_asset_library` with optional filters and relation expansion.
2. Review confidence and alternatives.
3. `place_asset_from_library` for one confirmed asset request.

Multi-asset scene:

1. `preview_asset_scene_plan(intent=...)`.
2. Review the recipe, roles, selected assets, alternatives, and placements.
3. `apply_asset_scene_plan(plan_id=...)`.
4. Poll `get_task_status(task_id)`.

`apply_asset_scene_plan` verifies that the scene token still matches, imports
each shared bundle once, and sends the complete placement list to Unity as one
Undo transaction. A required placement failure rolls back every object created
by that batch.

Manual relation maintenance:

1. `list_manual_asset_relations` to inspect existing curated knowledge.
2. `preview_asset_relation_changes(changes_json=...)` to validate changes and
   variant-group expansion without writing data.
3. Review conflicts, blocking reasons, and expanded edges.
4. `apply_asset_relation_changes(plan_id=...)` to atomically publish the overlay
   and rebuild the effective graph.

`pairs_with`, `supports`, `placed_near`, `placed_on`, and `lines_path` may add
scene candidates. `faces` and `avoid_overlap` never add retrieval score; they
compile only after both assets are selected. `avoid_overlap` becomes collision
avoidance plus `minimum_clearance`, while `faces` becomes `face_reference`.

## Semantic Placement

Each manifest carries a `placementProfile`. Structural assets such as roads and
platforms are `surface` providers; characters and mounts are `occupant` assets;
trees, lanterns, and banners are `roadside`; cliffs and mountains are
`background`. Export preview analyzes Prefab bounds, pivot-to-contact offset,
contact samples, Collider availability, and proxy surface geometry. Explicit
`metadata_overrides_json.placementProfile` values take precedence.

Scene planning places surface providers first. Occupants share the same
`supportReference` and `groundingGroup`; roadside and background assets use the
road as `zoneReference` while grounding against Terrain/Ground when available.
The Unity batch validates surface type, forbidden zones, slope, contact error,
and shared support before committing the Undo group.

Preview or apply placement metadata to an existing library:

```powershell
.\.venv\Scripts\python.exe Server\scripts\backfill_asset_placement_profiles.py
.\.venv\Scripts\python.exe Server\scripts\backfill_asset_placement_profiles.py --apply
```

## Editable Recipes

Recipes live in `Server/data/asset_library/scene_recipes.json`. Manual relations
live only in `Server/data/asset_library/manual_relations.json`; do not edit the
generated graph. Effective precedence is manual, manifest, recipe, then
automatic bundle/variant knowledge.
