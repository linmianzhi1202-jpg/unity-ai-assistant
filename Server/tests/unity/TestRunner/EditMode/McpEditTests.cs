using System.Collections;
using NUnit.Framework;
using UnityEngine.TestTools;
public class McpEditTests
{
    [Test] public void Pass() { Assert.AreEqual(4, 2 + 2); }
    [Test] public void Fail() { Assert.Fail("expected MCP fixture failure"); }
    [Test] public void Skip() { Assert.Ignore("expected MCP fixture skip"); }
    [UnityTest] public IEnumerator Slow()
    {
        double until = UnityEditor.EditorApplication.timeSinceStartup + 4;
        while (UnityEditor.EditorApplication.timeSinceStartup < until) yield return null;
        Assert.Pass();
    }
}
