import asyncio
import base64
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave
import zipfile
from unittest.mock import AsyncMock, patch

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Server/src"))
from core.config import config
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
from mcp.types import TextContent
from services.ai_generation_service import (AIGenerationService, AIGenerationRequest,
    AIGenerationType as Kind, ImageProviderAdapter, SfxProviderAdapter, Model3DProviderAdapter)
from services.tools import register_all_tools
from services.tools.tool_router import get_router
from services.tools.mcp_bridge import register_mcp_client, unregister_mcp_client

HTTP_CLIENT = httpx.AsyncClient

class ToolImplementationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = patch.object(config, "ai_output_directory", str(self.root))
        self.output.start(); self.addCleanup(self.output.stop)
        self.mcp = FastMCP("implementations")
        register_all_tools(self.mcp)

    def http(self, handler):
        return patch("httpx.AsyncClient", side_effect=lambda **kwargs: HTTP_CLIENT(
            **kwargs, transport=httpx.MockTransport(handler)))

    async def call(self, name, **kwargs):
        return (await self.mcp.call_tool(name, kwargs)).structured_content

    async def test_image_is_downloaded_and_decodable(self):
        buffer = io.BytesIO(); Image.new("RGB", (8, 8), "red").save(buffer, "PNG")
        def handler(request):
            self.assertEqual(request.url.path, "/v1/images/generations")
            self.assertEqual(json.loads(request.content)["size"], "1536x1024")
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]})
        with self.http(handler):
            result = await ImageProviderAdapter(api_key="test").generate(
                AIGenerationRequest(generation_type=Kind.IMAGE, prompt="red", aspect_ratio="3:2"))
        with Image.open(result["output_path"]) as image:
            self.assertEqual(image.size, (8, 8))

    async def test_image_corruption_http_failure_and_missing_file_never_complete(self):
        service = AIGenerationService(); service.register_provider(Kind.IMAGE, ImageProviderAdapter(api_key="test"))
        request = AIGenerationRequest(generation_type=Kind.IMAGE, prompt="red")
        for response in [httpx.Response(200, json={"data":[{"b64_json":base64.b64encode(b"\x89PNGbad").decode()}]}), httpx.Response(401, json={"error":"unauthorized"})]:
            with self.http(lambda _: response):
                self.assertEqual((await service.submit(request)).status, "failed")
        service.register_provider(Kind.IMAGE, type("Provider", (), {"generate": AsyncMock(return_value={"status":"completed", "output_path":str(self.root/"absent.png")})})())
        self.assertEqual((await service.submit(request)).status, "failed")

    async def test_sfx_pcm_becomes_valid_wave_and_mp3_is_saved(self):
        for fmt, body in [("wav", b"\0\0" * 100), ("mp3", b"ID3" + b"\0" * 100)]:
            def handler(request):
                self.assertEqual(request.url.path, "/v1/sound-generation")
                self.assertEqual(json.loads(request.content)["duration_seconds"], 1)
                return httpx.Response(200, content=body, headers={"content-type":"audio/mpeg"})
            with self.http(handler):
                result = await SfxProviderAdapter(api_key="test").generate(AIGenerationRequest(generation_type=Kind.SFX, prompt="chime", duration=1, format=fmt))
            if fmt == "wav":
                with wave.open(result["output_path"]) as wav:
                    self.assertEqual((wav.getframerate(), wav.getnframes()), (44100, 100))
            else:
                self.assertEqual(Path(result["output_path"]).read_bytes(), body)
        with self.http(lambda _: httpx.Response(200, json={"error":"no sound"})):
            with self.assertRaises(RuntimeError):
                await SfxProviderAdapter(api_key="test").generate(AIGenerationRequest(generation_type=Kind.SFX, prompt="chime"))

    async def test_all_meshy_actions_submit_poll_and_download(self):
        posts = []
        def handler(request):
            path = request.url.path
            if request.url.host == "download.test":
                return httpx.Response(200, content=b"model-or-texture-bytes")
            if path.endswith("/animations/library"):
                return httpx.Response(200, json=[{"action_id": 1, "name": "Walk"}])
            if request.method == "POST":
                posts.append((path, json.loads(request.content)))
                return httpx.Response(200, json={"result":"task1"})
            return httpx.Response(200, json={"status":"SUCCEEDED", "model_urls":{"fbx":"https://download.test/model.fbx"}, "texture_urls":[{"base_color":"https://download.test/color.png"}]})
        requests = [
            (Kind.MODEL_3D, {}), (Kind.MODEL_3D, {"image_path":"https://input.test/image.png"}),
            (Kind.MODEL_TEXTURE, {"model_path":"https://input.test/model.glb"}),
            (Kind.AUTO_RIG, {"model_path":"https://input.test/model.glb"}),
            (Kind.APPLY_ANIMATION, {"model_path":"rig:rig1", "animation_style":"Walk"}),
            (Kind.SEARCH_ANIMATION, {})]
        with self.http(handler):
            for kind, kwargs in requests:
                result = await Model3DProviderAdapter(api_key="test").generate(AIGenerationRequest(generation_type=kind, prompt="robot", **kwargs))
                if kind == Kind.SEARCH_ANIMATION:
                    self.assertEqual(result["count"], 1)
                else:
                    self.assertTrue(Path(result["output_path"]).is_file())
                    self.assertTrue(Path(result["textures"][0]).is_file())
        self.assertEqual([p[1].get("mode") for p in posts[:2]], ["preview", "refine"])
        self.assertEqual(posts[-1][1], {"rig_task_id":"rig1", "action_id":1})
        self.assertEqual(len(posts), 6)

    async def test_generation_timeout_cancel_and_missing_credentials(self):
        service = AIGenerationService()
        started = asyncio.Event()
        async def block(request):
            started.set(); await asyncio.Event().wait()
        service.register_provider(Kind.IMAGE, type("Provider", (), {"generate":staticmethod(block)})())
        request = AIGenerationRequest(generation_type=Kind.IMAGE, prompt="red")
        self.assertEqual((await service.submit(request, timeout=.01)).status, "failed")
        started.clear(); job = asyncio.create_task(service.submit(request)); await started.wait(); job.cancel()
        with self.assertRaises(asyncio.CancelledError): await job
        self.assertTrue(all(task.status == "failed" and task.completed_at for task in service.list_tasks()))
        with patch.dict("os.environ", {"OPENAI_API_KEY":"", "MESHY_API_KEY":"", "ELEVENLABS_API_KEY":""}):
            for name, args in [("generate_image", {"prompt":"test"}), ("generate_sfx", {"prompt":"test"}), ("generate_3d_model", {"action":"generate_from_text", "prompt":"test"})]:
                self.assertFalse((await self.call(name, **args))["success"])
        self.assertFalse((await self.call("generate_3d_model", action="generate_from_image", prompt="must not fall back to text"))["success"])

    async def test_graphics_properties_reach_handler_and_failures_propagate(self):
        for name in ["manage_camera", "manage_texture", "manage_shader", "manage_vfx"]:
            with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"error", "error":"missing property"})) as send:
                result = await self.call(name, action="set_property", properties=json.dumps({"property_name":"missing", "value":4}))
                self.assertFalse(result["success"]); self.assertEqual(result["error"], "missing property")
                self.assertEqual(send.call_args.args[1]["value"], 4)
                self.assertNotIn("properties", send.call_args.args[1])

    async def test_batch_uses_actual_parameter_conversion_and_stops_on_failure(self):
        commands = json.dumps([{"tool":"create_game_object", "params":{"name":"first", "position":"1,2,3"}}, {"tool":"create_game_object", "params":{"name":"second"}}])
        with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"error", "error":"offline"})) as send:
            result = await self.call("batch_execute", commands=commands)
            self.assertFalse(result["success"]); self.assertEqual(result["results"]["executed"], 1)
            self.assertEqual(send.call_args.args[1]["position"], {"x":1.,"y":2.,"z":3.})
        with patch.object(get_router(), "send_tool", new=AsyncMock(return_value={"status":"success", "result":{}})):
            self.assertTrue((await self.call("batch_execute", commands=commands))["success"])

    async def test_bridge_checks_dataclass_and_text_business_errors(self):
        for structured, text in [({"success":False}, "failure"), (None, '{"status":"error"}')]:
            result = CallToolResult(content=[TextContent(type="text", text=text)], structured_content=structured, meta=None, is_error=False)
            register_mcp_client("test", type("Client", (), {"call_tool":AsyncMock(return_value=result)})())
            try:
                response = await self.call("invoke_mcp_tool", server_name="test", tool_name="anything")
                self.assertFalse(response["success"]); json.dumps(response)
            finally: unregister_mcp_client("test")

    async def test_script_waits_for_verified_output_and_propagates_runtime_errors(self):
        for state in [{"state":"completed", "output":"42"}, {"state":"failed", "error":"runtime error"}]:
            responses = [{"status":"success", "result":{"state":"submitted", "output":"[MCP_EVAL_ID:abcdef12]"}},
                {"status":"success", "result":{"is_compiling":False,"has_errors":False}},
                {"status":"success", "result":{}}, {"status":"success", "result":state}, {"status":"success", "result":{"state":"source_removed"}}]
            with patch("services.tools.agent_tools.send_to_unity", new=AsyncMock(side_effect=responses)) as send:
                result = await self.call("execute_script", script="return 42;")
                self.assertEqual(result["success"], state["state"] == "completed")
                self.assertEqual(send.call_count, 5)
                if result["success"]: self.assertEqual(result["output"], "42")
        with patch("services.tools.agent_tools.send_to_unity", new=AsyncMock(return_value={"status":"success", "result":{}})):
            self.assertFalse((await self.call("execute_script", script="return 42;"))["success"])

    async def test_project_relative_text_docx_and_pdf_extraction(self):
        (self.root/"text.txt").write_text("actual text", encoding="utf-8")
        with zipfile.ZipFile(self.root/"doc.docx", "w") as document:
            document.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>actual docx</w:t></w:r></w:p></w:body></w:document>')
        pdf = b"%PDF-1.4\n1 0 obj <</Type /Catalog /Pages 2 0 R>> endobj\n2 0 obj <</Type /Pages /Kids [3 0 R] /Count 1>> endobj\n3 0 obj <</Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources <</Font <</F1 4 0 R>>>> /Contents 5 0 R>> endobj\n4 0 obj <</Type /Font /Subtype /Type1 /BaseFont /Helvetica>> endobj\n5 0 obj <</Length 43>> stream\nBT /F1 12 Tf 10 200 Td (actual pdf) Tj ET\nendstream endobj\ntrailer <</Root 1 0 R>>\n%%EOF"
        (self.root/"doc.pdf").write_bytes(pdf)
        with patch.object(config, "unity_project_path", str(self.root)):
            for file, expected in [("text.txt","actual text"), ("doc.docx","actual docx"), ("doc.pdf","actual pdf")]:
                result = await self.call("read_project_file", path=file)
                self.assertTrue(result["success"], result); self.assertIn(expected, result["content"])

if __name__ == "__main__": unittest.main()
