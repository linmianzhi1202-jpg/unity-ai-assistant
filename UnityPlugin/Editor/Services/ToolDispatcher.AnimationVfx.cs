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

        private static string HandleManageAnimation(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "";

            switch (action)
            {
                case "create_animation_clip":
                {
                    string clipName = a["clip_name"]?.ToString() ?? "NewClip";
                    string savePath = a["save_path"]?.ToString() ?? "Assets/Animations/" + clipName + ".anim";
                    float frameRate = a["frame_rate"]?.Value<float>() ?? 60f;

                    var clip = new AnimationClip();
                    clip.name = clipName;
                    clip.frameRate = frameRate;

                    if (a["wrap_mode"] != null)
                    {
                        string wm = a["wrap_mode"].ToString();
                        clip.wrapMode = wm switch
                        {
                            "Loop" => WrapMode.Loop,
                            "Once" => WrapMode.Once,
                            "PingPong" => WrapMode.PingPong,
                            "ClampForever" => WrapMode.ClampForever,
                            _ => WrapMode.Default
                        };
                    }

                    string dir = Path.GetDirectoryName(savePath);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                        Directory.CreateDirectory(dir);

                    if (a["is_looping"] != null) { var settings = AnimationUtility.GetAnimationClipSettings(clip); settings.loopTime = a["is_looping"].Value<bool>(); AnimationUtility.SetAnimationClipSettings(clip, settings); }
                    savePath = AssetDatabase.GenerateUniqueAssetPath(savePath);
                    AssetDatabase.CreateAsset(clip, savePath);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { clip_path = savePath, name = clipName, frame_rate = frameRate });
                }

                case "get_animation_clip_data":
                {
                    string clipPath = a["clip_path"]?.ToString();
                    if (string.IsNullOrEmpty(clipPath))
                        return ErrorResult("clip_path is required");

                    var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
                    if (clip == null) return ErrorResult($"AnimationClip not found: {clipPath}");

                    var bindings = AnimationUtility.GetCurveBindings(clip);
                    var curveData = new JArray();
                    int maxKeys = a["max_keyframes_per_curve"]?.Value<int>() ?? 1000;

                    foreach (var binding in bindings.Take(10))
                    {
                        var curve = AnimationUtility.GetEditorCurve(clip, binding);
                        var keys = new JArray();
                        if (curve != null)
                        {
                            foreach (var kf in curve.keys.Take(maxKeys))
                            {
                                keys.Add(new JObject
                                {
                                    ["time"] = kf.time,
                                    ["value"] = kf.value,
                                    ["inTangent"] = kf.inTangent,
                                    ["outTangent"] = kf.outTangent
                                });
                            }
                        }
                        curveData.Add(new JObject
                        {
                            ["path"] = binding.path,
                            ["property"] = binding.propertyName,
                            ["type"] = binding.type?.Name,
                            ["keyframe_count"] = keys.Count,
                            ["keyframes"] = keys
                        });
                    }

                    return SuccessResult(new
                    {
                        name = clip.name,
                        length = clip.length,
                        frame_rate = clip.frameRate,
                        wrap_mode = clip.wrapMode.ToString(),
                        curves = curveData,
                        total_curves = bindings.Length
                    });
                }

                case "set_animation_curves":
                {
                    string clipPath = a["clip_path"]?.ToString();
                    string goPath = a["gameobject_path"]?.ToString();
                    string compType = a["component_type"]?.ToString();
                    string propName = a["property_name"]?.ToString();
                    string keyframesStr = a["keyframes"]?.ToString();

                    if (string.IsNullOrEmpty(clipPath) || string.IsNullOrEmpty(goPath) ||
                        string.IsNullOrEmpty(compType) || string.IsNullOrEmpty(propName))
                        return ErrorResult("clip_path, gameobject_path, component_type, and property_name are required");

                    var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
                    if (clip == null) return ErrorResult($"AnimationClip not found: {clipPath}");

                    // Parse keyframes JSON
                    var keyframeData = JArray.Parse(keyframesStr ?? "[]");
                    var keys = new Keyframe[keyframeData.Count];
                    for (int i = 0; i < keyframeData.Count; i++)
                    {
                        var kf = keyframeData[i];
                        keys[i] = new Keyframe(
                            kf["time"]?.Value<float>() ?? 0f,
                            kf["value"]?.Value<float>() ?? 0f,
                            kf["inTangent"]?.Value<float>() ?? 0f,
                            kf["outTangent"]?.Value<float>() ?? 0f
                        );
                    }

                    var curve = new AnimationCurve(keys);
                    var binding = new EditorCurveBinding
                    {
                        path = goPath,
                        type = ResolveComponentType(compType) ?? typeof(Transform),
                        propertyName = propName
                    };

                    AnimationUtility.SetEditorCurve(clip, binding, curve);
                    EditorUtility.SetDirty(clip);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { clip_path = clipPath, keyframe_count = keys.Length });
                }

                case "set_animation_clip_settings":
                {
                    string clipPath = a["clip_path"]?.ToString();
                    if (string.IsNullOrEmpty(clipPath))
                        return ErrorResult("clip_path is required");

                    var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
                    if (clip == null) return ErrorResult($"AnimationClip not found: {clipPath}");

                    if (a["frame_rate"] != null) clip.frameRate = a["frame_rate"].Value<float>();
                    if (a["wrap_mode"] != null)
                    {
                        clip.wrapMode = a["wrap_mode"].ToString() switch
                        {
                            "Loop" => WrapMode.Loop,
                            "Once" => WrapMode.Once,
                            "PingPong" => WrapMode.PingPong,
                            "ClampForever" => WrapMode.ClampForever,
                            _ => WrapMode.Default
                        };
                    }
                    if (a["clear_curves"]?.Value<bool>() == true)
                    {
                        foreach (var b in AnimationUtility.GetCurveBindings(clip))
                            AnimationUtility.SetEditorCurve(clip, b, null);
                    }
                    if (a["clear_events"]?.Value<bool>() == true)
                    {
                        AnimationUtility.SetAnimationEvents(clip, new AnimationEvent[0]);
                    }

                    EditorUtility.SetDirty(clip);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { clip_path = clipPath, frame_rate = clip.frameRate, wrap_mode = clip.wrapMode.ToString() });
                }

                case "set_sprite_animation_curve":
                {
                    string clipPath = a["clip_path"]?.ToString();
                    string spritesStr = a["sprites"]?.ToString() ?? "";
                    float fps = a["frame_rate"]?.Value<float>() ?? 12f;

                    if (string.IsNullOrEmpty(clipPath))
                        return ErrorResult("clip_path is required");

                    var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(clipPath);
                    if (clip == null) return ErrorResult($"AnimationClip not found: {clipPath}");

                    var spritePaths = spritesStr.Split(new[] { ',' }, StringSplitOptions.RemoveEmptyEntries);
                    clip.frameRate = fps;

                    // Create object reference keyframes for sprite animation
                    var keyframes = new ObjectReferenceKeyframe[spritePaths.Length];
                    for (int i = 0; i < spritePaths.Length; i++)
                    {
                        var sprite = AssetDatabase.LoadAssetAtPath<Sprite>(spritePaths[i].Trim());
                        keyframes[i] = new ObjectReferenceKeyframe
                        {
                            time = i / fps,
                            value = sprite
                        };
                    }

                    var binding = new EditorCurveBinding
                    {
                        path = "",
                        type = typeof(SpriteRenderer),
                        propertyName = "m_Sprite"
                    };
                    AnimationUtility.SetObjectReferenceCurve(clip, binding, keyframes);
                    EditorUtility.SetDirty(clip);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { clip_path = clipPath, sprite_count = spritePaths.Length });
                }

                case "create_animator_controller":
                {
                    string controllerPath = a["controller_path"]?.ToString();
                    string controllerName = a["controller_name"]?.ToString();

                    if (string.IsNullOrEmpty(controllerPath))
                        return ErrorResult("controller_path is required");

                    string dir = Path.GetDirectoryName(controllerPath);
                    if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
                        Directory.CreateDirectory(dir);

                    var controller = UnityEditor.Animations.AnimatorController.CreateAnimatorControllerAtPath(
                        AssetDatabase.GenerateUniqueAssetPath(controllerPath));

                    if (!string.IsNullOrEmpty(controllerName))
                        controller.name = controllerName;

                    AssetDatabase.SaveAssets();
                    return SuccessResult(new { controller_path = controllerPath, name = controller.name });
                }

                case "get_animator_controller_data":
                {
                    string controllerPath = a["controller_path"]?.ToString();
                    if (string.IsNullOrEmpty(controllerPath))
                        return ErrorResult("controller_path is required");

                    var controller = AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(controllerPath);
                    if (controller == null) return ErrorResult($"AnimatorController not found: {controllerPath}");

                    var layers = new JArray();
                    foreach (var layer in controller.layers)
                    {
                        var states = new JArray();
                        foreach (var state in layer.stateMachine.states)
                        {
                            states.Add(new JObject
                            {
                                ["name"] = state.state.name,
                                ["speed"] = state.state.speed,
                                ["motion"] = state.state.motion?.name ?? "null"
                            });
                        }
                        layers.Add(new JObject
                        {
                            ["name"] = layer.name,
                            ["default_weight"] = layer.defaultWeight,
                            ["state_count"] = states.Count,
                            ["states"] = states
                        });
                    }

                    var parameters = new JArray();
                    foreach (var param in controller.parameters)
                    {
                        parameters.Add(new JObject
                        {
                            ["name"] = param.name,
                            ["type"] = param.type.ToString()
                        });
                    }

                    return SuccessResult(new { name = controller.name, layer_count = layers.Count, layers, parameters });
                }

                case "modify_animator_controller":
                {
                    string controllerPath = a["controller_path"]?.ToString();
                    string modAction = a["modification_action"]?.ToString() ?? "";
                    string modParams = a["modification_params"]?.ToString();

                    if (string.IsNullOrEmpty(controllerPath))
                        return ErrorResult("controller_path is required");

                    var controller = AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(controllerPath);
                    if (controller == null) return ErrorResult($"AnimatorController not found: {controllerPath}");

                    var options = string.IsNullOrWhiteSpace(modParams) ? new JObject() :
                        modParams.TrimStart().StartsWith("{") ? JObject.Parse(modParams) : new JObject { ["name"] = modParams };
                    string name = options["name"]?.ToString() ?? options["parameter_name"]?.ToString() ?? options["state_name"]?.ToString();
                    int layerIndex = options["layer_index"]?.Value<int>() ?? 0;
                    if (modAction != "add_layer" && (layerIndex < 0 || layerIndex >= controller.layers.Length))
                        return ErrorResult("layer_index out of range");
                    var machine = modAction == "add_layer" ? null : controller.layers[layerIndex].stateMachine;
                    Undo.RegisterCompleteObjectUndo(controller, "Modify Animator Controller");
                    if (machine != null) Undo.RegisterCompleteObjectUndo(machine, "Modify Animator State Machine");
                    switch (modAction)
                    {
                        case "add_parameter":
                            if (string.IsNullOrWhiteSpace(name)) return ErrorResult("name is required");
                            if (controller.parameters.Any(item => item.name == name)) return ErrorResult("Parameter already exists");
                            var parameter = new AnimatorControllerParameter {
                                name = name,
                                type = (AnimatorControllerParameterType)Enum.Parse(typeof(AnimatorControllerParameterType), options["type"]?.ToString() ?? "Float", true),
                                defaultFloat = options["default_float"]?.Value<float>() ?? 0f,
                                defaultInt = options["default_int"]?.Value<int>() ?? 0,
                                defaultBool = options["default_bool"]?.Value<bool>() ?? false
                            };
                            controller.AddParameter(parameter);
                            break;
                        case "remove_parameter":
                            int parameterIndex = Array.FindIndex(controller.parameters, item => item.name == name);
                            if (parameterIndex < 0) return ErrorResult("Parameter not found");
                            controller.RemoveParameter(parameterIndex);
                            break;
                        case "add_layer":
                            if (string.IsNullOrWhiteSpace(name)) return ErrorResult("name is required");
                            if (controller.layers.Any(item => item.name == name)) return ErrorResult("Layer already exists");
                            controller.AddLayer(name);
                            break;
                        case "remove_layer":
                            int removeIndex = name == null ? layerIndex : Array.FindIndex(controller.layers, item => item.name == name);
                            if (removeIndex < 0 || controller.layers.Length <= 1) return ErrorResult("Layer not found or cannot remove the last layer");
                            controller.RemoveLayer(removeIndex);
                            break;
                        case "add_state":
                            if (string.IsNullOrWhiteSpace(name)) return ErrorResult("name is required");
                            if (machine.states.Any(item => item.state.name == name)) return ErrorResult("State already exists");
                            string motionPath = options["motion"]?.ToString();
                            var motion = motionPath == null ? null : AssetDatabase.LoadAssetAtPath<Motion>(motionPath);
                            if (motionPath != null && motion == null) return ErrorResult("Motion asset not found");
                            var addedState = machine.AddState(name);
                            addedState.motion = motion;
                            if (options["default"]?.Value<bool>() == true) machine.defaultState = addedState;
                            break;
                        case "remove_state":
                            var removedState = machine.states.FirstOrDefault(item => item.state.name == name).state;
                            if (removedState == null) return ErrorResult("State not found");
                            machine.RemoveState(removedState);
                            break;
                        case "add_transition":
                        case "remove_transition":
                            string from = options["from"]?.ToString() ?? options["source_state"]?.ToString();
                            string to = options["to"]?.ToString() ?? options["destination_state"]?.ToString();
                            var source = machine.states.FirstOrDefault(item => item.state.name == from).state;
                            var destination = machine.states.FirstOrDefault(item => item.state.name == to).state;
                            if (source == null || destination == null) return ErrorResult("Source or destination state not found");
                            var transition = source.transitions.FirstOrDefault(item => item.destinationState == destination);
                            if (modAction == "remove_transition")
                            {
                                if (transition == null) return ErrorResult("Transition not found");
                                source.RemoveTransition(transition);
                            }
                            else
                            {
                                if (transition != null) return ErrorResult("Transition already exists");
                                var conditions = options["conditions"] as JArray ?? new JArray();
                                foreach (var condition in conditions)
                                {
                                    if (!controller.parameters.Any(item => item.name == condition["parameter"]?.ToString())) return ErrorResult("Transition condition parameter not found");
                                    Enum.Parse(typeof(AnimatorConditionMode), condition["mode"]?.ToString() ?? "If", true);
                                }
                                transition = source.AddTransition(destination);
                                transition.hasExitTime = options["has_exit_time"]?.Value<bool>() ?? false;
                                transition.duration = options["duration"]?.Value<float>() ?? 0.25f;
                                foreach (var condition in conditions)
                                    transition.AddCondition((AnimatorConditionMode)Enum.Parse(typeof(AnimatorConditionMode), condition["mode"]?.ToString() ?? "If", true), condition["threshold"]?.Value<float>() ?? 0f, condition["parameter"].ToString());
                            }
                            break;
                        default:
                            return ErrorResult($"Unsupported animator modification: {modAction}");
                    }
                    EditorUtility.SetDirty(controller);
                    if (machine != null) EditorUtility.SetDirty(machine);
                    AssetDatabase.SaveAssets();
                    return SuccessResult(new { controller_path = controllerPath, action = modAction, name });
                }

                case "create_blend_tree_state":
                {
                    string controllerPath = a["controller_path"]?.ToString();
                    string stateName = a["state_name"]?.ToString() ?? "BlendTree";
                    string blendParam = a["blend_parameter"]?.ToString() ?? "Speed";
                    int layerIndex = a["layer_index"]?.Value<int>() ?? 0;

                    if (string.IsNullOrEmpty(controllerPath))
                        return ErrorResult("controller_path is required");

                    var controller = AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(controllerPath);
                    if (controller == null) return ErrorResult($"AnimatorController not found: {controllerPath}");

                    if (layerIndex < 0 || layerIndex >= controller.layers.Length)
                        return ErrorResult($"Layer index {layerIndex} out of range (max {controller.layers.Length - 1})");

                    var stateMachine = controller.layers[layerIndex].stateMachine;
                    var blendTree = new BlendTree();
                    blendTree.name = stateName;
                    blendTree.blendParameter = blendParam;
                    blendTree.blendType = a["blend_type"]?.ToString() == "2D" ? BlendTreeType.SimpleDirectional2D : BlendTreeType.Simple1D;

                    if (a["blend_parameter_y"] != null)
                        blendTree.blendParameterY = a["blend_parameter_y"].ToString();

                    var motions = a["motions"] == null ? new JArray() : a["motions"] is JArray array ? array : JArray.Parse(a["motions"].ToString());
                    var children = new List<ChildMotion>();
                    foreach (var item in motions)
                    {
                        var motion = AssetDatabase.LoadAssetAtPath<Motion>(item["motion"]?.ToString());
                        if (motion == null) return ErrorResult($"Motion not found: {item["motion"]}");
                        var position = item["position"] as JArray;
                        children.Add(new ChildMotion { motion = motion, threshold = item["threshold"]?.Value<float>() ?? 0f,
                            timeScale = item["time_scale"]?.Value<float>() ?? 1f,
                            position = position == null ? Vector2.zero : new Vector2(position[0].Value<float>(), position[1].Value<float>()) });
                    }
                    blendTree.useAutomaticThresholds = false;
                    blendTree.children = children.ToArray();
                    AssetDatabase.AddObjectToAsset(blendTree, controller);
                    var state = stateMachine.AddState(stateName);
                    state.motion = blendTree;
                    EditorUtility.SetDirty(controller);
                    AssetDatabase.SaveAssets();

                    return SuccessResult(new { controller_path = controllerPath, state_name = stateName, blend_type = blendTree.blendType.ToString() });
                }

                case "get_blend_tree_state_data":
                {
                    string controllerPath = a["controller_path"]?.ToString();
                    string stateName = a["state_name"]?.ToString();
                    int layerIndex = a["layer_index"]?.Value<int>() ?? 0;

                    var controller = AssetDatabase.LoadAssetAtPath<UnityEditor.Animations.AnimatorController>(controllerPath);
                    if (controller == null) return ErrorResult($"AnimatorController not found: {controllerPath}");

                    if (layerIndex < 0 || layerIndex >= controller.layers.Length)
                        return ErrorResult($"Layer index out of range");

                    foreach (var s in controller.layers[layerIndex].stateMachine.states)
                    {
                        if (s.state.name == stateName && s.state.motion is BlendTree bt)
                        {
                            var children = new JArray();
                            foreach (var child in bt.children)
                            {
                                children.Add(new JObject
                                {
                                    ["motion"] = child.motion?.name ?? "null",
                                    ["threshold"] = child.threshold,
                                    ["position"] = SerializeVector3(child.position)
                                });
                            }

                            return SuccessResult(new
                            {
                                name = bt.name,
                                blend_type = bt.blendType.ToString(),
                                blend_parameter = bt.blendParameter,
                                blend_parameter_y = bt.blendParameterY,
                                child_count = bt.children.Length,
                                children
                            });
                        }
                    }

                    return ErrorResult($"Blend tree state '{stateName}' not found");
                }

                case "list_model_animation_clips":
                {
                    string modelPath = a["model_path"]?.ToString();
                    if (string.IsNullOrEmpty(modelPath))
                        return ErrorResult("model_path is required");

                    var assets = AssetDatabase.LoadAllAssetsAtPath(modelPath);
                    var clips = new JArray();
                    foreach (var asset in assets)
                    {
                        if (asset is AnimationClip clip)
                        {
                            clips.Add(new JObject
                            {
                                ["name"] = clip.name,
                                ["length"] = clip.length,
                                ["frame_rate"] = clip.frameRate,
                                ["wrap_mode"] = clip.wrapMode.ToString()
                            });
                        }
                    }

                    return SuccessResult(new { model_path = modelPath, clip_count = clips.Count, clips });
                }

                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleManageVfx(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "get";
            string vfxPath = a["vfx_path"]?.ToString();

            if (string.IsNullOrEmpty(vfxPath))
                return ErrorResult("vfx_path is required");

            // VFX Graph assets - basic get/set support
            if (action == "get")
            {
                var vfx = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(vfxPath);
                if (vfx == null) return ErrorResult($"VFX asset not found: {vfxPath}");
                return SuccessResult(new { vfx_path = vfxPath, name = vfx.name, type = vfx.GetType().FullName });
            }

            // set_property - attempt via SerializedObject
            if (action == "set_property")
            {
                var vfx = AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(vfxPath);
                if (vfx == null) return ErrorResult($"VFX asset not found: {vfxPath}");
                
                var so = new SerializedObject(vfx);
                string propName = a["property_name"]?.ToString();
                if (!string.IsNullOrEmpty(propName))
                {
                    var sp = so.FindProperty(propName);
                    if (sp != null)
                    {
                        var value = a["value"] ?? a["float_value"] ?? a["int_value"] ?? a["bool_value"] ?? a["string_value"];
                        if (value == null) return ErrorResult("A property value is required");
                        Undo.RecordObject(vfx, "Set VFX Property");
                        SetSerializedPropertyFromToken(sp, value);
                        so.ApplyModifiedProperties();
                        EditorUtility.SetDirty(vfx);
                        AssetDatabase.SaveAssets();
                        return SuccessResult(new { vfx_path = vfxPath, property = propName });
                    }
                }
            }

            return ErrorResult($"Unknown VFX action or missing property: {action}");
        }
    }
}
