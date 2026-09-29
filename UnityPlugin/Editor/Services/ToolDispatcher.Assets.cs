using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Reflection;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;
using UnityMCP.Editor.Core;

namespace UnityMCP.Editor.Services
{
    public static partial class ToolDispatcher
    {

        private static string HandleManageMaterial(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "create";

            switch (action)
            {
                case "create":
                {
                    string matName = a["name"]?.ToString() ?? "NewMaterial";
                    string shaderName = a["shader"]?.ToString() ?? "Standard";
                    string saveFolder = a["save_path"]?.ToString() ?? "Assets/Materials";
                    var color = ParseColor(a["color"]);

                    var shader = Shader.Find(shaderName);
                    if (shader == null) return ErrorResult($"Shader not found: {shaderName}");

                    var mat = new Material(shader);
                    mat.name = matName;
                    if (a["color"] != null) mat.color = color;
                    EditorUtility.SetDirty(mat);  // Mark dirty so color serializes to .mat file

                    // Handle metallic / smoothness
                    if (a["metallic"] != null)
                    {
                        var prop = mat.GetType().GetProperty("metallic");
                        if (prop == null)
                        {
                            var floatVal = a["metallic"].Value<float>();
                            if (mat.HasProperty("_Metallic")) mat.SetFloat("_Metallic", floatVal);
                        }
                    }
                    if (a["smoothness"] != null)
                    {
                        var floatVal = a["smoothness"].Value<float>();
                        if (mat.HasProperty("_Glossiness")) mat.SetFloat("_Glossiness", floatVal);
                    }

                    // Save as asset
                    if (!Directory.Exists(saveFolder))
                        Directory.CreateDirectory(saveFolder);
                    string assetPath = Path.Combine(saveFolder, $"{matName}.mat");
                    assetPath = AssetDatabase.GenerateUniqueAssetPath(assetPath);
                    AssetDatabase.CreateAsset(mat, assetPath);
                    AssetDatabase.SaveAssets();
                    AssetDatabase.Refresh();

                    return SuccessResult(new { material_path = assetPath, name = matName, shader = shaderName });
                }

                case "assign":
                {
                    string matPath = a["material_path"]?.ToString();
                    string goPath = a["path"]?.ToString();
                    if (string.IsNullOrEmpty(matPath) || string.IsNullOrEmpty(goPath))
                        return ErrorResult("assign requires material_path and path");

                    var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    if (mat == null) return ErrorResult($"Material not found: {matPath}");

                    var target = FindByPath(goPath);
                    if (target == null) return ErrorResult($"GameObject not found: {goPath}");

                    var smr = target.GetComponent<SkinnedMeshRenderer>();
                    var mr = target.GetComponent<MeshRenderer>();
                    if (smr == null && mr == null) return ErrorResult($"No renderer on {goPath}");

                    if (smr != null)
                    {
                        Undo.RecordObject(smr, "Assign Material");
                        smr.material = mat;
                    }
                    else
                    {
                        Undo.RecordObject(mr, "Assign Material");
                        mr.material = mat;
                    }

                    return SuccessResult(new { assigned = matPath, to = goPath });
                }

                case "set_property":
                {
                    string matPath = a["material_path"]?.ToString();
                    string propName = a["property_name"]?.ToString();
                    if (string.IsNullOrEmpty(matPath) || string.IsNullOrEmpty(propName))
                        return ErrorResult("set_property requires material_path and property_name");

                    var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    if (mat == null) return ErrorResult($"Material not found: {matPath}");

                    Undo.RecordObject(mat, "Set Material Property");

                    // Color property
                    if (a["color"] != null && mat.HasProperty(propName))
                    {
                        mat.SetColor(propName, ParseColor(a["color"]));
                    }
                    // Float property
                    else if (a["float_value"] != null && mat.HasProperty(propName))
                    {
                        mat.SetFloat(propName, a["float_value"].Value<float>());
                    }
                    // Texture property
                    else if (a["texture_path"] != null && mat.HasProperty(propName))
                    {
                        var tex = AssetDatabase.LoadAssetAtPath<Texture>(a["texture_path"].ToString());
                        if (tex != null) mat.SetTexture(propName, tex);
                        else return ErrorResult($"Texture not found: {a["texture_path"]}");
                    }
                    else
                    {
                        return ErrorResult($"Cannot set property '{propName}' - provide color, float_value, or texture_path");
                    }

                    EditorUtility.SetDirty(mat);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { material_path = matPath, property = propName });
                }

                case "get":
                {
                    string matPath = a["material_path"]?.ToString();
                    if (string.IsNullOrEmpty(matPath))
                        return ErrorResult("get requires material_path");

                    var mat = AssetDatabase.LoadAssetAtPath<Material>(matPath);
                    if (mat == null) return ErrorResult($"Material not found: {matPath}");

                    var info = new JObject
                    {
                        ["name"] = mat.name,
                        ["shader"] = mat.shader.name,
                        ["color"] = SerializeColor(mat.color)
                    };
                    if (mat.HasProperty("_Metallic"))
                        info["metallic"] = mat.GetFloat("_Metallic");
                    if (mat.HasProperty("_Glossiness"))
                        info["smoothness"] = mat.GetFloat("_Glossiness");

                    return SuccessResult(info);
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageShader(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get";
            string shaderPath = a["shader_path"]?.ToString();

            if (action == "get")
            {
                if (!string.IsNullOrEmpty(shaderPath))
                {
                    var shader = AssetDatabase.LoadAssetAtPath<Shader>(shaderPath);
                    if (shader == null) return ErrorResult($"Shader not found: {shaderPath}");
                    return SuccessResult(new { shader_path = shaderPath, name = shader.name, render_queue = shader.renderQueue });
                }
                return ErrorResult("shader_path is required");
            }

            if (action == "set_property")
            {
                if (string.IsNullOrEmpty(shaderPath))
                    return ErrorResult("shader_path is required for set_property");
                // Shader properties are set on materials, not shaders directly
                var mat = AssetDatabase.LoadAssetAtPath<Material>(shaderPath);
                if (mat == null) return ErrorResult($"Material not found: {shaderPath}");
                
                string propName = a["property_name"]?.ToString();
                if (propName != null && mat.HasProperty(propName))
                {
                    if (a["float_value"] == null && a["color"] == null) return ErrorResult("Provide float_value or color");
                    Undo.RecordObject(mat, "Set Shader Material Property");
                    if (a["float_value"] != null) mat.SetFloat(propName, a["float_value"].Value<float>());
                    if (a["color"] != null) mat.SetColor(propName, ParseColor(a["color"]));
                    EditorUtility.SetDirty(mat);
                    AssetDatabase.SaveAssets();
                    return SuccessResult(new { shader_path = shaderPath, property = propName });
                }
            }

            return ErrorResult($"Unsupported shader action or missing material property: {action}");
        }

        private static string HandleManagePrefabs(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "create_prefab";

            switch (action)
            {
                case "create_prefab":
                {
                    string goPath = a["gameobject_path"]?.ToString();
                    string prefabPath = a["prefab_path"]?.ToString();
                    if (string.IsNullOrEmpty(goPath) || string.IsNullOrEmpty(prefabPath))
                        return ErrorResult("gameobject_path and prefab_path are required");

                    var source = FindByPath(goPath);
                    if (source == null) return ErrorResult($"GameObject not found: {goPath}");

                    string dir = Path.GetDirectoryName(prefabPath);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                        Directory.CreateDirectory(dir);

                    var prefab = PrefabUtility.SaveAsPrefabAsset(source, AssetDatabase.GenerateUniqueAssetPath(prefabPath));
                    return SuccessResult(new { prefab_path = prefabPath, name = prefab?.name });
                }

                case "create_prefab_variant":
                {
                    string basePath = a["base_prefab_path"]?.ToString();
                    string variantPath = a["variant_path"]?.ToString();
                    if (string.IsNullOrEmpty(basePath) || string.IsNullOrEmpty(variantPath))
                        return ErrorResult("base_prefab_path and variant_path are required");

                    var basePrefab = AssetDatabase.LoadAssetAtPath<GameObject>(basePath);
                    if (basePrefab == null) return ErrorResult($"Base prefab not found: {basePath}");

                    string dir = Path.GetDirectoryName(variantPath);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                        Directory.CreateDirectory(dir);

                    var instance = (GameObject)PrefabUtility.InstantiatePrefab(basePrefab);
                    var variant = PrefabUtility.SaveAsPrefabAsset(instance, AssetDatabase.GenerateUniqueAssetPath(variantPath));
                    UnityEngine.Object.DestroyImmediate(instance);
                    return SuccessResult(new { variant_path = variantPath, base_path = basePath });
                }

                case "add_nested_object_to_prefab":
                {
                    string prefabPath = a["prefab_path"]?.ToString();
                    string objectName = a["object_name"]?.ToString() ?? "NewChild";
                    if (string.IsNullOrEmpty(prefabPath))
                        return ErrorResult("prefab_path is required");

                    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                    if (prefab == null) return ErrorResult($"Prefab not found: {prefabPath}");

                    using (var editingScope = new PrefabUtility.EditPrefabContentsScope(prefabPath))
                    {
                        var child = new GameObject(objectName);
                        child.transform.SetParent(editingScope.prefabContentsRoot.transform, false);
                        return SuccessResult(new { prefab_path = prefabPath, added = objectName });
                    }
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageScriptableObj(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "create";

            switch (action)
            {
                case "create":
                {
                    string typeName = a["type_name"]?.ToString() ?? "ScriptableObject";
                    string savePath = a["save_path"]?.ToString() ?? "Assets/NewScriptableObject.asset";
                    string name = a["name"]?.ToString() ?? "NewScriptableObject";

                    // Resolve the ScriptableObject type
                    Type soType = ResolveComponentType(typeName);
                    if (soType == null || !soType.IsSubclassOf(typeof(ScriptableObject)))
                        return ErrorResult($"ScriptableObject type not found: {typeName}");

                    var so = ScriptableObject.CreateInstance(soType);
                    so.name = name;

                    // Ensure directory exists
                    string dir = Path.GetDirectoryName(savePath);
                    if (!string.IsNullOrEmpty(dir))
                    {
                        var absDir = Path.Combine(Application.dataPath, "..", dir);
                        if (!Directory.Exists(absDir))
                            Directory.CreateDirectory(absDir);
                    }

                    AssetDatabase.CreateAsset(so, savePath);
                    AssetDatabase.SaveAssets();
                    AssetDatabase.Refresh();

                    return SuccessResult(new { asset_path = savePath, type = typeName, name });
                }
                case "get":
                {
                    string assetPath = a["asset_path"]?.ToString();
                    if (string.IsNullOrEmpty(assetPath))
                        return ErrorResult("get requires asset_path");

                    var so = AssetDatabase.LoadAssetAtPath<ScriptableObject>(assetPath);
                    if (so == null) return ErrorResult($"ScriptableObject not found: {assetPath}");

                    var info = new JObject { ["name"] = so.name, ["type"] = so.GetType().FullName };

                    // Read serialized properties
                    var serializedObj = new SerializedObject(so);
                    var prop = serializedObj.GetIterator();
                    while (prop.NextVisible(true))
                    {
                        if (prop.name == "m_Script") continue;
                        try
                        {
                            info[prop.name] = prop.propertyType switch
                            {
                                SerializedPropertyType.String => prop.stringValue,
                                SerializedPropertyType.Integer => prop.intValue,
                                SerializedPropertyType.Boolean => prop.boolValue,
                                SerializedPropertyType.Float => prop.floatValue,
                                _ => prop.propertyType.ToString()
                            };
                        }
                        catch { }
                    }

                    return SuccessResult(info);
                }
                case "set_property":
                {
                    string assetPath = a["asset_path"]?.ToString();
                    string propName = a["property_name"]?.ToString();
                    string propValue = a["value"]?.ToString();
                    if (string.IsNullOrEmpty(assetPath) || string.IsNullOrEmpty(propName))
                        return ErrorResult("set_property requires asset_path and property_name");

                    var so = AssetDatabase.LoadAssetAtPath<ScriptableObject>(assetPath);
                    if (so == null) return ErrorResult($"ScriptableObject not found: {assetPath}");

                    var serializedObj = new SerializedObject(so);
                    var serializedProp = serializedObj.FindProperty(propName);
                    if (serializedProp == null)
                        return ErrorResult($"Property '{propName}' not found on {assetPath}");

                    SetSerializedProperty(serializedProp, propValue, a["asset_reference_path"]?.ToString());
                    serializedObj.ApplyModifiedProperties();
                    EditorUtility.SetDirty(so);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { asset_path = assetPath, property = propName, value = propValue });
                }
                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageAsset(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "list";

            switch (action)
            {
                case "analyze_library_export":
                {
                    string sourceMode = a["source_mode"]?.ToString()
                        ?.Trim().ToLowerInvariant() ?? "selection";
                    bool recursive = a["recursive"]?.Value<bool>() ?? true;
                    var requestedPaths = ParseAssetExportPaths(a["source_paths"]);
                    var prefabPaths = ResolveAssetExportPrefabs(
                        sourceMode,
                        requestedPaths,
                        recursive,
                        out var resolutionErrors);

                    if (prefabPaths.Count > 200)
                        return ErrorResult(
                            $"Asset library export is limited to 200 Prefabs; found {prefabPaths.Count}");

                    var aggregateDependencies = new SortedSet<string>(
                        StringComparer.OrdinalIgnoreCase);
                    var packageDependencies = new SortedDictionary<string, string>(
                        StringComparer.OrdinalIgnoreCase);
                    var blockingDependencies = new SortedSet<string>(
                        StringComparer.OrdinalIgnoreCase);
                    var prefabResults = new JArray();

                    foreach (string prefabPath in prefabPaths)
                    {
                        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                        if (prefab == null)
                        {
                            resolutionErrors.Add($"Prefab could not be loaded: {prefabPath}");
                            continue;
                        }

                        string[] dependencies = AssetDatabase.GetDependencies(
                            prefabPath,
                            true);
                        var projectDependencies = new JArray();
                        foreach (string rawDependency in dependencies)
                        {
                            string dependency = rawDependency.Replace('\\', '/');
                            if (dependency.StartsWith("Packages/", StringComparison.OrdinalIgnoreCase))
                            {
                                packageDependencies[dependency] =
                                    AssetDatabase.AssetPathToGUID(dependency);
                                continue;
                            }
                            if (!dependency.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
                                continue;

                            aggregateDependencies.Add(dependency);
                            projectDependencies.Add(dependency);
                            string extension = Path.GetExtension(dependency).ToLowerInvariant();
                            if (extension == ".cs" || extension == ".dll"
                                || extension == ".asmdef" || extension == ".asmref")
                                blockingDependencies.Add(dependency);
                        }

                        JObject placementGeometry = AnalyzePrefabPlacementGeometry(
                            prefabPath,
                            out Bounds bounds,
                            out string boundsSource);
                        prefabResults.Add(new JObject
                        {
                            ["path"] = prefabPath,
                            ["name"] = prefab.name,
                            ["guid"] = AssetDatabase.AssetPathToGUID(prefabPath),
                            ["default_scale"] = SerializeVector3(prefab.transform.localScale),
                            ["bounds_center"] = SerializeVector3(bounds.center),
                            ["bounds_size"] = SerializeVector3(bounds.size),
                            ["bounds_source"] = boundsSource,
                            ["placement_geometry"] = placementGeometry,
                            ["dependency_paths"] = projectDependencies,
                        });
                    }

                    var dependencyResults = new JArray();
                    string projectRoot = Path.GetFullPath(
                        Path.Combine(Application.dataPath, ".."));
                    foreach (string dependency in aggregateDependencies)
                    {
                        string absolutePath = Path.GetFullPath(
                            Path.Combine(projectRoot, dependency));
                        string extension = Path.GetExtension(dependency).ToLowerInvariant();
                        var fileInfo = new FileInfo(absolutePath);
                        dependencyResults.Add(new JObject
                        {
                            ["path"] = dependency,
                            ["guid"] = AssetDatabase.AssetPathToGUID(dependency),
                            ["type"] = ClassifyAssetExportDependency(extension),
                            ["extension"] = extension,
                            ["size_bytes"] = fileInfo.Exists ? fileInfo.Length : 0,
                            ["exists"] = fileInfo.Exists,
                            ["meta_exists"] = File.Exists(absolutePath + ".meta"),
                            ["blocking"] = blockingDependencies.Contains(dependency),
                        });
                    }

                    return SuccessResult(new
                    {
                        source_mode = sourceMode,
                        recursive,
                        project_path = projectRoot,
                        prefab_count = prefabResults.Count,
                        dependency_count = dependencyResults.Count,
                        prefabs = prefabResults,
                        dependencies = dependencyResults,
                        blocking_dependencies = new JArray(blockingDependencies),
                        package_dependencies = new JArray(
                            packageDependencies.Select(item => new JObject
                            {
                                ["path"] = item.Key,
                                ["guid"] = item.Value,
                            })),
                        errors = new JArray(resolutionErrors),
                        can_export = prefabResults.Count > 0
                            && blockingDependencies.Count == 0
                            && resolutionErrors.Count == 0,
                    });
                }

                case "import_asset":
                {
                    string assetPath = a["asset_path"]?.ToString()
                        ?.Replace('\\', '/');
                    if (string.IsNullOrWhiteSpace(assetPath)
                        || !assetPath.StartsWith("Assets/", StringComparison.Ordinal))
                        return ErrorResult(
                            "asset_path must be a project-relative path under Assets");

                    AssetDatabase.ImportAsset(
                        assetPath,
                        ImportAssetOptions.ImportRecursive
                        | ImportAssetOptions.ForceUpdate);
                    return SuccessResult(new
                    {
                        imported = assetPath,
                        recursive = true,
                    });
                }

                case "duplicate_asset":
                {
                    string src = a["source_path"]?.ToString();
                    string dst = a["destination_path"]?.ToString();
                    if (string.IsNullOrEmpty(src) || string.IsNullOrEmpty(dst))
                        return ErrorResult("source_path and destination_path are required");

                    if (!AssetDatabase.CopyAsset(src, dst))
                        return ErrorResult($"Failed to duplicate asset from {src} to {dst}");

                    AssetDatabase.Refresh();
                    return SuccessResult(new { source = src, destination = dst });
                }

                case "rename_asset":
                {
                    string assetPath = a["asset_path"]?.ToString();
                    string newName = a["new_name"]?.ToString();
                    if (string.IsNullOrEmpty(assetPath) || string.IsNullOrEmpty(newName))
                        return ErrorResult("asset_path and new_name are required");

                    string result = AssetDatabase.RenameAsset(assetPath, newName);
                    if (string.IsNullOrEmpty(result))
                        return SuccessResult(new { renamed = assetPath, new_name = newName });
                    return ErrorResult($"Failed to rename: {result}");
                }

                case "list_all_prefabs_with_bounding_boxes":
                {
                    var guids = AssetDatabase.FindAssets("t:Prefab");
                    var prefabs = new JArray();
                    foreach (var guid in guids.Take(50))
                    {
                        var path = AssetDatabase.GUIDToAssetPath(guid);
                        var go = AssetDatabase.LoadAssetAtPath<GameObject>(path);
                        if (go != null)
                        {
                            var bounds = new Bounds(Vector3.zero, Vector3.zero);
                            foreach (var renderer in go.GetComponentsInChildren<Renderer>())
                                bounds.Encapsulate(renderer.bounds);

                            prefabs.Add(new JObject
                            {
                                ["path"] = path,
                                ["name"] = go.name,
                                ["bounds_center"] = SerializeVector3(bounds.center),
                                ["bounds_size"] = SerializeVector3(bounds.size)
                            });
                        }
                    }
                    return SuccessResult(new { prefabs, count = prefabs.Count });
                }

                case "place_asset_in_scene":
                {
                    string assetPath = a["asset_path"]?.ToString();
                    if (string.IsNullOrEmpty(assetPath))
                        return ErrorResult("asset_path is required");

                    var asset = AssetDatabase.LoadAssetAtPath<GameObject>(assetPath);
                    if (asset == null) return ErrorResult($"Asset not found: {assetPath}");

                    var pos = ParseVector3(a["position"]);
                    var rot = a["rotation"] != null ? Quaternion.Euler(ParseVector3(a["rotation"])) : Quaternion.identity;
                    var instance = (GameObject)PrefabUtility.InstantiatePrefab(asset);
                    instance.transform.position = pos;
                    instance.transform.rotation = rot;
                    if (a["scale"] != null) instance.transform.localScale = ParseVector33(a["scale"]);

                    Undo.RegisterCreatedObjectUndo(instance, $"Place {asset.name}");
                    return SuccessResult(new { placed = assetPath, instanceId = GetInstancePath(instance) });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static List<string> ParseAssetExportPaths(JToken token)
        {
            var paths = new List<string>();
            if (token is JArray array)
            {
                foreach (JToken item in array)
                {
                    string value = item?.ToString()?.Trim();
                    if (!string.IsNullOrWhiteSpace(value))
                        paths.Add(value.Replace('\\', '/'));
                }
            }
            else if (token != null)
            {
                foreach (string item in token.ToString().Split(
                    new[] { ',', '\n', '\r' },
                    StringSplitOptions.RemoveEmptyEntries))
                {
                    string value = item.Trim();
                    if (!string.IsNullOrWhiteSpace(value))
                        paths.Add(value.Replace('\\', '/'));
                }
            }
            return paths;
        }

        private static List<string> ResolveAssetExportPrefabs(
            string sourceMode,
            List<string> requestedPaths,
            bool recursive,
            out List<string> errors)
        {
            errors = new List<string>();
            var candidates = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);

            if (sourceMode == "selection")
            {
                foreach (UnityEngine.Object selected in Selection.objects)
                {
                    string path = AssetDatabase.GetAssetPath(selected);
                    if (string.IsNullOrWhiteSpace(path) && selected is GameObject selectedObject)
                    {
                        var source = PrefabUtility.GetCorrespondingObjectFromOriginalSource(
                            selectedObject);
                        path = AssetDatabase.GetAssetPath(source);
                    }
                    if (string.IsNullOrWhiteSpace(path))
                    {
                        errors.Add($"Selection is not a Prefab asset or instance: {selected.name}");
                        continue;
                    }
                    AddAssetExportCandidate(path, recursive, candidates, errors);
                }
            }
            else if (sourceMode == "paths" || sourceMode == "folder")
            {
                if (requestedPaths.Count == 0)
                    errors.Add("source_paths is required for paths or folder mode");
                foreach (string path in requestedPaths)
                    AddAssetExportCandidate(path, recursive, candidates, errors);
            }
            else
            {
                errors.Add("source_mode must be selection, paths, or folder");
            }

            return candidates.ToList();
        }

        private static void AddAssetExportCandidate(
            string rawPath,
            bool recursive,
            SortedSet<string> candidates,
            List<string> errors)
        {
            string path = rawPath.Replace('\\', '/').TrimEnd('/');
            if (!path.StartsWith("Assets/", StringComparison.OrdinalIgnoreCase))
            {
                errors.Add($"Source path must be under Assets: {path}");
                return;
            }

            if (AssetDatabase.IsValidFolder(path))
            {
                string[] guids = AssetDatabase.FindAssets("t:Prefab", new[] { path });
                foreach (string guid in guids)
                {
                    string prefabPath = AssetDatabase.GUIDToAssetPath(guid).Replace('\\', '/');
                    if (!recursive)
                    {
                        string parent = Path.GetDirectoryName(prefabPath)?.Replace('\\', '/');
                        if (!string.Equals(parent, path, StringComparison.OrdinalIgnoreCase))
                            continue;
                    }
                    candidates.Add(prefabPath);
                }
                return;
            }

            if (!path.EndsWith(".prefab", StringComparison.OrdinalIgnoreCase)
                || AssetDatabase.LoadAssetAtPath<GameObject>(path) == null)
            {
                errors.Add($"Source path is not a Prefab: {path}");
                return;
            }
            candidates.Add(path);
        }

        private static JObject AnalyzePrefabPlacementGeometry(
            string prefabPath,
            out Bounds bounds,
            out string source)
        {
            GameObject root = null;
            try
            {
                root = PrefabUtility.LoadPrefabContents(prefabPath);
                root.transform.position = Vector3.zero;
                root.transform.rotation = Quaternion.identity;
                source = "none";
                bool initialized = false;
                Bounds result = new Bounds(Vector3.zero, Vector3.zero);
                foreach (Renderer renderer in root.GetComponentsInChildren<Renderer>(true))
                {
                    if (!initialized)
                    {
                        result = renderer.bounds;
                        initialized = true;
                    }
                    else result.Encapsulate(renderer.bounds);
                }
                if (initialized)
                {
                    source = "renderers";
                }
                else foreach (Collider collider in root.GetComponentsInChildren<Collider>(true))
                {
                    if (!initialized)
                    {
                        result = collider.bounds;
                        initialized = true;
                    }
                    else result.Encapsulate(collider.bounds);
                }
                if (source != "renderers")
                    source = initialized ? "colliders" : "none";
                bounds = result;
                Vector3 pivot = root.transform.position;
                Vector3 contactCenter = new Vector3(
                    result.center.x,
                    result.min.y,
                    result.center.z);
                float insetX = result.extents.x * 0.65f;
                float insetZ = result.extents.z * 0.65f;
                var contacts = new JArray
                {
                    JToken.FromObject(SerializeVector3(contactCenter - pivot)),
                    JToken.FromObject(SerializeVector3(new Vector3(
                        result.center.x - insetX, result.min.y, result.center.z - insetZ) - pivot)),
                    JToken.FromObject(SerializeVector3(new Vector3(
                        result.center.x + insetX, result.min.y, result.center.z - insetZ) - pivot)),
                    JToken.FromObject(SerializeVector3(new Vector3(
                        result.center.x - insetX, result.min.y, result.center.z + insetZ) - pivot)),
                    JToken.FromObject(SerializeVector3(new Vector3(
                        result.center.x + insetX, result.min.y, result.center.z + insetZ) - pivot)),
                };
                bool hasCollider = root.GetComponentsInChildren<Collider>(true).Length > 0;
                return new JObject
                {
                    ["pivot"] = JToken.FromObject(SerializeVector3(pivot)),
                    ["bounds_min"] = JToken.FromObject(SerializeVector3(result.min)),
                    ["bounds_max"] = JToken.FromObject(SerializeVector3(result.max)),
                    ["pivot_to_contact"] = JToken.FromObject(
                        SerializeVector3(contactCenter - pivot)),
                    ["contact_points"] = contacts,
                    ["top_offset"] = result.max.y - pivot.y,
                    ["centerline_axis"] = "+Z",
                    ["forward"] = JToken.FromObject(
                        SerializeVector3(root.transform.forward)),
                    ["effective_width"] = result.size.x,
                    ["effective_length"] = result.size.z,
                    ["has_collider"] = hasCollider,
                    ["bounds_source"] = source,
                };
            }
            finally
            {
                if (root != null)
                    PrefabUtility.UnloadPrefabContents(root);
            }
        }

        private static string ClassifyAssetExportDependency(string extension)
        {
            switch (extension)
            {
                case ".prefab": return "prefab";
                case ".fbx":
                case ".obj": return "model";
                case ".mat": return "material";
                case ".png":
                case ".jpg":
                case ".jpeg":
                case ".tga":
                case ".psd":
                case ".exr": return "texture";
                case ".anim":
                case ".controller":
                case ".overridecontroller": return "animation";
                case ".shader":
                case ".shadergraph":
                case ".shadersubgraph": return "shader";
                case ".cs":
                case ".dll":
                case ".asmdef":
                case ".asmref": return "script";
                default: return "other";
            }
        }

        private static string HandleManagePackages(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "list";

            switch (action)
            {
                case "list":
                {
                    var packages = new JArray();
                    var request = UnityEditor.PackageManager.Client.List(true);
                    while (!request.IsCompleted)
                        System.Threading.Thread.Sleep(50);

                    if (request.Status == UnityEditor.PackageManager.StatusCode.Success)
                    {
                        foreach (var pkg in request.Result)
                        {
                            packages.Add(new JObject
                            {
                                ["name"] = pkg.name,
                                ["version"] = pkg.version,
                                ["displayName"] = pkg.displayName ?? pkg.name,
                                ["source"] = pkg.source.ToString()
                            });
                        }
                    }
                    return SuccessResult(new { packages, count = packages.Count });
                }
                case "install":
                {
                    string packageName = a["package_name"]?.ToString();
                    string version = a["version"]?.ToString();
                    if (string.IsNullOrEmpty(packageName))
                        return ErrorResult("install requires package_name");

                    string packageId = string.IsNullOrEmpty(version) ? packageName : $"{packageName}@{version}";
                    var request = UnityEditor.PackageManager.Client.Add(packageId);
                    
                    // Wait for completion (with timeout)
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    while (!request.IsCompleted && sw.ElapsedMilliseconds < 60000)
                        System.Threading.Thread.Sleep(100);

                    if (request.Status == UnityEditor.PackageManager.StatusCode.Success)
                        return SuccessResult(new { installed = request.Result.name, version = request.Result.version });
                    else
                        return ErrorResult($"Failed to install {packageId}: {request.Error?.message ?? "Unknown error"}");
                }
                case "remove":
                {
                    string packageName = a["package_name"]?.ToString();
                    if (string.IsNullOrEmpty(packageName))
                        return ErrorResult("remove requires package_name");

                    var request = UnityEditor.PackageManager.Client.Remove(packageName);
                    var sw = System.Diagnostics.Stopwatch.StartNew();
                    while (!request.IsCompleted && sw.ElapsedMilliseconds < 60000)
                        System.Threading.Thread.Sleep(100);

                    if (request.Status == UnityEditor.PackageManager.StatusCode.Success)
                        return SuccessResult(new { removed = packageName });
                    else
                        return ErrorResult($"Failed to remove {packageName}: {request.Error?.message ?? "Unknown error"}");
                }
                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageTexture(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get";
            string texPath = a["texture_path"]?.ToString();

            if (action == "get")
            {
                if (string.IsNullOrEmpty(texPath)) return ErrorResult("texture_path is required");
                var ti = AssetImporter.GetAtPath(texPath) as TextureImporter;
                if (ti == null) return ErrorResult($"Texture not found: {texPath}");
                return SuccessResult(new
                {
                    texture_path = texPath, max_size = ti.maxTextureSize,
                    format = ti.textureCompression.ToString(), mipmap_enabled = ti.mipmapEnabled
                });
            }
            if (action == "set_property" && !string.IsNullOrEmpty(texPath))
            {
                var ti = AssetImporter.GetAtPath(texPath) as TextureImporter;
                if (ti == null) return ErrorResult($"Texture not found: {texPath}");
                if (a["max_size"] == null && a["mipmap_enabled"] == null && a["format"] == null && a["filter_mode"] == null && a["wrap_mode"] == null) return ErrorResult("No supported texture settings supplied");
                if (a["format"] != null) ti.textureCompression = (TextureImporterCompression)Enum.Parse(typeof(TextureImporterCompression), a["format"].ToString(), true);
                if (a["filter_mode"] != null) ti.filterMode = (FilterMode)Enum.Parse(typeof(FilterMode), a["filter_mode"].ToString(), true);
                if (a["wrap_mode"] != null) ti.wrapMode = (TextureWrapMode)Enum.Parse(typeof(TextureWrapMode), a["wrap_mode"].ToString(), true);
                if (a["max_size"] != null) ti.maxTextureSize = a["max_size"].Value<int>();
                if (a["mipmap_enabled"] != null) ti.mipmapEnabled = a["mipmap_enabled"].Value<bool>();
                ti.SaveAndReimport();
                return SuccessResult(new { texture_path = texPath, updated = true });
            }
            return ErrorResult($"Unsupported texture action or missing texture_path: {action}");
        }
    }
}
