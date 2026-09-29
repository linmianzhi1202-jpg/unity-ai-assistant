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
    /// <summary>
    /// Dispatches tool calls from Python MCP Server to Unity Editor APIs.
    /// Uses reflection to find and invoke tool handler methods.
    /// </summary>
    public static partial class ToolDispatcher
    {
        private static readonly Dictionary<string, ToolHandler> _handlers = new();
        private static bool _initialized = false;

        // Rolling log buffer for get_unity_logs (avoids Editor.log file lock issues)
        // Each entry is (timestamp, level, message, stackTrace) to enable time-based filtering
        private static readonly List<(DateTime time, string level, string message, string stackTrace)> _logBuffer = new();
        private const int MaxLogBufferSize = 2000;

        // Timestamp of last refresh / explicit "mark this point" — used to filter out old logs
        private static DateTime _lastRefreshTime = DateTime.MinValue;

        private static void OnLogMessageReceived(string condition, string stackTrace, LogType type)
        {
            string level = type switch
            {
                LogType.Error or LogType.Exception or LogType.Assert => "error",
                LogType.Warning => "warning",
                _ => "log",
            };
            lock (_logBuffer)
            {
                if (_logBuffer.Count >= MaxLogBufferSize)
                    _logBuffer.RemoveRange(0, _logBuffer.Count - MaxLogBufferSize / 2);
                _logBuffer.Add((DateTime.Now, level, condition, stackTrace ?? ""));
            }
        }

        public static void Initialize()
        {
            if (_initialized) return;
            _handlers.Clear();

            // Collect Unity console logs into in-memory buffer
            Application.logMessageReceived += OnLogMessageReceived;

            // Register built-in tool handlers
            RegisterHandler("manage_scene", HandleManageScene);
            RegisterHandler("manage_gameobject", HandleManageGameObject);
            RegisterHandler("manage_components", HandleManageComponents);
            RegisterHandler("manage_transform", HandleManageTransform);
            RegisterHandler("set_tag", HandleSetTag);
            RegisterHandler("set_layer", HandleSetLayer);
            RegisterHandler("manage_script", HandleManageScript);
            RegisterHandler("validate_script", HandleValidateScript);
            RegisterHandler("execute_script", HandleExecuteScript);
            RegisterHandler("manage_animation", HandleManageAnimation);
            RegisterHandler("manage_vfx", HandleManageVfx);
            RegisterHandler("manage_material", HandleManageMaterial);
            RegisterHandler("manage_shader", HandleManageShader);
            RegisterHandler("manage_prefabs", HandleManagePrefabs);
            RegisterHandler("manage_scriptableObject", HandleManageScriptableObj);
            RegisterHandler("manage_asset", HandleManageAsset);
            RegisterHandler("manage_packages", HandleManagePackages);
            RegisterHandler("manage_texture", HandleManageTexture);
            RegisterHandler("manage_editor", HandleManageEditor);
            RegisterHandler("read_console", HandleReadConsole);
            RegisterHandler("batch_execute", HandleBatchExecute);
            RegisterHandler("run_tests", HandleRunTests);
            RegisterHandler("manage_camera", HandleManageCamera);
            RegisterHandler("manage_graphics", HandleManageGraphics);
            RegisterHandler("manage_ui", HandleManageUI);
            
            // Phase D: Extended Unity Editor Control
            RegisterHandler("create_scriptable_object", HandleCreateScriptableObject);
            RegisterHandler("attach_mbehaviour", HandleAttachMonoBehaviour);
            RegisterHandler("set_serialized_reference", HandleSetSerializedReference);
            
            // Auto-discover from [McpTool] attributed methods
            DiscoverAttributedTools();
            
            _initialized = true;
            Debug.Log($"[ToolDispatcher] Initialized with {_handlers.Count} handlers");
        }

        public static string Dispatch(string toolName, JToken args)
        {
            if (!_initialized) Initialize();
            
            if (!_handlers.TryGetValue(toolName.ToLowerInvariant(), out var handler))
            {
                return ErrorResult($"Unknown tool: {toolName}. Available: [{string.Join(", ", _handlers.Keys)}]");
            }

            try
            {
                return handler(args ?? new JObject());
            }
            catch (Exception ex)
            {
                return ErrorResult($"{toolName} error: {ex.Message}");
            }
        }

        #region Registration

        private delegate string ToolHandler(JToken args);

        private static void RegisterHandler(string name, ToolHandler handler)
        {
            if (string.IsNullOrEmpty(name)) return;
            string key = name.ToLowerInvariant();
            if (_handlers.ContainsKey(key))
                throw new InvalidOperationException($"Duplicate MCP handler: {name}");
            _handlers.Add(key, handler);
        }

        private static void DiscoverAttributedTools()
        {
            // Scan assemblies for [McpTool] attributed methods
            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    foreach (var type in assembly.GetTypes())
                    {
                        var attr = type.GetCustomAttribute<McpToolAttribute>(false);
                        if (attr == null) continue;
                        var methods = type.GetMethods(BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                            .Where(method => method.GetCustomAttribute<McpToolActionAttribute>(false) != null).ToArray();
                        if (methods.Length != 1)
                            throw new InvalidOperationException($"Expected one MCP action on {type.FullName}");
                        var action = methods[0];
                        RegisterHandler(attr.Name ?? type.Name, args => InvokeStaticMethod(action, args));
                    }
                }
                catch (ReflectionTypeLoadException) { /* skip non-loadable assemblies */ }
            }
        }

        private static string InvokeStaticMethod(MethodInfo method, JToken args)
        {
            try
            {
                object result = method.Invoke(null, ConvertArgs(method, args));
                var payload = JObject.FromObject(result);
                if (payload["success"]?.Value<bool>() == false)
                    return ErrorResult(payload["error"]?.ToString() ?? "Tool execution failed");
                return SuccessResult(result);
            }
            catch (TargetInvocationException tie)
            {
                throw tie.InnerException ?? tie;
            }
        }

        private static object[] ConvertArgs(MethodInfo method, JToken args)
        {
            
            var parameters = method.GetParameters();
            if (parameters.Length == 0) return null;
            
            var result = new object[parameters.Length];
            for (int i = 0; i < parameters.Length; i++)
            {
                JToken argVal = args?[parameters[i].Name];
                result[i] = argVal?.ToObject(parameters[i].ParameterType) ?? 
                             (parameters[i].HasDefaultValue ? parameters[i].DefaultValue : null);
            }
            return result;
        }

        #endregion


        private static JObject ParseArgs(JToken args, params string[] required)
        {
            var obj = args as JObject ?? new JObject();
            var missing = new List<string>();
            foreach (var r in required)
            {
                if (!obj.ContainsKey(r)) missing.Add(r);
            }
            if (missing.Count > 0)
                throw new ArgumentException($"Missing required args: {string.Join(", ", missing)}");
            return obj;
        }

    }
}
