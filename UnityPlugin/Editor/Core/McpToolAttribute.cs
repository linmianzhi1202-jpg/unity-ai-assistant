using System;

namespace UnityMCP.Editor.Core
{
    /// <summary>
    /// Marks a class as an MCP tool handler.
    /// </summary>
    [AttributeUsage(AttributeTargets.Class, AllowMultiple = false)]
    public class McpToolAttribute : Attribute
    {
        /// <summary>
        /// Tool name identifier (e.g., "get_editor_state").
        /// </summary>
        public string Name { get; set; }

        /// <summary>
        /// Tool description for LLM consumers.
        /// </summary>
        public string Description { get; set; }

        /// <summary>
        /// Tool group for categorization (e.g., "core", "animation", "ui").
        /// </summary>
        public string Group { get; set; } = "core";

        public McpToolAttribute() { }
    }
}
