import asyncio
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Server/src"))
from core.config import config, UnifiedServerConfig
from fastmcp import FastMCP
from services.tools import register_all_tools, configure_tools
from services.tools import rag_tools
from services.tools.unity_bridge import UnityBridge, ExecutionUncertainError, ProjectSelectionError, get_bridge, close_bridge
from services.rag.lightrag_store import LightRAGStore

REMOVED = set("create_checkpoint restore_checkpoint manage_input_action manage_action_map manage_input_action_binding manage_control_scheme manage_input_binding install_unity_package install_git_package remove_unity_package list_packages search_installed_packages search_all_packages export_package get_profiler_data list_high_poly_objects manage_scene_view create_coplay_task manage_probuilder".split())

class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_available_interfaces_remain_compatible(self):
        baseline = json.loads((Path(__file__).parent / "fixtures/tool_interfaces_before.json").read_text(encoding="utf-8"))
        mcp = FastMCP("test")
        register_all_tools(mcp)
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        self.assertEqual(set(baseline) - set(tools), REMOVED)
        for name in set(baseline) - REMOVED:
            old = baseline[name]
            new = tools[name].parameters
            self.assertTrue(set(old.get("properties", {})) <= set(new.get("properties", {})), name)
            self.assertFalse(set(new.get("required", [])) - set(old.get("required", [])), name)

    async def test_rag_filter_blocks_invocation_and_unknown_groups_fail(self):
        mcp = FastMCP("test")
        register_all_tools(mcp)
        with patch.object(config, "enabled_tool_groups", ["rag"]):
            await configure_tools(mcp)
        self.assertTrue(all("group:rag" in t.tags for t in await mcp.list_tools()))
        with self.assertRaises(Exception):
            await mcp.call_tool("create_game_object", {"name": "must-not-create"})
        with patch.object(config, "enabled_tool_groups", ["typo"]):
            with self.assertRaises(ValueError):
                await configure_tools(mcp)

    async def test_routes_are_complete_and_refresh_does_not_assume_success(self):
        from services.tools.tool_router import get_router
        from services.tools.scripting_tools import register_scripting_tools
        class Capture:
            def __init__(self): self.tools = {}
            def tool(self, **kwargs):
                def register(fn): self.tools[fn.__name__] = fn; return fn
                return register
        capture = Capture()
        register_scripting_tools(capture)
        with patch.object(get_router(), "send_tool", new=AsyncMock(side_effect=ConnectionError("offline"))):
            result = await capture.tools["refresh_unity"]()
        self.assertFalse(result["success"])

class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_defaults_explicit_sources_partial_failure_and_full_evidence(self):
        graph = MagicMock()
        graph.get_status.return_value = {"graph_exists": True}
        graph.aquery = AsyncMock(side_effect=TimeoutError())
        item = {"id": "GameObject", "content_preview": "short", "content": "whole"}
        with patch.object(rag_tools, "_search_vector", return_value=([item], 1)), patch.object(rag_tools, "_get_unified_lightrag_store", return_value=graph):
            result = await rag_tools.arun_knowledge_unified_search("object")
            self.assertEqual(result["sources_used"], ["vector"])
            graph.aquery.assert_not_called()
            result = await rag_tools.arun_knowledge_unified_search("object", include_graph_context=True)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["source_breakdown"]["api_graph"]["status"], "timeout")
            result = await rag_tools.arun_knowledge_unified_search("object", sources=["api_graph"])
            self.assertEqual(result["status"], "error")
            graph.aquery = AsyncMock(return_value="context" * 500 + "SOURCE_EVIDENCE")
            result = await rag_tools.arun_knowledge_unified_search("object", sources=["api_graph"], include_graph_context=False)
            self.assertTrue(result["api_graph_context"].endswith("SOURCE_EVIDENCE"))

    async def test_empty_and_missing_sources_are_distinct(self):
        graph = MagicMock(); graph.get_status.return_value = {"graph_exists": False}
        with patch.object(rag_tools, "_search_vector", return_value=([], 0)), patch.object(rag_tools, "_get_unified_lightrag_store", return_value=graph):
            result = await rag_tools.arun_knowledge_unified_search("x", sources=["vector", "api_graph"])
        self.assertEqual(result["source_breakdown"]["vector"]["status"], "empty")
        self.assertEqual(result["source_breakdown"]["api_graph"]["status"], "unavailable")

    async def test_graph_timeout_cancels_work_and_releases_queue(self):
        cancelled = threading.Event()
        started = threading.Event()
        async def slow(*args, **kwargs):
            started.set()
            try: await asyncio.sleep(10)
            finally: cancelled.set()
        store = LightRAGStore()
        store._initialized = True
        store.rag = types.SimpleNamespace(aquery=slow)
        fake = types.SimpleNamespace(QueryParam=lambda **kwargs: kwargs)
        with patch.dict(sys.modules, {"lightrag": fake}), patch.object(config, "rag_timeout", 0.1):
            with self.assertRaises(asyncio.TimeoutError): await store.aquery("slow")
            self.assertTrue(started.is_set())
            self.assertTrue(await asyncio.to_thread(cancelled.wait, 1))
            store.rag.aquery = AsyncMock(return_value="ok")
            self.assertEqual(await store.aquery("next"), "ok")

    async def test_external_cancellation_does_not_block_other_requests(self):
        cancelled = threading.Event()
        async def slow(*args, **kwargs):
            try: await asyncio.sleep(10)
            finally: cancelled.set()
        store = LightRAGStore(); store._initialized = True
        store.rag = types.SimpleNamespace(aquery=slow)
        with patch.dict(sys.modules, {"lightrag": types.SimpleNamespace(QueryParam=lambda **kwargs: kwargs)}):
            task = asyncio.create_task(store.aquery("slow"))
            await asyncio.sleep(0.05)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assertTrue(await asyncio.to_thread(cancelled.wait, 1))

class GraphIsolationTests(unittest.TestCase):
    def test_same_path_aliases_reuse_graph_and_vector_instances(self):
        from services.rag import vector_store, lightrag_store
        with tempfile.TemporaryDirectory() as temp, patch.object(vector_store, "VectorStore") as create:
            canonical = str(Path(temp) / "index")
            alias = str(Path(temp) / "unused" / ".." / "index")
            if os.name == "nt":
                alias = alias.upper()
            self.assertIs(vector_store.get_vector_store("test", canonical), vector_store.get_vector_store("test", alias))
            create.assert_called_once()
            self.assertIs(lightrag_store.get_lightrag_store(canonical), lightrag_store.get_lightrag_store(alias))

    def test_real_lightrag_stores_do_not_share_documents_across_paths(self):
        import numpy as np
        from services.rag.lightrag_store import _get_or_create_bg_loop
        manager = MagicMock()
        manager.encode.return_value = np.zeros((1, 1024))
        with tempfile.TemporaryDirectory() as temp, patch("services.rag.embedding_manager.get_embedding_manager", return_value=manager):
            stores = [LightRAGStore(str(Path(temp) / parent / "index")) for parent in ("api", "code")]
            for store in stores:
                store.initialize()
            async def verify():
                await stores[0].rag.text_chunks.upsert({"same-id": {"content": "API only"}})
                await stores[1].rag.text_chunks.upsert({"same-id": {"content": "Code only"}})
                self.assertEqual((await stores[0].rag.text_chunks.get_by_id("same-id"))["content"], "API only")
                self.assertEqual((await stores[1].rag.text_chunks.get_by_id("same-id"))["content"], "Code only")
                for store in stores:
                    self.assertEqual(Path(store.rag.text_chunks._file_name), Path(store.working_dir) / "kv_store_text_chunks.json")
                    await store.rag.finalize_storages()
            asyncio.run_coroutine_threadsafe(verify(), _get_or_create_bg_loop()).result(timeout=10)

class ModelCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_cancels_detached_model_call(self):
        entered, stopped = threading.Event(), threading.Event()
        async def post(*args, **kwargs):
            entered.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()
        client = MagicMock()
        client.post = post
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        store = LightRAGStore()
        store._initialized = True
        complete = store._get_llm_func()
        detached = []
        async def query(*args, **kwargs):
            task = asyncio.create_task(complete("test", keyword_extraction=True))
            detached.append(task)
            return await asyncio.shield(task)
        store.rag = types.SimpleNamespace(aquery=query)
        with patch("httpx.AsyncClient", return_value=client), patch.object(config, "rag_timeout", .2), patch.dict(sys.modules, {"lightrag": types.SimpleNamespace(QueryParam=lambda **kw: kw)}):
            with self.assertRaises(asyncio.TimeoutError):
                await store.aquery("query")
            self.assertTrue(entered.is_set())
            self.assertTrue(await asyncio.to_thread(stopped.wait, 1))
            store.rag.aquery = AsyncMock(return_value="next")
            self.assertEqual(await store.aquery("next"), "next")
        self.assertTrue(all(task.done() for task in detached))

    async def test_missing_model_is_unavailable_and_request_preserves_json_format(self):
        import httpx
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=False)
        client.post = AsyncMock(return_value=httpx.Response(404, text="model not found"))
        store = LightRAGStore(llm_model="missing-model")
        with patch("httpx.AsyncClient", return_value=client):
            with self.assertRaises(FileNotFoundError):
                await store._get_llm_func()("test", keyword_extraction=True)
        payload = client.post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "missing-model")
        self.assertEqual(payload["format"], "json")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "test"}])

class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.root = str(ROOT.resolve())
        self.commands = []
        self.connections = 0
        self.drop_first = False
        self.delay = False
        self.actual_root = self.root
        self.handlers = set()
        async def frame(writer, value):
            data = json.dumps(value).encode();writer.write(struct.pack(">Q",len(data))+data);await writer.drain()
        async def read(reader):
            size=struct.unpack(">Q",await reader.readexactly(8))[0]
            return (await reader.readexactly(size)).decode()
        async def handler(reader,writer):
            task=asyncio.current_task();self.handlers.add(task);self.connections+=1
            try:
                writer.write(b"WELCOME UNITY-MCP 1 FRAMING=1\n");await writer.drain()
                self.assertEqual(await read(reader),'get_info')
                await frame(writer,{"status":"success","result":{"project_path":self.actual_root}})
                while True:
                    payload=await read(reader);self.commands.append(payload)
                    if self.drop_first:
                        self.drop_first=False;break
                    if self.delay: await asyncio.sleep(10)
                    await frame(writer,{"status":"success","result":{}})
            except (asyncio.IncompleteReadError,ConnectionError,asyncio.CancelledError): pass
            finally:
                writer.close();await writer.wait_closed();self.handlers.discard(task)
        self.server=await asyncio.start_server(handler,'127.0.0.1',0)
        self.port=self.server.sockets[0].getsockname()[1]
        self.discovery=patch('services.tools.unity_bridge.discover_unity_instances',return_value=[{'project_path':os.path.normcase(self.root),'unity_port':self.port}])
        self.discovery.start()
        self.bridge=UnityBridge(timeout=.2)
    async def asyncTearDown(self):
        self.bridge.close();close_bridge();self.discovery.stop();self.server.close();await self.server.wait_closed()
        pending=list(self.handlers)
        for task in pending:task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
    async def test_mutation_with_lost_response_is_not_replayed(self):
        self.drop_first=True
        with self.assertRaises(ExecutionUncertainError):
            await self.bridge.send_command('manage_gameobject',{'action':'create'},max_retries=3)
        self.assertEqual(len(self.commands),1)
        self.assertFalse(self.bridge.is_connected)
    async def test_read_only_can_retry(self):
        self.drop_first=True
        result=await self.bridge.send_command('manage_editor',{'action':'get_editor_state'},max_retries=2)
        self.assertEqual(result['status'],'success');self.assertEqual(len(self.commands),2)
    async def test_timeout_and_cancel_close_stream(self):
        self.delay=True
        with self.assertRaises(ExecutionUncertainError):
            await self.bridge.send_command('manage_gameobject',{'action':'create'},timeout=.03)
        self.assertFalse(self.bridge.is_connected)
        task=asyncio.create_task(self.bridge.send_command('manage_gameobject',{'action':'create'}))
        await asyncio.sleep(.02);task.cancel()
        with self.assertRaises(asyncio.CancelledError):await task
        self.assertFalse(self.bridge.is_connected)
    async def test_multiple_instances_and_project_mismatch_fail_before_mutation(self):
        with patch('services.tools.unity_bridge.discover_unity_instances',return_value=[{'project_path':'a','unity_port':1},{'project_path':'b','unity_port':2}]):
            with self.assertRaises(ProjectSelectionError):await self.bridge.connect()
        self.actual_root=str(ROOT.parent)
        with self.assertRaises(ProjectSelectionError):await self.bridge.send_command('manage_gameobject',{'action':'create'})
        self.assertEqual(self.commands,[])
    async def test_singleton_survives_disconnect(self):
        first=get_bridge();first.close();self.assertIs(first,get_bridge())

class StdioTests(unittest.TestCase):
    def test_actual_stdio_session_has_only_json_and_filters_calls(self):
        bootstrap = r"""
import sys
sys.path.insert(0,'Server/src')
from services.tools import rag_tools
from unittest.mock import MagicMock
store=MagicMock()
store.get_count.return_value=1
store.search.return_value=[{'id':'fixture','document':'complete source','metadata':{'source_url':'https://example.test/doc'},'distance':0.0}]
def get_store():
    print('third party diagnostic must go to stderr')
    return store
rag_tools._get_unified_vector_store=get_store
import main
main.main()
"""
        with tempfile.TemporaryDirectory() as temp:
            env={**os.environ,'UNITY_MCP_ENABLED_GROUPS':'rag','UNITY_MCP_TRANSPORT':'stdio','LOCALAPPDATA':temp,'PYTHONIOENCODING':'utf-8'}
            with open(Path(temp)/'stderr.log','w+',encoding='utf-8') as errors:
                process=subprocess.Popen([sys.executable,'-X','utf8','-u','-c',bootstrap],cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True,encoding='utf-8')
                output=queue.Queue()
                def reader():
                    for line in process.stdout:output.put(line)
                thread=threading.Thread(target=reader,daemon=True);thread.start()
                def send(value):process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
                def receive(identifier):
                    while True:
                        line=output.get(timeout=20)
                        message=json.loads(line)
                        if message.get('id')==identifier:return message
                try:
                    send({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'core-test','version':'1'}}})
                    self.assertIn('result',receive(1))
                    send({'jsonrpc':'2.0','method':'notifications/initialized'})
                    send({'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}})
                    names={t['name'] for t in receive(2)['result']['tools']}
                    self.assertIn('knowledge_search',names);self.assertNotIn('create_game_object',names)
                    send({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'knowledge_search','arguments':{'query':'test','include_full_content':True}}})
                    payload=json.loads(receive(3)['result']['content'][0]['text'])
                    self.assertEqual(payload['results'][0]['content'],'complete source')
                    self.assertEqual(payload['results'][0]['distance'],0)
                    send({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'create_game_object','arguments':{'name':'blocked'}}})
                    denied=receive(4)
                    self.assertTrue('error' in denied or denied['result'].get('isError'))
                finally:
                    process.stdin.close()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.kill();process.wait()
                    thread.join(timeout=2);process.stdout.close()
                errors.seek(0)
                self.assertIn('third party diagnostic',errors.read())
