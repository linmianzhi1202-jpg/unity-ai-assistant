using System.Collections;
using NUnit.Framework;
using UnityEngine;
using UnityEngine.TestTools;
public class McpPlayTests
{
    [UnityTest] public IEnumerator Pass()
    {
        var go = new GameObject("MCP Test Object");
        yield return null;
        Assert.IsTrue(Application.isPlaying);
        Assert.IsNotNull(go);
        Object.Destroy(go);
    }
    [UnityTest] public IEnumerator Fail()
    {
        yield return null;
        Assert.Fail("expected PlayMode fixture failure");
    }
}
