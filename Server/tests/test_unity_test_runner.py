import asyncio
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "Server/src"))
from fastmcp import FastMCP
from services.tools import register_all_tools, configure_tools
from services.tools.tool_router import get_router
from services.tools.unity_bridge import ExecutionUncertainError, _READ_ONLY
from core.config import config

class TestRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mcp = FastMCP("test-runner"); register_all_tools(self.mcp)

    async def call(self, **args):
        return (await self.mcp.call_tool("run_tests", args)).structured_content

    async def test_results_propagate_without_false_success(self):
        for state, passed in [("passed", 1), ("failed", 0), ("no_tests", 0), ("error", 0), ("interrupted", 0)]:
            with self.subTest(state=state), patch.object(get_router(), "send_tool", new=AsyncMock(side_effect=[
                {"status":"success","result":{"state":"submitted"}},
                {"status":"success","result":{"state":state,"success":state=="passed","passed":passed,"error":None if state=="passed" else "expected failure"}}
            ])) as send:
                result = await self.call()
                self.assertEqual(result["success"], state=="passed")
                self.assertEqual(send.call_args_list[0].args[1]["action"], "start")
                self.assertEqual(send.call_args_list[1].args[1]["action"], "status")

    async def test_uncertain_submission_never_replays_start(self):
        with patch.object(get_router(), "send_tool", new=AsyncMock(side_effect=[ExecutionUncertainError("response lost"),
            ConnectionError("domain reload"), {"status":"success","result":{"state":"passed","success":True,"passed":1}}])) as send:
            self.assertTrue((await self.call())["success"])
            actions = [c.args[1]["action"] for c in send.call_args_list]
            self.assertEqual(actions, ["start", "status", "status"])
            self.assertEqual(_READ_ONLY["run_tests"], {"status"})

    async def test_timeout_keeps_id_and_resume_does_not_restart(self):
        with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"success","result":{"state":"running"}})) as send:
            result=await self.call(timeout=.01)
            self.assertFalse(result["success"]); self.assertEqual(result["state"], "timeout")
            identifier=result["run_id"]; self.assertEqual(len(identifier),32)
            self.assertEqual(send.call_count,1)
        with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"success","result":{"state":"passed","success":True,"passed":1}})) as send:
            self.assertTrue((await self.call(run_id=identifier))["success"])
            self.assertEqual(send.call_args.args[1], {"action":"status","run_id":identifier})

    async def test_cancel_wait_does_not_claim_unity_cancelled(self):
        started=asyncio.Event()
        async def block(*args, **kwargs):
            started.set(); await asyncio.Event().wait()
        with patch.object(get_router(), "send_tool", new=block):
            task=asyncio.create_task(self.call()); await started.wait(); task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task

    async def test_invalid_input_and_backend_errors_do_not_succeed(self):
        with patch.object(get_router(), "send_tool", new=AsyncMock()) as send:
            for args in [{"timeout":0},{"test_mode":"Other"},{"run_id":"../outside"}]:
                self.assertFalse((await self.call(**args))["success"])
            send.assert_not_called()
        for message in ["already active", "compilation failed", "integration unavailable"]:
            with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"error","error":message})):
                self.assertEqual((await self.call())["error"], message)

    async def test_tool_group_filter_applies_to_tests(self):
        with patch.object(config,"enabled_tool_groups",["testing"]): await configure_tools(self.mcp)
        self.assertEqual({t.name for t in await self.mcp.list_tools()}, {"run_tests","batch_execute"})
        other=FastMCP("rag-only"); register_all_tools(other)
        with patch.object(config,"enabled_tool_groups",["rag"]): await configure_tools(other)
        with self.assertRaises(Exception): await other.call_tool("run_tests", {})
