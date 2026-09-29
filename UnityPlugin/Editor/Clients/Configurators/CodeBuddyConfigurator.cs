using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Sockets;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;

namespace MCPForUnity.Editor.Clients.Configurators
{
    /// <summary>
    /// Enhanced CodeBuddy MCP Configurator with automation support.
    /// Supports alwaysAllow whitelist, dual-mode (uvx/source) switching,
    /// health checking, and Unity Editor menu integration.
    /// </summary>
    public static class CodeBuddyConfigurator
    {
        private const string ServerName = "unified-mcp-unity";
        private const string ModePrefKey = "CodeBuddy_MCP_Mode";
        private const string SourcePathPrefKey = "CodeBuddy_MCP_SourcePath";
        private const string PluginHubHost = "127.0.0.1";
        private const int PluginHubPort = 6400;
        private const int HealthCheckTimeoutMs = 1000;

        /// <summary>
        /// Automation tool whitelist — these tools will be called without
        /// user confirmation in CodeBuddy, enabling unattended automation
        /// for building game objects, scripts, and animations.
        /// </summary>
        private static readonly string[] AutomationToolWhitelist = {
            // Scene & GameObject (building elements)
            "manage_scene", "manage_gameobject", "manage_components",
            "manage_transform", "set_tag", "set_layer",
            // Scripts
            "manage_script", "validate_script", "execute_script",
            // Animation & VFX
            "manage_animation", "manage_vfx",
            // Materials & Prefabs
            "manage_material", "manage_shader", "manage_prefabs",
            "manage_scriptableObject",
            // Assets & Packages
            "manage_asset", "manage_packages", "manage_texture",
            // Editor & Console
            "manage_editor", "read_console", "batch_execute",
            // Camera & Graphics
            "manage_camera", "manage_graphics",
            // AI Generation
            "generate_image", "generate_3d_model", "generate_sfx",
            // UI
            "manage_ui",
        };

        /// <summary>
        /// Configuration mode: uvx (published package) or source (local development).
        /// </summary>
        public enum ConfigMode
        {
            Uvx = 0,
            Source = 1,
        }

        /// <summary>
        /// Health check result states.
        /// </summary>
        public enum HealthStatus
        {
            Healthy,
            ServerRunningNoUnity,
            NotRunning,
            Error,
        }

        // ─── Configuration Path ──────────────────────────────────────────

        /// <summary>
        /// Returns the path to the CodeBuddy MCP configuration file.
        /// </summary>
        public static string GetConfigPath()
        {
            string home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            return Path.Combine(home, ".codebuddy", "mcp.json");
        }

        // ─── Status Check ─────────────────────────────────────────────────

        /// <summary>
        /// Checks whether the MCP server is configured in CodeBuddy.
        /// </summary>
        public static bool IsConfigured()
        {
            string path = GetConfigPath();
            if (!File.Exists(path)) return false;

            try
            {
                string json = File.ReadAllText(path);
                var config = JObject.Parse(json);
                var servers = config["mcpServers"] as JObject;
                return servers != null && servers.ContainsKey(ServerName);
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Checks whether the configured entry includes the alwaysAllow whitelist.
        /// </summary>
        public static bool HasAlwaysAllow()
        {
            string path = GetConfigPath();
            if (!File.Exists(path)) return false;

            try
            {
                string json = File.ReadAllText(path);
                var config = JObject.Parse(json);
                var servers = config["mcpServers"] as JObject;
                var entry = servers?[ServerName] as JObject;
                var whitelist = entry?["alwaysAllow"] as JArray;
                return whitelist != null && whitelist.Count >= AutomationToolWhitelist.Length;
            }
            catch
            {
                return false;
            }
        }

        /// <summary>
        /// Gets the current configuration mode from EditorPrefs.
        /// </summary>
        public static ConfigMode GetMode()
        {
            return (ConfigMode)EditorPrefs.GetInt(ModePrefKey, (int)ConfigMode.Uvx);
        }

        /// <summary>
        /// Sets the configuration mode in EditorPrefs.
        /// </summary>
        public static void SetMode(ConfigMode mode)
        {
            EditorPrefs.SetInt(ModePrefKey, (int)mode);
        }

        /// <summary>
        /// Gets the source path for development mode.
        /// </summary>
        public static string GetSourcePath()
        {
            return EditorPrefs.GetString(SourcePathPrefKey, "");
        }

        /// <summary>
        /// Sets the source path for development mode.
        /// </summary>
        public static void SetSourcePath(string path)
        {
            EditorPrefs.SetString(SourcePathPrefKey, path);
        }

        // ─── Health Check ─────────────────────────────────────────────────

        /// <summary>
        /// Checks the health of the MCP → Unity connection by testing
        /// TCP connectivity to the PluginHub WebSocket port.
        /// </summary>
        public static HealthStatus CheckHealth()
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var result = client.BeginConnect(PluginHubHost, PluginHubPort, null, null);
                    bool connected = result.AsyncWaitHandle.WaitOne(HealthCheckTimeoutMs);

                    if (connected)
                    {
                        client.EndConnect(result);
                        return HealthStatus.Healthy;
                    }
                    else
                    {
                        return HealthStatus.NotRunning;
                    }
                }
            }
            catch (SocketException)
            {
                return HealthStatus.NotRunning;
            }
            catch (Exception ex)
            {
                Debug.LogWarning($"[CodeBuddy] Health check error: {ex.Message}");
                return HealthStatus.Error;
            }
        }

        /// <summary>
        /// Returns a human-readable status summary.
        /// </summary>
        public static string GetStatusSummary()
        {
            var sb = new StringBuilder();
            bool configured = IsConfigured();
            var health = CheckHealth();
            var mode = GetMode();

            sb.AppendLine($"Configured: {(configured ? "Yes" : "No")}");
            sb.AppendLine($"Mode: {mode}");
            sb.AppendLine($"Health: {health}");
            sb.AppendLine($"AlwaysAllow: {(HasAlwaysAllow() ? "Yes" : "No")}");

            if (configured)
            {
                string path = GetConfigPath();
                try
                {
                    string json = File.ReadAllText(path);
                    var config = JObject.Parse(json);
                    var servers = config["mcpServers"] as JObject;
                    var entry = servers?[ServerName] as JObject;
                    if (entry != null)
                    {
                        sb.AppendLine($"Command: {entry["command"]}");
                        var args = entry["args"] as JArray;
                        if (args != null)
                            sb.AppendLine($"Args: {string.Join(" ", args.Values<string>())}");
                    }
                }
                catch { /* ignore read errors in summary */ }
            }

            return sb.ToString();
        }

        // ─── Configure / Unconfigure ──────────────────────────────────────

        /// <summary>
        /// Configures the CodeBuddy MCP server entry.
        /// Uses the current mode (uvx or source) from EditorPrefs.
        /// Includes alwaysAllow whitelist for automation.
        /// </summary>
        public static void Configure()
        {
            var mode = GetMode();
            Configure(mode);
        }

        /// <summary>
        /// Configures the CodeBuddy MCP server entry with a specific mode.
        /// </summary>
        public static void Configure(ConfigMode mode)
        {
            string path = GetConfigPath();
            string dir = Path.GetDirectoryName(path);
            if (!Directory.Exists(dir))
            {
                Directory.CreateDirectory(dir);
            }

            JObject config;
            if (File.Exists(path))
            {
                string json = File.ReadAllText(path);
                try
                {
                    config = JObject.Parse(json);
                }
                catch (JsonReaderException)
                {
                    Debug.LogWarning("[CodeBuddy] Existing mcp.json is invalid, overwriting.");
                    config = new JObject();
                }
            }
            else
            {
                config = new JObject();
            }

            var servers = config["mcpServers"] as JObject;
            if (servers == null)
            {
                servers = new JObject();
                config["mcpServers"] = servers;
            }

            // Build server entry based on mode
            var serverEntry = BuildServerEntry(mode);
            servers[ServerName] = serverEntry;

            File.WriteAllText(path, config.ToString(Formatting.Indented));

            string modeDesc = mode == ConfigMode.Uvx ? "uvx (published)" : "source (development)";
            Debug.Log($"[CodeBuddy] MCP configured ({modeDesc}): {path}");
        }

        /// <summary>
        /// Removes the MCP server entry from CodeBuddy configuration.
        /// </summary>
        public static void Unconfigure()
        {
            string path = GetConfigPath();
            if (!File.Exists(path)) return;

            try
            {
                string json = File.ReadAllText(path);
                var config = JObject.Parse(json);
                var servers = config["mcpServers"] as JObject;
                if (servers != null && servers.ContainsKey(ServerName))
                {
                    servers.Remove(ServerName);
                    File.WriteAllText(path, config.ToString(Formatting.Indented));
                    Debug.Log($"[CodeBuddy] MCP unconfigured: {path}");
                }
            }
            catch (Exception ex)
            {
                Debug.LogError($"[CodeBuddy] Failed to unconfigure: {ex.Message}");
            }
        }

        // ─── Server Entry Builder ─────────────────────────────────────────

        private static JObject BuildServerEntry(ConfigMode mode)
        {
            var entry = new JObject
            {
                ["type"] = "stdio",
                ["description"] = "Unified MCP for Unity - AI-powered Unity Editor automation",
            };

            if (mode == ConfigMode.Source)
            {
                string sourcePath = GetSourcePath();
                if (string.IsNullOrEmpty(sourcePath))
                {
                    // Auto-detect: look for Server/src relative to the Unity project
                    string projectDir = Directory.GetParent(UnityEngine.Application.dataPath)?.FullName;
                    sourcePath = Path.Combine(projectDir ?? "", "unified-mcp-unity", "Server", "src");
                }

                entry["command"] = "python";
                entry["args"] = new JArray("-m", "main");
                entry["cwd"] = sourcePath.Replace('\\', '/');
                entry["env"] = new JObject
                {
                    ["PYTHONIOENCODING"] = "utf-8",
                    ["UNITY_MCP_TRANSPORT"] = "stdio",
                };
            }
            else
            {
                // uvx mode (published package)
                entry["command"] = "uvx";
                entry["args"] = new JArray(
                    "--from", "unified-mcp-unity",
                    "unified-mcp-server",
                    "--transport", "stdio"
                );
            }

            // Always add automation whitelist
            var alwaysAllow = new JArray();
            foreach (var tool in AutomationToolWhitelist)
            {
                alwaysAllow.Add(tool);
            }
            entry["alwaysAllow"] = alwaysAllow;

            return entry;
        }

        // ─── Manual Snippet ───────────────────────────────────────────────

        /// <summary>
        /// Returns the manual configuration JSON snippet for display.
        /// Includes alwaysAllow whitelist.
        /// </summary>
        public static string GetManualSnippet()
        {
            var entry = BuildServerEntry(ConfigMode.Uvx);
            var snippet = new JObject
            {
                ["mcpServers"] = new JObject
                {
                    [ServerName] = entry,
                }
            };
            return snippet.ToString(Formatting.Indented);
        }

        /// <summary>
        /// Returns the manual configuration JSON snippet for source mode.
        /// </summary>
        public static string GetSourceModeSnippet()
        {
            var entry = BuildServerEntry(ConfigMode.Source);
            var snippet = new JObject
            {
                ["mcpServers"] = new JObject
                {
                    [ServerName] = entry,
                }
            };
            return snippet.ToString(Formatting.Indented);
        }

        // ─── Unity Editor Menu ────────────────────────────────────────────

        [MenuItem("Window/MCP for Unity/Configure CodeBuddy", false, 100)]
        private static void MenuConfigure()
        {
            Configure();
            var health = CheckHealth();
            string healthMsg = health == HealthStatus.Healthy
                ? "Unity PluginHub is reachable."
                : "Unity PluginHub is NOT reachable. Start the MCP server in Unity first.";
            EditorUtility.DisplayDialog(
                "CodeBuddy MCP Configuration",
                $"MCP server entry written to:\n{GetConfigPath()}\n\n{healthMsg}",
                "OK"
            );
        }

        [MenuItem("Window/MCP for Unity/Configure CodeBuddy (Source Mode)", false, 101)]
        private static void MenuConfigureSource()
        {
            string currentPath = GetSourcePath();
            string selectedPath = EditorUtility.OpenFolderPanel(
                "Select Server Source Directory (containing main.py)",
                string.IsNullOrEmpty(currentPath) ? "" : currentPath,
                ""
            );

            if (!string.IsNullOrEmpty(selectedPath))
            {
                SetSourcePath(selectedPath);
                SetMode(ConfigMode.Source);
                Configure(ConfigMode.Source);

                EditorUtility.DisplayDialog(
                    "CodeBuddy MCP Configuration (Source Mode)",
                    $"Source path: {selectedPath}\n\nConfiguration written to:\n{GetConfigPath()}",
                    "OK"
                );
            }
        }

        [MenuItem("Window/MCP for Unity/Unconfigure CodeBuddy", false, 102)]
        private static void MenuUnconfigure()
        {
            if (EditorUtility.DisplayDialog(
                "Unconfigure CodeBuddy MCP",
                "Remove the unified-mcp-unity entry from CodeBuddy configuration?",
                "Yes", "Cancel"))
            {
                Unconfigure();
            }
        }

        [MenuItem("Window/MCP for Unity/Check CodeBuddy Status", false, 103)]
        private static void MenuCheckStatus()
        {
            string summary = GetStatusSummary();
            EditorUtility.DisplayDialog("CodeBuddy MCP Status", summary, "OK");
        }

        [MenuItem("Window/MCP for Unity/Toggle uvx/source Mode", false, 104)]
        private static void MenuToggleMode()
        {
            var current = GetMode();
            var next = current == ConfigMode.Uvx ? ConfigMode.Source : ConfigMode.Uvx;
            string msg = next == ConfigMode.Uvx
                ? "Switch to uvx (published package) mode?"
                : "Switch to source (local development) mode?";

            if (EditorUtility.DisplayDialog("Toggle Config Mode", msg, "Yes", "Cancel"))
            {
                SetMode(next);
                if (IsConfigured())
                {
                    Configure(next);
                }
                Debug.Log($"[CodeBuddy] Mode switched to: {next}");
            }
        }
    }
}
