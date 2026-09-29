using System;
using UnityEditor;
using UnityEngine;

namespace UnityMCP.Editor.Helpers
{
    /// <summary>
    /// Simplified logging utility for Unified MCP for Unity.
    /// Outputs to both Unity Console and optional file log.
    /// </summary>
    public static class McpLog
    {
        private const string Prefix = "[UnityMCP]";
        
        private static bool _debugEnabled;
        
        static McpLog()
        {
            try { _debugEnabled = EditorPrefs.GetBool("UnityMCP_DebugLogs", false); }
            catch { _debugEnabled = false; }
        }
        
        public static void Info(string message, bool always = true)
        {
            if (always || _debugEnabled)
                Debug.Log($"{Prefix} {message}");
        }
        
        public static void Warn(string message)
        {
            Debug.LogWarning($"{Prefix} {message}");
        }
        
        public static void Error(string message)
        {
            Debug.LogError($"{Prefix} {message}");
        }
        
        public static bool IsDebugEnabled()
        {
            return _debugEnabled;
        }
    }
}
