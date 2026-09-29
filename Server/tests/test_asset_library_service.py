from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_service import (
    IMPORT_METADATA_FILENAME,
    calculate_asset_content_hash,
    create_embeddings,
    find_project_guid_conflicts,
    import_asset_to_project,
    load_asset_records,
    search_asset_library,
    validate_asset_library,
    active_asset_collection_name,
    load_asset_index_state,
    _write_asset_index_state,
    build_placement_profile,
)
from services.asset_graph_service import (
    apply_asset_relation_changes,
    build_asset_graph,
    graph_expansion_scores,
    get_asset_relations,
    list_manual_asset_relations,
    load_asset_graph_index,
    preview_asset_relation_changes,
)
from services.asset_scene_plan_service import build_asset_scene_preview
from services.tools.asset_library_tools import _parse_vector3
from services.tools.asset_tools import _parse_position as parse_asset_position
from services.tools.scene_tools import _parse_position as parse_scene_position


class AssetLibraryServiceTests(unittest.TestCase):
    def test_active_index_state_switch_is_atomic_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            index_dir = Path(temp) / "index"
            state_path = _write_asset_index_state(
                index_dir,
                collection_name="unity_asset_library_bge_m3_v2",
                embedding_provider="bge-m3",
                evaluation={"passed": True, "top1_accuracy": 1.0},
            )
            self.assertTrue(state_path.is_file())
            state = load_asset_index_state(index_dir)
            self.assertEqual(state["embedding_provider"], "bge-m3")
            self.assertEqual(
                active_asset_collection_name(index_dir),
                "unity_asset_library_bge_m3_v2",
            )

    def test_vector_parsers_require_exact_finite_xyz_values(self) -> None:
        self.assertEqual(parse_asset_position("1,2,3"), [1.0, 2.0, 3.0])
        self.assertEqual(parse_scene_position("1,2,3"), [1.0, 2.0, 3.0])
        self.assertEqual(
            _parse_vector3("1,2,3", "position"),
            {"x": 1.0, "y": 2.0, "z": 3.0},
        )
        for parser in (parse_asset_position, parse_scene_position):
            with self.assertRaises(ValueError):
                parser("1,2")
            with self.assertRaises(ValueError):
                parser("1,2,nan")
        with self.assertRaises(ValueError):
            _parse_vector3("1,2", "position")

    def test_local_hash_embeddings_are_fast_and_deterministic(self) -> None:
        first = create_embeddings(["古代书生", "汗血宝马"], "local-hash")
        second = create_embeddings(["古代书生", "汗血宝马"], "local-hash")

        self.assertEqual(first.shape, (2, 512))
        self.assertTrue((first == second).all())

    def _write_asset(
        self,
        library_root: Path,
        folder: str,
        asset_id: str,
        display_name: str,
        category: str,
        aliases: list[str],
    ) -> Path:
        root = library_root / folder
        (root / "Prefabs").mkdir(parents=True)
        (root / "Materials").mkdir()
        prefab_path = root / "Prefabs" / f"{display_name}.prefab"
        model_path = root / f"{display_name}.fbx"
        material_path = root / "Materials" / "main.mat"
        prefab_path.write_text(
            "prefab", encoding="utf-8"
        )
        model_path.write_text("model", encoding="utf-8")
        material_path.write_text(
            "material", encoding="utf-8"
        )
        guid_prefix = hashlib.md5(asset_id.encode("utf-8")).hexdigest()[:26]
        model_guid = f"{guid_prefix}000001"
        prefab_guid = f"{guid_prefix}000002"
        material_guid = f"{guid_prefix}000003"
        Path(str(model_path) + ".meta").write_text(
            f"fileFormatVersion: 2\nguid: {model_guid}\n",
            encoding="utf-8",
        )
        Path(str(prefab_path) + ".meta").write_text(
            f"fileFormatVersion: 2\nguid: {prefab_guid}\n",
            encoding="utf-8",
        )
        Path(str(material_path) + ".meta").write_text(
            f"fileFormatVersion: 2\nguid: {material_guid}\n",
            encoding="utf-8",
        )
        (root / "asset.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "id": asset_id,
                    "displayName": display_name,
                    "category": category,
                    "prefab": f"Prefabs/{display_name}.prefab",
                    "model": f"{display_name}.fbx",
                    "material": "Materials/main.mat",
                    "sourceModelGuid": model_guid,
                    "defaultScale": [1, 1, 1],
                    "groundOffset": 0.0,
                    "forwardAxis": "+Z",
                    "placementRadius": 0.5,
                    "bounds": {"x": 1, "y": 2, "z": 1},
                    "tags": [display_name],
                    "aliases": aliases,
                    "description": f"{display_name} test asset",
                    "useCases": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return root

    def _update_manifest(self, root: Path, **changes: object) -> None:
        path = root / "asset.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest.update(changes)
        path.write_text(
            json.dumps(manifest, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_search_matches_alias_without_vector_index(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "library"
            self._write_asset(
                library,
                "Characters/Scholar",
                "scholar",
                "古代文人",
                "character",
                ["书生", "士人"],
            )
            self._write_asset(
                library,
                "Animals/Horse",
                "horse",
                "汗血宝马",
                "animal",
                ["战马", "坐骑"],
            )

            result = search_asset_library(
                "在亭子旁边放一个书生",
                library_root=library,
                use_vector=False,
            )

            self.assertEqual(result["results"][0]["assetId"], "scholar")

    def test_schema_v3_runtime_view_and_utf8_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "library"
            self._write_asset(
                library,
                "Props/Teapot",
                "teapot",
                "国风瓷茶壶",
                "prop",
                ["茶具", "中式茶壶"],
            )
            record = load_asset_records(library)[0]
            self.assertEqual(record.data["schemaVersion"], 3)
            self.assertIn("semanticAttributes", record.data)
            self.assertIn("placementProfile", record.data)
            self.assertIn("资产名称: 国风瓷茶壶", record.document)
            self.assertNotIn("鍥", record.document)

    def test_asset_record_cache_reuses_and_invalidates_on_manifest_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "library"
            root = self._write_asset(
                library,
                "Props/Table",
                "table",
                "国风木桌",
                "prop",
                ["书桌"],
            )
            first = load_asset_records(library)
            second = load_asset_records(library)
            self.assertIs(first[0], second[0])
            self._update_manifest(root, aliases=["书桌", "长木桌"])
            third = load_asset_records(library)
            self.assertIsNot(first[0], third[0])
            self.assertIn("长木桌", third[0].data["aliases"])

    def test_hybrid_search_filters_and_explanations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "library"
            horse = self._write_asset(
                library,
                "Animals/Horse",
                "horse",
                "汗血宝马",
                "animal",
                ["坐骑", "骏马"],
            )
            scholar = self._write_asset(
                library,
                "Characters/Scholar",
                "scholar",
                "古代文人",
                "character",
                ["书生"],
            )
            horse_manifest = json.loads(
                (horse / "asset.json").read_text(encoding="utf-8")
            )
            horse_manifest["tags"] = ["动物", "坐骑"]
            (horse / "asset.json").write_text(
                json.dumps(horse_manifest, ensure_ascii=False), encoding="utf-8"
            )
            result = search_asset_library(
                "安排一匹古代坐骑",
                library_root=library,
                use_vector=False,
                filters={"tags": ["坐骑"]},
            )
            self.assertEqual(result["results"][0]["assetId"], "horse")
            self.assertGreater(result["results"][0]["confidence"], 0.5)
            self.assertIn("lexical_match", result["results"][0]["matchReasons"])
            self.assertNotEqual(result["results"][0]["assetId"], "scholar")

    def test_semantic_placement_profile_inference_and_override(self) -> None:
        road = build_placement_profile(
            {
                "id": "road",
                "displayName": "国风石板道路",
                "category": "environment",
                "bounds": {"x": 6.0, "y": 0.2, "z": 12.0},
                "placementRadius": 6.0,
                "tags": ["道路"],
            },
            {},
            {
                "pivot_to_contact": [0.0, -0.1, 0.0],
                "contact_points": [[0.0, -0.1, 0.0]],
                "effective_width": 6.0,
                "effective_length": 12.0,
                "has_collider": False,
            },
        )
        self.assertEqual(road["placementRole"], "surface")
        self.assertEqual(road["surfaceType"], "road")
        self.assertTrue(road["surfaceGeometry"]["proxySurface"])
        self.assertEqual(road["pivotToContact"], [0.0, -0.1, 0.0])

        overridden = build_placement_profile(
            {
                "id": "tree",
                "displayName": "国风树木",
                "category": "environment",
                "bounds": {"x": 2.0, "y": 5.0, "z": 2.0},
            },
            {"placementRole": "obstacle", "groundingMode": "manual_offset"},
        )
        self.assertEqual(overridden["placementRole"], "obstacle")
        self.assertEqual(overridden["groundingMode"], "manual_offset")

    def test_scene_plan_uses_road_as_support_and_zone_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(
                library, "Road", "road", "国风道路", "environment", ["石板路"]
            )
            self._write_asset(
                library, "Scholar", "scholar", "古代文人", "character", ["书生"]
            )
            self._write_asset(
                library, "Horse", "horse", "汗血宝马", "animal", ["坐骑"]
            )
            self._write_asset(
                library, "Tree", "tree", "国风树木", "environment", ["树木"]
            )
            self._write_asset(
                library, "Cliff", "cliff", "国风山崖", "environment", ["山崖"]
            )
            recipes = root / "recipes.json"
            recipes.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "id": "road_scene",
                                "displayName": "道路人物场景",
                                "keywords": ["道路人物场景"],
                                "roles": [
                                    {"id": "tree", "assetIds": ["tree"], "count": 2},
                                    {"id": "horse", "assetIds": ["horse"], "count": 1},
                                    {"id": "cliff", "assetIds": ["cliff"], "count": 1},
                                    {"id": "road", "assetIds": ["road"], "count": 1},
                                    {"id": "scholar", "assetIds": ["scholar"], "count": 1},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview = build_asset_scene_preview(
                intent="道路人物场景",
                scene_context={"scene_token": "token", "objects": [], "surfaces": []},
                region_size={"x": 1.0, "y": 1.0, "z": 1.0},
                constraints={"expandRelations": False},
                library_root=library,
                recipes_path=recipes,
            )
            self.assertTrue(preview["can_apply"])
            placements = preview["placements"]
            self.assertEqual(placements[0]["asset_id"], "road")
            by_id = {item["asset_id"]: item for item in placements}
            self.assertEqual(by_id["scholar"]["supportReference"], "@road-1")
            self.assertEqual(by_id["horse"]["supportReference"], "@road-1")
            self.assertEqual(
                by_id["scholar"]["groundingGroup"],
                by_id["horse"]["groundingGroup"],
            )
            self.assertEqual(by_id["scholar"]["surfaceZone"], "top")
            self.assertEqual(by_id["tree"]["zoneReference"], "@road-1")
            self.assertIn(by_id["tree"]["surfaceZone"], {"left_side", "right_side"})
            self.assertIsNone(by_id["tree"]["supportReference"])
            self.assertIn(by_id["cliff"]["surfaceZone"], {"left_outer", "right_outer"})
            self.assertEqual(by_id["tree"]["forbiddenZoneViolations"], [])
            self.assertEqual(by_id["tree"]["footprint"], {"x": 1.0, "z": 1.0})

    def test_scene_plan_tiles_small_road_to_cover_requested_region(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            road_root = self._write_asset(
                library, "Road", "road", "Road Tile", "environment", ["road"]
            )
            self._update_manifest(
                road_root,
                placementProfile={
                    "placementRole": "surface",
                    "surfaceType": "road",
                    "footprint": {"x": 4.0, "z": 2.0},
                    "surfaceGeometry": {
                        "effectiveWidth": 4.0,
                        "effectiveLength": 2.0,
                        "centerlineAxis": "+Z",
                    },
                },
            )
            self._write_asset(
                library, "Scholar", "scholar", "Scholar", "character", ["scholar"]
            )
            tree_root = self._write_asset(
                library, "Tree", "tree", "Tree", "environment", ["tree"]
            )
            self._update_manifest(
                tree_root,
                placementProfile={
                    "placementRole": "roadside",
                    "footprint": {"x": 1.0, "z": 1.0},
                    "preferredDistance": 1.0,
                    "forbiddenZones": ["top", "centerline"],
                },
            )
            recipes = root / "recipes.json"
            recipes.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "id": "tile_scene",
                                "displayName": "Tile Scene",
                                "keywords": ["tile scene"],
                                "roles": [
                                    {"id": "road", "assetIds": ["road"], "count": 1},
                                    {"id": "scholar", "assetIds": ["scholar"], "count": 1},
                                    {"id": "tree", "assetIds": ["tree"], "count": 4},
                                ],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            preview = build_asset_scene_preview(
                intent="tile scene",
                scene_context={"scene_token": "token", "objects": [], "surfaces": []},
                region_size={"x": 4.0, "y": 1.0, "z": 5.0},
                max_assets=10,
                constraints={"expandRelations": False},
                library_root=library,
                recipes_path=recipes,
            )

            self.assertTrue(preview["can_apply"])
            coverage = preview["surface_coverage"]
            self.assertEqual(coverage["requiredTiles"], 3)
            self.assertEqual(coverage["plannedTiles"], 3)
            roads = [item for item in preview["placements"] if item["asset_id"] == "road"]
            self.assertEqual(len(roads), 3)
            self.assertEqual([item["surface_tile_row"] for item in roads], [0, 1, 2])
            self.assertEqual([item["reference"] for item in roads], ["", "", ""])
            scholar = next(
                item for item in preview["placements"] if item["asset_id"] == "scholar"
            )
            self.assertEqual(scholar["supportReference"], "@road-1")
            trees = [item for item in preview["placements"] if item["asset_id"] == "tree"]
            self.assertEqual(
                [item["zoneReference"] for item in trees],
                ["@road-1", "@road-1", "@road-2", "@road-2"],
            )

    def test_asset_graph_recipe_relations_and_depth_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(
                library, "Characters/Scholar", "scholar", "古代文人",
                "character", ["书生"]
            )
            self._write_asset(
                library, "Animals/Horse", "horse", "汗血宝马",
                "animal", ["坐骑"]
            )
            recipes = root / "recipes.json"
            recipes.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "id": "scholar_mount",
                                "displayName": "文人与坐骑",
                                "keywords": ["坐骑"],
                                "roles": [
                                    {"id": "scholar", "primary": True, "assetIds": ["scholar"]},
                                    {"id": "mount", "assetIds": ["horse"], "graphRelation": "pairs_with"},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            graph = root / "asset_graph.json"
            result = build_asset_graph(library, graph, recipes)
            self.assertGreaterEqual(result["edge_count"], 3)
            relations = get_asset_relations(
                "scholar", ["pairs_with"], 5, graph, library
            )
            self.assertEqual(relations["depth"], 3)
            self.assertTrue(
                any(item["target"] == "horse" for item in relations["relations"])
            )

    def test_scene_recipe_reuses_existing_scholar_and_places_horse(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(
                library, "Characters/Scholar", "scholar", "古代文人",
                "character", ["书生", "读书人"]
            )
            self._write_asset(
                library, "Animals/Horse", "horse", "汗血宝马",
                "animal", ["坐骑", "骏马"]
            )
            recipes = root / "recipes.json"
            recipes.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "id": "scholar_mount",
                                "displayName": "文人与坐骑",
                                "keywords": ["文人", "坐骑"],
                                "roles": [
                                    {"id": "scholar", "primary": True, "assetIds": ["scholar"], "existingPreferred": True},
                                    {"id": "mount", "assetIds": ["horse"], "count": 1, "relation": "right"},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            preview = build_asset_scene_preview(
                intent="给古代文人安排一匹坐骑",
                scene_context={
                    "scene_token": "token",
                    "scene_path": "Assets/Test.unity",
                    "objects": [
                        {
                            "name": "古代文人",
                            "path": "Environment/古代文人",
                            "position": {"x": 2, "y": 0, "z": 3},
                        }
                    ],
                },
                library_root=library,
                recipes_path=recipes,
            )
            self.assertTrue(preview["can_apply"])
            self.assertEqual(preview["recipe_id"], "scholar_mount")
            self.assertEqual(preview["asset_count"], 1)
            self.assertEqual(preview["placements"][0]["asset_id"], "horse")
            self.assertEqual(
                preview["placements"][0]["reference"],
                "Environment/古代文人",
            )

    def test_manual_relation_preview_expands_groups_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(
                library, "Props/Lantern", "lantern", "石灯", "prop", ["石灯笼"]
            )
            banner_a = self._write_asset(
                library, "Props/BannerA", "banner-a", "旗幡一型", "prop", ["旗帜"]
            )
            banner_b = self._write_asset(
                library, "Props/BannerB", "banner-b", "旗幡二型", "prop", ["旗帜"]
            )
            self._update_manifest(banner_a, variantGroup="banner")
            self._update_manifest(banner_b, variantGroup="banner")
            manual_path = root / "manual_relations.json"
            preview = preview_asset_relation_changes(
                [
                    {
                        "op": "upsert",
                        "relation": {
                            "source": {"assetId": "lantern"},
                            "target": {"variantGroup": "banner"},
                            "type": "avoid_overlap",
                            "spatial": {"minDistance": 1.5},
                        },
                    }
                ],
                manual_relations_path=manual_path,
                library_root=library,
            )
            self.assertTrue(preview["can_apply"])
            self.assertFalse(manual_path.exists())
            self.assertEqual(len(preview["expanded_edges"]), 4)

            applied = apply_asset_relation_changes(preview["plan_id"])
            self.assertEqual(applied["status"], "applied")
            listed = list_manual_asset_relations(
                manual_relations_path=manual_path,
                library_root=library,
            )
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["relations"][0]["targetAssets"], ["banner-a", "banner-b"])
            self.assertFalse(listed["relations"][0]["retrievalEligible"])
            self.assertTrue(listed["relations"][0]["constraintEligible"])

    def test_manual_relation_apply_rejects_changed_source_and_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(library, "A", "asset-a", "资产甲", "prop", ["甲"])
            self._write_asset(library, "B", "asset-b", "资产乙", "prop", ["乙"])
            manual_path = root / "manual_relations.json"
            manual_path.write_text('{"schemaVersion":1,"relations":[]}', encoding="utf-8")
            change = [
                {
                    "op": "upsert",
                    "relation": {
                        "id": "manual-a-b",
                        "source": {"assetId": "asset-a"},
                        "target": {"assetId": "asset-b"},
                        "type": "pairs_with",
                    },
                }
            ]
            stale = preview_asset_relation_changes(
                change,
                manual_relations_path=manual_path,
                library_root=library,
            )
            manual_path.write_text(
                '{"schemaVersion":1,"relations":[]}\n', encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "changed after preview"):
                apply_asset_relation_changes(stale["plan_id"])

            preview = preview_asset_relation_changes(
                change,
                manual_relations_path=manual_path,
                library_root=library,
            )
            old_manual = manual_path.read_bytes()
            with patch(
                "services.asset_graph_service.build_asset_graph",
                side_effect=RuntimeError("forced graph failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "forced graph failure"):
                    apply_asset_relation_changes(preview["plan_id"])
            self.assertEqual(manual_path.read_bytes(), old_manual)

    def test_constraint_only_relations_do_not_add_retrieval_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(
                library, "Characters/Scholar", "scholar", "古代文人", "character", ["书生"]
            )
            self._write_asset(
                library, "Props/Table", "table", "国风木桌", "prop", ["书桌"]
            )
            self._write_asset(
                library, "Props/Banner", "banner", "旗幡", "prop", ["旗帜"]
            )
            manual = root / "manual_relations.json"
            manual.write_text(
                json.dumps(
                    {
                        "relations": [
                            {
                                "id": "faces-table",
                                "source": {"assetId": "scholar"},
                                "target": {"assetId": "table"},
                                "type": "faces",
                            },
                            {
                                "id": "avoids-banner",
                                "source": {"assetId": "scholar"},
                                "target": {"assetId": "banner"},
                                "type": "avoid_overlap",
                                "spatial": {"minDistance": 1.5},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            build_asset_graph(library_root=library, manual_relations_path=manual)
            expanded, _ = graph_expansion_scores({"scholar": 100.0}, library_root=library)
            self.assertNotIn("table", expanded)
            self.assertNotIn("banner", expanded)
            relations = get_asset_relations(
                "scholar",
                relation_types={"faces", "avoid_overlap"},
                include_constraints=True,
                library_root=library,
            )
            compiled = {
                item["type"]: item["compiledConstraint"]
                for item in relations["relations"]
            }
            self.assertTrue(compiled["faces"]["faceReference"])
            self.assertEqual(compiled["avoid_overlap"]["minimumClearance"], 1.5)

    def test_graph_cache_is_reused_and_invalidated_after_manual_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            self._write_asset(library, "A", "asset-a", "资产甲", "prop", ["甲"])
            self._write_asset(library, "B", "asset-b", "资产乙", "prop", ["乙"])
            manual = root / "manual_relations.json"
            manual.write_text('{"schemaVersion":1,"relations":[]}', encoding="utf-8")
            build_asset_graph(library_root=library, manual_relations_path=manual)
            first = load_asset_graph_index(library_root=library)
            second = load_asset_graph_index(library_root=library)
            self.assertIs(first, second)
            preview = preview_asset_relation_changes(
                [
                    {
                        "op": "upsert",
                        "relation": {
                            "source": {"assetId": "asset-a"},
                            "target": {"assetId": "asset-b"},
                            "type": "pairs_with",
                        },
                    }
                ],
                manual_relations_path=manual,
                library_root=library,
            )
            apply_asset_relation_changes(preview["plan_id"])
            third = load_asset_graph_index(library_root=library)
            self.assertIsNot(first, third)
            self.assertTrue(
                any(edge["target"] == "asset-b" for edge in third.outgoing["asset-a"])
            )

    def test_scene_plan_compiles_facing_line_and_clearance_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            library = root / "library"
            scholar = self._write_asset(
                library, "Scholar", "scholar", "古代文人", "character", ["书生"]
            )
            table = self._write_asset(
                library, "Table", "table", "国风木桌", "prop", ["书桌"]
            )
            road = self._write_asset(
                library, "Road", "road", "石板道路", "environment", ["道路"]
            )
            lantern = self._write_asset(
                library, "Lantern", "lantern", "石灯", "prop", ["石灯笼"]
            )
            banner = self._write_asset(
                library, "Banner", "banner", "旗幡", "prop", ["旗帜"]
            )
            self._update_manifest(scholar, placementProfile={"minSpacing": 0.5})
            self._update_manifest(table, placementProfile={"minSpacing": 0.75})
            self._update_manifest(road, placementProfile={"minSpacing": 0.5})
            self._update_manifest(lantern, placementProfile={"minSpacing": 0.5})
            self._update_manifest(banner, placementProfile={"minSpacing": 2.0})
            recipes = root / "recipes.json"
            recipes.write_text(
                json.dumps(
                    {
                        "recipes": [
                            {
                                "id": "constraint-scene",
                                "displayName": "约束场景",
                                "keywords": ["约束场景"],
                                "roles": [
                                    {"id": "scholar", "assetIds": ["scholar"], "count": 1},
                                    {"id": "table", "assetIds": ["table"], "count": 1},
                                    {"id": "road", "assetIds": ["road"], "count": 1},
                                    {"id": "lantern", "assetIds": ["lantern"], "count": 1},
                                    {"id": "banner", "assetIds": ["banner"], "count": 1},
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manual = root / "manual_relations.json"
            manual.write_text(
                json.dumps(
                    {
                        "relations": [
                            {
                                "id": "scholar-faces-table",
                                "source": {"assetId": "scholar"},
                                "target": {"assetId": "table"},
                                "type": "faces",
                            },
                            {
                                "id": "lantern-lines-road",
                                "source": {"assetId": "lantern"},
                                "target": {"assetId": "road"},
                                "type": "lines_path",
                                "spatial": {"minDistance": 2.5},
                            },
                            {
                                "id": "lantern-avoids-banner",
                                "source": {"assetId": "lantern"},
                                "target": {"assetId": "banner"},
                                "type": "avoid_overlap",
                                "spatial": {"minDistance": 1.5},
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            build_asset_graph(
                library_root=library,
                recipes_path=recipes,
                manual_relations_path=manual,
            )
            preview = build_asset_scene_preview(
                intent="约束场景",
                scene_context={"scene_token": "token", "objects": []},
                constraints={"expandRelations": False},
                library_root=library,
                recipes_path=recipes,
            )
            by_id = {item["asset_id"]: item for item in preview["placements"]}
            self.assertTrue(by_id["scholar"]["face_reference"])
            self.assertEqual(by_id["scholar"]["reference"], "@table-1")
            self.assertEqual(by_id["lantern"]["layout"], "line")
            self.assertEqual(by_id["lantern"]["reference"], "@road-1")
            self.assertEqual(by_id["lantern"]["minimum_clearance"], 2.0)
            self.assertTrue(by_id["lantern"]["relationEvidence"])
            self.assertTrue(by_id["lantern"]["compiledConstraints"])
            order = [item["asset_id"] for item in preview["placements"]]
            self.assertLess(order.index("table"), order.index("scholar"))
            self.assertLess(order.index("road"), order.index("lantern"))

    def test_import_copies_complete_folder_and_returns_prefab_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            self._write_asset(
                library,
                "Animals/Horse",
                "horse",
                "汗血宝马",
                "animal",
                ["坐骑"],
            )
            result = import_asset_to_project(
                "horse",
                project,
                library_root=library,
            )

            self.assertEqual(
                result["prefab_asset_path"],
                "Assets/AIAssetLibrary/animal/汗血宝马/Prefabs/汗血宝马.prefab",
            )
            copied_meta = (
                project
                / "Assets/AIAssetLibrary/animal/汗血宝马/汗血宝马.fbx.meta"
            )
            self.assertTrue(copied_meta.is_file())
            self.assertEqual(load_asset_records(library)[0].asset_id, "horse")

    def test_content_hash_is_deterministic_and_changes_with_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "nested").mkdir()
            (root / "b.txt").write_text("second", encoding="utf-8")
            (root / "nested" / "a.txt").write_text("first", encoding="utf-8")

            first = calculate_asset_content_hash(root)
            second = calculate_asset_content_hash(root)
            self.assertEqual(first, second)

            (root / "nested" / "a.txt").write_text("changed", encoding="utf-8")
            self.assertNotEqual(first, calculate_asset_content_hash(root))

    def test_second_import_skips_copy_and_writes_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            self._write_asset(
                library,
                "Characters/Scholar",
                "scholar",
                "古代文人",
                "character",
                ["书生"],
            )

            first = import_asset_to_project(
                "scholar", project, library_root=library
            )
            second = import_asset_to_project(
                "scholar", project, library_root=library
            )

            sidecar = Path(first["target_path"]) / IMPORT_METADATA_FILENAME
            self.assertTrue(sidecar.is_file())
            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertTrue(second["already_imported"])
            self.assertEqual(second["copied_file_count"], 0)
            self.assertEqual(second["copied_byte_count"], 0)

    def test_bundle_entries_share_one_import_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            root = self._write_asset(
                library,
                "Environment/TreePack",
                "tree-red",
                "Red Tree",
                "environment",
                ["red tree"],
            )
            primary_manifest = json.loads(
                (root / "asset.json").read_text(encoding="utf-8")
            )
            primary_manifest["bundleId"] = "far-east-trees"
            primary_manifest["bundleDisplayName"] = "Far East Trees"
            (root / "asset.json").write_text(
                json.dumps(primary_manifest), encoding="utf-8"
            )

            second_prefab = root / "Prefabs/Yellow Tree.prefab"
            second_prefab.write_text("yellow prefab", encoding="utf-8")
            second_prefab_meta = Path(str(second_prefab) + ".meta")
            second_prefab_meta.write_text(
                "fileFormatVersion: 2\n"
                "guid: 1234567890abcdef1234567890abcdef\n",
                encoding="utf-8",
            )
            second_manifest = dict(primary_manifest)
            second_manifest.update(
                {
                    "id": "tree-yellow",
                    "displayName": "Yellow Tree",
                    "prefab": "Prefabs/Yellow Tree.prefab",
                    "aliases": ["yellow tree"],
                }
            )
            (root / "yellow.asset.json").write_text(
                json.dumps(second_manifest), encoding="utf-8"
            )

            records = load_asset_records(library)
            self.assertEqual({record.asset_id for record in records}, {
                "tree-red", "tree-yellow"
            })

            first = import_asset_to_project(
                "tree-red", project, library_root=library
            )
            second = import_asset_to_project(
                "tree-yellow", project, library_root=library
            )

            self.assertTrue(first["changed"])
            self.assertFalse(second["changed"])
            self.assertEqual(first["target_path"], second["target_path"])
            self.assertEqual(second["bundle_id"], "far-east-trees")
            self.assertTrue(
                second["prefab_asset_path"].endswith(
                    "Far East Trees/Prefabs/Yellow Tree.prefab"
                )
            )

    def test_identical_source_assets_already_in_project_are_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            source = self._write_asset(
                library,
                "Environment/Tree",
                "tree",
                "Far East Tree",
                "environment",
                ["tree"],
            )
            installed = project / "Assets/OriginalTree"
            shutil.copytree(source, installed)

            result = import_asset_to_project(
                "tree", project, library_root=library
            )

            self.assertTrue(result["already_imported"])
            self.assertTrue(result["reused_existing_asset"])
            self.assertFalse(result["changed"])
            self.assertEqual(result["copied_file_count"], 0)
            self.assertEqual(
                result["prefab_asset_path"],
                "Assets/OriginalTree/Prefabs/Far East Tree.prefab",
            )

    def test_changed_source_requires_overwrite_and_removes_stale_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            source = self._write_asset(
                library,
                "Animals/Horse",
                "horse",
                "汗血宝马",
                "animal",
                ["坐骑"],
            )

            first = import_asset_to_project(
                "horse", project, library_root=library
            )
            target = Path(first["target_path"])
            stale = target / "stale.txt"
            stale.write_text("remove me", encoding="utf-8")
            (source / "汗血宝马.fbx").write_text(
                "updated model", encoding="utf-8"
            )

            pending = import_asset_to_project(
                "horse", project, library_root=library
            )
            self.assertFalse(pending["changed"])
            self.assertTrue(pending["update_available"])
            self.assertTrue(stale.exists())

            updated = import_asset_to_project(
                "horse",
                project,
                library_root=library,
                overwrite=True,
            )
            self.assertTrue(updated["changed"])
            self.assertFalse(updated["update_available"])
            self.assertFalse(stale.exists())
            self.assertEqual(
                (target / "汗血宝马.fbx").read_text(encoding="utf-8"),
                "updated model",
            )

    def test_project_guid_conflict_blocks_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            library = temp_path / "library"
            project = temp_path / "project"
            (project / "Assets/Existing").mkdir(parents=True)
            (project / "ProjectSettings").mkdir()
            source = self._write_asset(
                library,
                "Characters/Scholar",
                "scholar",
                "古代文人",
                "character",
                ["书生"],
            )
            source_guid = (
                source / "古代文人.fbx.meta"
            ).read_text(encoding="utf-8").split("guid: ", 1)[1].strip()
            (project / "Assets/Existing/model.fbx.meta").write_text(
                f"fileFormatVersion: 2\nguid: {source_guid}\n",
                encoding="utf-8",
            )

            scan = find_project_guid_conflicts(
                source,
                project / "Assets",
            )
            self.assertEqual(scan["conflict_count"], 1)
            with self.assertRaisesRegex(ValueError, "GUID conflict"):
                import_asset_to_project(
                    "scholar",
                    project,
                    library_root=library,
                )

    def test_validation_reports_duplicate_and_unresolved_guids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            library = Path(temp) / "library"
            source = self._write_asset(
                library,
                "Characters/Scholar",
                "scholar",
                "古代文人",
                "character",
                ["书生"],
            )
            duplicate_guid = (
                source / "Materials/main.mat.meta"
            ).read_text(encoding="utf-8").split("guid: ", 1)[1].strip()
            (source / "duplicate.asset").write_text(
                "asset", encoding="utf-8"
            )
            (source / "duplicate.asset.meta").write_text(
                f"fileFormatVersion: 2\nguid: {duplicate_guid}\n",
                encoding="utf-8",
            )
            unresolved_guid = "1234567890abcdef1234567890abcdef"
            (source / "Prefabs/古代文人.prefab").write_text(
                "m_LocalScale: {x: 2, y: 2, z: 2}\n"
                f"m_Material: {{fileID: 2100000, guid: {unresolved_guid}, "
                "type: 2}\n",
                encoding="utf-8",
            )

            result = validate_asset_library(library)

            self.assertFalse(result["valid"])
            self.assertEqual(result["duplicate_guid_count"], 1)
            self.assertGreaterEqual(result["error_count"], 2)
            asset = result["assets"][0]
            self.assertEqual(asset["unresolved_guid_count"], 1)
            self.assertTrue(
                any("root scale" in warning for warning in asset["warnings"])
            )


if __name__ == "__main__":
    unittest.main()
