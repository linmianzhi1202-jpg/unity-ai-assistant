import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SERVER_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = SERVER_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from services.asset_library_export_service import (
    AssetExportPlanStore,
    apply_asset_export_plan,
    build_asset_export_preview,
)
from services.asset_library_service import (
    import_asset_to_project,
    load_asset_records,
    validate_asset_library,
)


class AssetLibraryExportServiceTests(unittest.TestCase):
    MODEL_GUID = "11111111111111111111111111111111"
    MATERIAL_GUID = "22222222222222222222222222222222"
    PREFAB_A_GUID = "33333333333333333333333333333333"
    PREFAB_B_GUID = "44444444444444444444444444444444"
    TEXTURE_GUID = "55555555555555555555555555555555"

    def _write_asset(self, project: Path, relative: str, content: bytes, guid: str) -> Path:
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        Path(str(path) + ".meta").write_text(
            f"fileFormatVersion: 2\nguid: {guid}\n",
            encoding="utf-8",
        )
        return path

    def _project_and_analysis(self, root: Path, two_prefabs: bool = True):
        project = root / "project"
        (project / "Assets/Pack").mkdir(parents=True)
        (project / "ProjectSettings").mkdir()
        self._write_asset(
            project,
            "Assets/Pack/tree.fbx",
            b"binary model",
            self.MODEL_GUID,
        )
        self._write_asset(
            project,
            "Assets/Pack/leaves.png",
            b"binary texture",
            self.TEXTURE_GUID,
        )
        material = (
            "Material:\n"
            f"  m_Texture: {{fileID: 2800000, guid: {self.TEXTURE_GUID}, type: 3}}\n"
        ).encode("utf-8")
        self._write_asset(
            project,
            "Assets/Pack/tree.mat",
            material,
            self.MATERIAL_GUID,
        )

        prefab_paths = []
        prefab_specs = [
            ("TreeA.prefab", self.PREFAB_A_GUID),
            ("TreeB.prefab", self.PREFAB_B_GUID),
        ]
        if not two_prefabs:
            prefab_specs = prefab_specs[:1]
        for name, guid in prefab_specs:
            prefab = (
                "Prefab:\n"
                f"  m_Mesh: {{fileID: 4300000, guid: {self.MODEL_GUID}, type: 3}}\n"
                f"  m_Material: {{fileID: 2100000, guid: {self.MATERIAL_GUID}, type: 2}}\n"
            ).encode("utf-8")
            path = f"Assets/Pack/{name}"
            self._write_asset(project, path, prefab, guid)
            prefab_paths.append((path, guid))

        common = [
            {
                "path": "Assets/Pack/tree.fbx",
                "guid": self.MODEL_GUID,
                "type": "model",
                "extension": ".fbx",
            },
            {
                "path": "Assets/Pack/tree.mat",
                "guid": self.MATERIAL_GUID,
                "type": "material",
                "extension": ".mat",
            },
            {
                "path": "Assets/Pack/leaves.png",
                "guid": self.TEXTURE_GUID,
                "type": "texture",
                "extension": ".png",
            },
        ]
        dependencies = list(common)
        prefabs = []
        for path, guid in prefab_paths:
            dependencies.append(
                {
                    "path": path,
                    "guid": guid,
                    "type": "prefab",
                    "extension": ".prefab",
                }
            )
            prefabs.append(
                {
                    "path": path,
                    "name": Path(path).stem,
                    "guid": guid,
                    "default_scale": {"x": 1, "y": 1, "z": 1},
                    "bounds_size": {"x": 4, "y": 8, "z": 5},
                    "placement_geometry": {
                        "pivot_to_contact": [0.0, -4.0, 0.0],
                        "contact_points": [[0.0, -4.0, 0.0]],
                        "effective_width": 4.0,
                        "effective_length": 5.0,
                        "has_collider": False,
                    },
                    "dependency_paths": [
                        path,
                        "Assets/Pack/tree.fbx",
                        "Assets/Pack/tree.mat",
                        "Assets/Pack/leaves.png",
                    ],
                }
            )
        return project, {
            "project_path": str(project),
            "prefabs": prefabs,
            "dependencies": dependencies,
            "blocking_dependencies": [],
            "package_dependencies": [],
            "errors": [],
        }

    def test_preview_is_read_only_and_deduplicates_shared_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, analysis = self._project_and_analysis(root)
            library = root / "library"

            preview = build_asset_export_preview(
                analysis,
                bundle_name="Far East Trees",
                category="environment",
                intent="Chinese garden trees",
                library_root=library,
            )

            self.assertTrue(preview["can_export"])
            self.assertEqual(preview["prefab_count"], 2)
            self.assertEqual(preview["dependency_count"], 5)
            self.assertEqual(preview["changes"]["added"], 2)
            profile = preview["entries"][0]["placement_profile"]
            self.assertEqual(profile["placementRole"], "roadside")
            self.assertEqual(profile["pivotToContact"], [0.0, -4.0, 0.0])
            self.assertEqual(
                preview["entries"][0]["placement_analysis"]["effective_width"],
                4.0,
            )
            self.assertFalse(library.exists())
            self.assertTrue((project / "Assets/Pack/TreeA.prefab").is_file())

    def test_script_dependency_blocks_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, analysis = self._project_and_analysis(root, two_prefabs=False)
            script = self._write_asset(
                project,
                "Assets/Pack/TreeBehaviour.cs",
                b"class TreeBehaviour {}",
                "66666666666666666666666666666666",
            )
            analysis["dependencies"].append(
                {
                    "path": "Assets/Pack/TreeBehaviour.cs",
                    "guid": "66666666666666666666666666666666",
                    "type": "script",
                    "extension": ".cs",
                }
            )
            analysis["blocking_dependencies"] = [
                "Assets/Pack/TreeBehaviour.cs"
            ]
            analysis["prefabs"][0]["dependency_paths"].append(
                "Assets/Pack/TreeBehaviour.cs"
            )

            preview = build_asset_export_preview(
                analysis,
                bundle_name="Scripted Tree",
                library_root=root / "library",
            )

            self.assertFalse(preview["can_export"])
            self.assertIn(
                "Assets/Pack/TreeBehaviour.cs",
                preview["blocking_dependencies"],
            )
            self.assertTrue(script.is_file())

    def test_unresolved_source_guid_blocks_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, analysis = self._project_and_analysis(
                root, two_prefabs=False
            )
            missing_guid = "77777777777777777777777777777777"
            material = project / "Assets/Pack/tree.mat"
            material.write_text(
                material.read_text(encoding="utf-8")
                + f"  m_Missing: {{fileID: 2800000, guid: {missing_guid}, type: 3}}\n",
                encoding="utf-8",
            )

            preview = build_asset_export_preview(
                analysis,
                bundle_name="Broken Tree",
                library_root=root / "library",
            )

            self.assertFalse(preview["can_export"])
            self.assertIn(
                "Unresolved source Unity GUID reference in "
                f"Assets/Pack/tree.mat: {missing_guid}",
                preview["errors"],
            )

    def test_apply_remaps_guids_validates_and_reuses_source_prefab(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, analysis = self._project_and_analysis(root)
            library = root / "library"
            preview = build_asset_export_preview(
                analysis,
                bundle_name="Far East Trees",
                category="environment",
                metadata_overrides={
                    "Assets/Pack/TreeA.prefab": {
                        "displayName": "Chinese Tree A",
                        "tags": ["tree", "Chinese"],
                        "placementProfile": {
                            "groundingMode": "manual_offset",
                            "preferredDistance": 3.5,
                        },
                    }
                },
                library_root=library,
            )

            with patch(
                "services.asset_library_export_service.index_asset_library_records",
                return_value={"success": True, "upserted_count": 2},
            ):
                result = apply_asset_export_plan(preview["plan_id"])

            self.assertEqual(result["status"], "applied")
            bundle = Path(result["bundle_path"])
            self.assertTrue(validate_asset_library(library)["valid"])
            self.assertEqual(len(list(bundle.rglob("tree.fbx"))), 1)
            remapped_model_guid = (
                bundle / "Source/Assets/Pack/tree.fbx.meta"
            ).read_text(encoding="utf-8").split("guid: ", 1)[1].strip()
            self.assertNotEqual(remapped_model_guid, self.MODEL_GUID)
            prefab_text = (
                bundle / "Source/Assets/Pack/TreeA.prefab"
            ).read_text(encoding="utf-8")
            self.assertIn(remapped_model_guid, prefab_text)
            self.assertNotIn(self.MODEL_GUID, prefab_text)

            records = load_asset_records(library)
            tree_a = next(
                record for record in records
                if record.data.get("sourcePrefabGuid") == self.PREFAB_A_GUID
            )
            self.assertEqual(
                tree_a.data["placementProfile"]["groundingMode"],
                "manual_offset",
            )
            self.assertEqual(
                tree_a.data["placementProfile"]["preferredDistance"],
                3.5,
            )
            imported = import_asset_to_project(
                tree_a.asset_id,
                project,
                library_root=library,
            )
            self.assertTrue(imported["reused_existing_asset"])
            self.assertEqual(
                imported["prefab_asset_path"],
                "Assets/Pack/TreeA.prefab",
            )

    def test_failed_post_publish_validation_restores_previous_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, analysis = self._project_and_analysis(root, two_prefabs=False)
            library = root / "library"
            target = library / "Environment/Far East Trees"
            target.mkdir(parents=True)
            marker = target / "old.txt"
            marker.write_text("old", encoding="utf-8")
            preview = build_asset_export_preview(
                analysis,
                bundle_name="Far East Trees",
                library_root=library,
            )

            with patch(
                "services.asset_library_export_service.validate_asset_library",
                side_effect=[
                    {"valid": True},
                    {"valid": False, "error_count": 1},
                ],
            ):
                with self.assertRaisesRegex(RuntimeError, "Published library"):
                    apply_asset_export_plan(preview["plan_id"])

            self.assertEqual(marker.read_text(encoding="utf-8"), "old")

    def test_plan_store_expires_entries(self):
        store = AssetExportPlanStore(ttl_seconds=0.01)
        plan_id = store.put({"can_export": True})
        self.assertIsNotNone(store.get(plan_id))
        time.sleep(0.02)
        self.assertIsNone(store.get(plan_id))


if __name__ == "__main__":
    unittest.main()
