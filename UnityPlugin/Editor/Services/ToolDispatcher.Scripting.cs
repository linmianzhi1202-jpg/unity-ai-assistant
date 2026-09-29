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

        private static string HandleRunTests(JToken args)
        {
            var integration = Type.GetType("UnityMCP.Editor.Testing.UnityTestRunner, UnityMCP.TestRunner.Editor");
            if (integration == null)
                return ErrorResult("Unity Test Framework integration is unavailable; check package installation and compilation");
            try { return (string)integration.GetMethod("Handle").Invoke(null, new object[] { args }); }
            catch (TargetInvocationException error) { return ErrorResult(error.InnerException?.Message ?? error.Message); }
        }

        private static string HandleManageScript(JToken args)
        {
            var a = ParseArgs(args, "action");
            string action = a["action"]?.ToString() ?? "create";
            
            switch (action)
            {
                case "create":
                    string scriptName = a["name"]?.ToString() ?? "NewScript";
                    string content = a["content"]?.ToString() ?? "// New script\nusing UnityEngine;\npublic class NewScript : MonoBehaviour\n{\n}";
                    string folder = a["folder"]?.ToString() ?? "Assets";
                    
                    string fullPath = Path.Combine(folder, $"{scriptName}.cs");
                    Directory.CreateDirectory(folder);
                    File.WriteAllText(fullPath, content);
                    AssetDatabase.ImportAsset(fullPath);
                    return SuccessResult(new { file_path = fullPath });

                case "update":
                    string updateName = a["name"]?.ToString();
                    string updateContent = a["content"]?.ToString();
                    string updateFolder = a["folder"]?.ToString() ?? "Assets";

                    if (string.IsNullOrEmpty(updateName))
                        return ErrorResult("name is required for update");
                    if (updateContent == null)
                        return ErrorResult("content is required for update");

                    string updatePath = Path.Combine(updateFolder, $"{updateName}.cs");
                    if (!File.Exists(updatePath))
                        return ErrorResult($"Script not found: {updatePath}");

                    File.WriteAllText(updatePath, updateContent);
                    AssetDatabase.ImportAsset(updatePath);
                    return SuccessResult(new { file_path = updatePath, updated = true });
                    
                case "read":
                    string readName = a["name"]?.ToString();
                    if (string.IsNullOrWhiteSpace(readName)) return ErrorResult("name is required for read");
                    string readPath = Path.Combine(a["folder"]?.ToString() ?? "Assets", $"{readName}.cs");
                    if (!File.Exists(readPath)) return ErrorResult($"Script not found: {readPath}");
                    return SuccessResult(new { file_path = readPath, content = File.ReadAllText(readPath) });

                case "validate":
                    var compilation = JObject.Parse(CheckCompileErrors())["result"];
                    bool compiling = compilation?["is_compiling"]?.Value<bool>() ?? false;
                    bool errors = compilation?["has_errors"]?.Value<bool>() ?? false;
                    return SuccessResult(new {
                        valid = compiling ? (bool?)null : !errors,
                        state = compiling ? "compiling" : errors ? "failed" : "completed",
                        compilation, message = "Current project compilation state; unsaved source is not validated"
                    });
                    
                default:
                    throw new ArgumentException($"Unknown action: {action}");
            }
        }

        private static string HandleValidateScript(JToken args)
        {
            var validateArgs = args as JObject ?? new JObject();
            validateArgs["action"] = "validate";
            return HandleManageScript(validateArgs);
        }

        private static string HandleExecuteScript(JToken args)
        {
            string evalId = args?["eval_id"]?.ToString();
            if (!string.IsNullOrEmpty(evalId))
            {
                if (args?["cleanup"]?.Value<bool>() == true)
                {
                    if (evalId.Length != 8 || evalId.Any(c => !Uri.IsHexDigit(c)))
                        return ErrorResult("Invalid script execution ID");
                    string sourcePath = $"Assets/MCPTemp/Editor/McpEval_{evalId}.cs";
                    if (File.Exists(sourcePath) && !AssetDatabase.DeleteAsset(sourcePath))
                        return ErrorResult("Could not remove temporary script");
                    return SuccessResult(new { state = "source_removed" });
                }
                string saved = SessionState.GetString("MCP_Eval_" + evalId, "");
                if (string.IsNullOrEmpty(saved)) return ErrorResult("Unknown script execution ID");
                return SuccessResult(JObject.Parse(saved));
            }
            var code = args?["code"]?.ToString() ?? args?["script"]?.ToString() ?? "";
            if (string.IsNullOrEmpty(code)) return ErrorResult("No code provided");

            // Safety: block dangerous patterns
            var blocked = new[] { "System.IO.File.Delete", "System.IO.Directory.Delete", 
                "Process.Start", "Registry" };
            foreach (var pattern in blocked)
            {
                if (code.Contains(pattern))
                    return ErrorResult($"Blocked dangerous pattern: {pattern}");
            }

            // ToolDispatcher already runs on Unity's main thread.
            string result;
            try { result = EvaluateCode(code); }
            catch (Exception error) { return ErrorResult($"Script error: {error.Message}"); }
            if (result != null && result.StartsWith("Error:")) return ErrorResult(result);

            // Parse return value: if result starts with "RETURN:", extract the actual value
            string output = result ?? "";
            string returnValue = null;
            if (output.StartsWith("RETURN:"))
            {
                returnValue = output.Substring(7).Trim();
                output = returnValue;
            }

            return SuccessResult(new
            {
                output = output,
                return_value = returnValue ?? output,
                state = "submitted",
                message = "Script submitted for compilation; execution is not yet confirmed",
            });
        }

        /// <summary>
        /// Evaluate C# code using Unity's Editor scripting API.
        /// Supports statements, expressions, and return values.
        /// </summary>

        private static string EvaluateCode(string code)
        {
            var logs = new List<string>();
            ExecuteViaCompilationPipeline(code, logs);
            return string.Join("\n", logs);
        }

        private static void ExecuteViaCompilationPipeline(string code, List<string> logs)
        {
            try
            {
                // Generate unique ID
                string evalId = Guid.NewGuid().ToString("N").Substring(0, 8);
                string tempDir = "Assets/MCPTemp/Editor";
                string tempFile = Path.Combine(tempDir, $"McpEval_{evalId}.cs");

                // Ensure directory
                string absDir = Path.Combine(Application.dataPath, "MCPTemp/Editor");
                if (!Directory.Exists(absDir))
                    Directory.CreateDirectory(absDir);

                foreach (string previous in Directory.GetFiles(tempDir, "McpEval_*.cs"))
                {
                    string previousId = Path.GetFileNameWithoutExtension(previous).Substring("McpEval_".Length);
                    string previousState = SessionState.GetString("MCP_Eval_" + previousId, "");
                    if (previousState.Contains("completed") || previousState.Contains("failed"))
                        AssetDatabase.DeleteAsset(previous);
                }

                // Compile the complete script; retain its source until the next submission.
                string wrappedCode = $@"// MCP Auto-generated eval script — safe to delete
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using System;
using System.Linq;
using System.Collections.Generic;
using System.IO;

public static class McpEval_{evalId}
{{
    [UnityEditor.MenuItem(""Temp/MCP Eval {evalId}"")]
    public static void Execute()
    {{
        try
        {{
            object result = Run();
            SessionState.SetString(""MCP_Eval_{evalId}"", Newtonsoft.Json.JsonConvert.SerializeObject(new {{ state = ""completed"", output = result?.ToString() ?? """" }}));
            Debug.Log($""[MCP_Eval_{evalId}] SUCCESS: {{result}}"");
        }}
        catch (Exception ex)
        {{
            SessionState.SetString(""MCP_Eval_{evalId}"", Newtonsoft.Json.JsonConvert.SerializeObject(new {{ state = ""failed"", error = ex.Message }}));
            Debug.LogError($""[MCP_Eval_{evalId}] ERROR: {{ex.Message}}\n{{ex.StackTrace}}"");
        }}

    }}

    public static object Run()
    {{
        {WrapCodeWithReturn(code)}
    }}
}}";

                File.WriteAllText(tempFile, wrappedCode);

                // Trigger compilation (don't wait — domain reload would kill the wait loop)
                SessionState.SetString("MCP_Eval_" + evalId, "{\"state\":\"compiling\"}");
                AssetDatabase.Refresh(ImportAssetOptions.ForceUpdate);

                // Return async instruction for the caller to follow up
                logs.Add($"[MCP_EVAL_ID:{evalId}] Script written to {tempFile}. Next step: call execute_menu_item(\"Temp/MCP Eval {evalId}\") then check logs for [MCP_Eval_{evalId}].");
            }
            catch (Exception ex)
            {
                throw new InvalidOperationException($"Script submission failed: {ex.Message}", ex);
            }
        }

        /// <summary>
        /// Wrap user code to capture the return value.
        /// </summary>

        private static string WrapCodeWithReturn(string code)
        {
            // If code already has a return statement, use as-is
            if (code.Contains("return "))
                return code;
            
            return code + "\nreturn \"ok\";";
        }

        private static string HandleBatchExecute(JToken args)
        {
            var commands = args?["commands"] as JArray;
            if (commands == null || commands.Count == 0) return ErrorResult("No commands provided");
            bool stopOnError = args?["stop_on_error"]?.Value<bool>() ?? true;

            var results = new JArray();
            var errors = new JArray();
            int ok = 0, fail = 0;

            foreach (JToken cmd in commands)
            {
                string tool = cmd["tool"]?.ToString();
                var toolArgs = cmd["arguments"] ?? cmd["params"];

                try
                {
                    string dispatchResult = Dispatch(tool, toolArgs);
                    // Dispatch returns JSON string — parse or wrap as string
                    JToken parsed;
                    try { parsed = JToken.Parse(dispatchResult); }
                    catch { parsed = new JValue(dispatchResult); }

                    if (parsed["status"]?.ToString() != "success")
                        throw new InvalidOperationException(parsed["error"]?.ToString() ?? "Command returned an invalid response");
                    results.Add(new JObject
                    {
                        ["tool"] = tool,
                        ["status"] = "ok",
                        ["result"] = parsed,
                    });
                    ok++;
                }
                catch (Exception ex)
                {
                    fail++;
                    var errEntry = new JObject
                    {
                        ["tool"] = tool,
                        ["status"] = "error",
                        ["error"] = ex.Message,
                    };
                    errors.Add(errEntry);
                    results.Add(errEntry);

                    if (stopOnError)
                        break;
                }
            }

            return JsonConvert.SerializeObject(new {
                status = fail == 0 ? "success" : "error",
                error = fail == 0 ? null : $"{fail} batch command(s) failed",
                result = new { results, count = commands.Count, executed = results.Count, ok, fail, errors }
            });
        }
    }
}
