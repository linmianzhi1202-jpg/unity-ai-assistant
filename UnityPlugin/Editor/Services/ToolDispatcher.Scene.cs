using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Reflection;
using System.Security.Cryptography;
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

        private static string HandleManageScene(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get_hierarchy";
            
            switch (action)
            {
                case "save":
                    {
                        string savePath = a["path"]?.ToString();
                        var activeScene = EditorSceneManager.GetActiveScene();
                        if (!string.IsNullOrEmpty(savePath))
                        {
                            EditorSceneManager.SaveScene(activeScene, savePath);
                        }
                        else
                        {
                            // Direct save to avoid dialog popups that block MCP
                            if (!string.IsNullOrEmpty(activeScene.path))
                                EditorSceneManager.SaveScene(activeScene, activeScene.path);
                            else
                                return ErrorResult("Cannot save: scene has no path. Use save_as with a path.");
                        }
                    }
                    break;
                case "open":
                    {
                        string path = a["path"]?.ToString();
                        if (!string.IsNullOrEmpty(path))
                            EditorSceneManager.OpenScene(path);
                    }
                    break;
                case "create":
                    {
                        var setup = NewSceneSetup.EmptyScene;
                        var mode = NewSceneMode.Single;
                        var modeStr = a["mode"]?.ToString() ?? "Single";
                        if (modeStr.Equals("Additive", StringComparison.OrdinalIgnoreCase))
                            mode = NewSceneMode.Additive;
                        var scene = EditorSceneManager.NewScene(setup, mode);

                        // Save to specified path if provided
                        string savePath = a["path"]?.ToString();
                        if (!string.IsNullOrEmpty(savePath))
                        {
                            // Ensure directory exists
                            string dir = Path.GetDirectoryName(savePath);
                            if (!string.IsNullOrEmpty(dir) && !Directory.Exists(Path.Combine(Application.dataPath, "..", dir)))
                            {
                                var absDir = Path.Combine(Application.dataPath, "..", dir);
                                if (!Directory.Exists(absDir))
                                    Directory.CreateDirectory(absDir);
                            }
                            EditorSceneManager.SaveScene(scene, savePath);
                            Debug.Log($"[MCP] Scene created and saved to: {savePath}");
                        }
                    }
                    break;
                case "get_hierarchy":
                    {
                        string nameFilter = a["name_filter"]?.ToString();
                        string tagFilter = a["tag_filter"]?.ToString();
                        string componentFilter = a["component_filter"]?.ToString();
                        int maxDepth = Math.Max(0, a["max_depth"]?.Value<int>() ?? int.MaxValue);
                        bool hasFilters = !string.IsNullOrWhiteSpace(nameFilter)
                            || !string.IsNullOrWhiteSpace(tagFilter)
                            || !string.IsNullOrWhiteSpace(componentFilter);
                        Type componentType = null;
                        if (!string.IsNullOrWhiteSpace(componentFilter))
                        {
                            componentType = ResolveComponentType(componentFilter);
                            if (componentType == null)
                                return ErrorResult($"Unknown component type: {componentFilter}");
                        }

                        var roots = SceneManager.GetActiveScene().GetRootGameObjects();
                        var list = new JArray();
                        int matchedCount = 0;
                        int returnedCount = 0;
                        foreach (var go in roots)
                        {
                            var node = SerializeFilteredHierarchy(
                                go,
                                0,
                                maxDepth,
                                nameFilter,
                                tagFilter,
                                componentType,
                                hasFilters,
                                ref matchedCount,
                                ref returnedCount);
                            if (node != null)
                                list.Add(node);
                        }
                        return SuccessResult(new
                        {
                            hierarchy = list,
                            matched_count = matchedCount,
                            returned_count = returnedCount,
                            filters_applied = hasFilters,
                            max_depth = maxDepth == int.MaxValue ? (int?)null : maxDepth
                        });
                    }
                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
            return SuccessResult(new { action });
        }

        private static JObject SerializeFilteredHierarchy(
            GameObject go,
            int depth,
            int maxDepth,
            string nameFilter,
            string tagFilter,
            Type componentType,
            bool hasFilters,
            ref int matchedCount,
            ref int returnedCount)
        {
            bool matches = MatchesHierarchyFilters(go, nameFilter, tagFilter, componentType);
            var children = new JArray();

            if (depth < maxDepth)
            {
                for (int i = 0; i < go.transform.childCount; i++)
                {
                    var childNode = SerializeFilteredHierarchy(
                        go.transform.GetChild(i).gameObject,
                        depth + 1,
                        maxDepth,
                        nameFilter,
                        tagFilter,
                        componentType,
                        hasFilters,
                        ref matchedCount,
                        ref returnedCount);
                    if (childNode != null)
                        children.Add(childNode);
                }
            }

            if (hasFilters && !matches && children.Count == 0)
                return null;

            if (matches)
                matchedCount++;

            returnedCount++;
            var obj = SerializeGameObject(go, false);
            obj["depth"] = depth;
            if (hasFilters)
                obj["matched"] = matches;
            if (children.Count > 0)
                obj["children"] = children;
            return obj;
        }

        private static bool MatchesHierarchyFilters(
            GameObject go,
            string nameFilter,
            string tagFilter,
            Type componentType)
        {
            if (!string.IsNullOrWhiteSpace(nameFilter)
                && go.name.IndexOf(nameFilter, StringComparison.OrdinalIgnoreCase) < 0)
                return false;

            if (!string.IsNullOrWhiteSpace(tagFilter)
                && !string.Equals(go.tag, tagFilter, StringComparison.OrdinalIgnoreCase))
                return false;

            if (componentType != null && go.GetComponent(componentType) == null)
                return false;

            return true;
        }

        private static string HandleManageGameObject(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "list";
            
            switch (action)
            {
                case "create":
                    var name = a["name"] ?? "New GameObject";
                    var position = ParseVector3(a["position"]);
                    var primitiveType = a["primitive_type"]?.ToString();
                    var prefabPath = a["prefab_path"]?.ToString();
                    
                    GameObject go;
                    
                    // Handle primitive type creation
                    if (!string.IsNullOrEmpty(primitiveType))
                    {
                        var primType = (PrimitiveType)Enum.Parse(typeof(PrimitiveType), primitiveType, true);
                        go = GameObject.CreatePrimitive(primType);
                        go.name = name.ToString();
                    }
                    else if (!string.IsNullOrEmpty(prefabPath))
                    {
                        var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
                        if (prefab == null)
                            return ErrorResult($"Prefab not found at path: {prefabPath}");
                        go = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
                        go.name = name.ToString();
                    }
                    else
                    {
                        go = new GameObject(name.ToString());
                    }
                    
                    if (position != Vector3.zero) go.transform.position = position;
                    
                    // Handle rotation
                    if (a["rotation"] != null)
                    {
                        go.transform.rotation = Quaternion.Euler(ParseVector3(a["rotation"]));
                    }
                    
                    // Handle size
                    if (a["size"] != null)
                    {
                        var scale = ParseVector33(a["size"]);
                        go.transform.localScale = scale;
                    }
                    
                    // Handle use_world_coordinates
                    if (a["use_world_coordinates"]?.Value<bool>() == true)
                    {
                        // Position is already in world coordinates since we set transform.position
                    }
                    
                    // Register undo
                    Undo.RegisterCreatedObjectUndo(go, $"Create {go.name}");
                    
                    return SuccessResult(new { instanceId = GetInstancePath(go), name = go.name });

                case "place_prefab_smart":
                    return PlacePrefabSmart(a);

                case "analyze_scene_placement_context":
                    return AnalyzeScenePlacementContext(a);

                case "place_prefab_batch_smart":
                    return PlacePrefabBatchSmart(a);
                    
                case "delete":
                {
                    string path = a["path"]?.ToString();
                    var target = FindByPath(path);
                    if (target != null) Undo.DestroyObjectImmediate(target);
                    return SuccessResult(new { deleted = path });
                }
                    
                case "list":
                    var allGo = FindGameObjects(a["name"]?.ToString());
                    var list = new JArray();
                    foreach (var obj in allGo)
                        list.Add(SerializeGameObject(obj, false));
                    return SuccessResult(new { objects = list, count = allGo.Count });
                    
                case "rename":
                {
                    string path = a["path"]?.ToString();
                    string newName = a["name"]?.ToString();
                    var target = FindByPath(path);
                    if (target != null)
                    {
                        Undo.RecordObject(target, "Rename");
                        target.name = newName;
                    }
                    return SuccessResult(new { renamed = newName });
                }
                    
                case "parent":
                {
                    string childPath = a["child_path"]?.ToString();
                    string parentPath = a["parent_path"]?.ToString();
                    bool worldStays = a["world_position_stays"]?.Value<bool>() ?? true;

                    var child = FindByPath(childPath);
                    if (child == null) return ErrorResult($"Child not found: {childPath}");

                    if (string.IsNullOrEmpty(parentPath))
                    {
                        // Unparent
                        Undo.SetTransformParent(child.transform, null, "Unparent");
                        child.transform.SetParent(null, true);
                        return SuccessResult(new { child = GetInstancePath(child), parent = (string)null, action = "unparent" });
                    }

                    var parentObj = FindByPath(parentPath);
                    if (parentObj == null) return ErrorResult($"Parent not found: {parentPath}");

                    Undo.SetTransformParent(child.transform, parentObj.transform, "Parent GameObject");
                    child.transform.SetParent(parentObj.transform, worldStays);
                    return SuccessResult(new { child = GetInstancePath(child), parent = parentPath, world_position_stays = worldStays });
                }

                case "duplicate":
                {
                    string path = a["path"]?.ToString();
                    string newName = a["name"]?.ToString();
                    var source = FindByPath(path);
                    if (source == null) return ErrorResult($"Source not found: {path}");

                    var duplicate = UnityEngine.Object.Instantiate(source, source.transform.parent, true);
                    duplicate.name = string.IsNullOrEmpty(newName) ? source.name + "_Copy" : newName;
                    Undo.RegisterCreatedObjectUndo(duplicate, $"Duplicate {source.name}");
                    return SuccessResult(new { original = path, duplicate = GetInstancePath(duplicate), name = duplicate.name });
                }

                case "set_sibling_index":
                {
                    string path = a["path"]?.ToString();
                    int siblingIndex = a["index"]?.Value<int>() ?? 0;
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"Object not found: {path}");

                    Undo.RecordObject(target.transform, "Set Sibling Index");
                    target.transform.SetSiblingIndex(siblingIndex);
                    return SuccessResult(new { path = path, sibling_index = siblingIndex, parent = target.transform.parent?.name });
                }

                case "set_tag":
                {
                    string path = a["path"]?.ToString();
                    string tag = a["tag"]?.ToString() ?? "Untagged";
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"Object not found: {path}");

                    Undo.RecordObject(target, "Set Tag");
                    target.tag = tag;
                    return SuccessResult(new { path = path, tag = tag });
                }

                case "set_layer":
                {
                    string path = a["path"]?.ToString();
                    int layer = a["layer"]?.Value<int>() ?? 0;
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"Object not found: {path}");

                    Undo.RecordObject(target, "Set Layer");
                    target.layer = layer;
                    return SuccessResult(new { path = path, layer = layer, layer_name = LayerMask.LayerToName(layer) });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string PlacePrefabSmart(JObject args)
        {
            string prefabPath = args["prefab_path"]?.ToString();
            if (string.IsNullOrWhiteSpace(prefabPath))
                return ErrorResult("prefab_path is required");

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(prefabPath);
            if (prefab == null)
                return ErrorResult($"Prefab not found at path: {prefabPath}");

            string referencePath = args["reference_path"]?.ToString();
            var reference = string.IsNullOrWhiteSpace(referencePath)
                ? null
                : FindByPath(referencePath);
            if (!string.IsNullOrWhiteSpace(referencePath) && reference == null)
                return ErrorResult($"Reference object not found: {referencePath}");

            string supportPath = args["support_reference_path"]?.ToString();
            var supportReference = string.IsNullOrWhiteSpace(supportPath)
                ? null
                : FindByPath(supportPath);
            if (!string.IsNullOrWhiteSpace(supportPath) && supportReference == null)
                return ErrorResult($"Support object not found: {supportPath}");
            string surfaceZone = args["surfaceZone"]?.ToString() ?? "near";
            string groundingGroup = args["groundingGroup"]?.ToString() ?? "";
            string supportSurfaceType = args["supportSurfaceType"]?.ToString() ?? "ground";
            float lateralOffset = args["lateralOffset"]?.Value<float>() ?? 0f;
            float maxSlopeDegrees = Mathf.Clamp(
                args["maxSlopeDegrees"]?.Value<float>() ?? 25f,
                0f,
                89f);
            bool alignToPath = args["alignToPath"]?.Value<bool>() ?? false;
            var forbiddenZones = new HashSet<string>(
                (args["forbiddenZones"] as JArray ?? new JArray())
                    .Select(item => item.ToString()),
                StringComparer.OrdinalIgnoreCase);
            if (forbiddenZones.Contains(surfaceZone))
                return ErrorResult($"Surface zone is forbidden for this asset: {surfaceZone}");
            var allowedSurfaceTypes = new HashSet<string>(
                (args["allowedSurfaceTypes"] as JArray ?? new JArray())
                    .Select(item => item.ToString()),
                StringComparer.OrdinalIgnoreCase);
            if (supportReference != null
                && allowedSurfaceTypes.Count > 0
                && !allowedSurfaceTypes.Contains(supportSurfaceType))
            {
                return ErrorResult(
                    $"Asset cannot be placed on surface type '{supportSurfaceType}'");
            }

            string relation = (args["relation"]?.ToString() ?? "near")
                .Trim()
                .ToLowerInvariant();
            var supportedRelations = new HashSet<string>
            {
                "near", "left", "right", "front", "behind", "on"
            };
            if (!supportedRelations.Contains(relation))
                return ErrorResult(
                    "relation must be near, left, right, front, behind, or on");

            float minimumClearance = Mathf.Max(
                0f,
                args["minimum_clearance"]?.Value<float>() ?? 0f);
            float distance = Mathf.Max(
                minimumClearance,
                Mathf.Max(0f, args["distance"]?.Value<float>() ?? 2f));
            bool groundSnap = args["ground_snap"]?.Value<bool>() ?? true;
            bool avoidCollisions = args["avoid_collisions"]?.Value<bool>() ?? true;
            bool faceReference = args["face_reference"]?.Value<bool>() ?? false;
            float groundOffset = args["ground_offset"]?.Value<float>() ?? 0f;
            string forwardAxis = args["forward_axis"]?.ToString() ?? "+Z";
            int maxAttempts = Mathf.Clamp(args["max_attempts"]?.Value<int>() ?? 12, 1, 36);
            bool hasExplicitPosition = args["position"] != null;
            bool positionIsGroundPoint =
                args["position_is_ground_point"]?.Value<bool>() ?? false;
            bool hasFallbackGroundY = args["fallback_ground_y"] != null;
            float fallbackGroundY = hasFallbackGroundY
                ? args["fallback_ground_y"].Value<float>()
                : 0f;

            var instance = (GameObject)PrefabUtility.InstantiatePrefab(prefab);
            if (instance == null)
                return ErrorResult($"Failed to instantiate prefab: {prefabPath}");

            instance.name = args["name"]?.ToString() ?? prefab.name;
            if (args["scale"] != null)
                instance.transform.localScale = ParseVector33(args["scale"]);
            if (args["rotation"] != null)
                instance.transform.rotation = Quaternion.Euler(ParseVector3(args["rotation"]));
            if (alignToPath && supportReference != null)
            {
                Vector3 pathForward = supportReference.transform.forward;
                pathForward.y = 0f;
                if (pathForward.sqrMagnitude > 0.0001f)
                    instance.transform.rotation = Quaternion.LookRotation(
                        pathForward.normalized,
                        Vector3.up) * ForwardAxisCorrection(forwardAxis);
            }

            if (!TryGetObjectBounds(instance, out var initialBounds))
            {
                UnityEngine.Object.DestroyImmediate(instance);
                return ErrorResult(
                    $"Prefab has no Renderer or Collider bounds: {prefabPath}");
            }
            Vector3 pivotToBoundsCenter =
                instance.transform.position - initialBounds.center;

            Bounds referenceBounds = default;
            if (reference != null && !TryGetObjectBounds(reference, out referenceBounds))
                referenceBounds = new Bounds(reference.transform.position, Vector3.zero);

            Vector3 explicitPosition = hasExplicitPosition
                ? ParseVector3(args["position"])
                : Vector3.zero;
            Vector3 baseDirection = GetPlacementDirection(reference, relation);
            bool collisionFree = false;
            bool grounded = false;
            string groundingSource = "none";
            GameObject groundSupport = null;
            Vector3 surfaceNormal = Vector3.up;
            float contactError = float.PositiveInfinity;
            var blockingObjects = new List<string>();
            int attemptsUsed = 0;

            for (int attempt = 0; attempt < maxAttempts; attempt++)
            {
                attemptsUsed = attempt + 1;
                Vector3 candidatePosition;
                if (hasExplicitPosition)
                {
                    candidatePosition = explicitPosition;
                    if (attempt > 0)
                    {
                        float radius = distance * (1f + ((attempt - 1) / 8f));
                        float angle = (attempt - 1) * 45f;
                        candidatePosition += Quaternion.Euler(0f, angle, 0f)
                            * Vector3.right * Mathf.Max(radius, 0.5f);
                    }
                }
                else if (reference != null)
                {
                    Vector3 direction = baseDirection;
                    if (attempt > 0 && relation != "on")
                    {
                        float angle = AlternatingPlacementAngle(attempt);
                        direction = Quaternion.Euler(0f, angle, 0f) * baseDirection;
                    }
                    candidatePosition = PositionRelativeToReference(
                        initialBounds,
                        pivotToBoundsCenter,
                        referenceBounds,
                        direction,
                        relation,
                        distance,
                        attempt);
                }
                else
                {
                    float angle = attempt * 45f;
                    float radius = attempt == 0 ? 0f : Mathf.Max(distance, 0.5f);
                    candidatePosition = Quaternion.Euler(0f, angle, 0f)
                        * Vector3.right * radius;
                }

                instance.transform.position = candidatePosition;
                grounded = false;
                groundingSource = "none";
                groundSupport = null;
                surfaceNormal = Vector3.up;
                contactError = float.PositiveInfinity;

                if (supportReference != null && groundSnap)
                {
                    grounded = TrySnapObjectToSupport(
                        instance,
                        supportReference,
                        maxSlopeDegrees,
                        out groundingSource,
                        out surfaceNormal,
                        out contactError);
                    groundSupport = grounded ? supportReference : null;
                }
                else if (reference != null && relation == "on")
                {
                    if (TryGetObjectBounds(instance, out var instanceBounds))
                    {
                        instance.transform.position += Vector3.up
                            * (referenceBounds.max.y - instanceBounds.min.y);
                        grounded = true;
                        groundingSource = "reference";
                        groundSupport = reference;
                        surfaceNormal = reference.transform.up;
                        contactError = 0f;
                    }
                }
                else if (groundSnap)
                {
                    grounded = TrySnapObjectToGround(
                        instance,
                        out groundingSource,
                        out groundSupport);
                }
                if (!grounded && supportReference != null)
                {
                    blockingObjects = new List<string>
                    {
                        $"support:{GetInstancePath(supportReference)}"
                    };
                    collisionFree = false;
                    continue;
                }
                if (!grounded && relation != "on")
                {
                    bool useFallbackPlane =
                        (hasExplicitPosition && positionIsGroundPoint)
                        || (reference == null && hasFallbackGroundY);
                    if (useFallbackPlane
                        && TryGetObjectBounds(instance, out var fallbackBounds))
                    {
                        float planeY = hasExplicitPosition && positionIsGroundPoint
                            ? explicitPosition.y
                            : fallbackGroundY;
                        instance.transform.position += Vector3.up
                            * (planeY - fallbackBounds.min.y);
                        grounded = true;
                        groundingSource = "fallback_plane";
                        surfaceNormal = Vector3.up;
                        contactError = 0f;
                    }
                }
                if (grounded && Mathf.Abs(groundOffset) > 0.0001f)
                    instance.transform.position += Vector3.up * groundOffset;

                blockingObjects = avoidCollisions
                    ? FindBlockingBoundsIntersections(
                        instance,
                        groundSupport,
                        minimumClearance)
                    : new List<string>();
                collisionFree = blockingObjects.Count == 0;
                if (collisionFree)
                    break;
            }

            if (!collisionFree)
            {
                UnityEngine.Object.DestroyImmediate(instance);
                return ErrorResult(
                    $"No collision-free placement found after {attemptsUsed} attempts. "
                    + $"Blocking objects: {string.Join(", ", blockingObjects)}");
            }

            if (faceReference && reference != null)
            {
                Vector3 lookDirection = referenceBounds.center
                    - instance.transform.position;
                lookDirection.y = 0f;
                if (lookDirection.sqrMagnitude > 0.0001f)
                    instance.transform.rotation =
                        Quaternion.LookRotation(
                            lookDirection.normalized,
                            Vector3.up)
                        * ForwardAxisCorrection(forwardAxis);
            }

            Undo.RegisterCreatedObjectUndo(instance, $"Place {instance.name}");
            EditorSceneManager.MarkSceneDirty(instance.scene);

            TryGetObjectBounds(instance, out var finalBounds);
            return SuccessResult(new
            {
                instanceId = GetInstancePath(instance),
                path = GetInstancePath(instance),
                name = instance.name,
                prefab_path = prefabPath,
                reference_path = reference != null ? GetInstancePath(reference) : null,
                support_reference = supportReference != null
                    ? GetInstancePath(supportReference)
                    : null,
                zone_reference = args["zone_reference_path"]?.ToString(),
                surface_zone = surfaceZone,
                grounding_group = groundingGroup,
                support_surface_type = supportSurfaceType,
                support_evidence = args["supportEvidence"],
                surface_normal = SerializeVector3(surfaceNormal),
                contact_error = float.IsPositiveInfinity(contactError)
                    ? (float?)null
                    : contactError,
                lateral_offset = lateralOffset,
                align_to_path = alignToPath,
                forbidden_zone_violations = new string[0],
                relation,
                position = SerializeVector3(instance.transform.position),
                rotation = SerializeVector3(instance.transform.eulerAngles),
                scale = SerializeVector3(instance.transform.localScale),
                bounds = SerializeBounds(finalBounds),
                grounded,
                grounding_source = groundingSource,
                ground_offset = groundOffset,
                minimum_clearance = minimumClearance,
                forward_axis = forwardAxis,
                collision_free = collisionFree,
                blocking_objects = blockingObjects,
                attempts = attemptsUsed,
            });
        }

        private static string AnalyzeScenePlacementContext(JObject args)
        {
            var scene = EditorSceneManager.GetActiveScene();
            string referencePath = args["reference_path"]?.ToString();
            var reference = string.IsNullOrWhiteSpace(referencePath)
                ? null
                : FindByPath(referencePath);
            if (!string.IsNullOrWhiteSpace(referencePath) && reference == null)
                return ErrorResult($"Reference object not found: {referencePath}");

            var objects = new JArray();
            var grounds = new JArray();
            var surfaces = new JArray();
            foreach (var root in scene.GetRootGameObjects())
            {
                foreach (var transform in root.GetComponentsInChildren<Transform>(true))
                {
                    var gameObject = transform.gameObject;
                    var item = new JObject
                    {
                        ["name"] = gameObject.name,
                        ["path"] = GetInstancePath(gameObject),
                        ["position"] = JToken.FromObject(SerializeVector3(transform.position)),
                        ["rotation"] = JToken.FromObject(SerializeVector3(transform.eulerAngles)),
                        ["active"] = gameObject.activeInHierarchy,
                        ["layer"] = LayerMask.LayerToName(gameObject.layer),
                    };
                    if (TryGetObjectBounds(gameObject, out var bounds))
                        item["bounds"] = JToken.FromObject(SerializeBounds(bounds));
                    objects.Add(item);

                    string surfaceType = ClassifySceneSurface(gameObject);
                    if (!string.IsNullOrEmpty(surfaceType) && item["bounds"] != null)
                    {
                        var surface = (JObject)item.DeepClone();
                        surface["surface_type"] = surfaceType;
                        surface["proxy_surface"] =
                            gameObject.GetComponentsInChildren<Collider>(true).Length == 0;
                        surfaces.Add(surface);
                        if (surfaceType == "terrain" || surfaceType == "ground")
                            grounds.Add(surface.DeepClone());
                    }
                }
            }

            return SuccessResult(new
            {
                scene_path = scene.path,
                scene_name = scene.name,
                scene_dirty = scene.isDirty,
                scene_token = ComputeSceneToken(scene),
                reference_object = reference != null ? GetInstancePath(reference) : null,
                object_count = objects.Count,
                objects,
                grounds,
                surfaces,
                region_center = args["region_center"],
                region_size = args["region_size"],
            });
        }

        private static string ClassifySceneSurface(GameObject gameObject)
        {
            if (gameObject.GetComponent<Terrain>() != null)
                return "terrain";
            string name = gameObject.name.ToLowerInvariant();
            if (name.Contains("\u9053\u8def") || name.Contains("\u8def\u9762"))
                return "road";
            if (name.Contains("\u6865"))
                return "bridge";
            if (name.Contains("\u5e73\u53f0") || name.Contains("\u53f0\u57fa"))
                return "platform";
            if (name.Contains("\u5730\u9762") || name.Contains("\u5730\u5f62"))
                return "ground";
            if (name.Contains("road") || name.Contains("道路") || name.Contains("路面"))
                return "road";
            if (name.Contains("bridge") || name.Contains("桥"))
                return "bridge";
            if (name.Contains("platform") || name.Contains("平台") || name.Contains("台基"))
                return "platform";
            if (name.Contains("ground") || name.Contains("terrain") || name.Contains("地面"))
                return "ground";
            return "";
        }

        private static bool IsGroundSurfaceCandidate(Transform candidate)
        {
            for (Transform current = candidate; current != null; current = current.parent)
            {
                var gameObject = current.gameObject;
                if (gameObject.GetComponent<Terrain>() != null)
                    return true;

                string layerName = LayerMask.LayerToName(gameObject.layer);
                if (string.Equals(layerName, "Ground", StringComparison.OrdinalIgnoreCase)
                    || string.Equals(layerName, "Terrain", StringComparison.OrdinalIgnoreCase))
                    return true;

                if (!string.IsNullOrEmpty(ClassifySceneSurface(gameObject)))
                    return true;
            }
            return false;
        }

        private static string ComputeSceneToken(Scene scene)
        {
            var builder = new StringBuilder();
            builder.Append(scene.path).Append('|').Append(scene.name).Append('|');
            foreach (var root in scene.GetRootGameObjects().OrderBy(item => item.name))
            {
                foreach (var transform in root.GetComponentsInChildren<Transform>(true)
                    .OrderBy(item => GetInstancePath(item.gameObject)))
                {
                    builder.Append(GetInstancePath(transform.gameObject)).Append('|')
                        .Append(transform.position.ToString("R")).Append('|')
                        .Append(transform.rotation.eulerAngles.ToString("R")).Append('|')
                        .Append(transform.localScale.ToString("R")).Append('|')
                        .Append(transform.gameObject.activeSelf).Append(';');
                }
            }
            using (var sha = SHA256.Create())
            {
                byte[] digest = sha.ComputeHash(Encoding.UTF8.GetBytes(builder.ToString()));
                return BitConverter.ToString(digest).Replace("-", "").ToLowerInvariant();
            }
        }

        private static string PlacePrefabBatchSmart(JObject args)
        {
            string expectedToken = args["scene_token"]?.ToString();
            var scene = EditorSceneManager.GetActiveScene();
            if (!string.IsNullOrWhiteSpace(expectedToken)
                && !string.Equals(expectedToken, ComputeSceneToken(scene), StringComparison.Ordinal))
            {
                return ErrorResult("Scene changed after preview; preview again");
            }

            var placements = args["placements"] as JArray;
            if (placements == null || placements.Count == 0)
                return ErrorResult("placements must contain at least one item");

            int undoGroup = Undo.GetCurrentGroup();
            Undo.SetCurrentGroupName("Place Asset Scene Plan");
            var aliases = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            var groundingSupports = new Dictionary<string, string>(
                StringComparer.OrdinalIgnoreCase);
            var results = new JArray();
            Vector3 regionCenter = ParseOptionalVector3(
                args["region_center"],
                Vector3.zero);
            try
            {
                foreach (var token in placements)
                {
                    if (!(token is JObject placement))
                        throw new ArgumentException("Each placement must be an object");
                    var call = (JObject)placement.DeepClone();
                    string referencePath = call["reference"]?.ToString() ?? "";
                    if (referencePath.StartsWith("@", StringComparison.Ordinal))
                    {
                        string aliasReference = referencePath.Substring(1);
                        if (!aliases.TryGetValue(aliasReference, out referencePath))
                            throw new InvalidOperationException(
                                $"Placement reference alias was not created: {aliasReference}");
                    }
                    call["reference_path"] = referencePath;
                    string supportPath = call["supportReference"]?.ToString() ?? "";
                    if (supportPath.StartsWith("@", StringComparison.Ordinal))
                    {
                        string supportAlias = supportPath.Substring(1);
                        if (!aliases.TryGetValue(supportAlias, out supportPath))
                            throw new InvalidOperationException(
                                $"Placement support alias was not created: {supportAlias}");
                    }
                    call["support_reference_path"] = supportPath;
                    string groundingGroup = call["groundingGroup"]?.ToString() ?? "";
                    if (!string.IsNullOrWhiteSpace(groundingGroup))
                    {
                        if (groundingSupports.TryGetValue(
                            groundingGroup,
                            out string expectedSupport)
                            && !string.Equals(
                                expectedSupport,
                                supportPath,
                                StringComparison.OrdinalIgnoreCase))
                        {
                            throw new InvalidOperationException(
                                $"Grounding group '{groundingGroup}' resolved to multiple supports");
                        }
                        groundingSupports[groundingGroup] = supportPath;
                    }
                    string zonePath = call["zoneReference"]?.ToString() ?? supportPath;
                    if (zonePath.StartsWith("@", StringComparison.Ordinal))
                    {
                        string zoneAlias = zonePath.Substring(1);
                        if (!aliases.TryGetValue(zoneAlias, out zonePath))
                            throw new InvalidOperationException(
                                $"Placement zone alias was not created: {zoneAlias}");
                    }
                    call["zone_reference_path"] = zonePath;
                    if (call["fallback_ground_y"] == null)
                        call["fallback_ground_y"] = regionCenter.y;

                    string layout = (call["layout"]?.ToString() ?? "single").ToLowerInvariant();
                    string surfaceZone = call["surfaceZone"]?.ToString() ?? "near";
                    var zoneObject = string.IsNullOrWhiteSpace(zonePath)
                        ? null
                        : FindByPath(zonePath);
                    if (zoneObject != null
                        && surfaceZone != "near"
                        && surfaceZone != "anchor")
                    {
                        if (!TryGetObjectBounds(zoneObject, out var supportBounds))
                            throw new InvalidOperationException(
                                $"Zone reference has no usable bounds: {zonePath}");
                        int surfaceSlot = call["surface_slot_index"]?.Value<int>() ?? 0;
                        float spacing = Mathf.Max(
                            0.25f,
                            call["distance"]?.Value<float>() ?? 2f);
                        float lateral = call["lateralOffset"]?.Value<float>() ?? 0f;
                        float assetHalfWidth = Mathf.Max(
                            0f,
                            call["footprint"]?["x"]?.Value<float>() ?? 0f) / 2f;
                        call["position"] = JToken.FromObject(
                            SerializeVector3(CalculateSupportZonePosition(
                                zoneObject,
                                supportBounds,
                                surfaceZone,
                                surfaceSlot,
                                spacing,
                                lateral,
                                assetHalfWidth)));
                        call["position_is_ground_point"] = true;
                    }
                    else if (layout != "single")
                    {
                        int layoutIndex = call["layout_index"]?.Value<int>() ?? 0;
                        float distance = Mathf.Max(0.1f, call["distance"]?.Value<float>() ?? 2f);
                        var reference = string.IsNullOrWhiteSpace(referencePath)
                            ? null
                            : FindByPath(referencePath);
                        Vector3 center = reference != null
                            ? reference.transform.position
                            : regionCenter;
                        call["position"] = JToken.FromObject(
                            SerializeVector3(CalculateBatchPosition(
                                center, reference, layout, layoutIndex, distance)));
                        call["position_is_ground_point"] = true;
                    }

                    string response = PlacePrefabSmart(call);
                    var parsed = JObject.Parse(response);
                    if (!string.Equals(parsed["status"]?.ToString(), "success", StringComparison.OrdinalIgnoreCase))
                    {
                        bool required = call["required"]?.Value<bool>() ?? true;
                        if (required)
                            throw new InvalidOperationException(
                                parsed["error"]?.ToString() ?? "Required placement failed");
                        results.Add(new JObject
                        {
                            ["alias"] = call["alias"],
                            ["status"] = "skipped",
                            ["error"] = parsed["error"],
                        });
                        continue;
                    }
                    var result = parsed["result"] as JObject ?? new JObject();
                    string alias = call["alias"]?.ToString() ?? "";
                    string path = result["path"]?.ToString() ?? "";
                    if (!string.IsNullOrWhiteSpace(alias) && !string.IsNullOrWhiteSpace(path))
                        aliases[alias] = path;
                    result["alias"] = alias;
                    result["role"] = call["role"];
                    results.Add(result);
                }
                Undo.CollapseUndoOperations(undoGroup);
                return SuccessResult(new
                {
                    placed_count = results.Count,
                    placements = results,
                    undo_group = undoGroup,
                    scene_token_before = expectedToken,
                    scene_token_after = ComputeSceneToken(scene),
                });
            }
            catch (Exception exc)
            {
                Undo.RevertAllDownToGroup(undoGroup);
                return ErrorResult($"Batch placement rolled back: {exc.Message}");
            }
        }

        private static Vector3 ParseOptionalVector3(JToken token, Vector3 fallback)
        {
            return token == null || token.Type == JTokenType.Null
                ? fallback
                : ParseVector3(token);
        }

        private static Vector3 CalculateBatchPosition(
            Vector3 center,
            GameObject reference,
            string layout,
            int index,
            float spacing)
        {
            Vector3 right = reference != null ? reference.transform.right : Vector3.right;
            Vector3 forward = reference != null ? reference.transform.forward : Vector3.forward;
            right.y = 0f;
            forward.y = 0f;
            right = right.sqrMagnitude > 0.0001f ? right.normalized : Vector3.right;
            forward = forward.sqrMagnitude > 0.0001f ? forward.normalized : Vector3.forward;
            switch (layout)
            {
                case "pair":
                    return center + right * (index % 2 == 0 ? -spacing : spacing);
                case "pair_line":
                    return center
                        + right * (index % 2 == 0 ? -spacing : spacing)
                        + forward * (index / 2) * spacing * 2f;
                case "line":
                    return center + forward * index * spacing;
                case "grid":
                    int width = Mathf.Max(1, Mathf.CeilToInt(Mathf.Sqrt(index + 1)));
                    return center + right * (index % width) * spacing
                        + forward * (index / width) * spacing;
                case "ring":
                    float ringAngle = index * 45f;
                    return center + Quaternion.Euler(0f, ringAngle, 0f) * forward * spacing;
                case "scatter":
                    float angle = index * 137.5f;
                    float radius = spacing * (1f + index * 0.35f);
                    return center + Quaternion.Euler(0f, angle, 0f) * forward * radius;
                default:
                    return center;
            }
        }

        private static Vector3 CalculateSupportZonePosition(
            GameObject support,
            Bounds bounds,
            string zone,
            int index,
            float spacing,
            float lateralOffset,
            float assetHalfWidth)
        {
            Vector3 right = support.transform.right;
            Vector3 forward = support.transform.forward;
            right.y = 0f;
            forward.y = 0f;
            right = right.sqrMagnitude > 0.0001f ? right.normalized : Vector3.right;
            forward = forward.sqrMagnitude > 0.0001f ? forward.normalized : Vector3.forward;
            float halfWidth = Mathf.Abs(right.x) * bounds.extents.x
                + Mathf.Abs(right.z) * bounds.extents.z;
            float halfLength = Mathf.Abs(forward.x) * bounds.extents.x
                + Mathf.Abs(forward.z) * bounds.extents.z;
            int pairIndex = index / 2;
            float longitudinal = pairIndex == 0
                ? 0f
                : (pairIndex % 2 == 1 ? 1f : -1f)
                    * Mathf.Ceil(pairIndex / 2f) * spacing;
            longitudinal = Mathf.Clamp(
                longitudinal,
                -Mathf.Max(0f, halfLength - spacing * 0.5f),
                Mathf.Max(0f, halfLength - spacing * 0.5f));
            float sideDistance = halfWidth
                + Mathf.Abs(lateralOffset)
                + Mathf.Max(0f, assetHalfWidth);
            Vector3 offset;
            switch ((zone ?? "near").ToLowerInvariant())
            {
                case "top":
                    offset = right * lateralOffset + forward * longitudinal;
                    break;
                case "left_side":
                    offset = -right * sideDistance + forward * longitudinal;
                    break;
                case "right_side":
                    offset = right * sideDistance + forward * longitudinal;
                    break;
                case "left_outer":
                    offset = -right * sideDistance + forward * longitudinal;
                    break;
                case "right_outer":
                    offset = right * sideDistance + forward * longitudinal;
                    break;
                case "backdrop":
                    offset = -forward * (halfLength + Mathf.Abs(lateralOffset));
                    break;
                default:
                    offset = Vector3.zero;
                    break;
            }
            return new Vector3(
                bounds.center.x + offset.x,
                bounds.max.y,
                bounds.center.z + offset.z);
        }

        private static bool TryGetObjectBounds(GameObject gameObject, out Bounds bounds)
        {
            string source;
            return TryGetCombinedBounds(
                gameObject.GetComponentsInChildren<Renderer>(true),
                gameObject.GetComponentsInChildren<Collider>(true),
                out bounds,
                out source);
        }

        private static Vector3 GetPlacementDirection(
            GameObject reference,
            string relation)
        {
            if (reference == null)
                return Vector3.right;

            Vector3 right = reference.transform.right;
            right.y = 0f;
            if (right.sqrMagnitude < 0.0001f)
                right = Vector3.right;
            right.Normalize();

            Vector3 forward = reference.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.0001f)
                forward = Vector3.forward;
            forward.Normalize();

            return relation switch
            {
                "left" => -right,
                "front" => forward,
                "behind" => -forward,
                _ => right,
            };
        }

        private static float AlternatingPlacementAngle(int attempt)
        {
            int step = (attempt + 1) / 2;
            return step * 45f * (attempt % 2 == 1 ? 1f : -1f);
        }

        private static Quaternion ForwardAxisCorrection(string forwardAxis)
        {
            switch ((forwardAxis ?? "+Z").Trim().ToUpperInvariant())
            {
                case "-Z":
                    return Quaternion.Euler(0f, 180f, 0f);
                case "+X":
                    return Quaternion.Euler(0f, -90f, 0f);
                case "-X":
                    return Quaternion.Euler(0f, 90f, 0f);
                default:
                    return Quaternion.identity;
            }
        }

        private static Vector3 PositionRelativeToReference(
            Bounds instanceBounds,
            Vector3 pivotToBoundsCenter,
            Bounds referenceBounds,
            Vector3 direction,
            string relation,
            float distance,
            int attempt)
        {
            if (relation == "on")
            {
                Vector3 onTargetCenter = referenceBounds.center;
                return new Vector3(
                    onTargetCenter.x + pivotToBoundsCenter.x,
                    referenceBounds.max.y + pivotToBoundsCenter.y,
                    onTargetCenter.z + pivotToBoundsCenter.z);
            }

            direction.y = 0f;
            direction.Normalize();
            float referenceRadius =
                Mathf.Abs(direction.x) * referenceBounds.extents.x
                + Mathf.Abs(direction.z) * referenceBounds.extents.z;
            float instanceRadius =
                Mathf.Abs(direction.x) * instanceBounds.extents.x
                + Mathf.Abs(direction.z) * instanceBounds.extents.z;
            float extraDistance = distance + (attempt / 8) * Mathf.Max(distance, 0.5f);
            Vector3 targetCenter = referenceBounds.center
                + direction * (referenceRadius + instanceRadius + extraDistance);
            // If no ground surface can be sampled, related objects should
            // share a foot plane rather than align their differently sized
            // bounds by center height.
            float pivotToBoundsBottom =
                pivotToBoundsCenter.y + instanceBounds.extents.y;
            return new Vector3(
                targetCenter.x + pivotToBoundsCenter.x,
                referenceBounds.min.y + pivotToBoundsBottom,
                targetCenter.z + pivotToBoundsCenter.z);
        }

        private static bool TrySnapObjectToGround(
            GameObject instance,
            out string source,
            out GameObject support)
        {
            source = "none";
            support = null;
            if (!TryGetObjectBounds(instance, out var bounds))
                return false;

            Vector3 rayOrigin = new Vector3(
                bounds.center.x,
                Mathf.Max(bounds.max.y + 100f, 1000f),
                bounds.center.z);
            var hits = Physics.RaycastAll(
                rayOrigin,
                Vector3.down,
                Mathf.Infinity,
                Physics.DefaultRaycastLayers,
                QueryTriggerInteraction.Ignore);
            RaycastHit? bestHit = null;
            float bestHitDelta = float.PositiveInfinity;
            foreach (var hit in hits)
            {
                if (hit.collider == null
                    || hit.collider.transform.IsChildOf(instance.transform)
                    || !IsGroundSurfaceCandidate(hit.collider.transform))
                    continue;

                float delta = Mathf.Abs(hit.point.y - bounds.min.y);
                if (delta < bestHitDelta)
                {
                    bestHitDelta = delta;
                    bestHit = hit;
                }
            }
            if (bestHit.HasValue)
            {
                instance.transform.position += Vector3.up
                    * (bestHit.Value.point.y - bounds.min.y);
                source = "physics";
                support = bestHit.Value.collider.gameObject;
                return true;
            }

            float bestTop = float.NegativeInfinity;
            float bestTopDelta = float.PositiveInfinity;
            foreach (var candidate in FindObjectsOfType<Collider>())
            {
                if (candidate == null
                    || candidate.transform.IsChildOf(instance.transform)
                    || !IsGroundSurfaceCandidate(candidate.transform))
                    continue;
                if (TryGetBoundsSupportTop(
                    candidate.bounds,
                    bounds.center,
                    bounds.min.y,
                    bestTopDelta,
                    out var top,
                    out var delta))
                {
                    bestTop = top;
                    bestTopDelta = delta;
                    support = candidate.gameObject;
                }
            }
            foreach (var candidate in FindObjectsOfType<Renderer>())
            {
                if (candidate == null
                    || candidate.transform.IsChildOf(instance.transform)
                    || !IsGroundSurfaceCandidate(candidate.transform))
                    continue;
                if (TryGetBoundsSupportTop(
                    candidate.bounds,
                    bounds.center,
                    bounds.min.y,
                    bestTopDelta,
                    out var top,
                    out var delta))
                {
                    bestTop = top;
                    bestTopDelta = delta;
                    support = candidate.gameObject;
                }
            }

            if (float.IsNegativeInfinity(bestTop))
                return false;

            instance.transform.position += Vector3.up * (bestTop - bounds.min.y);
            source = "bounds";
            return true;
        }

        private static bool TrySnapObjectToSupport(
            GameObject instance,
            GameObject support,
            float maxSlopeDegrees,
            out string source,
            out Vector3 surfaceNormal,
            out float contactError)
        {
            source = "none";
            surfaceNormal = Vector3.up;
            contactError = float.PositiveInfinity;
            if (support == null
                || !TryGetObjectBounds(instance, out var instanceBounds)
                || !TryGetObjectBounds(support, out var supportBounds))
                return false;

            Vector3 sample = instanceBounds.center;
            float rayHeight = Mathf.Max(
                supportBounds.max.y + 100f,
                instanceBounds.max.y + 100f);
            var ray = new Ray(
                new Vector3(sample.x, rayHeight, sample.z),
                Vector3.down);
            bool hasCollider = false;
            bool found = false;
            RaycastHit bestHit = default;
            foreach (var collider in support.GetComponentsInChildren<Collider>(true))
            {
                if (collider == null || !collider.enabled)
                    continue;
                hasCollider = true;
                if (collider.Raycast(ray, out var hit, Mathf.Infinity)
                    && (!found || hit.point.y > bestHit.point.y))
                {
                    found = true;
                    bestHit = hit;
                }
            }

            float targetY;
            if (found)
            {
                targetY = bestHit.point.y;
                surfaceNormal = bestHit.normal.normalized;
                source = "support_collider";
            }
            else
            {
                if (hasCollider
                    || sample.x < supportBounds.min.x
                    || sample.x > supportBounds.max.x
                    || sample.z < supportBounds.min.z
                    || sample.z > supportBounds.max.z)
                    return false;
                targetY = supportBounds.max.y;
                surfaceNormal = support.transform.up.normalized;
                source = "support_proxy_bounds";
            }

            if (Vector3.Angle(surfaceNormal, Vector3.up) > maxSlopeDegrees)
                return false;
            instance.transform.position += Vector3.up
                * (targetY - instanceBounds.min.y);
            if (!TryGetObjectBounds(instance, out var groundedBounds))
                return false;
            contactError = Mathf.Abs(groundedBounds.min.y - targetY);
            return contactError <= 0.02f;
        }

        private static bool TryGetBoundsSupportTop(
            Bounds candidate,
            Vector3 point,
            float targetBottom,
            float bestDelta,
            out float top,
            out float delta)
        {
            top = candidate.max.y;
            delta = Mathf.Abs(top - targetBottom);
            const float tolerance = 0.01f;
            if (point.x < candidate.min.x - tolerance
                || point.x > candidate.max.x + tolerance
                || point.z < candidate.min.z - tolerance
                || point.z > candidate.max.z + tolerance)
                return false;

            if (delta >= bestDelta)
                return false;

            return true;
        }

        private static List<string> FindBlockingBoundsIntersections(
            GameObject instance,
            GameObject allowedSupport,
            float minimumClearance = 0f)
        {
            var blockers = new List<string>();
            if (!TryGetObjectBounds(instance, out var instanceBounds))
                return blockers;

            Bounds clearanceBounds = instanceBounds;
            float clearance = Mathf.Max(0f, minimumClearance);
            if (clearance > 0f)
                clearanceBounds.Expand(new Vector3(clearance * 2f, 0f, clearance * 2f));
            Vector3 overlapExtents = clearanceBounds.extents;
            overlapExtents.x = Mathf.Max(0.001f, overlapExtents.x - 0.01f);
            overlapExtents.y = Mathf.Max(0.001f, overlapExtents.y - 0.01f);
            overlapExtents.z = Mathf.Max(0.001f, overlapExtents.z - 0.01f);
            foreach (var collider in Physics.OverlapBox(
                clearanceBounds.center,
                overlapExtents,
                Quaternion.identity,
                Physics.DefaultRaycastLayers,
                QueryTriggerInteraction.Ignore))
            {
                if (collider == null
                    || collider.transform.IsChildOf(instance.transform)
                    || IsAllowedSupport(collider.transform, allowedSupport))
                    continue;
                AddBlockingPath(blockers, collider.gameObject);
            }

            foreach (var renderer in FindObjectsOfType<Renderer>())
            {
                if (renderer == null
                    || (!(renderer is MeshRenderer)
                        && !(renderer is SkinnedMeshRenderer))
                    || renderer.transform.IsChildOf(instance.transform)
                    || IsAllowedSupport(renderer.transform, allowedSupport))
                    continue;

                // A related collider has already provided the more reliable
                // physical overlap test for this rendered object.
                if (renderer.GetComponent<Collider>() != null
                    || renderer.GetComponentInParent<Collider>() != null
                    || renderer.GetComponentInChildren<Collider>() != null)
                    continue;

                if (BoundsPenetrate(clearanceBounds, renderer.bounds))
                    AddBlockingPath(blockers, renderer.gameObject);
            }
            return blockers;
        }

        private static void AddBlockingPath(
            List<string> blockers,
            GameObject gameObject)
        {
            if (blockers.Count >= 8)
                return;
            string path = GetInstancePath(gameObject);
            if (!blockers.Contains(path))
                blockers.Add(path);
        }

        private static bool IsAllowedSupport(
            Transform candidate,
            GameObject allowedSupport)
        {
            return allowedSupport != null
                && (candidate == allowedSupport.transform
                    || candidate.IsChildOf(allowedSupport.transform)
                    || allowedSupport.transform.IsChildOf(candidate));
        }

        private static bool BoundsPenetrate(Bounds left, Bounds right)
        {
            const float epsilon = 0.01f;
            return Mathf.Min(left.max.x, right.max.x)
                    - Mathf.Max(left.min.x, right.min.x) > epsilon
                && Mathf.Min(left.max.y, right.max.y)
                    - Mathf.Max(left.min.y, right.min.y) > epsilon
                && Mathf.Min(left.max.z, right.max.z)
                    - Mathf.Max(left.min.z, right.min.z) > epsilon;
        }

        private static string HandleManageTransform(JToken args)
        {
            var a = ParseArgs(args, "path");
            string path = a["path"]?.ToString();
            var target = FindByPath(path);
            if (target == null) return ErrorResult($"Object not found: {path}");

            bool changed = false;
            if (a.ContainsKey("position"))
            {
                target.transform.position = ParseVector3(a["position"]); changed = true;
            }
            if (a.ContainsKey("rotation"))
            {
                target.transform.rotation = Quaternion.Euler(ParseVector3(a["rotation"])); changed = true;
            }
            if (a.ContainsKey("scale"))
            {
                target.transform.localScale = ParseVector33(a["scale"]); changed = true;
            }
            if (a.ContainsKey("world_coordinates"))
            {
                // Already using world by default
            }

            if (changed) Undo.RecordObject(target.gameObject, "Transform Change");
                
            return SuccessResult(new
            {
                position = SerializeVector3(target.transform.position),
                rotation = SerializeVector3(target.transform.eulerAngles),
                scale = SerializeVector3(target.transform.localScale),
                instanceId = GetInstancePath(target)
            });
        }

        private static string HandleSetTag(JToken args)
        {
            var a = ParseArgs(args, "path", "tag");
            string tag = a["tag"]?.ToString();
            var target = FindByPath(a["path"]?.ToString());
            if (target == null) return ErrorResult("Target not found");
            Undo.RecordObject(target, "Set Tag");
            target.tag = tag;
            return SuccessResult(new { tag, instanceId = GetInstancePath(target) });
        }

        private static string HandleSetLayer(JToken args)
        {
            var a = ParseArgs(args, "path", "layer");
            int layer = a["layer"]?.Value<int>() ?? 0;
            var target = FindByPath(a["path"]?.ToString());
            if (target == null) return ErrorResult("Target not found");
            Undo.RecordObject(target, "Set Layer");
            target.layer = layer;
            return SuccessResult(new { layer, instanceId = GetInstancePath(target) });
        }
    }
}
