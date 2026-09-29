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

        private static string HandleManageEditor(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "play";

            switch (action)
            {
                case "play":
                    EditorApplication.isPlaying = true;
                    break;
                case "stop":
                    EditorApplication.isPlaying = false;
                    break;
                case "pause":
                    EditorApplication.isPaused = true;
                    break;
                case "check_compile_errors":
                    return CheckCompileErrors();
                case "refresh":
                    {
                        bool forceRefresh = a["force"]?.Value<bool>() ?? false;
                        _lastRefreshTime = DateTime.Now; // mark cutoff for future log queries
                        AssetDatabase.Refresh(forceRefresh ? ImportAssetOptions.ForceUpdate : ImportAssetOptions.Default);
                    }
                    return SuccessResult(new { action = "refresh", state = EditorApplication.isCompiling ? "compiling" : "submitted" });

                case "get_unity_logs":
                    return GetUnityLogs(a);

                case "get_game_object_info":
                    return GetGameObjectInfo(a);

                case "list_hierarchy":
                    return ListHierarchy(a);

                case "capture_screenshot":
                case "capture_scene_object":
                case "capture_ui_canvas":
                    return CaptureScreenshot(a);

                case "get_editor_state":
                    return SuccessResult(new {
                        is_playing = EditorApplication.isPlaying,
                        is_paused = EditorApplication.isPaused,
                        is_compiling = EditorApplication.isCompiling,
                        active_scene = SceneManager.GetActiveScene().name,
                        active_scene_path = SceneManager.GetActiveScene().path,
                        selection_count = Selection.gameObjects.Length,
                    });

                case "execute_menu_item":
                    {
                        string menuPath = a["menu_path"]?.ToString();
                        if (!string.IsNullOrEmpty(menuPath))
                        {
                            EditorApplication.ExecuteMenuItem(menuPath);
                            return SuccessResult(new { menu_path = menuPath });
                        }
                        return ErrorResult("menu_path is required for execute_menu_item");
                    }

                case "get_registered_actions":
                    return SuccessResult(new {
                        handlers = _handlers.Keys.ToList(),
                        handler_count = _handlers.Count,
                    });

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
            return SuccessResult(new { state = action });
        }

        /// <summary>
        /// Check for compilation errors by querying Unity's log and compiler state.
        /// </summary>

        private static string CheckCompileErrors()
        {
            bool isCompiling = EditorApplication.isCompiling;
            if (isCompiling)
            {
                return SuccessResult(new
                {
                    is_compiling = true,
                    has_errors = false,
                    error_count = 0,
                    message = "Unity is currently compiling. Please wait and check again."
                });
            }

            // Collect compile errors from the rolling log buffer + Unity console
            var errorCount = 0;
            var errors = new List<string>();

            // ── Strategy 1: Scan our own in-memory log buffer, filtering by _lastRefreshTime ──
            lock (_logBuffer)
            {
                foreach (var entry in _logBuffer)
                {
                    // Skip logs from before the last refresh point
                    if (entry.time < _lastRefreshTime) continue;

                    if (entry.level == "error" && entry.message != null && entry.message.Contains("error CS"))
                    {
                        errorCount++;
                        if (errors.Count < 50)
                            errors.Add(entry.message.Length > 300
                                ? entry.message.Substring(0, 300) + "..." : entry.message);
                    }
                }
            }

            // ── Strategy 2: Try Unity's internal log API for completeness ──
            if (errorCount == 0)
            {
                try
                {
                    var logEntriesType = Assembly.GetAssembly(typeof(EditorWindow))
                        ?.GetType("UnityEditor.LogEntries");
                    if (logEntriesType != null)
                    {
                        var getCountMethod = logEntriesType.GetMethod("GetCount",
                            BindingFlags.Static | BindingFlags.Public);
                        int totalCount = getCountMethod != null
                            ? (int)getCountMethod.Invoke(null, null) : 0;

                        // Use newer API: GetEntry(int, out LogEntry) for 2022+
                        var getEntryMethod = logEntriesType.GetMethod("GetEntry",
                            BindingFlags.Static | BindingFlags.Public);

                        var startRowMethod = logEntriesType.GetMethod("StartGettingEntries",
                            BindingFlags.Static | BindingFlags.Public);
                        var endRowMethod = logEntriesType.GetMethod("EndGettingEntries",
                            BindingFlags.Static | BindingFlags.Public);

                        if (getEntryMethod != null)
                        {
                            startRowMethod?.Invoke(null, new object[] { 0 });
                            for (int i = 0; i < totalCount && i < 200; i++)
                            {
                                try
                                {
                                    var args = new object[] { i, null };
                                    getEntryMethod.Invoke(null, args);
                                    var logEntry = args[1];
                                    if (logEntry != null)
                                    {
                                        var modeProp = logEntry.GetType().GetProperty("mode");
                                        int mode = modeProp != null ? (int)modeProp.GetValue(logEntry) : -1;
                                        if (mode == 0 || mode == 1)
                                        {
                                            var msgProp = logEntry.GetType().GetProperty("message");
                                            var msg = msgProp?.GetValue(logEntry)?.ToString();
                                            if (msg != null && msg.Contains("error CS"))
                                            {
                                                errorCount++;
                                                if (errors.Count < 50)
                                                    errors.Add(msg.Length > 300
                                                        ? msg.Substring(0, 300) + "..." : msg);
                                            }
                                        }
                                    }
                                }
                                catch (ArgumentOutOfRangeException) { break; }
                                catch (TargetInvocationException) { break; }
                            }
                            endRowMethod?.Invoke(null, null);
                        }
                    }
                }
                catch (Exception ex)
                {
                    Debug.Log($"[MCP] Compile check reflection fallback: {ex.Message}");
                }
            }

            return SuccessResult(new
            {
                is_compiling = false,
                has_errors = errorCount > 0,
                error_count = errorCount,
                errors = errorCount > 0 ? JArray.FromObject(errors) : new JArray(),
                message = errorCount > 0
                    ? $"Found {errorCount} compilation error(s)"
                    : "No compilation errors"
            });
        }


        /// <summary>Retrieve Unity console log entries with timestamp-based filtering.</summary>

        private static string GetUnityLogs(JToken args)
        {
            int skip = args?["skip_newest_n_logs"]?.Value<int>() ?? 0;
            int limit = args?["limit"]?.Value<int>() ?? 100;
            bool showLogs = args?["show_logs"]?.Value<bool>() ?? true;
            bool showWarnings = args?["show_warnings"]?.Value<bool>() ?? true;
            bool showErrors = args?["show_errors"]?.Value<bool>() ?? true;
            string searchTerm = args?["search_term"]?.ToString();

            // ── clear_buffer: reset the in-memory buffer (optional) ──
            if (args?["clear_buffer"]?.Value<bool>() == true)
            {
                lock (_logBuffer) { _logBuffer.Clear(); }
                return SuccessResult(new { logs = new JArray(), count = 0, source = "buffer",
                    message = "Log buffer cleared" });
            }

            // ── since_seconds: filter entries older than this many seconds ──
            double? sinceSeconds = args?["since_seconds"]?.Value<double>();
            DateTime cutoff;
            if (sinceSeconds.HasValue && sinceSeconds.Value > 0)
                cutoff = DateTime.Now.AddSeconds(-sinceSeconds.Value);
            else if (_lastRefreshTime > DateTime.MinValue)
                cutoff = _lastRefreshTime;
            else
                cutoff = DateTime.MinValue;

            var entries = new JArray();

            // Primary: use in-memory buffer collected from Application.logMessageReceived
            try
            {
                List<(DateTime time, string level, string message, string stackTrace)> bufferCopy;
                lock (_logBuffer)
                {
                    bufferCopy = new List<(DateTime, string, string, string)>(_logBuffer);
                }

                if (bufferCopy.Count > 0)
                {
                    int startIdx = Math.Max(0, bufferCopy.Count - skip - limit);
                    int collected = 0;
                    for (int i = startIdx; i < bufferCopy.Count && collected < limit; i++)
                    {
                        var (time, level, msg, stack) = bufferCopy[i];

                        // Time-based cutoff filter
                        if (time < cutoff) continue;

                        if (level == "error" && !showErrors) continue;
                        if (level == "warning" && !showWarnings) continue;
                        if (level == "log" && !showLogs) continue;
                        if (!string.IsNullOrEmpty(searchTerm) && msg.IndexOf(searchTerm, StringComparison.OrdinalIgnoreCase) < 0) continue;

                        entries.Add(new JObject
                        {
                            ["level"] = level,
                            ["message"] = msg.Length > 500 ? msg.Substring(0, 500) + "..." : msg,
                            ["stack_trace"] = stack.Length > 500 ? stack.Substring(0, 500) + "..." : stack,
                            ["time"] = time.ToString("HH:mm:ss.fff"),
                        });
                        collected++;
                    }
                    return SuccessResult(new { logs = entries, count = entries.Count, source = "buffer",
                        total_buffered = bufferCopy.Count,
                        filtered_by_time = cutoff > DateTime.MinValue,
                        cutoff_time = cutoff > DateTime.MinValue ? cutoff.ToString("HH:mm:ss.fff") : null
                    });
                }
            }
            catch { /* fall through to file-based approach */ }

            // Fallback: try reflection-based LogEntries API, then file-based
            try
            {
                var assembly = Assembly.GetAssembly(typeof(EditorWindow));
                var logEntriesType = assembly?.GetType("UnityEditor.LogEntries");
                if (logEntriesType == null)
                    return ReadLogsFromFile(skip, limit, showLogs, showWarnings, showErrors, searchTerm);

                var startGettingMethod = logEntriesType.GetMethod("StartGettingEntries", BindingFlags.Static | BindingFlags.Public);
                var endGettingMethod = logEntriesType.GetMethod("EndGettingEntries", BindingFlags.Static | BindingFlags.Public);
                var getEntryMethod = logEntriesType.GetMethod("GetEntryInternal", BindingFlags.Static | BindingFlags.Public);
                var getCountMethod = logEntriesType.GetMethod("GetCount", BindingFlags.Static | BindingFlags.Public);

                if (startGettingMethod == null || endGettingMethod == null || getEntryMethod == null)
                    return ReadLogsFromFile(skip, limit, showLogs, showWarnings, showErrors, searchTerm);

                startGettingMethod.Invoke(null, null);
                try
                {
                    int totalCount = getCountMethod != null ? (int)getCountMethod.Invoke(null, null) : 0;

                    var parameters = new object[] { 0, null };
                    int collected = 0;
                    int startIdx = Math.Max(0, totalCount - skip - limit);
                    int endIdx = totalCount - skip;

                    for (int i = startIdx; i < endIdx && collected < limit; i++)
                    {
                        parameters[0] = i;
                        parameters[1] = null;
                        // GetEntryInternal may return bool or void depending on Unity version
                        object invokeResult = getEntryMethod.Invoke(null, parameters);
                        var logEntry = parameters[1];
                        bool ok = invokeResult is bool b ? b : logEntry != null;
                        if (!ok || logEntry == null) continue;

                        var logType = logEntry.GetType().GetProperty("mode")?.GetValue(logEntry);
                        int mode = logType != null ? (int)logType : 3;

                        if (mode == 0 && !showErrors) continue;
                        if (mode == 2 && !showWarnings) continue;
                        if (mode >= 3 && !showLogs) continue;

                        var msg = logEntry.GetType().GetProperty("message")?.GetValue(logEntry)?.ToString() ?? "";

                        if (!string.IsNullOrEmpty(searchTerm) && msg.IndexOf(searchTerm, StringComparison.OrdinalIgnoreCase) < 0) continue;

                        var stackTrace = "";
                        try
                        {
                            stackTrace = logEntry.GetType().GetProperty("stackTrace")?.GetValue(logEntry)?.ToString() ?? "";
                        }
                        catch { }

                        string level = mode <= 1 ? "error" : mode == 2 ? "warning" : "log";
                        entries.Add(new JObject
                        {
                            ["level"] = level,
                            ["message"] = msg.Length > 500 ? msg.Substring(0, 500) + "..." : msg,
                            ["stack_trace"] = stackTrace.Length > 500 ? stackTrace.Substring(0, 500) + "..." : stackTrace,
                        });
                        collected++;
                    }
                }
                finally
                {
                    endGettingMethod.Invoke(null, null);
                }
            }
            catch (TargetInvocationException)
            {
                // Fallback: read from Editor log file when reflection API fails
                return ReadLogsFromFile(skip, limit, showLogs, showWarnings, showErrors, searchTerm);
            }
            catch (Exception ex)
            {
                return ReadLogsFromFile(skip, limit, showLogs, showWarnings, showErrors, searchTerm);
            }

            return SuccessResult(new { logs = entries, count = entries.Count });
        }

        /// <summary>Fallback: read Unity console logs from Editor.log file.</summary>

        private static string ReadLogsFromFile(int skip, int limit, bool showLogs, bool showWarnings, bool showErrors, string searchTerm)
        {
            var entries = new JArray();
            try
            {
                string logPath = Application.consoleLogPath;
                if (!File.Exists(logPath))
                    return SuccessResult(new { logs = entries, count = 0, message = "Log file not found", source = "file" });

                // Use FileShare.ReadWrite because Unity has the log file open for writing
                string[] allLines;
                using (var fs = new FileStream(logPath, FileMode.Open, FileAccess.Read, FileShare.ReadWrite))
                using (var reader = new StreamReader(fs))
                {
                    var lines = new List<string>();
                    while (!reader.EndOfStream)
                        lines.Add(reader.ReadLine());
                    allLines = lines.ToArray();
                }
                int startIdx = Math.Max(0, allLines.Length - skip - limit);
                int collected = 0;

                for (int i = startIdx; i < allLines.Length && collected < limit; i++)
                {
                    string line = allLines[i];
                    string level = "log";
                    if (line.Contains("Exception") || line.Contains("Error") || line.Contains("error"))
                        level = "error";
                    else if (line.Contains("Warning") || line.Contains("warning"))
                        level = "warning";

                    if (level == "error" && !showErrors) continue;
                    if (level == "warning" && !showWarnings) continue;
                    if (level == "log" && !showLogs) continue;
                    if (!string.IsNullOrEmpty(searchTerm) && line.IndexOf(searchTerm, StringComparison.OrdinalIgnoreCase) < 0) continue;

                    entries.Add(new JObject
                    {
                        ["level"] = level,
                        ["message"] = line.Length > 500 ? line.Substring(0, 500) + "..." : line,
                        ["stack_trace"] = "",
                    });
                    collected++;
                }

                return SuccessResult(new { logs = entries, count = entries.Count, source = "file" });
            }
            catch (Exception ex)
            {
                return ErrorResult($"Failed to read logs from file: {ex.Message}");
            }
        }

        /// <summary>Get detailed info about a GameObject by name or path.</summary>

        private static string GetGameObjectInfo(JToken args)
        {
            string objectName = args?["object_name"]?.ToString();
            string path = args?["path"]?.ToString();
            bool includeChildren = args?["include_children"]?.Value<bool>() ?? true;
            bool includeComponents = args?["include_components"]?.Value<bool>() ?? true;
            int maxChildren = args?["max_children"]?.Value<int>() ?? 50;

            var target = !string.IsNullOrEmpty(objectName) ? FindByPath(objectName) : FindByPath(path);
            if (target == null) return ErrorResult($"Object not found: {objectName ?? path}");

            var obj = new JObject
            {
                ["name"] = target.name,
                ["active"] = target.activeSelf,
                ["tag"] = target.tag,
                ["layer"] = LayerMask.LayerToName(target.layer),
                ["instance_id"] = target.GetInstanceID(),
                ["path"] = GetInstancePath(target),
            };

            // Transform info
            var t = target.transform;
            obj["position"] = new JObject { ["x"] = t.position.x, ["y"] = t.position.y, ["z"] = t.position.z };
            obj["rotation"] = new JObject { ["x"] = t.rotation.eulerAngles.x, ["y"] = t.rotation.eulerAngles.y, ["z"] = t.rotation.eulerAngles.z };
            obj["scale"] = new JObject { ["x"] = t.localScale.x, ["y"] = t.localScale.y, ["z"] = t.localScale.z };
            obj["parent"] = t.parent?.name;
            obj["child_count"] = t.childCount;

            var renderers = target.GetComponentsInChildren<Renderer>(true);
            var colliders = target.GetComponentsInChildren<Collider>(true);
            Bounds combinedBounds;
            string boundsSource;
            bool hasBounds = TryGetCombinedBounds(renderers, colliders, out combinedBounds, out boundsSource);
            if (hasBounds)
            {
                obj["bounds"] = SerializeBounds(combinedBounds);
                obj["aabb"] = SerializeBounds(combinedBounds);
                obj["bounds_source"] = boundsSource;
            }
            else
            {
                obj["bounds"] = null;
                obj["aabb"] = null;
                obj["bounds_source"] = "none";
            }
            obj["renderer_count"] = renderers.Length;
            obj["collider_count"] = colliders.Length;

            if (includeComponents)
            {
                // Components
                var comps = new JArray();
                foreach (var comp in target.GetComponents<Component>())
                {
                    if (comp == null) continue;
                    comps.Add(new JObject
                    {
                        ["type"] = comp.GetType().FullName,
                        ["enabled"] = (comp is Behaviour b) ? b.enabled : true,
                    });
                }
                obj["components"] = comps;

                // Renderer info (if any)
                var renderer = target.GetComponent<Renderer>();
                if (renderer != null)
                {
                    var matInfo = new JArray();
                    foreach (var mat in renderer.sharedMaterials)
                    {
                        if (mat == null) continue;
                        matInfo.Add(new JObject
                        {
                            ["name"] = mat.name,
                            ["color"] = new JObject { ["r"] = mat.color.r, ["g"] = mat.color.g, ["b"] = mat.color.b, ["a"] = mat.color.a },
                        });
                    }
                    obj["materials"] = matInfo;
                }
            }

            // Children
            if (includeChildren && t.childCount > 0)
            {
                var children = new JArray();
                for (int i = 0; i < Math.Min(t.childCount, maxChildren); i++)
                {
                    var child = t.GetChild(i);
                    children.Add(new JObject
                    {
                        ["name"] = child.name,
                        ["active"] = child.gameObject.activeSelf,
                        ["position"] = new JObject { ["x"] = child.position.x, ["y"] = child.position.y, ["z"] = child.position.z },
                    });
                }
                obj["children"] = children;
            }

            return SuccessResult(obj);
        }

        private static bool TryGetCombinedBounds(
            Renderer[] renderers,
            Collider[] colliders,
            out Bounds bounds,
            out string source)
        {
            bounds = default;
            source = "none";
            bool initialized = false;

            foreach (var renderer in renderers)
            {
                if (renderer == null) continue;
                if (!initialized)
                {
                    bounds = renderer.bounds;
                    initialized = true;
                }
                else
                {
                    bounds.Encapsulate(renderer.bounds);
                }
            }

            if (initialized)
            {
                source = "renderers";
                return true;
            }

            foreach (var collider in colliders)
            {
                if (collider == null) continue;
                if (!initialized)
                {
                    bounds = collider.bounds;
                    initialized = true;
                }
                else
                {
                    bounds.Encapsulate(collider.bounds);
                }
            }

            if (initialized)
                source = "colliders";
            return initialized;
        }

        private static JObject SerializeBounds(Bounds bounds)
        {
            return new JObject
            {
                ["center"] = new JObject
                {
                    ["x"] = bounds.center.x,
                    ["y"] = bounds.center.y,
                    ["z"] = bounds.center.z
                },
                ["size"] = new JObject
                {
                    ["x"] = bounds.size.x,
                    ["y"] = bounds.size.y,
                    ["z"] = bounds.size.z
                },
                ["min"] = new JObject
                {
                    ["x"] = bounds.min.x,
                    ["y"] = bounds.min.y,
                    ["z"] = bounds.min.z
                },
                ["max"] = new JObject
                {
                    ["x"] = bounds.max.x,
                    ["y"] = bounds.max.y,
                    ["z"] = bounds.max.z
                }
            };
        }

        /// <summary>List GameObjects in hierarchy tree.</summary>

        private static string ListHierarchy(JToken args)
        {
            int count = args?["count"]?.Value<int>() ?? 30;
            string parentPath = args?["parent"]?.ToString();
            bool includeRoots = args?["include_roots"]?.Value<bool>() ?? true;

            var result = new JObject();

            if (includeRoots)
            {
                var rootObjects = new JArray();
                foreach (var go in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
                {
                    rootObjects.Add(BuildHierarchyNode(go, count / 5));
                }
                result["roots"] = rootObjects;
                result["root_count"] = rootObjects.Count;
            }

            if (!string.IsNullOrEmpty(parentPath))
            {
                var parent = FindByPath(parentPath);
                if (parent != null)
                {
                    var children = new JArray();
                    int childLimit = Math.Min(count, parent.transform.childCount);
                    for (int i = 0; i < childLimit; i++)
                    {
                        children.Add(BuildHierarchyNode(parent.transform.GetChild(i).gameObject, 3));
                    }
                    result["parent_path"] = parentPath;
                    result["children"] = children;
                    result["total_children"] = parent.transform.childCount;
                }
            }

            return SuccessResult(result);
        }

        private static JObject BuildHierarchyNode(GameObject go, int maxChildren, int depth = 0)
        {
            if (depth > 4) return new JObject { ["name"] = go.name, ["_truncated"] = true };

            var node = new JObject
            {
                ["name"] = go.name,
                ["active"] = go.activeSelf,
            };

            if (go.transform.childCount > 0)
            {
                var kids = new JArray();
                int limit = Math.Min(maxChildren, go.transform.childCount);
                for (int i = 0; i < limit; i++)
                {
                    kids.Add(BuildHierarchyNode(go.transform.GetChild(i).gameObject, Math.Max(1, maxChildren / 2), depth + 1));
                }
                node["children"] = kids;
                if (go.transform.childCount > maxChildren)
                    node["_truncated_children"] = go.transform.childCount;
            }

            return node;
        }

        /// <summary>Capture a screenshot from SceneView or GameView.</summary>

        private static string CaptureScreenshot(JToken args)
        {
            int width = Mathf.Clamp(args?["width"]?.Value<int>() ?? 1920, 64, 8192);
            int height = Mathf.Clamp(args?["height"]?.Value<int>() ?? 1080, 64, 8192);
            string format = args?["format"]?.ToString()?.ToUpperInvariant() ?? "PNG";
            if (format != "PNG" && format != "JPG" && format != "JPEG")
                return ErrorResult($"Unsupported screenshot format: {format}. Use PNG or JPG.");

            string extension = format == "PNG" ? ".png" : ".jpg";
            string filename = args?["filename"]?.ToString() ?? $"MCP_Screenshot_{DateTime.Now:yyyyMMdd_HHmmss}{extension}";
            string outputPath = args?["output_path"]?.ToString();
            string gameObjectPath = args?["gameobject_path"]?.ToString();
            if (string.IsNullOrEmpty(gameObjectPath))
                gameObjectPath = args?["canvas_path"]?.ToString();

            string fullPath;
            if (!string.IsNullOrEmpty(outputPath))
            {
                fullPath = outputPath;
            }
            else
            {
                fullPath = System.IO.Path.Combine(Application.dataPath, "..", filename);
            }

            try
            {
                fullPath = Path.GetFullPath(fullPath);
                string directory = Path.GetDirectoryName(fullPath);
                if (!string.IsNullOrEmpty(directory))
                    Directory.CreateDirectory(directory);

                var sceneView = SceneView.lastActiveSceneView ?? EditorWindow.GetWindow<SceneView>();
                if (sceneView == null || sceneView.camera == null)
                    return ErrorResult("No Scene view is available for screenshot capture.");

                GameObject framedObject = null;
                if (!string.IsNullOrEmpty(gameObjectPath))
                {
                    framedObject = FindByPath(gameObjectPath);
                    if (framedObject == null)
                        return ErrorResult($"Object not found for screenshot: {gameObjectPath}");

                    var objectRenderers = framedObject.GetComponentsInChildren<Renderer>(true);
                    var objectColliders = framedObject.GetComponentsInChildren<Collider>(true);
                    if (TryGetCombinedBounds(objectRenderers, objectColliders, out var bounds, out _))
                    {
                        float frameSize = Mathf.Max(bounds.size.x, bounds.size.y, bounds.size.z);
                        sceneView.LookAt(bounds.center, sceneView.rotation, Mathf.Max(frameSize * 2.1f, 0.5f), false, false);
                    }
                    else
                    {
                        sceneView.LookAt(framedObject.transform.position, sceneView.rotation, 2f, false, false);
                    }
                }

                var camera = sceneView.camera;
                var previousTarget = camera.targetTexture;
                var previousActive = RenderTexture.active;
                var renderTexture = RenderTexture.GetTemporary(width, height, 24, RenderTextureFormat.ARGB32);
                var texture = new Texture2D(width, height, TextureFormat.RGB24, false);
                try
                {
                    camera.targetTexture = renderTexture;
                    camera.Render();
                    RenderTexture.active = renderTexture;
                    texture.ReadPixels(new Rect(0, 0, width, height), 0, 0);
                    texture.Apply();

                    byte[] bytes = format == "PNG"
                        ? texture.EncodeToPNG()
                        : texture.EncodeToJPG(90);
                    File.WriteAllBytes(fullPath, bytes);
                }
                finally
                {
                    camera.targetTexture = previousTarget;
                    RenderTexture.active = previousActive;
                    RenderTexture.ReleaseTemporary(renderTexture);
                    UnityEngine.Object.DestroyImmediate(texture);
                }

                var fileInfo = new FileInfo(fullPath);
                return SuccessResult(new
                {
                    path = fullPath,
                    width,
                    height,
                    format = format == "JPEG" ? "JPG" : format,
                    framed_object = framedObject != null ? GetInstancePath(framedObject) : null,
                    file_exists = fileInfo.Exists,
                    file_size = fileInfo.Exists ? fileInfo.Length : 0,
                    message = $"Screenshot saved to {fullPath}"
                });
            }
            catch (Exception ex)
            {
                return ErrorResult($"Screenshot failed: {ex.Message}");
            }
        }

        private static string HandleReadConsole(JToken args)
        {
            int maxLines = args?["max_lines"]?.Value<int>() ?? 50;
            var lines = new List<string>();
            try
            {
                // Read from log file
                var logDir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "UnityMCP/Logs");
                var logFile = Path.Combine(logDir, "unified_mcp_server.log");
                if (File.Exists(logFile))
                {
                    var logLines = File.ReadAllLines(logFile);
                    lines.AddRange(logLines.Take(maxLines));
                }
            } catch { }
            return SuccessResult(new { logs = JArray.FromObject(lines), count = lines.Count });
        }

        private static string HandleManageCamera(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get";
            string cameraPath = a["camera_path"]?.ToString();
            Camera cam = !string.IsNullOrEmpty(cameraPath) ? FindByPath(cameraPath)?.GetComponent<Camera>() : Camera.main ?? UnityEngine.Object.FindFirstObjectByType<Camera>();
            if (cam == null) return ErrorResult("No camera found");

            switch (action)
            {
                case "get": return SuccessResult(new { name = cam.name, field_of_view = cam.fieldOfView, clear_flags = cam.clearFlags.ToString(), background = SerializeColor(cam.backgroundColor), near_clip = cam.nearClipPlane, far_clip = cam.farClipPlane, orthographic = cam.orthographic });
                case "set_property":
                    if (a["field_of_view"] == null && a["orthographic"] == null && a["orthographic_size"] == null && a["near_clip"] == null && a["far_clip"] == null) return ErrorResult("No supported camera properties supplied");
                    Undo.RecordObject(cam, "Set Camera Property");
                    if (a["orthographic_size"] != null) cam.orthographicSize = a["orthographic_size"].Value<float>();
                    if (a["near_clip"] != null) cam.nearClipPlane = a["near_clip"].Value<float>();
                    if (a["far_clip"] != null) cam.farClipPlane = a["far_clip"].Value<float>();
                    if (a["field_of_view"] != null) cam.fieldOfView = a["field_of_view"].Value<float>();
                    if (a["orthographic"] != null) cam.orthographic = a["orthographic"].Value<bool>();
                    return SuccessResult(new { camera = cam.name, updated = true });
                case "set_clear_flags":
                    Undo.RecordObject(cam, "Set Clear Flags");
                    if (a["clear_flags"] == null) return ErrorResult("clear_flags is required");
                    cam.clearFlags = (CameraClearFlags)Enum.Parse(typeof(CameraClearFlags), a["clear_flags"].ToString(), true);
                    return SuccessResult(new { camera = cam.name, clear_flags = cam.clearFlags.ToString() });
                case "set_background_color":
                    Undo.RecordObject(cam, "Set Background Color");
                    if (a["color"] == null) return ErrorResult("color is required");
                    cam.backgroundColor = ParseColor(a["color"]);
                    return SuccessResult(new { camera = cam.name, background = SerializeColor(cam.backgroundColor) });
                default: throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageGraphics(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get";
            if (action == "get")
                return SuccessResult(new { quality_level = QualitySettings.GetQualityLevel(), quality_name = QualitySettings.names[QualitySettings.GetQualityLevel()], vsync = QualitySettings.vSyncCount, target_fps = Application.targetFrameRate });
            if (action == "set_property")
            {
                if (a["v_sync_count"] == null && a["target_fps"] == null && a["quality_level"] == null) return ErrorResult("No supported graphics settings supplied");
                if (a["quality_level"] != null) QualitySettings.SetQualityLevel(a["quality_level"].Value<int>());
                if (a["v_sync_count"] != null) QualitySettings.vSyncCount = a["v_sync_count"].Value<int>();
                if (a["target_fps"] != null) Application.targetFrameRate = a["target_fps"].Value<int>();
                return SuccessResult(new { updated = true });
            }
            return ErrorResult($"Unknown graphics action: {action}");
        }
    }
}
