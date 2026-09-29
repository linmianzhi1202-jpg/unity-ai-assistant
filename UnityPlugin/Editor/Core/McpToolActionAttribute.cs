using System;

namespace UnityMCP.Editor.Core
{
    /// <summary>
    /// Marks a method as the execution entry point for an MCP tool.
    /// </summary>
    [AttributeUsage(AttributeTargets.Method, AllowMultiple = false)]
    public class McpToolActionAttribute : Attribute
    {
        public McpToolActionAttribute() { }
    }
}
