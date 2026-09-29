using System;
using System.IO;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityMCP.Editor.Services;
using UnityMCP.Editor.Core;

public static class CorePipelineSmoke
{
    private static JObject Call(string tool, JObject args)
    {
        var response = JObject.Parse(ToolDispatcher.Dispatch(tool, args));
        if (response["status"]?.ToString() != "success") throw new Exception(response.ToString());
        return response;
    }
    public static void Run()
    {
        try
        {
            if (EditorApplication.isCompiling) throw new Exception("Editor is still compiling");
            PluginHub.Start();
            if (!PluginHub.IsRunning) throw new Exception("PluginHub is not healthy");
            Call("manage_editor", new JObject { ["action"] = "get_editor_state" });
            var attributed = Call("core_smoke_attribute", new JObject());
            if (attributed["result"]?["value"]?.Value<int>() != 7) throw new Exception("Attribute/default parameter dispatch failed");
            var register = typeof(ToolDispatcher).GetMethod("RegisterHandler", System.Reflection.BindingFlags.Static | System.Reflection.BindingFlags.NonPublic);
            try
            {
                register.Invoke(null, new object[] { "manage_scene", null });
                throw new Exception("Duplicate registration was accepted");
            }
            catch (System.Reflection.TargetInvocationException error) when (error.InnerException is InvalidOperationException) { }
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            Call("manage_gameobject", new JObject { ["action"] = "create", ["name"] = "CoreSmoke" });
            Call("manage_components", new JObject { ["action"] = "add", ["path"] = "CoreSmoke", ["component_type"] = "Rigidbody" });
            Call("manage_components", new JObject { ["action"] = "set_property", ["path"] = "CoreSmoke", ["component_type"] = "Rigidbody", ["property_name"] = "mass", ["value"] = 2.0 });
            if (Math.Abs(GameObject.Find("CoreSmoke").GetComponent<Rigidbody>().mass - 2f) > .001f) throw new Exception("Component update failed");
            Call("manage_editor", new JObject { ["action"] = "refresh" });
            var compilation = Call("manage_editor", new JObject { ["action"] = "check_compile_errors" });
            if (compilation["result"]?["has_errors"]?.Value<bool>() == true) throw new Exception(compilation.ToString());
            var validation = Call("validate_script", new JObject());
            if (validation["result"]?["valid"]?.Value<bool>() != true) throw new Exception(validation.ToString());
            File.WriteAllText("smoke-result.json", new JObject { ["status"] = "passed", ["checks"] = new JArray("health", "editor_state", "attribute_discovery", "duplicate_registration", "create", "component_update", "refresh", "compile_errors", "validate") }.ToString());
            PluginHub.Stop();
            EditorApplication.Exit(0);
        }
        catch (Exception error)
        {
            File.WriteAllText("smoke-result.json", new JObject { ["status"] = "failed", ["error"] = error.ToString() }.ToString());
            Debug.LogException(error);
            EditorApplication.Exit(1);
        }
    }
}

[McpTool(Name = "core_smoke_attribute", Group = "core")]
public static class CoreSmokeAttributedTool
{
    [McpToolAction]
    public static object Execute(int value = 7) => new { success = true, value };
}
