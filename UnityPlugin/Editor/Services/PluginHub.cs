using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEditor;
using UnityEngine;
using UnityMCP.Editor.Helpers;

namespace UnityMCP.Editor.Services
{
    /// <summary>
    /// Simplified PluginHub for Unified MCP for Unity.
    /// Listens on TCP port 6400 for commands from the Python MCP Server,
    /// executes them on Unity's main thread, and returns results.
    /// 
    /// Protocol: Length-prefixed UTF-8 JSON frames (8-byte big-endian header + payload).
    /// </summary>
    [InitializeOnLoad]
    public static class PluginHub
    {
        private const int DefaultPort = 6400;
        private const int MaxFrameBytes = 64 * 1024 * 1024; // 64MB
        private const int FrameTimeoutMs = 60000; // Increased from 30s to 60s
        private const int MaxClients = 5; // Allow multiple clients instead of 1
        private const int ClientIdleTimeoutMs = 120000; // 2 minutes idle timeout
        private const int KeepAliveIntervalMs = 15000; // 15 seconds keepalive
        
        private static TcpListener _listener;
        private static bool _isRunning = false;
        private static CancellationTokenSource _cts;
        private static Task _listenerTask;
        private static readonly object _lockObj = new object();
        private static readonly object _clientsLock = new object();
        private static Dictionary<TcpClient, ClientInfo> _activeClients = new Dictionary<TcpClient, ClientInfo>();
        private static int _currentPort = DefaultPort;
        private static readonly Dictionary<string, QueuedCommand> _commandQueue = new Dictionary<string, QueuedCommand>();
        
        // Main thread dispatch
        private static int _processingCommands = 0;
        
        // Heartbeat
        private static float _nextHeartbeatAt;
        private static int _heartbeatSeq;
        private static readonly int _processId = System.Diagnostics.Process.GetCurrentProcess().Id;
        private static readonly string _heartbeatPath = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".unity-mcp",
            $"unity-mcp-{_processId}.json");
        private static string _projectRoot;
        private static string _assetsPath;
        private static string _unityVersion;
        private static string _projectInfoJson;
        private static readonly Stopwatch _uptime = Stopwatch.StartNew();

        internal class ClientInfo
        {
            public DateTime ConnectedAt;
            public DateTime LastActivityAt;
            public string Endpoint;
            public int CommandsProcessed;
        }

        internal class QueuedCommand
        {
            public string CommandJson;
            public TaskCompletionSource<string> Tcs;
            public bool IsExecuting;
            public long EnqueuedAtMs;
            public TcpClient Owner;
        }

        #region Public API

        public static bool IsRunning => _isRunning;
        public static int CurrentPort => _currentPort;

        [MenuItem("Window/MCP for Unity/Start Server", false, 100)]
        public static void MenuStart()
        {
            Start();
            var status = _isRunning ? $"Started on port {_currentPort}" : "Failed to start";
            EditorUtility.DisplayDialog("MCP for Unity", status, "OK");
        }

        [MenuItem("Window/MCP for Unity/Stop Server", false, 101)]
        public static void MenuStop()
        {
            Stop();
            UnityEngine.Debug.Log("[UnityMCP] PluginHub stopped.");
        }

        [MenuItem("Window/MCP for Unity/Check Status", false, 102)]
        public static void MenuCheckStatus()
        {
            var sb = new StringBuilder();
            sb.AppendLine($"Running: {_isRunning}");
            sb.AppendLine($"Port: {_currentPort}");
            lock (_clientsLock)
            {
                sb.AppendLine($"Active Clients: {_activeClients.Count}");
                foreach (var kvp in _activeClients)
                {
                    sb.AppendLine($"  - {kvp.Value.Endpoint}: {kvp.Value.CommandsProcessed} cmds, idle {(DateTime.UtcNow - kvp.Value.LastActivityAt).TotalSeconds:F0}s");
                }
            }
            
            if (_isRunning)
            {
                var health = CheckHealth();
                sb.AppendLine($"Health: {health}");
            }
            
            EditorUtility.DisplayDialog("MCP for Unity Status", sb.ToString(), "OK");
        }

        public static HealthStatus CheckHealth()
        {
            try
            {
                using (var client = new TcpClient())
                {
                    var result = client.BeginConnect(IPAddress.Loopback, _currentPort, null, null);
                    bool connected = result.AsyncWaitHandle.WaitOne(500);
                    if (connected)
                    {
                        client.EndConnect(result);
                        return HealthStatus.Healthy;
                    }
                    return _isRunning ? HealthStatus.RunningNoConnection : HealthStatus.NotRunning;
                }
            }
            catch (SocketException)
            {
                return HealthStatus.NotRunning;
            }
            catch (Exception)
            {
                return HealthStatus.Error;
            }
        }

        #endregion

        #region Lifecycle

        static PluginHub()
        {
            // Auto-start on load (optional - can be disabled via pref)
            if (EditorPrefs.GetBool("UnityMCP_AutoStart", true))
            {
                EditorApplication.delayCall += () =>
                {
                    if (!_isRunning) Start();
                };
            }
            
            EditorApplication.quitting += Stop;

            // Reconnect after domain reload (compilation, play mode changes)
            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;

            // Also try to restart after compilation finishes
            EditorApplication.update += OnEditorUpdate;
        }

        private static void OnPlayModeStateChanged(PlayModeStateChange state)
        {
            switch (state)
            {
                case PlayModeStateChange.EnteredEditMode:
                    // After exiting play mode, restart if not running
                    ScheduleStartRetry();
                    break;
                case PlayModeStateChange.ExitingPlayMode:
                    // Stopping play mode can cause issues, ensure clean state
                    break;
            }
        }

        private static double _lastRestartAttempt;
        private static bool _restartScheduled;

        private static void OnEditorUpdate()
        {
            // Auto-restart after compilation if not running
            if (!_isRunning && !EditorApplication.isCompiling && !EditorApplication.isPlaying)
            {
                var now = EditorApplication.timeSinceStartup;
                if (!_restartScheduled && (now - _lastRestartAttempt > 2.0))
                {
                    _restartScheduled = true;
                    _lastRestartAttempt = now;
                    EditorApplication.delayCall += () =>
                    {
                        _restartScheduled = false;
                        if (!_isRunning && !EditorApplication.isCompiling)
                        {
                            Start();
                        }
                    };
                }
            }
        }

        private static void ScheduleStartRetry()
        {
            if (_isRunning) return;
            EditorApplication.delayCall += () =>
            {
                if (!_isRunning && !EditorApplication.isCompiling)
                    Start();
            };
        }

        public static void Start()
        {
            lock (_lockObj)
            {
                if (_isRunning && _listener != null)
                {
                    McpLog.Info($"PluginHub already running on port {_currentPort}");
                    return;
                }

                Stop();

                try
                {
                    _currentPort = FindAvailablePort(DefaultPort);
                    
                    McpLog.Info($"Starting PluginHub on port {_currentPort}...");
                    
                    _assetsPath = Application.dataPath;
                    _projectRoot = Directory.GetParent(_assetsPath)?.FullName ?? _assetsPath;
                    _unityVersion = Application.unityVersion;
                    _projectInfoJson = SuccessResult(new {
                        project_path = _projectRoot, assets_path = _assetsPath,
                        project_name = Directory.GetParent(_assetsPath)?.Name ?? "Unknown",
                        unity_version = _unityVersion, port = _currentPort, process_id = _processId
                    });
                    _listener = new TcpListener(IPAddress.Loopback, _currentPort);
                    _listener.Start();
                    
                    _isRunning = true;
                    _cts = new CancellationTokenSource();
                    _listenerTask = Task.Run(() => ListenerLoopAsync(_cts.Token));
                    
                    // Hook into update loop for command processing
                    EditorApplication.update -= ProcessCommands;
                    EditorApplication.update += ProcessCommands;
                    
                    EditorApplication.quitting -= Stop;
                    EditorApplication.quitting += Stop;
                    
                    WriteHeartbeat("ready");
                    _nextHeartbeatAt = Time.realtimeSinceStartup + 0.5f;
                    _heartbeatSeq++;
                    
                    McpLog.Info($"PluginHub started on port {_currentPort} ({Environment.OSVersion.Platform})");
                }
                catch (SocketException ex)
                {
                    McpLog.Error($"Failed to start listener: {ex.Message}");
                }
            }
        }

        public static void Stop()
        {
            Task toWait = null;
            lock (_lockObj)
            {
                if (!_isRunning) return;

                _isRunning = false;

                var cancel = _cts;
                _cts = null;
                try { cancel?.Cancel(); } catch { }

                try { _listener?.Stop(); } catch { }
                try { _listener?.Server?.Dispose(); } catch { }
                _listener = null;

                toWait = _listenerTask;
                _listenerTask = null;
            }

            // Close all active clients
            TcpClient[] toClose;
            lock (_clientsLock)
            {
                toClose = _activeClients.Keys.ToArray();
                _activeClients.Clear();
            }
            foreach (var c in toClose)
            {
                try { c.Close(); } catch { }
            }

            if (toWait != null)
            {
                try { toWait.Wait(500); } catch { }
            }

            EditorApplication.update -= ProcessCommands;
            lock (_lockObj)
            {
                foreach (var command in _commandQueue.Values)
                    command.Tcs.TrySetResult(ErrorResult("Unity server stopped"));
                _commandQueue.Clear();
            }
            DeleteHeartbeatFile();
            
            McpLog.Info("PluginHub stopped.");
        }

        #endregion

        #region Listener Loop

        private static async Task ListenerLoopAsync(CancellationToken token)
        {
            while (_isRunning && !token.IsCancellationRequested)
            {
                try
                {
                    TcpClient client = await _listener.AcceptTcpClientAsync();
                    client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
                    client.ReceiveTimeout = 60000;
                    
                    _ = Task.Run(() => HandleClientAsync(client, token), token);
                }
                catch (ObjectDisposedException)
                {
                    if (!_isRunning || token.IsCancellationRequested) break;
                }
                catch (OperationCanceledException)
                {
                    break;
                }
                catch (Exception ex)
                {
                    if (_isRunning && !token.IsCancellationRequested)
                        McpLog.Info($"Listener error: {ex.Message}");
                }
            }
        }

        #endregion

        #region Client Handling

        private static async Task HandleClientAsync(TcpClient client, CancellationToken token)
        {
            var clientInfo = new ClientInfo
            {
                ConnectedAt = DateTime.UtcNow,
                LastActivityAt = DateTime.UtcNow,
                Endpoint = client.Client?.RemoteEndPoint?.ToString() ?? "unknown",
                CommandsProcessed = 0,
            };

            using (client)
            using (var stream = client.GetStream())
            {
                int count;
                lock (_clientsLock)
                {
                    // If at max capacity, close the OLDEST client (not all clients)
                    if (_activeClients.Count >= MaxClients)
                    {
                        var oldest = _activeClients.OrderBy(kvp => kvp.Value.ConnectedAt).FirstOrDefault();
                        if (oldest.Key != null)
                        {
                            McpLog.Info($"Max clients ({MaxClients}) reached, closing oldest: {oldest.Value.Endpoint}");
                            try { oldest.Key.Close(); } catch { }
                            _activeClients.Remove(oldest.Key);
                        }
                    }
                    _activeClients[client] = clientInfo;
                    count = _activeClients.Count;
                }

                try
                {
                    McpLog.Info($"Client connected: {clientInfo.Endpoint} (total: {count})");

                    client.NoDelay = true;
                    client.ReceiveTimeout = ClientIdleTimeoutMs;
                    client.SendTimeout = FrameTimeoutMs;

                    // Enable TCP KeepAlive for early detection of broken connections
                    try
                    {
                        client.Client.SetSocketOption(SocketOptionLevel.Socket, SocketOptionName.KeepAlive, true);
                        // Windows TCP KeepAlive settings: start after 10s, interval 5s, fail after 3 misses
                        byte[] keepAliveValues = new byte[12];
                        // onoff
                        keepAliveValues[0] = 1;
                        // keepalivetime (ms) - 10000ms = 10s
                        keepAliveValues[4] = 0x10; keepAliveValues[5] = 0x27;
                        // keepaliveinterval (ms) - 5000ms = 5s
                        keepAliveValues[8] = 0x88; keepAliveValues[9] = 0x13;
                        client.Client.IOControl(IOControlCode.KeepAliveValues, keepAliveValues, null);
                    }
                    catch (Exception kex)
                    {
                        McpLog.Warn($"Failed to set TCP KeepAlive: {kex.Message}");
                    }

                    // Send handshake
                    string handshake = "WELCOME UNITY-MCP 1 FRAMING=1\n";
                    byte[] handshakeBytes = Encoding.ASCII.GetBytes(handshake);
                    await stream.WriteAsync(handshakeBytes, 0, handshakeBytes.Length, token);

                    // Command loop - resilient to transient errors
                    int consecutiveErrors = 0;
                    const int maxConsecutiveErrors = 3;
                    
                    while (_isRunning && !token.IsCancellationRequested)
                    {
                        try
                        {
                            string commandText = await ReadFrameAsync(stream);
                            
                            // Reset error counter on successful read
                            consecutiveErrors = 0;
                            clientInfo.LastActivityAt = DateTime.UtcNow;
                            
                            if (string.IsNullOrWhiteSpace(commandText))
                            {
                                await WriteFrameAsync(stream, ErrorResult("Empty command"));
                                continue;
                            }

                            // Ping check
                            if (commandText.Trim() == "ping")
                            {
                                await WriteFrameAsync(stream, SuccessResult(new { message = "pong" }));
                                continue;
                            }

                            // Get project info check (built-in command, no main-thread dispatch needed)
                            if (commandText.Trim() == "get_info")
                            {
                                await WriteFrameAsync(stream, _projectInfoJson);
                                continue;
                            }

                            // Queue command for main thread execution
                            string commandId = Guid.NewGuid().ToString();
                            var tcs = new TaskCompletionSource<string>(TaskCreationOptions.RunContinuationsAsynchronously);

                            lock (_lockObj)
                            {
                                _commandQueue[commandId] = new QueuedCommand
                                {
                                    CommandJson = commandText,
                                    Tcs = tcs,
                                    IsExecuting = false,
                                    EnqueuedAtMs = _uptime.ElapsedMilliseconds,
                                    Owner = client
                                };
                            }

                            // Force editor update
                            // EditorApplication.update drains the queue on the main thread.

                            // Wait for result with timeout
                            string response;
                            using (var respCts = new CancellationTokenSource(FrameTimeoutMs))
                            {
                                var completed = await Task.WhenAny(tcs.Task, Task.Delay(FrameTimeoutMs, respCts.Token));
                                if (completed == tcs.Task)
                                {
                                    respCts.Cancel();
                                    response = tcs.Task.Result;
                                }
                                else
                                {
                                    bool started;
                                    lock (_lockObj)
                                    {
                                        started = _commandQueue.TryGetValue(commandId, out var queued) && queued.IsExecuting;
                                        if (!started) _commandQueue.Remove(commandId);
                                    }
                                    response = ErrorResult(started
                                        ? "execution_uncertain: command already started before timeout"
                                        : "Command expired before execution");
                                    McpLog.Warn($"Command timed out: {commandText.Substring(0, Math.Min(100, commandText.Length))}");
                                }
                            }

                            await WriteFrameAsync(stream, response);
                            clientInfo.CommandsProcessed++;
                            clientInfo.LastActivityAt = DateTime.UtcNow;
                        }
                        catch (IOException iox)
                        {
                            // Connection-level errors - these are fatal for this client
                            if (iox.Message.Contains("Connection closed") ||
                                iox.Message.Contains("Read timed out") ||
                                iox.Message.Contains("Unable to read"))
                            {
                                McpLog.Info($"Client {clientInfo.Endpoint} connection closed: {iox.Message}");
                                break;
                            }
                            // Other IO errors - retry
                            consecutiveErrors++;
                            McpLog.Warn($"IO error for {clientInfo.Endpoint} ({consecutiveErrors}/{maxConsecutiveErrors}): {iox.Message}");
                            if (consecutiveErrors >= maxConsecutiveErrors) break;
                            await Task.Delay(100, token);
                        }
                        catch (System.Net.Sockets.SocketException sx)
                        {
                            // Socket errors are typically fatal
                            McpLog.Info($"Socket error for {clientInfo.Endpoint}: {sx.Message}");
                            break;
                        }
                        catch (ObjectDisposedException)
                        {
                            // Client was disposed - fatal
                            break;
                        }
                        catch (OperationCanceledException)
                        {
                            // Cancellation - exit gracefully
                            break;
                        }
                        catch (Exception ex)
                        {
                            consecutiveErrors++;
                            McpLog.Warn($"Command error for {clientInfo.Endpoint} ({consecutiveErrors}/{maxConsecutiveErrors}): {ex.Message}");
                            if (consecutiveErrors >= maxConsecutiveErrors) break;
                            // Try to send error response before continuing
                            try
                            {
                                await WriteFrameAsync(stream, ErrorResult($"Internal error: {ex.Message}"));
                            }
                            catch
                            {
                                break; // Can't write response - connection is dead
                            }
                        }
                    }
                }
                finally
                {
                    lock (_clientsLock) { _activeClients.Remove(client); }
                    int remaining;
                    lock (_clientsLock) { remaining = _activeClients.Count; }
                    McpLog.Info($"Client disconnected: {clientInfo.Endpoint} ({clientInfo.CommandsProcessed} cmds, remaining: {remaining})");
                }
            }
        }

        #endregion

        #region Command Processing (runs on main thread)

        private static void ProcessCommands()
        {
            if (!_isRunning) return;
            if (Interlocked.Exchange(ref _processingCommands, 1) == 1) return;

            try
            {
                // Heartbeat
                if (Time.realtimeSinceStartup >= _nextHeartbeatAt)
                {
                    WriteHeartbeat("ready");
                    _nextHeartbeatAt = Time.realtimeSinceStartup + 0.5f;
                }

                List<(string id, QueuedCommand cmd)> work;
                lock (_lockObj)
                {
                    if (_commandQueue.Count == 0) return;

                    work = new List<(string, QueuedCommand)>();
                    foreach (var kvp in _commandQueue)
                    {
                        if (!kvp.Value.IsExecuting)
                            work.Add((kvp.Key, kvp.Value));
                    }
                }

                foreach (var (id, cmd) in work)
                {
                    lock (_lockObj)
                    {
                        if (!_commandQueue.ContainsKey(id)) continue;
                        bool disconnected = !cmd.Owner.Connected;
                        try {
                            disconnected |= cmd.Owner.Client.Poll(0, SelectMode.SelectRead) && cmd.Owner.Client.Available == 0;
                        } catch { disconnected = true; }
                        if (disconnected || _uptime.ElapsedMilliseconds - cmd.EnqueuedAtMs >= FrameTimeoutMs)
                        {
                            _commandQueue.Remove(id);
                            cmd.Tcs.TrySetResult(ErrorResult("Command expired before execution"));
                            continue;
                        }
                        cmd.IsExecuting = true;
                    }
                    ExecuteCommand(id, cmd.CommandJson, cmd.Tcs);
                }
            }
            finally
            {
                Interlocked.Exchange(ref _processingCommands, 0);
            }
        }

        private static void ExecuteCommand(string commandId, string payload, TaskCompletionSource<string> completion)
        {
            try
            {
                JObject cmd = JObject.Parse(payload);
                string toolName = cmd["tool"]?.ToString();
                JToken args = cmd["arguments"];
                
                McpLog.Info($"[CMD] {toolName}");

                // Route to tool executor
                string resultJson = ToolDispatcher.Dispatch(toolName, args);

                // ToolDispatcher already returns a complete JSON with status/result,
                // don't double-wrap it
                completion.TrySetResult(resultJson);
            }
            catch (JsonException jex)
            {
                completion.TrySetResult(ErrorResult($"Invalid JSON: {jex.Message}"));
            }
            catch (Exception ex)
            {
                McpLog.Error($"[CMD Error] {ex.Message}\n{ex.StackTrace}");
                completion.TrySetResult(ErrorResult(ex.Message));
            }
            finally
            {
                lock (_lockObj) { _commandQueue.Remove(commandId); }
            }
        }

        #endregion

        #region Framing Protocol

        private static async Task<string> ReadFrameAsync(NetworkStream stream)
        {
            byte[] header = await ReadExactAsync(stream, 8);
            ulong payloadLen = ReadUInt64BigEndian(header);
            
            if (payloadLen == 0) throw new IOException("Zero-length frame");
            if (payloadLen > MaxFrameBytes) throw new IOException($"Frame too large: {payloadLen}");
            
            int count = (int)payloadLen;
            byte[] payload = await ReadExactAsync(stream, count);
            return Encoding.UTF8.GetString(payload);
        }

        private static async Task WriteFrameAsync(NetworkStream stream, string json)
        {
            byte[] payload = Encoding.UTF8.GetBytes(json);
            if ((ulong)payload.Length > MaxFrameBytes)
                throw new IOException($"Frame too large: {payload.Length}");

            byte[] header = new byte[8];
            WriteUInt64BigEndian(header, (ulong)payload.Length);
            
            using (var cts = new CancellationTokenSource(FrameTimeoutMs))
            {
                await stream.WriteAsync(header, 0, header.Length, cts.Token);
                await stream.WriteAsync(payload, 0, payload.Length, cts.Token);
            }
        }

        private static async Task<byte[]> ReadExactAsync(NetworkStream stream, int count)
        {
            byte[] buffer = new byte[count];
            int offset = 0;
            var sw = Stopwatch.StartNew();

            while (offset < count)
            {
                int remaining = count - offset;
                int timeout = FrameTimeoutMs - (int)sw.ElapsedMilliseconds;
                
                if (timeout <= 0) throw new IOException("Read timeout");
                
                using (var cts = new CancellationTokenSource(timeout))
                {
                    int read = await stream.ReadAsync(buffer, offset, remaining, cts.Token);
                    if (read == 0) throw new IOException("Connection closed");
                    offset += read;
                }
            }
            return buffer;
        }

        private static ulong ReadUInt64BigEndian(byte[] buf)
        {
            if (buf == null || buf.Length < 8) return 0UL;
            return ((ulong)buf[0] << 56) | ((ulong)buf[1] << 48) |
                   ((ulong)buf[2] << 40) | ((ulong)buf[3] << 32) |
                   ((ulong)buf[4] << 24) | ((ulong)buf[5] << 16) |
                   ((ulong)buf[6] << 8) | buf[7];
        }

        private static void WriteUInt64BigEndian(byte[] dest, ulong val)
        {
            dest[0] = (byte)(val >> 56);
            dest[1] = (byte)(val >> 48);
            dest[2] = (byte)(val >> 40);
            dest[3] = (byte)(val >> 32);
            dest[4] = (byte)(val >> 24);
            dest[5] = (byte)(val >> 16);
            dest[6] = (byte)(val >> 8);
            dest[7] = (byte)val;
        }

        #endregion

        #region Port Management

        private static int FindAvailablePort(int startPort)
        {
            if (IsPortAvailable(startPort)) return startPort;
            
            for (int port = startPort + 1; port < startPort + 100; port++)
            {
                if (IsPortAvailable(port)) return port;
            }
            
            throw new Exception($"No available port in range {startPort}-{startPort + 99}");
        }

        private static bool IsPortAvailable(int port)
        {
            try
            {
                var test = new TcpListener(IPAddress.Loopback, port);
                test.Start();
                test.Stop();
                return true;
            }
            catch (SocketException)
            {
                return false;
            }
        }

        #endregion

        #region Helpers

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

        private static void WriteHeartbeat(string state)
        {
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(_heartbeatPath));
                string temporary = _heartbeatPath + ".tmp";
                File.WriteAllText(temporary, JsonConvert.SerializeObject(new
                {
                    unity_port = _currentPort, state, seq = ++_heartbeatSeq,
                    project_path = _projectRoot, unity_version = _unityVersion,
                    process_id = _processId, timestamp = DateTime.UtcNow.ToString("O")
                }, Formatting.None));
                if (File.Exists(_heartbeatPath)) File.Replace(temporary, _heartbeatPath, null);
                else File.Move(temporary, _heartbeatPath);
            }
            catch (Exception ex)
            {
                McpLog.Warn($"Heartbeat write failed: {ex.Message}");
            }
        }

        private static void DeleteHeartbeatFile()
        {
            try
            {
                if (File.Exists(_heartbeatPath)) File.Delete(_heartbeatPath);
            }
            catch { }
        }

        #endregion
    }

    public enum HealthStatus
    {
        Healthy,
        RunningNoConnection,
        NotRunning,
        Error
    }
}
