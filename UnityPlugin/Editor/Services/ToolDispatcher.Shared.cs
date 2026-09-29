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

        private static Color ParseColor(JToken token)
        {
            if (token == null) return Color.white;
            // Array format: [r, g, b] or [r, g, b, a] (0-1 range)
            var arr = token as JArray;
            if (arr != null)
            {
                float r = arr.Count > 0 ? arr[0].Value<float>() : 1f;
                float g = arr.Count > 1 ? arr[1].Value<float>() : 1f;
                float b = arr.Count > 2 ? arr[2].Value<float>() : 1f;
                float a = arr.Count > 3 ? arr[3].Value<float>() : 1f;
                return new Color(r, g, b, a);
            }
            // Named colors
            string name = token.ToString().ToLowerInvariant();
            return name switch
            {
                "red" => Color.red,
                "green" => Color.green,
                "blue" => Color.blue,
                "yellow" => new Color(1f, 0.92f, 0.016f, 1f),
                "white" => Color.white,
                "black" => Color.black,
                "cyan" => Color.cyan,
                "magenta" => Color.magenta,
                "orange" => new Color(1f, 0.5f, 0f, 1f),
                "purple" => new Color(0.5f, 0f, 0.5f, 1f),
                "gray" or "grey" => Color.gray,
                _ => Color.white
            };
        }

        private static JToken SerializeColor(Color c)
        {
            return new JArray { c.r, c.g, c.b, c.a };
        }

        private static Type ResolveAnyType(string typeName)
        {
            if (string.IsNullOrEmpty(typeName)) return null;

            // 1. Try direct Type.GetType (works for fully qualified + assembly names)
            var type = Type.GetType(typeName);
            if (type != null) return type;

            // 2. Search all loaded assemblies by exact full name
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    type = assembly.GetType(typeName);
                    if (type != null) return type;
                }
                catch { }
            }

            // 3. Search by short name (last segment after last '.')
            string shortName = typeName.Contains('.') ? typeName.Substring(typeName.LastIndexOf('.') + 1) : typeName;
            // Also handle comma-separated assembly qualified names
            if (shortName.Contains(','))
                shortName = shortName.Split(',')[0].Trim();

            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    foreach (var t in assembly.GetTypes())
                    {
                        if (t.Name.Equals(shortName, StringComparison.OrdinalIgnoreCase) ||
                            t.FullName.Equals(shortName, StringComparison.OrdinalIgnoreCase))
                        {
                            return t;
                        }
                    }
                }
                catch { }
            }

            return null;
        }

        /// <summary>
        /// Resolve a MonoBehaviour type by short name, full name, or assembly-qualified name.
        /// Scans ALL loaded assemblies, not just Components. This is the key difference
        /// from ResolveComponentType — it finds MonoBehaviour scripts in ANY asmdef.
        /// </summary>

        private static Type ResolveMonoBehaviourType(string typeName)
        {
            if (string.IsNullOrEmpty(typeName)) return null;

            // 1. Try direct Type.GetType
            var type = Type.GetType(typeName);
            if (type != null && typeof(MonoBehaviour).IsAssignableFrom(type)) return type;

            // 2. Search by full name across assemblies
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    type = assembly.GetType(typeName);
                    if (type != null && typeof(MonoBehaviour).IsAssignableFrom(type)) return type;
                }
                catch { }
            }

            // 3. Parse assembly-qualified name (e.g., "MyGame.UI.HudController, MyGame.UI")
            string className = typeName;
            string assemblyName = null;
            int commaIdx = typeName.IndexOf(',');
            if (commaIdx > 0)
            {
                className = typeName.Substring(0, commaIdx).Trim();
                assemblyName = typeName.Substring(commaIdx + 1).Trim();
            }

            // 4. Target specific assembly if provided
            if (!string.IsNullOrEmpty(assemblyName))
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    try
                    {
                        if (assembly.GetName().Name.Equals(assemblyName, StringComparison.OrdinalIgnoreCase))
                        {
                            type = assembly.GetType(className);
                            if (type != null && typeof(MonoBehaviour).IsAssignableFrom(type)) return type;
                            break;
                        }
                    }
                    catch { }
                }
            }

            // 5. Fallback: scan all types for name match
            string shortName = className.Contains('.') ? className.Substring(className.LastIndexOf('.') + 1) : className;
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    foreach (var t in assembly.GetTypes())
                    {
                        if ((t.Name.Equals(shortName, StringComparison.OrdinalIgnoreCase) ||
                             t.FullName.Equals(className, StringComparison.OrdinalIgnoreCase)) &&
                            typeof(MonoBehaviour).IsAssignableFrom(t))
                        {
                            return t;
                        }
                    }
                }
                catch { }
            }

            return null;
        }

        /// <summary>
        /// Set a SerializedProperty from a JToken value, handling all common property types.
        /// Supports: string, int, float, bool, enum (by name), object reference (by asset path),
        /// array (JSON arrays), Vector3, Color.
        /// </summary>

        private static void SetSerializedPropertyFromToken(SerializedProperty prop, JToken token)
        {
            switch (prop.propertyType)
            {
                case SerializedPropertyType.String:
                    prop.stringValue = token.ToString();
                    break;

                case SerializedPropertyType.Integer:
                    prop.intValue = token.Value<int>();
                    break;

                case SerializedPropertyType.Float:
                    prop.floatValue = token.Value<float>();
                    break;

                case SerializedPropertyType.Boolean:
                    prop.boolValue = token.Value<bool>();
                    break;

                case SerializedPropertyType.Enum:
                    {
                        string enumStr = token.ToString();
                        // Try by name first
                        for (int i = 0; i < prop.enumDisplayNames.Length; i++)
                        {
                            if (prop.enumDisplayNames[i].Equals(enumStr, StringComparison.OrdinalIgnoreCase))
                            {
                                prop.enumValueIndex = i;
                                return;
                            }
                        }
                        // Try by int value
                        if (int.TryParse(enumStr, out int enumIdx) && enumIdx >= 0 && enumIdx < prop.enumDisplayNames.Length)
                        {
                            prop.enumValueIndex = enumIdx;
                        }
                    }
                    break;

                case SerializedPropertyType.ObjectReference:
                    {
                        string assetRef = token.ToString();
                        if (!string.IsNullOrEmpty(assetRef) && assetRef.StartsWith("Assets/"))
                        {
                            var obj = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(assetRef);
                            if (obj != null) prop.objectReferenceValue = obj;
                        }
                    }
                    break;

                case SerializedPropertyType.Color:
                    if (token is JObject colorObj)
                    {
                        float r = colorObj["r"]?.Value<float>() ?? 0f;
                        float g = colorObj["g"]?.Value<float>() ?? 0f;
                        float b = colorObj["b"]?.Value<float>() ?? 0f;
                        float a = colorObj["a"]?.Value<float>() ?? 1f;
                        prop.colorValue = new Color(r, g, b, a);
                    }
                    break;

                case SerializedPropertyType.Vector3:
                    if (token is JObject v3Obj)
                    {
                        float x = v3Obj["x"]?.Value<float>() ?? 0f;
                        float y = v3Obj["y"]?.Value<float>() ?? 0f;
                        float z = v3Obj["z"]?.Value<float>() ?? 0f;
                        prop.vector3Value = new Vector3(x, y, z);
                    }
                    else if (token is JArray v3Arr && v3Arr.Count >= 3)
                    {
                        prop.vector3Value = new Vector3(
                            v3Arr[0].Value<float>(), v3Arr[1].Value<float>(), v3Arr[2].Value<float>());
                    }
                    break;

                case SerializedPropertyType.Generic:
                    // Handle arrays (e.g., producedSchools[], requiredImageryTags[])
                    if (token is JArray jArr && prop.isArray)
                    {
                        prop.ClearArray();
                        for (int i = 0; i < jArr.Count; i++)
                        {
                            prop.InsertArrayElementAtIndex(i);
                            var elem = prop.GetArrayElementAtIndex(i);
                            SetSerializedPropertyFromToken(elem, jArr[i]);
                        }
                    }
                    break;

                default:
                    Debug.LogWarning(
                        $"[SetSerializedPropertyFromToken] Unsupported type {prop.propertyType} for '{prop.name}'. " +
                        $"Value: {token}");
                    break;
            }
        }

        private static Type ResolveComponentType(string typeName)
        {
            if (string.IsNullOrEmpty(typeName)) return null;

            // 1. Try direct Type.GetType (works for mscorlib types)
            var type = Type.GetType(typeName);
            if (type != null) return type;

            // 2. Search all loaded assemblies by short name and full name
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    // Exact match
                    type = assembly.GetType(typeName);
                    if (type != null) return type;

                    // With UnityEngine prefix
                    type = assembly.GetType("UnityEngine." + typeName);
                    if (type != null) return type;

                    // With UnityEditor prefix
                    type = assembly.GetType("UnityEditor." + typeName);
                    if (type != null) return type;

                    // With UnityEngine.AI prefix
                    type = assembly.GetType("UnityEngine.AI." + typeName);
                    if (type != null) return type;
                }
                catch { }
            }

            // 3. Fallback: scan all types for short name match that are Components
            try
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    try
                    {
                        foreach (var t in assembly.GetTypes())
                        {
                            if (t.Name.Equals(typeName, StringComparison.OrdinalIgnoreCase) &&
                                t.IsSubclassOf(typeof(Component)))
                            {
                                return t;
                            }
                        }
                    }
                    catch { }
                }
            }
            catch { }

            return null;
        }

        internal static GameObject FindByPath(string path)
        {
            if (string.IsNullOrEmpty(path)) return null;
            
            // Try hierarchy path first
            var parts = path.Split('/');
            GameObject current = null;
            for (int i = 0; i < parts.Length; i++)
            {
                var part = parts[i].Trim();
                if (string.IsNullOrEmpty(part)) continue;
                if (current == null)
                {
                    // First part: try root-level first, then deep search
                    current = GameObject.Find(part);
                    if (current == null)
                    {
                        // Deep search: scan all transforms for matching name
                        var roots = UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects();
                        foreach (var root in roots)
                        {
                            var allTransforms = root.GetComponentsInChildren<Transform>(true);
                            foreach (var t in allTransforms)
                            {
                                if (t.gameObject.name.Equals(part, StringComparison.OrdinalIgnoreCase))
                                {
                                    current = t.gameObject;
                                    break;
                                }
                            }
                            if (current != null) break;
                        }
                    }
                    if (current == null && i == 0) return null; // can't find root
                }
                else
                {
                    // Support "Name (N)" syntax for sibling index disambiguation
                    // e.g. "BuildGround (2)" → 3rd child named BuildGround
                    var match = System.Text.RegularExpressions.Regex.Match(part, @"^(.+?)\s*\((\d+)\)\s*$");
                    if (match.Success)
                    {
                        string baseName = match.Groups[1].Value.Trim();
                        int targetIndex = int.Parse(match.Groups[2].Value);
                        int foundIndex = 0;
                        Transform child = null;
                        for (int ci = 0; ci < current.transform.childCount; ci++)
                        {
                            var c = current.transform.GetChild(ci);
                            if (c.name.Equals(baseName, StringComparison.OrdinalIgnoreCase))
                            {
                                if (foundIndex == targetIndex)
                                {
                                    child = c;
                                    break;
                                }
                                foundIndex++;
                            }
                        }
                        if (child == null) return null;
                        current = child.gameObject;
                    }
                    else
                    {
                        Transform child = current.transform.Find(part);
                        if (child == null) return null;
                        current = child.gameObject;
                    }
                }
            }
            return current;
        }

        /// <summary>
        /// Get the C# field type for a SerializedProperty from its owning SerializedObject.
        /// </summary>

        private static Type GetFieldType(SerializedObject so, string propertyName)
        {
            var targetType = so?.targetObject?.GetType();
            if (targetType == null) return null;
            if (!string.IsNullOrEmpty(propertyName) && propertyName.Contains("."))
            {
                var pathType = GetFieldTypeFromPropertyPath(targetType, propertyName);
                if (pathType != null) return pathType;
            }
            var field = FindField(targetType, propertyName);
            if (field != null) return field.FieldType;
            // Also try stripped "m_" prefix
            if (propertyName.StartsWith("m_"))
            {
                var stripped = propertyName.Substring(2);
                field = FindField(targetType, stripped);
                if (field != null) return field.FieldType;
            }
            return null;
        }

        private static Type GetFieldType(SerializedProperty prop)
        {
            if (prop == null) return null;
            return GetFieldType(prop.serializedObject, prop.propertyPath)
                ?? GetFieldType(prop.serializedObject, prop.name);
        }

        private static FieldInfo FindField(Type type, string fieldName)
        {
            if (type == null || string.IsNullOrEmpty(fieldName)) return null;
            var flags = BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance;
            while (type != null)
            {
                var field = type.GetField(fieldName, flags);
                if (field != null) return field;
                if (fieldName.StartsWith("m_"))
                {
                    field = type.GetField(fieldName.Substring(2), flags);
                    if (field != null) return field;
                }
                type = type.BaseType;
            }
            return null;
        }

        private static Type GetFieldTypeFromPropertyPath(Type rootType, string propertyPath)
        {
            if (rootType == null || string.IsNullOrEmpty(propertyPath)) return null;
            Type currentType = rootType;
            var parts = propertyPath.Split('.');
            foreach (var rawPart in parts)
            {
                if (string.IsNullOrEmpty(rawPart) || rawPart == "Array") continue;
                if (rawPart.StartsWith("data[", StringComparison.Ordinal))
                {
                    currentType = GetElementType(currentType);
                    if (currentType == null) return null;
                    continue;
                }

                var field = FindField(currentType, rawPart);
                if (field == null) return null;
                currentType = field.FieldType;
            }
            return currentType;
        }

        private static Type GetElementType(Type type)
        {
            if (type == null) return null;
            if (type.IsArray) return type.GetElementType();
            if (type.IsGenericType && typeof(System.Collections.IEnumerable).IsAssignableFrom(type))
            {
                var args = type.GetGenericArguments();
                if (args.Length == 1) return args[0];
            }
            return null;
        }

        /// <summary>
        /// Try to find a GameObject by field name, with suffix-stripping, camelcase split,
        /// and GameObject.Find fallback strategies. Used by audit_references.
        /// </summary>
        internal static GameObject TryResolveByName(string lookupName, ref string strategy)
        {
            var resolved = FindByPath(lookupName);
            if (resolved != null) { strategy = "exact"; return resolved; }

            // Try stripping common suffixes
            var trialName = lookupName;
            foreach (var suffix in new[] { "Label", "Button", "Text", "Display", "Panel" })
            {
                if (trialName.EndsWith(suffix, StringComparison.OrdinalIgnoreCase) && trialName.Length > suffix.Length)
                {
                    trialName = trialName.Substring(0, trialName.Length - suffix.Length);
                    resolved = FindByPath(trialName);
                    if (resolved != null) { strategy = "suffix_stripped"; return resolved; }
                    trialName = lookupName;
                }
            }

            // Try CamelCase token splitting
            if (TryCamelCaseMatch(lookupName, out var ccGo, out var ccStrat))
            {
                strategy = ccStrat;
                return ccGo;
            }

            // Last-resort: plain GameObject.Find
            resolved = GameObject.Find(lookupName);
            if (resolved != null) { strategy = "gameobject_find"; return resolved; }

            return null;
        }

        /// <summary>
        /// Resolve the correct UnityEngine.Object reference for a SerializedProperty.
        /// If the property expects a Component type, get that component from the GameObject.
        /// </summary>

        private static UnityEngine.Object ResolveObjectRef(SerializedProperty prop, GameObject go)
        {
            if (go == null) return null;
            var fieldType = GetFieldType(prop);
            if (fieldType != null && typeof(Component).IsAssignableFrom(fieldType))
            {
                var comp = go.GetComponent(fieldType);
                if (comp != null) return comp;
            }
            return go;
        }

        private static UnityEngine.Object ResolveObjectRef(SerializedProperty prop, UnityEngine.Object obj)
        {
            if (obj == null) return null;
            if (obj is GameObject go) return ResolveObjectRef(prop, go);
            return obj;
        }

        /// <summary>
        /// Split a CamelCase name into tokens and try to match a GameObject
        /// by removing the leading token, using the last token, or matching individual tokens.
        /// </summary>
        /// <returns>True if a matching GameObject was found.</returns>

        private static bool TryCamelCaseMatch(string lookupName, out GameObject go, out string strategy)
        {
            go = null;
            strategy = null;

            if (string.IsNullOrEmpty(lookupName)) return false;

            // Split by upper-case transitions: "towerFirePoint" → ["tower","Fire","Point"]
            var tokens = new List<string>();
            var word = new System.Text.StringBuilder();
            foreach (var ch in lookupName)
            {
                if (char.IsUpper(ch) && word.Length > 0)
                {
                    tokens.Add(word.ToString());
                    word.Clear();
                }
                word.Append(ch);
            }
            if (word.Length > 0) tokens.Add(word.ToString());

            if (tokens.Count <= 1) return false;

            // Strategy A: skip first token  ("towerFirePoint" → "FirePoint")
            var variant = string.Concat(tokens.Skip(1));
            go = FindByPath(variant);
            if (go != null) { strategy = "camelcase_split"; return true; }

            // Strategy B: last token only
            variant = tokens[tokens.Count - 1];
            go = FindByPath(variant);
            if (go != null) { strategy = "camelcase_split"; return true; }

            // Strategy C: try each token individually
            foreach (var token in tokens)
            {
                if (token.Length <= 1) continue;
                go = FindByPath(token);
                if (go != null) { strategy = "camelcase_split"; return true; }
            }

            return false;
        }

        internal static List<T> FindObjectsOfType<T>(string nameFilter = null) where T : Component
        {
            var results = new List<T>();
            var roots = UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects();
            
            foreach (var root in roots)
            {
                var comps = root.GetComponentsInChildren<T>(true);
                foreach (var c in comps)
                {
                    var go = c.gameObject;
                    if (string.IsNullOrEmpty(nameFilter) ||
                        go.name.IndexOf(nameFilter, StringComparison.OrdinalIgnoreCase) >= 0)
                        results.Add(c);
                }
            }
            return results;
        }

        internal static List<GameObject> FindGameObjects(string nameFilter = null)
        {
            var results = new List<GameObject>();
            var roots = UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects();
            
            foreach (var root in roots)
            {
                if (string.IsNullOrEmpty(nameFilter) ||
                    root.name.IndexOf(nameFilter, StringComparison.OrdinalIgnoreCase) >= 0)
                    results.Add(root);
                
                var children = root.GetComponentsInChildren<Transform>(true);
                foreach (var t in children)
                {
                    if (t != root.transform &&
                        (string.IsNullOrEmpty(nameFilter) ||
                         t.gameObject.name.IndexOf(nameFilter, StringComparison.OrdinalIgnoreCase) >= 0))
                        results.Add(t.gameObject);
                }
            }
            return results;
        }

        internal static string GetInstancePath(GameObject go)
        {
            if (go == null) return "null";
            var path = new StringBuilder(go.name);
            var parent = go.transform.parent;
            while (parent != null)
            {
                path.Insert(0, parent.name + "/");
                parent = parent.parent;
            }
            return path.ToString();
        }

        internal static JObject SerializeGameObject(GameObject go, bool recursive = false)
        {
            var obj = new JObject
            {
                ["name"] = go.name,
                ["instanceId"] = GetInstancePath(go),
                ["path"] = GetInstancePath(go),
                ["active"] = go.activeInHierarchy
            };
            
            var pos = go.transform.position;
            obj["position"] = SerializeVector3(pos);
            
            var rot = go.transform.eulerAngles;
            obj["rotation"] = SerializeVector3(rot);
            
            var scl = go.transform.localScale;
            obj["scale"] = SerializeVector3(scl);
            
            if (recursive)
            {
                var children = new JArray();
                for (int i = 0; i < go.transform.childCount; i++)
                {
                    var child = go.transform.GetChild(i).gameObject;
                    children.Add(SerializeGameObject(child, true));
                }
                if (children.Count > 0) obj["children"] = children;
            }
            
            return obj;
        }

        internal static Vector3 ParseVector3(JToken token)
        {
            if (token == null) return Vector3.zero;
            var arr = token as JArray;
            if (arr != null && arr.Count >= 3)
                return new Vector3(arr[0].Value<float>(), arr[1].Value<float>(), arr[2].Value<float>());
            
            var x = token["x"]?.Value<float>() ?? 0f;
            var y = token["y"]?.Value<float>() ?? 0f;
            var z = token["z"]?.Value<float>() ?? 0f;
            return new Vector3(x, y, z);
        }

        internal static Vector3 ParseVector33(JToken token)
        {
            if (token == null) return Vector3.one;
            var x = token["x"]?.Value<float>() ?? 1f;
            var y = token["y"]?.Value<float>() ?? 1f;
            var z = token["z"]?.Value<float>() ?? 1f;
            return new Vector3(x, y, z);
        }

        internal static JToken SerializeVector3(Vector3 v)
        {
            return new JArray { v.x, v.y, v.z };
        }

        private static string SuccessResult(object data = null)
        {
            var result = new JObject { ["status"] = "success" };
            if (data != null) result["result"] = JToken.FromObject(data);
            return result.ToString(Formatting.None);
        }

        private static string ErrorResult(string error)
        {
            return new JObject
            {
                ["status"] = "error",
                ["error"] = error
            }.ToString(Formatting.None);
        }

        private static string NotImplemented(string tool)
        {
            return ErrorResult($"Tool '{tool}' not yet implemented. Use MCP tools via unified-mcp-unity server instead.");
        }

        /// <summary>
        /// Convert a string value to the target type, with special handling for Unity Object references.
        /// </summary>

        private static object ConvertValue(Type targetType, string stringValue, string assetPath)
        {
            // Handle arrays: comma-separated values
            if (targetType.IsArray)
            {
                var elemType = targetType.GetElementType();
                var parts = stringValue.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
                var array = Array.CreateInstance(elemType, parts.Length);
                for (int i = 0; i < parts.Length; i++)
                {
                    var val = ConvertValue(elemType, parts[i].Trim(), assetPath);
                    if (val != null) array.SetValue(val, i);
                }
                return array;
            }
            // Handle Unity Object references (Component types loaded from Prefab/GameObject)
            if (typeof(Component).IsAssignableFrom(targetType))
            {
                // Try as prefab path → load GameObject → GetComponent
                string loadPath = assetPath ?? stringValue;
                if (!string.IsNullOrEmpty(loadPath) && loadPath.StartsWith("Assets/"))
                {
                    var go = AssetDatabase.LoadAssetAtPath<GameObject>(loadPath);
                    if (go != null) return go.GetComponent(targetType);
                }
                // Try as scene hierarchy path (e.g., "Canvas/Button")
                var sceneGo = FindByPath(stringValue);
                if (sceneGo != null) return sceneGo.GetComponent(targetType);
                // Fallback: try by plain name
                sceneGo = GameObject.Find(stringValue);
                if (sceneGo != null) return sceneGo.GetComponent(targetType);
                return null;
            }
            // Handle Unity Object references (ScriptableObject, Material, etc.)
            if (typeof(UnityEngine.Object).IsAssignableFrom(targetType))
            {
                string loadPath = assetPath ?? stringValue;
                if (!string.IsNullOrEmpty(loadPath) && loadPath.StartsWith("Assets/"))
                {
                    var obj = AssetDatabase.LoadAssetAtPath(loadPath, targetType);
                    if (obj != null) return obj;
                }
                if (!string.IsNullOrEmpty(stringValue) && stringValue.StartsWith("Assets/"))
                {
                    var obj = AssetDatabase.LoadAssetAtPath(stringValue, targetType);
                    if (obj != null) return obj;
                }
                // Try as scene hierarchy path (e.g., "Canvas/Button")
                var go = FindByPath(stringValue);
                if (go != null) return go;
                // Fallback: try by plain name
                go = GameObject.Find(stringValue);
                if (go != null) return go;
                return null;
            }
            // Handle enums
            if (targetType.IsEnum)
                return Enum.Parse(targetType, stringValue, true);
            // Handle bool
            if (targetType == typeof(bool))
                return stringValue.ToLowerInvariant() is "true" or "1" or "yes";
            // Handle Vector2/Vector3/Vector4
            if (targetType == typeof(Vector2))
            {
                var parts = stringValue.Split(',').Select(s => float.Parse(s.Trim())).ToArray();
                return new Vector2(parts[0], parts.Length > 1 ? parts[1] : 0);
            }
            if (targetType == typeof(Vector3))
            {
                var parts = stringValue.Split(',').Select(s => float.Parse(s.Trim())).ToArray();
                return new Vector3(parts[0], parts.Length > 1 ? parts[1] : 0, parts.Length > 2 ? parts[2] : 0);
            }
            // Default: Convert.ChangeType (int, float, string, double)
            return Convert.ChangeType(stringValue, targetType);
        }

        /// <summary>
        /// Set a SerializedProperty value from a string, handling different property types.
        /// </summary>

        private static void SetSerializedProperty(SerializedProperty prop, string stringValue, string assetPath)
        {
            // Handle arrays: split by comma, clear existing, add each element
            if (prop.isArray)
            {
                prop.ClearArray();
                var items = stringValue.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
                for (int i = 0; i < items.Length; i++)
                {
                    prop.InsertArrayElementAtIndex(i);
                    var elem = prop.GetArrayElementAtIndex(i);
                    SetSerializedProperty(elem, items[i].Trim(), assetPath);
                }
                return;
            }
            switch (prop.propertyType)
            {
                case SerializedPropertyType.ObjectReference:
                    // 1) Try asset path (e.g., "Assets/Prefabs/Enemy1.prefab")
                    string loadPath = assetPath ?? stringValue;
                    if (!string.IsNullOrEmpty(loadPath) && loadPath.StartsWith("Assets/"))
                    {
                        var obj = AssetDatabase.LoadAssetAtPath(loadPath, typeof(UnityEngine.Object));
                        if (obj != null) { prop.objectReferenceValue = ResolveObjectRef(prop, obj); break; }
                    }
                    // 2) Try scene hierarchy path (e.g., "Canvas/Button")
                    var sceneGo = FindByPath(stringValue);
                    if (sceneGo != null) { prop.objectReferenceValue = ResolveObjectRef(prop, sceneGo); break; }
                    // 3) Fallback: try by plain name
                    sceneGo = GameObject.Find(stringValue);
                    if (sceneGo != null) { prop.objectReferenceValue = ResolveObjectRef(prop, sceneGo); }
                    break;
                case SerializedPropertyType.Boolean:
                    prop.boolValue = stringValue.ToLowerInvariant() is "true" or "1" or "yes";
                    break;
                case SerializedPropertyType.Integer:
                    prop.intValue = int.Parse(stringValue);
                    break;
                case SerializedPropertyType.Float:
                    prop.floatValue = float.Parse(stringValue);
                    break;
                case SerializedPropertyType.String:
                    prop.stringValue = stringValue;
                    break;
                case SerializedPropertyType.Enum:
                    prop.enumValueIndex = prop.enumValueIndex; // Use string lookup
                    for (int i = 0; i < prop.enumDisplayNames.Length; i++)
                    {
                        if (prop.enumDisplayNames[i].Equals(stringValue, StringComparison.OrdinalIgnoreCase))
                        {
                            prop.enumValueIndex = i;
                            break;
                        }
                    }
                    break;
                case SerializedPropertyType.Color:
                    var color = ParseColor(JToken.FromObject(stringValue));
                    prop.colorValue = color;
                    break;
                case SerializedPropertyType.Vector3:
                    var v3 = ParseVector3(JToken.FromObject(stringValue.Split(',').Select(float.Parse).ToArray()));
                    prop.vector3Value = v3;
                    break;
                default:
                    throw new ArgumentException($"Unsupported property type: {prop.propertyType}");
            }
        }
    }
}
