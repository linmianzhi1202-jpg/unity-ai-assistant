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

        private static string HandleManageUI(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "create_ui_element";

            switch (action)
            {
                case "create_ui_element":
                {
                    string elementType = a["element_type"]?.ToString() ?? "panel";
                    string elementName = a["element_name"]?.ToString() ?? "NewUIElement";
                    string parentPath = a["parent_path"]?.ToString();

                    // Find or create parent
                    GameObject parentGo = null;
                    if (!string.IsNullOrEmpty(parentPath))
                        parentGo = FindByPath(parentPath);

                    // Default to first Canvas if no parent specified
                    if (parentGo == null)
                    {
                        var canvases = FindObjectsOfType<Canvas>();
                        if (canvases.Count > 0)
                            parentGo = canvases[0].gameObject;
                        else
                        {
                            // Create a default Canvas
                            parentGo = new GameObject("GameCanvas");
                            var canvas = parentGo.AddComponent<Canvas>();
                            canvas.renderMode = RenderMode.ScreenSpaceOverlay;
                            parentGo.AddComponent<UnityEngine.UI.CanvasScaler>();
                            parentGo.AddComponent<UnityEngine.UI.GraphicRaycaster>();
                            Undo.RegisterCreatedObjectUndo(parentGo, "Create Canvas");
                        }
                    }

                    GameObject newElement = null;
                    switch (elementType.ToLowerInvariant())
                    {
                        case "panel":
                            newElement = new GameObject(elementName);
                            newElement.AddComponent<UnityEngine.UI.Image>();
                            break;
                        case "text":
                            newElement = new GameObject(elementName);
                            var text = newElement.AddComponent<UnityEngine.UI.Text>();
                            text.text = elementName;
                            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                            text.fontSize = 14;
                            text.color = Color.black;
                            break;
                        case "image":
                            newElement = new GameObject(elementName);
                            newElement.AddComponent<UnityEngine.UI.Image>();
                            break;
                        case "button":
                            newElement = new GameObject(elementName);
                            var btnImg = newElement.AddComponent<UnityEngine.UI.Image>();
                            btnImg.color = Color.white;
                            newElement.AddComponent<UnityEngine.UI.Button>();
                            // Add child Text for button label
                            var labelGo = new GameObject("Text");
                            labelGo.transform.SetParent(newElement.transform, false);
                            var labelText = labelGo.AddComponent<UnityEngine.UI.Text>();
                            labelText.text = elementName;
                            labelText.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
                            labelText.fontSize = 14;
                            labelText.color = Color.black;
                            labelText.alignment = TextAnchor.MiddleCenter;
                            var labelRT = labelGo.GetComponent<RectTransform>();
                            labelRT.anchorMin = Vector2.zero;
                            labelRT.anchorMax = Vector2.one;
                            labelRT.sizeDelta = Vector2.zero;
                            break;
                        case "inputfield":
                            newElement = new GameObject(elementName);
                            var inputImg = newElement.AddComponent<UnityEngine.UI.Image>();
                            inputImg.color = Color.white;
                            newElement.AddComponent<UnityEngine.UI.InputField>();
                            break;
                        case "dropdown":
                            newElement = new GameObject(elementName);
                            newElement.AddComponent<UnityEngine.UI.Image>();
                            newElement.AddComponent<UnityEngine.UI.Dropdown>();
                            break;
                        case "toggle":
                            newElement = new GameObject(elementName);
                            newElement.AddComponent<UnityEngine.UI.Toggle>();
                            break;
                        case "scrollview":
                            newElement = new GameObject(elementName);
                            var scrollImg = newElement.AddComponent<UnityEngine.UI.Image>();
                            scrollImg.color = Color.white;
                            newElement.AddComponent<UnityEngine.UI.ScrollRect>();
                            // Add content child
                            var contentGo = new GameObject("Content");
                            contentGo.transform.SetParent(newElement.transform, false);
                            var contentRT = contentGo.AddComponent<RectTransform>();
                            contentRT.anchorMin = new Vector2(0, 1);
                            contentRT.anchorMax = new Vector2(1, 1);
                            contentRT.pivot = new Vector2(0.5f, 1);
                            contentRT.sizeDelta = new Vector2(0, 200);
                            scrollImg.raycastTarget = true;
                            break;
                        default:
                            newElement = new GameObject(elementName);
                            newElement.AddComponent<UnityEngine.UI.Image>();
                            break;
                    }

                    if (newElement != null)
                    {
                        newElement.transform.SetParent(parentGo.transform, false);
                        var rt = newElement.GetComponent<RectTransform>();
                        if (rt == null) rt = newElement.AddComponent<RectTransform>();
                        rt.anchorMin = new Vector2(0.5f, 0.5f);
                        rt.anchorMax = new Vector2(0.5f, 0.5f);
                        rt.sizeDelta = new Vector2(160, 30);
                        Undo.RegisterCreatedObjectUndo(newElement, $"Create UI {elementType} '{elementName}'");
                    }

                    return SuccessResult(new { created = elementName, type = elementType, instanceId = GetInstancePath(newElement) });
                }

                case "set_ui_text":
                {
                    string path = a["gameobject_path"]?.ToString();
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"UI GameObject not found: {path}");

                    var textComp = target.GetComponent<UnityEngine.UI.Text>();
                    if (textComp == null) return ErrorResult($"No Text component on '{path}'");

                    Undo.RecordObject(textComp, "Set UI Text");
                    if (a["text"] != null) textComp.text = a["text"].ToString();
                    if (a["font_size"] != null) textComp.fontSize = a["font_size"].Value<int>();
                    if (a["color"] != null) textComp.color = ParseColor(a["color"]);
                    if (a["alignment"] != null)
                    {
                        string alignStr = a["alignment"].ToString();
                        textComp.alignment = alignStr switch
                        {
                            "UpperLeft" => TextAnchor.UpperLeft,
                            "UpperCenter" => TextAnchor.UpperCenter,
                            "UpperRight" => TextAnchor.UpperRight,
                            "MiddleLeft" => TextAnchor.MiddleLeft,
                            "MiddleCenter" => TextAnchor.MiddleCenter,
                            "MiddleRight" => TextAnchor.MiddleRight,
                            "LowerLeft" => TextAnchor.LowerLeft,
                            "LowerCenter" => TextAnchor.LowerCenter,
                            "LowerRight" => TextAnchor.LowerRight,
                            _ => TextAnchor.MiddleCenter
                        };
                    }

                    return SuccessResult(new { path, text = textComp.text });
                }

                case "set_rect_transform":
                {
                    string path = a["gameobject_path"]?.ToString();
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"UI GameObject not found: {path}");

                    var rt = target.GetComponent<RectTransform>();
                    if (rt == null) return ErrorResult($"No RectTransform on '{path}'");

                    Undo.RecordObject(rt, "Set RectTransform");
                    if (a["anchor_min"] != null)
                    {
                        var v = ParseVector3(a["anchor_min"]);
                        rt.anchorMin = new Vector2(v.x, v.y);
                    }
                    if (a["anchor_max"] != null)
                    {
                        var v = ParseVector3(a["anchor_max"]);
                        rt.anchorMax = new Vector2(v.x, v.y);
                    }
                    if (a["pivot"] != null)
                    {
                        var v = ParseVector3(a["pivot"]);
                        rt.pivot = new Vector2(v.x, v.y);
                    }
                    if (a["size_delta"] != null)
                    {
                        var v = ParseVector3(a["size_delta"]);
                        rt.sizeDelta = new Vector2(v.x, v.y);
                    }
                    if (a["anchored_position"] != null)
                    {
                        var v = ParseVector3(a["anchored_position"]);
                        rt.anchoredPosition = new Vector2(v.x, v.y);
                    }

                    return SuccessResult(new { path, anchoredPosition = SerializeVector3(rt.anchoredPosition) });
                }

                case "set_ui_layout":
                {
                    string path = a["gameobject_path"]?.ToString();
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"UI GameObject not found: {path}");

                    string layoutType = a["layout_type"]?.ToString() ?? "vertical";
                    // Remove or add layout components as needed
                    var existingH = target.GetComponent<UnityEngine.UI.HorizontalLayoutGroup>();
                    var existingV = target.GetComponent<UnityEngine.UI.VerticalLayoutGroup>();
                    var existingG = target.GetComponent<UnityEngine.UI.GridLayoutGroup>();

                    UnityEngine.UI.HorizontalOrVerticalLayoutGroup layout = null;
                    if (layoutType == "horizontal")
                    {
                        if (existingV != null) Undo.DestroyObjectImmediate(existingV);
                        if (existingG != null) Undo.DestroyObjectImmediate(existingG);
                        if (existingH == null) existingH = Undo.AddComponent<UnityEngine.UI.HorizontalLayoutGroup>(target);
                        layout = existingH;
                    }
                    else if (layoutType == "vertical")
                    {
                        if (existingH != null) Undo.DestroyObjectImmediate(existingH);
                        if (existingG != null) Undo.DestroyObjectImmediate(existingG);
                        if (existingV == null) existingV = Undo.AddComponent<UnityEngine.UI.VerticalLayoutGroup>(target);
                        layout = existingV;
                    }
                    else if (layoutType == "grid")
                    {
                        if (existingH != null) Undo.DestroyObjectImmediate(existingH);
                        if (existingV != null) Undo.DestroyObjectImmediate(existingV);
                        if (existingG == null) existingG = Undo.AddComponent<UnityEngine.UI.GridLayoutGroup>(target);
                    }

                    if (layout != null)
                    {
                        if (a["spacing"] != null) layout.spacing = a["spacing"].Value<float>();
                        if (a["child_alignment"] != null)
                        {
                            string alignStr = a["child_alignment"].ToString();
                            layout.childAlignment = alignStr switch
                            {
                                "UpperLeft" => TextAnchor.UpperLeft,
                                "UpperCenter" => TextAnchor.UpperCenter,
                                "UpperRight" => TextAnchor.UpperRight,
                                "MiddleLeft" => TextAnchor.MiddleLeft,
                                "MiddleCenter" => TextAnchor.MiddleCenter,
                                "MiddleRight" => TextAnchor.MiddleRight,
                                "LowerLeft" => TextAnchor.LowerLeft,
                                "LowerCenter" => TextAnchor.LowerCenter,
                                "LowerRight" => TextAnchor.LowerRight,
                                _ => TextAnchor.MiddleCenter
                            };
                        }
                    }

                    return SuccessResult(new { path, layout_type = layoutType });
                }

                case "add_persistent_listener":
                {
                    string path = a["gameobject_path"]?.ToString();
                    var sourceGo = FindByPath(path);
                    if (sourceGo == null) return ErrorResult($"UI GameObject not found: {path}");

                    string eventName = a["event_name"]?.ToString() ?? "onClick";
                    string methodName = a["method_name"]?.ToString();
                    string targetPath = a["target_path"]?.ToString();

                    if (string.IsNullOrEmpty(methodName))
                        return ErrorResult("method_name is required for add_persistent_listener");

                    var button = sourceGo.GetComponent<UnityEngine.UI.Button>();
                    if (button == null || (eventName != "onClick" && eventName != "onValueChanged"))
                        return ErrorResult($"No supported event handler for '{eventName}' on '{path}'. Only Button.onClick is supported.");

                    // ── Step 1: Find the target component that has the method ──
                    GameObject targetGo = null;
                    MonoBehaviour targetComp = null;
                    System.Reflection.MethodInfo targetMethod = null;
                    string bindingStrategy = null;

                    if (!string.IsNullOrEmpty(targetPath))
                        targetGo = FindByPath(targetPath);

                    // Search for the method on targetGo first, then global search
                    var flags = System.Reflection.BindingFlags.Public
                        | System.Reflection.BindingFlags.NonPublic
                        | System.Reflection.BindingFlags.Instance;

                    if (targetGo != null)
                    {
                        foreach (var c in targetGo.GetComponents<MonoBehaviour>())
                        {
                            if (c == null) continue;
                            var m = c.GetType().GetMethod(methodName, flags);
                            if (m != null) { targetComp = c; targetMethod = m; break; }
                        }
                    }

                    // Global fallback: search all MonoBehaviour instances
                    if (targetComp == null)
                    {
                        var roots = UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects();
                        foreach (var root in roots)
                        {
                            foreach (var c in root.GetComponentsInChildren<MonoBehaviour>(true))
                            {
                                if (c == null) continue;
                                var m = c.GetType().GetMethod(methodName, flags);
                                if (m != null) { targetComp = c; targetGo = c.gameObject; targetMethod = m; break; }
                            }
                            if (targetComp != null) break;
                        }
                    }

                    if (targetComp == null || targetMethod == null)
                    {
                        // Build helpful diagnostics: list available methods on the target GameObject
                        var hint = new System.Text.StringBuilder();
                        hint.AppendLine($"Method '{methodName}' not found on any MonoBehaviour"
                            + (!string.IsNullOrEmpty(targetPath) ? $" at '{targetPath}'" : " in scene"));
                        if (!string.IsNullOrEmpty(targetPath) && targetGo != null)
                        {
                            var comps = targetGo.GetComponents<MonoBehaviour>();
                            if (comps.Length > 0)
                            {
                                hint.AppendLine($"Available public methods on '{targetPath}':");
                                foreach (var c in comps)
                                {
                                    if (c == null) continue;
                                    foreach (var m in c.GetType().GetMethods(
                                        System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.DeclaredOnly))
                                    {
                                        hint.AppendLine($"  {c.GetType().Name}.{m.Name}({string.Join(", ", System.Array.ConvertAll(m.GetParameters(), p => p.ParameterType.Name + " " + p.Name))})");
                                    }
                                }
                            }
                        }
                        return ErrorResult(hint.ToString().TrimEnd());
                    }

                    // ── Warning: method was found via global fallback, not on specified targetPath ──
                    string targetMismatchNote = null;
                    if (!string.IsNullOrEmpty(targetPath) && targetGo != null && targetComp.gameObject != targetGo)
                    {
                        targetMismatchNote = $"Method '{methodName}' was found on '{targetComp.gameObject.name}' "
                            + $"({targetComp.GetType().Name}), not on the explicitly requested '{targetPath}'. ";
                    }

                    // ── Step 2: Bind the method to the button event ──
                    var parameters = targetMethod.GetParameters();
                    Undo.RecordObject(button.gameObject, "Add Persistent Listener");

                    if (parameters.Length == 0)
                    {
                        // Void/no-param method: use persistent binding (survives scene reload)
                        var unityAction = (UnityEngine.Events.UnityAction)System.Delegate.CreateDelegate(
                            typeof(UnityEngine.Events.UnityAction), targetComp, methodName);
                        UnityEditor.Events.UnityEventTools.AddVoidPersistentListener(
                            button.onClick, unityAction);
                        bindingStrategy = "persistent_void";
                    }
                    else
                    {
                        // Method with parameter(s): auto-resolve argument from source button's components
                        var paramType = parameters[0].ParameterType;
                        var sourceParam = sourceGo.GetComponent(paramType);

                        if (sourceParam != null)
                        {
                            // Use runtime AddListener with captured reference (functional, non-persistent)
                            var capturedTarget = targetComp;
                            var capturedParam = sourceParam;
                            button.onClick.AddListener(() => capturedTarget.SendMessage(methodName, capturedParam,
                                SendMessageOptions.RequireReceiver));
                            bindingStrategy = "runtime_with_autoresolved_arg";
                        }
                        else
                        {
                            // No matching component on source — try AddListener with null (unity will coerce)
                            var capturedTarget = targetComp;
                            button.onClick.AddListener(() => capturedTarget.SendMessage(methodName,
                                SendMessageOptions.RequireReceiver));
                            bindingStrategy = "runtime_no_arg_source";
                        }
                    }

                    EditorUtility.SetDirty(button.gameObject);
                    UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(button.gameObject.scene);

                    return SuccessResult(new
                    {
                        source = path,
                        target = targetGo != null ? targetGo.name : "(auto-found)",
                        target_component = targetComp.GetType().Name,
                        method_name = methodName,
                        method_params = parameters.Length,
                        binding_strategy = bindingStrategy,
                        target_mismatch_warning = targetMismatchNote,
                        message = (targetMismatchNote ?? "")
                            + $"Wired {path}→{targetComp.GetType().Name}.{methodName} (strategy={bindingStrategy})"
                    });
                }

                case "remove_persistent_listener":
                {
                    string path = a["gameobject_path"]?.ToString();
                    var target = FindByPath(path);
                    if (target == null) return ErrorResult($"UI GameObject not found: {path}");

                    string eventName = a["event_name"]?.ToString() ?? "onClick";
                    int listenerIndex = a["listener_index"]?.Value<int>() ?? 0;

                    var button = target.GetComponent<UnityEngine.UI.Button>();
                    if (button != null && button.onClick != null && button.onClick.GetPersistentEventCount() > listenerIndex)
                    {
                        UnityEditor.Events.UnityEventTools.RemovePersistentListener(button.onClick, listenerIndex);
                        return SuccessResult(new { path, removed_listener_index = listenerIndex });
                    }

                    return ErrorResult($"No persistent listener at index {listenerIndex} on '{path}'");
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }



        /// <summary>
        /// Create a ScriptableObject .asset with type name and property values in one step.
        /// Resolves type by scanning ALL assemblies (cross-asmdef), creates the asset,
        /// and optionally writes SerializedObject properties from a JSON properties dict.
        /// </summary>

        private static string HandleCreateScriptableObject(JToken args)
        {
            var a = ParseArgs(args, "action", "type_name", "asset_path");
            string action = a["action"]?.ToString() ?? "create_with_properties";

            switch (action)
            {
                case "create_with_properties":
                {
                    string typeName = a["type_name"]?.ToString();
                    string assetPath = a["asset_path"]?.ToString();
                    string propsJson = a["properties"]?.ToString();

                    // 1. Resolve the type (any ScriptableObject, cross-asmdef)
                    Type soType = ResolveAnyType(typeName);
                    if (soType == null)
                        return ErrorResult($"Type not found in any loaded assembly: {typeName}");
                    if (!typeof(ScriptableObject).IsAssignableFrom(soType))
                        return ErrorResult($"Type '{soType.FullName}' is not a ScriptableObject");

                    // 2. Create the ScriptableObject instance
                    var so = ScriptableObject.CreateInstance(soType);

                    // 3. Ensure parent directory exists
                    string dir = Path.GetDirectoryName(assetPath);
                    if (!string.IsNullOrEmpty(dir))
                    {
                        string absDir = Path.GetFullPath(Path.Combine(Application.dataPath, "..", dir));
                        if (!Directory.Exists(absDir))
                            Directory.CreateDirectory(absDir);
                    }

                    // 4. Write properties if provided
                    int propsApplied = 0;
                    if (!string.IsNullOrEmpty(propsJson))
                    {
                        try
                        {
                            var props = JObject.Parse(propsJson);
                            var serializedSo = new SerializedObject(so);

                            foreach (var kv in props)
                            {
                                try
                                {
                                    var prop = serializedSo.FindProperty(kv.Key);
                                    if (prop != null)
                                    {
                                        SetSerializedPropertyFromToken(prop, kv.Value);
                                        propsApplied++;
                                    }
                                }
                                catch (Exception ex)
                                {
                                    Debug.LogWarning($"[CreateScriptableObject] Failed to set '{kv.Key}': {ex.Message}");
                                }
                            }

                            serializedSo.ApplyModifiedProperties();
                        }
                        catch (Exception ex)
                        {
                            return ErrorResult($"Failed to parse properties JSON: {ex.Message}");
                        }
                    }

                    // 5. Create the asset
                    AssetDatabase.CreateAsset(so, assetPath);
                    AssetDatabase.SaveAssets();
                    AssetDatabase.Refresh();

                    return SuccessResult(new
                    {
                        asset_path = assetPath,
                        type = soType.FullName,
                        type_name = typeName,
                        properties_applied = propsApplied
                    });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        /// <summary>
        /// Attach a custom MonoBehaviour script to a GameObject.
        /// Resolves the type by scanning ALL assemblies, so it works across asmdef boundaries.
        /// Supports short names, full names, and assembly-qualified names.
        /// </summary>

        private static string HandleAttachMonoBehaviour(JToken args)
        {
            var a = ParseArgs(args, "action", "path", "script_type_name");
            string action = a["action"]?.ToString() ?? "attach";

            switch (action)
            {
                case "attach":
                {
                    string path = a["path"]?.ToString();
                    string scriptTypeName = a["script_type_name"]?.ToString();
                    var target = FindByPath(path);
                    if (target == null)
                        return ErrorResult($"GameObject not found: {path}");

                    // Resolve type by scanning ALL assemblies (not just Component subclasses)
                    Type scriptType = ResolveMonoBehaviourType(scriptTypeName);
                    if (scriptType == null)
                        return ErrorResult(
                            $"MonoBehaviour type not found in any assembly: '{scriptTypeName}'. " +
                            $"Make sure the script exists and Unity has compiled it. " +
                            $"Try the full name like 'MyGame.UI.HudController, MyGame.UI'.");

                    if (!typeof(MonoBehaviour).IsAssignableFrom(scriptType))
                        return ErrorResult($"Type '{scriptType.FullName}' is not a MonoBehaviour");

                    // Check if already attached
                    var existing = target.GetComponent(scriptType);
                    if (existing != null)
                        return SuccessResult(new
                        {
                            attached = scriptType.FullName,
                            instanceId = GetInstancePath(target),
                            message = "Component already attached (no duplicate added)"
                        });

                    // Add component via Undo
                    var comp = Undo.AddComponent(target, scriptType);
                    if (comp == null)
                        return ErrorResult($"Failed to add component '{scriptTypeName}' to '{path}'");

                    return SuccessResult(new
                    {
                        attached = scriptType.FullName,
                        short_name = scriptType.Name,
                        instanceId = GetInstancePath(target)
                    });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        /// <summary>
        /// Set a SerializeField object reference — the drag-and-drop equivalent.
        /// Binds a GameObject hint or asset to a serialized field on a component.
        /// Supports: GameObject references, TextureAsset, Sprite, Material, ScriptableObject, etc.
        /// </summary>

        private static string HandleSetSerializedReference(JToken args)
        {
            var a = ParseArgs(args, "action", "path", "component_type", "property_name", "target_path");
            string action = a["action"]?.ToString() ?? "set_reference";

            switch (action)
            {
                case "set_reference":
                {
                    string path = a["path"]?.ToString();
                    string componentType = a["component_type"]?.ToString();
                    string propertyName = a["property_name"]?.ToString();
                    string targetPath = a["target_path"]?.ToString();

                    // 1. Find the target GameObject
                    var target = FindByPath(path);
                    if (target == null)
                        return ErrorResult($"GameObject not found: {path}");

                    // 2. Find the component on that GameObject
                    Type compType = ResolveAnyType(componentType);
                    if (compType == null)
                        return ErrorResult($"Component type not found: {componentType}");

                    var comp = target.GetComponent(compType);
                    if (comp == null)
                        return ErrorResult($"Component '{componentType}' not found on '{path}'");

                    // 3. Resolve the target to assign
                    UnityEngine.Object assignTarget = null;

                    // Try hierarchy path first (GameObject or component child)
                    var hierarchyTarget = FindByPath(targetPath);
                    if (hierarchyTarget != null)
                    {
                        // Check if the field expects a specific component type
                        var serializedComp = new SerializedObject(comp);
                        var refProp = serializedComp.FindProperty(propertyName);
                        if (refProp != null)
                        {
                            // Try to get the correct component from the hierarchy target
                            string expectedType = refProp.type;
                            if (expectedType.StartsWith("PPtr<$"))
                            {
                                // Parse the expected type from PPtr<$T> format
                                string innerType = expectedType.Replace("PPtr<$", "").TrimEnd('>');
                                if (innerType == "GameObject")
                                {
                                    assignTarget = hierarchyTarget;
                                }
                                else
                                {
                                    // Try to get component of the expected type
                                    var expectedCompType = ResolveAnyType(innerType);
                                    if (expectedCompType != null)
                                    {
                                        var childComp = hierarchyTarget.GetComponent(expectedCompType);
                                        if (childComp != null)
                                            assignTarget = childComp;
                                        else
                                            assignTarget = hierarchyTarget; // Fallback
                                    }
                                    else
                                    {
                                        assignTarget = hierarchyTarget; // Fallback to GameObject
                                    }
                                }
                            }
                            else
                            {
                                assignTarget = hierarchyTarget; // Unknown type, assign GameObject
                            }
                        }
                        else
                        {
                            assignTarget = hierarchyTarget; // Property not found yet, try as GameObject
                        }
                    }

                    // Try asset path
                    if (assignTarget == null && targetPath.StartsWith("Assets/"))
                    {
                        assignTarget = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(targetPath);
                        if (assignTarget == null)
                        {
                            // Try loading as specific type by checking the serialized property
                            var serializedComp2 = new SerializedObject(comp);
                            var refProp2 = serializedComp2.FindProperty(propertyName);
                            if (refProp2 != null && refProp2.propertyType == SerializedPropertyType.ObjectReference)
                            {
                                assignTarget = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(targetPath);
                            }
                        }
                    }

                    if (assignTarget == null)
                        return ErrorResult($"Target not found: '{targetPath}'. Check that the GameObject exists in the scene or the asset exists at the given path.");

                    // 4. Set via SerializedObject (handles all Unity serialized fields)
                    var serializedObj = new SerializedObject(comp);
                    var serializedProp = serializedObj.FindProperty(propertyName);

                    if (serializedProp == null)
                    {
                        // Try direct reflection as fallback
                        var field = compType.GetField(propertyName,
                            BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                        if (field != null)
                        {
                            Undo.RecordObject(comp, $"Set {propertyName}");
                            field.SetValue(comp, assignTarget);
                            EditorUtility.SetDirty(comp);
                            return SuccessResult(new
                            {
                                property = $"{componentType}.{propertyName}",
                                assigned = targetPath,
                                via = "Reflection.Field"
                            });
                        }

                        return ErrorResult(
                            $"SerializedProperty '{propertyName}' not found on '{componentType}'. " +
                            $"Available properties can be found via manage_scriptable_object with action=get.");
                    }

                    if (serializedProp.propertyType != SerializedPropertyType.ObjectReference)
                        return ErrorResult(
                            $"Property '{propertyName}' is not an object reference type (is {serializedProp.propertyType}). " +
                            $"Use set_property on manage_components or manage_scriptable_object for value types.");

                    Undo.RecordObject(comp, $"Set {propertyName} reference");
                    serializedProp.objectReferenceValue = assignTarget;
                    serializedObj.ApplyModifiedProperties();
                    EditorUtility.SetDirty(comp);

                    return SuccessResult(new
                    {
                        property = $"{componentType}.{propertyName}",
                        assigned = targetPath,
                        target_type = assignTarget.GetType().FullName,
                        via = "SerializedObject"
                    });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        /// <summary>
        /// Resolve a type name to a ScriptableObject type by scanning ALL loaded assemblies.
        /// More flexible than ResolveComponentType — finds any class type, not just Components.
        /// Supports short names, full names, and assembly-qualified names.
        /// </summary>
    }
}
