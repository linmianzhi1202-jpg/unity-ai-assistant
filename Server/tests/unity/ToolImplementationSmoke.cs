using System;
using System.IO;
using System.Text.RegularExpressions;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.Animations;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityMCP.Editor.Services;

public class ToolSmokeData : ScriptableObject { public float amount; }

[InitializeOnLoad]
public static class ToolImplementationSmoke
{
    static ToolImplementationSmoke()
    {
        if (SessionState.GetString("ToolSmokeStage", "") != "") EditorApplication.update += Continue;
    }
    static JObject Call(string name, JObject args, bool success = true)
    {
        var response = JObject.Parse(ToolDispatcher.Dispatch(name, args));
        if ((response["status"]?.ToString() == "success") != success) throw new Exception(name + ": " + response);
        return response;
    }
    static void Require(bool value, string message) { if (!value) throw new Exception(message); }
    static void Finish(Exception error = null)
    {
        SessionState.EraseString("ToolSmokeStage");
        EditorApplication.update -= Continue;
        File.WriteAllText("tool-implementation-result.json", new JObject {
            ["status"] = error == null ? "passed" : "failed", ["error"] = error?.ToString(),
            ["checks"] = new JArray("camera", "texture", "shader", "vfx", "animator_eight_actions", "blend_motion", "script_read", "batch_failure", "compiled_multistatement_execution", "runtime_exception")
        }.ToString());
        if (error != null) Debug.LogException(error);
        EditorApplication.Exit(error == null ? 0 : 1);
    }
    static void Submit(string code, string stage)
    {
        SessionState.SetString("ToolSmokeStage", stage);
        var response = Call("execute_script", new JObject { ["script"] = code });
        var id = Regex.Match(response["result"]?["output"]?.ToString() ?? "", @"\[MCP_EVAL_ID:([a-f0-9]+)\]").Groups[1].Value;
        Require(id.Length > 0, "No execution ID");
        SessionState.SetString("ToolSmokeEval", id);
    }
    static void Continue()
    {
        if (EditorApplication.isCompiling || EditorApplication.isUpdating) return;
        EditorApplication.update -= Continue;
        try
        {
            string id = SessionState.GetString("ToolSmokeEval", "");
            Require(EditorApplication.ExecuteMenuItem("Temp/MCP Eval " + id), "Compiled menu not available");
            var result = Call("execute_script", new JObject { ["eval_id"] = id })["result"];
            if (SessionState.GetString("ToolSmokeStage", "") == "success")
            {
                Require(result["state"]?.ToString() == "completed" && result["output"]?.ToString() == "42", "Wrong script result");
                Require(GameObject.Find("ExecutionProof").transform.position.y == 2, "Only part of script executed");
                Submit("throw new Exception(\"expected smoke failure\");", "failure");
            }
            else
            {
                Require(result["state"]?.ToString() == "failed", "Runtime exception reported success");
                Finish();
            }
        }
        catch (Exception error) { Finish(error); }
    }
    public static void Run()
    {
        try
        {
            PluginHub.Start(); Require(PluginHub.IsRunning && !EditorApplication.isCompiling, "Editor unavailable");
            Call("manage_editor", new JObject { ["action"] = "get_editor_state" });
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            string dir = "Assets/ToolSmoke_" + Guid.NewGuid().ToString("N"); Directory.CreateDirectory(dir); AssetDatabase.Refresh();
            var camera = new GameObject("ToolSmokeCamera").AddComponent<Camera>();
            Call("manage_camera", new JObject { ["action"] = "set_property", ["camera_path"] = "ToolSmokeCamera", ["field_of_view"] = 71 });
            Require(camera.fieldOfView == 71, "Camera did not change");
            Call("manage_camera", new JObject { ["action"] = "set_property", ["camera_path"] = "ToolSmokeCamera" }, false);
            string texturePath = dir + "/test.png"; var texture = new Texture2D(4,4); File.WriteAllBytes(texturePath, texture.EncodeToPNG()); UnityEngine.Object.DestroyImmediate(texture); AssetDatabase.ImportAsset(texturePath);
            Call("manage_texture", new JObject { ["action"] = "set_property", ["texture_path"] = texturePath, ["max_size"] = 512, ["mipmap_enabled"] = false });
            var importer = (TextureImporter)AssetImporter.GetAtPath(texturePath); Require(importer.maxTextureSize == 512 && !importer.mipmapEnabled, "Texture did not change");
            Call("manage_texture", new JObject { ["action"] = "bogus", ["texture_path"] = texturePath }, false);
            var material = new Material(Shader.Find("Standard")); string materialPath = dir + "/test.mat"; AssetDatabase.CreateAsset(material, materialPath);
            Call("manage_shader", new JObject { ["action"] = "set_property", ["shader_path"] = materialPath, ["property_name"] = "_Glossiness", ["float_value"] = .37f });
            Require(Mathf.Abs(material.GetFloat("_Glossiness")-.37f)<.001f, "Shader property did not change");
            Call("manage_shader", new JObject { ["action"] = "set_property", ["shader_path"] = materialPath, ["property_name"] = "absent", ["float_value"] = 1 }, false);
            var data = ScriptableObject.CreateInstance<ToolSmokeData>(); string dataPath = dir + "/data.asset"; AssetDatabase.CreateAsset(data, dataPath);
            Call("manage_vfx", new JObject { ["action"] = "set_property", ["vfx_path"] = dataPath, ["property_name"] = "amount", ["value"] = 6f }); Require(data.amount == 6, "Serialized VFX property did not change");
            Call("manage_vfx", new JObject { ["action"] = "set_property", ["vfx_path"] = dataPath, ["property_name"] = "absent", ["value"] = 6 }, false);
            string controllerPath = dir + "/test.controller"; var controller = AnimatorController.CreateAnimatorControllerAtPath(controllerPath);
            Action<string,JObject> edit = (action, options) => Call("manage_animation", new JObject { ["action"] = "modify_animator_controller", ["controller_path"] = controllerPath, ["modification_action"] = action, ["modification_params"] = options.ToString() });
            edit("add_parameter",new JObject { ["name"]="Speed", ["type"]="Float" }); Require(controller.parameters.Length == 1, "Parameter not added");
            edit("add_layer",new JObject { ["name"]="Upper" }); Require(controller.layers.Length == 2, "Layer not added");
            edit("add_state",new JObject { ["name"]="Idle" }); edit("add_state",new JObject { ["name"]="Run" });
            edit("add_transition",new JObject { ["from"]="Idle", ["to"]="Run" }); Require(controller.layers[0].stateMachine.states[0].state.transitions.Length == 1, "Transition not added");
            edit("remove_transition",new JObject { ["from"]="Idle", ["to"]="Run" }); edit("remove_state",new JObject { ["name"]="Run" }); edit("remove_layer",new JObject { ["name"]="Upper" }); edit("remove_parameter",new JObject { ["name"]="Speed" });
            Require(controller.layers.Length == 1 && controller.parameters.Length == 0 && controller.layers[0].stateMachine.states.Length == 1, "Animator removal failed");
            var clip = new AnimationClip(); string clipPath=dir+"/clip.anim"; AssetDatabase.CreateAsset(clip,clipPath);
            Call("manage_animation",new JObject { ["action"]="create_blend_tree_state", ["controller_path"]=controllerPath, ["state_name"]="Blend", ["motions"]=new JArray(new JObject { ["motion"]=clipPath, ["threshold"]=1 }) });
            Require(((BlendTree)controller.layers[0].stateMachine.states[1].state.motion).children.Length == 1,"Blend motion ignored");
            var read=Call("manage_script",new JObject { ["action"]="read",["folder"]="Assets/Editor",["name"]="ToolImplementationSmoke" }); Require(read["result"]?["content"]?.ToString().Contains("public static void Run") == true,"Script content absent");
            var batch=Call("batch_execute",new JObject { ["commands"]=new JArray(new JObject { ["tool"]="absent", ["params"]=new JObject() },new JObject { ["tool"]="manage_gameobject", ["params"]=new JObject { ["action"]="create",["name"]="MustNotExist" } }), ["stop_on_error"]=true },false);
            Require(batch["result"]?["fail"]?.Value<int>()==1 && GameObject.Find("MustNotExist")==null,"Batch failure ignored");
            var compile=Call("manage_editor",new JObject { ["action"]="check_compile_errors" }); Require(compile["result"]?["has_errors"]?.Value<bool>()==false,"Compilation errors");
            Submit("Debug.Log(\"first statement\"); var go = new GameObject(\"ExecutionProof\"); go.transform.position = new Vector3(1,2,3); return 42;", "success");
        }
        catch(Exception error) { Finish(error); }
    }
}
