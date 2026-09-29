using System;
using System.IO;
using System.Text.RegularExpressions;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEditor.TestTools.TestRunner.Api;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace UnityMCP.Editor.Testing
{
    [InitializeOnLoad]
    public static class UnityTestRunner
    {
        private const string ActiveKey = "UnityMCP.ActiveTestRun";
        private const string ExternalKey = "UnityMCP.ExternalTestRun";
        private static TestRunnerApi api;
        private static readonly Callbacks callbacks = new Callbacks();
        private static string DirectoryPath => Path.GetFullPath("Library/UnityMCP/TestRuns");

        static UnityTestRunner()
        {
            TestRunnerApi.RegisterTestCallback(callbacks);
            AssemblyReloadEvents.beforeAssemblyReload += () => TestRunnerApi.UnregisterTestCallback(callbacks);
        }

        private static string ResultPath(string id)
        {
            if (!Guid.TryParseExact(id, "N", out _)) throw new ArgumentException("Invalid run_id");
            return Path.Combine(DirectoryPath, id + ".json");
        }

        private static JObject Read(string id)
        {
            string path = ResultPath(id);
            if (!File.Exists(path)) throw new ArgumentException("Unknown run_id in this Unity project");
            return JObject.Parse(File.ReadAllText(path));
        }

        private static void Save(JObject data)
        {
            Directory.CreateDirectory(DirectoryPath);
            File.WriteAllText(ResultPath(data["run_id"].ToString()), data.ToString());
        }

        public static string Handle(JToken args)
        {
            try
            {
                string id = args?["run_id"]?.ToString();
                string action = args?["action"]?.ToString() ?? "start";
                if (action == "status")
                {
                    var saved = Read(id);
                    if ((saved["state"]?.ToString() == "running" || saved["state"]?.ToString() == "submitted") &&
                        SessionState.GetString(ActiveKey, "") != id)
                    {
                        saved["state"] = "interrupted";
                        saved["error"] = "Editor session ended before test completion was recorded";
                        Save(saved);
                    }
                    return JsonConvert.SerializeObject(new { status = "success", result = saved });
                }
                if (action != "start") throw new ArgumentException("Unknown test action");
                string path = ResultPath(id);
                if (File.Exists(path)) throw new InvalidOperationException("run_id already exists; query its status instead");
                if (SessionState.GetString(ActiveKey, "") != "" || SessionState.GetBool(ExternalKey, false))
                    throw new InvalidOperationException("A Unity test run is already active");
                if (EditorApplication.isCompiling || EditorApplication.isUpdating || EditorUtility.scriptCompilationFailed)
                    throw new InvalidOperationException($"Editor not ready: compiling={EditorApplication.isCompiling}, updating={EditorApplication.isUpdating}, compilationFailed={EditorUtility.scriptCompilationFailed}");
                if (EditorApplication.isPlayingOrWillChangePlaymode)
                    throw new InvalidOperationException("Exit Play Mode before starting tests");
                for (int i = 0; i < SceneManager.sceneCount; i++)
                    if (SceneManager.GetSceneAt(i).isDirty)
                        throw new InvalidOperationException("Save modified scenes before starting tests");
                string mode = args?["test_mode"]?.ToString() ?? "EditMode";
                if (mode != "EditMode" && mode != "PlayMode") throw new ArgumentException("test_mode must be EditMode or PlayMode");
                string name = args?["test_filter"]?.ToString();
                var filter = new Filter { testMode = mode == "EditMode" ? TestMode.EditMode : TestMode.PlayMode };
                if (!string.IsNullOrWhiteSpace(name))
                    filter.groupNames = new[] { "(^|\\.)" + Regex.Escape(name) + "($|\\.|\\()" };
                var data = new JObject {
                    ["run_id"] = id, ["state"] = "submitted", ["test_mode"] = mode, ["test_filter"] = name,
                    ["success"] = false, ["started_at"] = DateTime.UtcNow.ToString("o"),
                    ["results_path"] = path
                };
                Save(data);
                SessionState.SetString(ActiveKey, id);
                try
                {
                    if (api == null) api = ScriptableObject.CreateInstance<TestRunnerApi>();
                    api.Execute(new ExecutionSettings(filter));
                }
                catch (Exception error)
                {
                    callbacks.OnError(error.Message);
                    throw;
                }
                return JsonConvert.SerializeObject(new { status = "success", result = Read(id) });
            }
            catch (Exception error)
            {
                return JsonConvert.SerializeObject(new { status = "error", error = error.Message });
            }
        }

        private class Callbacks : IErrorCallbacks
        {
            public void RunStarted(ITestAdaptor testsToRun)
            {
                string id = SessionState.GetString(ActiveKey, "");
                if (id == "") { SessionState.SetBool(ExternalKey, true); return; }
                var data = Read(id); data["state"] = "running"; Save(data);
            }
            public void TestStarted(ITestAdaptor test) { }
            public void TestFinished(ITestResultAdaptor result) { }
            public void RunFinished(ITestResultAdaptor result)
            {
                SessionState.SetBool(ExternalKey, false);
                string id = SessionState.GetString(ActiveKey, "");
                if (id == "") return;
                try
                {
                    var data = Read(id);
                    int total = result.PassCount + result.FailCount + result.SkipCount + result.InconclusiveCount;
                    bool passed = result.ResultState == "Passed" && result.PassCount > 0 && result.FailCount == 0 && result.InconclusiveCount == 0;
                    data["state"] = total == 0 ? "no_tests" : passed ? "passed" : "failed";
                    data["success"] = passed;
                    data["total"] = total; data["passed"] = result.PassCount; data["failed"] = result.FailCount;
                    data["skipped"] = result.SkipCount; data["inconclusive"] = result.InconclusiveCount;
                    data["duration"] = result.Duration; data["finished_at"] = DateTime.UtcNow.ToString("o");
                    data["result_state"] = result.ResultState;
                    data["error"] = passed ? null : total == 0 ? "No tests matched the requested mode/filter" : "Tests did not pass; inspect test results";
                    var cases = new JArray(); Collect(result, cases); data["tests"] = cases;
                    string xmlPath = Path.Combine(DirectoryPath, id + ".xml");
                    File.WriteAllText(xmlPath, result.ToXml().OuterXml);
                    data["xml_path"] = xmlPath;
                    Save(data);
                }
                catch (Exception error) { OnError("Could not record test results: " + error.Message); }
                finally { SessionState.EraseString(ActiveKey); }
            }
            private static void Collect(ITestResultAdaptor result, JArray cases)
            {
                if (!result.Test.IsSuite)
                    cases.Add(new JObject { ["name"] = result.FullName, ["state"] = result.ResultState,
                        ["duration"] = result.Duration, ["message"] = result.Message,
                        ["stack_trace"] = result.StackTrace, ["output"] = result.Output });
                if (result.HasChildren)
                    foreach (var child in result.Children) Collect(child, cases);
            }
            public void OnError(string message)
            {
                SessionState.SetBool(ExternalKey, false);
                string id = SessionState.GetString(ActiveKey, "");
                if (id == "") return;
                var data = Read(id); data["state"] = "error"; data["error"] = message;
                data["finished_at"] = DateTime.UtcNow.ToString("o"); Save(data);
                SessionState.EraseString(ActiveKey);
            }
        }
    }
}
