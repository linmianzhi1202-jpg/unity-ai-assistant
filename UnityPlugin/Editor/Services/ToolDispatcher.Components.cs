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

        private static string HandleManageComponents(JToken args)
        {
            var a = ParseArgs(args, "action", "path");
            string action = a["action"]?.ToString() ?? "add";
            string path = a["path"]?.ToString();
            string prefabPath = a["prefab_path"]?.ToString();
            GameObject target = null;
            bool isPrefabEdit = false;

            // Prefab editing support: load prefab contents first
            if (!string.IsNullOrEmpty(prefabPath) && action != "list")
            {
                target = PrefabUtility.LoadPrefabContents(prefabPath);
                isPrefabEdit = true;
            }
            else
            {
                target = FindByPath(path);
            }

            if (target == null && action != "list")
                return ErrorResult($"Object not found: {path}");

            try
            {
                switch (action)
                {
                    case "add":
                {
                    string componentType = a["component_type"]?.ToString() ?? "Rigidbody";
                    bool allowDuplicate = a["allow_duplicate"]?.Value<bool>() ?? false;
                    Type compType = ResolveComponentType(componentType);
                    if (compType == null)
                        return ErrorResult($"Unknown component type: {componentType}");
                    var existing = target.GetComponent(compType);
                    if (existing != null && !allowDuplicate)
                    {
                        return SuccessResult(new
                        {
                            added = componentType,
                            added_component = false,
                            already_exists = true,
                            component_type = compType.FullName,
                            instanceId = GetInstancePath(target),
                            warning = $"Component already exists on '{GetInstancePath(target)}'. Pass allow_duplicate=true to add another instance intentionally."
                        });
                    }
                    var comp = Undo.AddComponent(target, compType);
                    if (comp != null) return SuccessResult(new { added = componentType, added_component = true, component_type = componentType, instanceId = GetInstancePath(target) });
                    return ErrorResult($"Failed to add component: {componentType}");
                }
                case "remove":
                {
                    string compType = a["component_type"]?.ToString();
                    if (!string.IsNullOrEmpty(compType))
                    {
                        var comp = target.GetComponent(compType);
                        if (comp != null) Undo.DestroyObjectImmediate(comp);
                    }
                    return SuccessResult(new { removed = compType });
                }
                case "list":
                    var comps = target.GetComponents<Component>();
                    var list = new JArray();
                    foreach (var c in comps)
                        list.Add(c.GetType().FullName);
                    return SuccessResult(new { components = list, instanceId = GetInstancePath(target) });
                case "set_property":
                {
                    string compType = a["component_type"]?.ToString();
                    string propName = a["property_name"]?.ToString();
                    string propValue = a["value"]?.ToString();
                    if (string.IsNullOrEmpty(compType) || string.IsNullOrEmpty(propName))
                        return ErrorResult("set_property requires component_type and property_name");
                    var comp = target.GetComponent(compType);
                    if (comp == null) return ErrorResult($"Component {compType} not found on {path}");
                    try
                    {
                        var flags = System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance;
                        // Try SerializedObject FIRST (handles Vector2 structs correctly, plus private serialized)
                        var so = new SerializedObject(comp);
                        var serializedProp = so.FindProperty(propName);
                        if (serializedProp != null)
                        {
                            SetSerializedProperty(serializedProp, propValue, a["asset_path"]?.ToString());
                            so.ApplyModifiedProperties();
                            EditorUtility.SetDirty(comp);
                            return SuccessResult(new { set = $"{compType}.{propName} = {propValue}", via = "SerializedObject" });
                        }
                        // Try property (public + non-public)
                        var prop = comp.GetType().GetProperty(propName, flags);
                        if (prop == null) prop = comp.GetType().GetProperty(propName); // fallback: public only
                        if (prop != null && prop.CanWrite)
                        {
                            object converted = ConvertValue(prop.PropertyType, propValue, a["asset_path"]?.ToString());
                            prop.SetValue(comp, converted);
                            EditorUtility.SetDirty(comp);
                            return SuccessResult(new { set = $"{compType}.{propName} = {propValue}", via = "PropertyInfo" });
                        }
                        // Try field (public + non-public)
                        var field = comp.GetType().GetField(propName, flags);
                        if (field == null) field = comp.GetType().GetField(propName); // fallback: public only
                        if (field != null)
                        {
                            object converted = ConvertValue(field.FieldType, propValue, a["asset_path"]?.ToString());
                            field.SetValue(comp, converted);
                            EditorUtility.SetDirty(comp);
                            return SuccessResult(new { set = $"{compType}.{propName} = {propValue}", via = "FieldInfo" });
                        }
                        return ErrorResult($"Property/field '{propName}' not found on {compType}");
                    }
                    catch (Exception ex)
                    {
                        return ErrorResult($"Failed to set {compType}.{propName}: {ex.Message}");
                    }
                }

                case "audit_references":
                {
                    string compType = a["component_type"]?.ToString();
                    if (string.IsNullOrEmpty(compType))
                        return ErrorResult("component_type is required for audit_references");
                    var comp = target.GetComponent(compType);
                    if (comp == null) return ErrorResult($"Component {compType} not found on {path}");

                    var so = new SerializedObject(comp);
                    var issues = new List<object>();
                    var warnings = new List<object>();
                    int totalNullRefs = 0;
                    int repairedCount = 0;
                    var prop = so.GetIterator();
                    if (prop.NextVisible(true))
                    {
                        do
                        {
                            if (prop.isArray && prop.propertyType != SerializedPropertyType.String && prop.name != "m_Script" && prop.arraySize == 0)
                            {
                                var propNameLower = prop.name.ToLowerInvariant();
                                if (propNameLower.Contains("enem") || propNameLower.Contains("spawn") || propNameLower.Contains("wave") || propNameLower.Contains("prefab"))
                                {
                                    warnings.Add(new
                                    {
                                        field = prop.name,
                                        displayName = prop.displayName,
                                        warning_type = "empty_array",
                                        value = 0,
                                        message = $"{prop.displayName} is empty; gameplay code may early-exit or spawn nothing."
                                    });
                                }
                            }

                            if ((prop.propertyType == SerializedPropertyType.Integer || prop.propertyType == SerializedPropertyType.Float)
                                && prop.name != "m_Script")
                            {
                                var propNameLower = prop.name.ToLowerInvariant();
                                bool spawnCountLike = propNameLower.Contains("count")
                                    || propNameLower.Contains("spawn")
                                    || propNameLower.Contains("enem")
                                    || propNameLower.Contains("wave")
                                    || propNameLower.Contains("per");
                                bool zeroValue = prop.propertyType == SerializedPropertyType.Integer
                                    ? prop.intValue == 0
                                    : Math.Abs(prop.floatValue) < 0.0001f;
                                if (spawnCountLike && zeroValue)
                                {
                                    warnings.Add(new
                                    {
                                        field = prop.name,
                                        displayName = prop.displayName,
                                        warning_type = "zero_value",
                                        value = prop.propertyType == SerializedPropertyType.Integer ? (object)prop.intValue : prop.floatValue,
                                        message = $"{prop.displayName} is zero; gameplay code may early-exit, skip spawning, or never progress."
                                    });
                                }
                            }

                            if (prop.propertyType == SerializedPropertyType.ObjectReference
                                && prop.name != "m_Script")  // skip built-in
                            {
                                // ─── Handle array elements individually ───
                                if (prop.isArray)
                                {
                                    for (int ei = 0; ei < prop.arraySize; ei++)
                                    {
                                        var elem = prop.GetArrayElementAtIndex(ei);
                                        if (elem.propertyType == SerializedPropertyType.ObjectReference
                                            && elem.objectReferenceValue == null)
                                        {
                                            totalNullRefs++;
                                            string lookupName = $"ArrayElem_{prop.name}_{ei}";
                                            string strategy = null;
                                            var resolvedObj = TryResolveByName(prop.name, ref strategy);

                                            bool repaired = false;
                                            if (resolvedObj != null)
                                            {
                                                var fieldType = GetFieldType(so, prop.name);
                                                if (fieldType != null && fieldType.IsGenericType
                                                    && fieldType.GetGenericTypeDefinition() == typeof(List<>))
                                                    fieldType = fieldType.GetGenericArguments()[0];

                                                if (fieldType != null && typeof(Component).IsAssignableFrom(fieldType))
                                                {
                                                    var resolvedComp = resolvedObj.GetComponent(fieldType);
                                                    if (resolvedComp == null)
                                                    {
                                                        try { resolvedComp = resolvedObj.AddComponent(fieldType); }
                                                        catch { }
                                                    }
                                                    if (resolvedComp != null)
                                                    {
                                                        elem.objectReferenceValue = resolvedComp;
                                                        repaired = true;
                                                        repairedCount++;
                                                    }
                                                }
                                                else
                                                {
                                                    // Prefab asset: try loading from path
                                                    var loadPath = "Assets/Prefabs/" + lookupName + ".prefab";
                                                    var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(loadPath);
                                                    if (prefab == null) loadPath = "Assets/Prefabs/Enemies/" + lookupName + ".prefab";
                                                    prefab = AssetDatabase.LoadAssetAtPath<GameObject>(loadPath);
                                                    if (prefab != null)
                                                    {
                                                        elem.objectReferenceValue = prefab;
                                                        repaired = true;
                                                        repairedCount++;
                                                    }
                                                    else
                                                    {
                                                        elem.objectReferenceValue = resolvedObj;
                                                        repaired = true;
                                                        repairedCount++;
                                                    }
                                                }
                                            }

                                            issues.Add(new
                                            {
                                                field = $"{prop.name}[{ei}]",
                                                displayName = $"{prop.displayName}[{ei}]",
                                                null_reference = true,
                                                resolved_path = resolvedObj != null ? resolvedObj.name : null,
                                                repaired = repaired,
                                                strategy = strategy ?? "none",
                                                auto_created_component = false,
                                                failure_reason = repaired ? null : "no_gameobject_found"
                                            });
                                        }
                                    }
                                    so.ApplyModifiedProperties();
                                    continue;
                                }

                                // ─── Scalar ObjectReference with null value ───
                                if (prop.objectReferenceValue != null) continue;

                                totalNullRefs++;
                                string propName = prop.name;
                                string lookupName2 = propName;
                                if (lookupName2.StartsWith("m_")) lookupName2 = lookupName2.Substring(2);

                                // ─── Phase 1: Match GameObject by field name ───
                                string strategy2 = null;
                                var resolvedObj2 = TryResolveByName(lookupName2, ref strategy2);

                                // ─── Phase 2: Resolve reference & auto-create missing components ───
                                bool repaired2 = false;
                                bool autoCreated = false;
                                string failureReason = null;

                                if (resolvedObj2 != null)
                                {
                                    var fieldType = GetFieldType(so, propName);
                                    if (fieldType != null && typeof(Component).IsAssignableFrom(fieldType))
                                    {
                                        var resolvedComp = resolvedObj2.GetComponent(fieldType);
                                        if (resolvedComp == null)
                                        {
                                            try
                                            {
                                                resolvedComp = resolvedObj2.AddComponent(fieldType);
                                                autoCreated = true;
                                            }
                                            catch (Exception addEx)
                                            {
                                                failureReason = $"component_type_missing: {addEx.Message}";
                                            }
                                        }
                                        if (resolvedComp != null)
                                        {
                                            prop.objectReferenceValue = resolvedComp;
                                            so.ApplyModifiedProperties();
                                            repaired2 = true;
                                            repairedCount++;
                                        }
                                    }
                                    else
                                    {
                                        prop.objectReferenceValue = resolvedObj2;
                                        so.ApplyModifiedProperties();
                                        repaired2 = true;
                                        repairedCount++;
                                    }
                                }
                                else
                                {
                                    failureReason = "no_gameobject_found";
                                }

                                // ─── Phase 3: Record issue with full diagnostics ───
                                issues.Add(new
                                {
                                    field = propName,
                                    displayName = prop.displayName,
                                    null_reference = true,
                                    resolved_path = resolvedObj2 != null ? resolvedObj2.name : null,
                                    repaired = repaired2,
                                    strategy = strategy2 ?? "none",
                                    auto_created_component = autoCreated,
                                    failure_reason = failureReason
                                });
                            }
                        } while (prop.NextVisible(false));
                    }
                    if (repairedCount > 0)
                    {
                        EditorUtility.SetDirty(comp);
                        UnityEditor.SceneManagement.EditorSceneManager.MarkSceneDirty(comp.gameObject.scene);
                    }

                    return SuccessResult(new
                    {
                        component = compType,
                        path = path,
                        total_null_refs = totalNullRefs,
                        repaired_count = repairedCount,
                        scene_dirty = repairedCount > 0,
                        auto_saved = false,
                        issues = issues,
                        warnings = warnings,
                        configuration_warnings_count = warnings.Count
                    });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
            }
            finally
            {
                // Save prefab edits back
                if (isPrefabEdit && target != null)
                {
                    PrefabUtility.SaveAsPrefabAsset(target, prefabPath);
                    PrefabUtility.UnloadPrefabContents(target);
                }
            }
        }
    }
}
