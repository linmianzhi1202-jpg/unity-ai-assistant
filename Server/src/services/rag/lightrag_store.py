"""
LightRAG 图谱存储 — 基于 HKUDS LightRAG 的知识图谱检索

使用配置指定的 Ollama 模型作为 LLM + 本地 bge-m3 作为 Embedding

支持三种查询模式：
- local: 局部搜索（精确匹配实体和关系）
- global: 全局搜索（社区摘要）
- hybrid: 混合搜索（local + global）

实体类型：UnityAPI, CSharpClass, Method, Property, Parameter
关系类型：INHERITS_FROM, HAS_METHOD, HAS_PARAMETER, SIMILAR_TO
"""

import asyncio
import json
import logging
import os
import threading
from core.config import config
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── 持久化后台 Event Loop ──────────────────────────────────────────
# FastMCP 的 running loop 会导致 LightRAG 的 run_until_complete 死锁。
# 创建/销毁临时 loop 又会产生 worker 残留，导致第二次查询报 NoneType 错误。
# 解决：一个长期存在的后台线程，专用 event loop，所有 LightRAG 查询提交给它。
_loop_lock = threading.Lock()
_bg_loop = None
_query_gate = None

def _get_or_create_bg_loop():
    global _bg_loop
    with _loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            loop = asyncio.new_event_loop()
            ready = threading.Event()
            def run():
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()
            threading.Thread(target=run, daemon=True, name="lightrag-bg-loop").start()
            if not ready.wait(10):
                raise TimeoutError("LightRAG event loop did not start")
            _bg_loop = loop
    return _bg_loop

# 默认数据目录
DEFAULT_WORKING_DIR = str(Path(__file__).parent.parent.parent.parent / "data" / "base_kb" / "lightrag_db_v3_structured")
GAME_CODE_DEFAULT_WORKING_DIR = str(Path(__file__).parent.parent.parent.parent / "data" / "base_kb" / "lightrag_db_game_code")

# Ollama 模型配置
DEFAULT_LLM_MODEL = config.rag_model
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
OLLAMA_HOST = config.ollama_host

# Unity API 专用实体类型 — 精简为 6 种核心类型（P0 优化）
# 减少碎片实体，提升 LLM 抽取精度。Interface/Attribute/Event/Delegate/ReturnType
# 已被移除，因为它们导致实体碎片化。InheritedClass 和 UnityAPI 也被移除，
# 继承关系通过关系边（INHERITS_FROM）表达，API 概念通过 Method/Property 描述。
UNITY_ENTITY_TYPES = [
    "CSharpClass",      # C# 类/结构体定义（如 GameObject, Transform, Vector3）
    "Method",           # 方法定义（如 Start(), Update(), AddForce()）
    "Property",         # 属性/字段定义（如 transform, gameObject, mass）
    "Parameter",        # 方法参数定义（类型+名称组合如 Vector3 force）
    "Enum",             # 枚举类型（如 KeyCode, ForceMode, Space）
    "Namespace",        # 命名空间（如 UnityEngine, UnityEditor）
]

# 游戏源码知识图谱实体类型 — 对应 game_code_graph.json 的 entity_type
GAME_CODE_ENTITY_TYPES = [
    "GameProject",      # 游戏项目（对应 graph 中 entity_type="game"）
    "GameSourceFile",   # C# 源文件（对应 entity_type="file"）
    "GameClass",        # 游戏代码类（对应 entity_type="class"）
    "GameMethod",       # 方法（对应 entity_type="method"）
    "GameField",        # 字段/属性（对应 entity_type="field"）
    "GameAsset",        # 资产（图片/预制体等，对应 entity_type="asset"）
]

# entity_type 映射: graph 原始类型 → LightRAG 实体类型
GRAPH_TO_LIGHTRAG_TYPE = {
    "game": "GameProject",
    "file": "GameSourceFile",
    "class": "GameClass",
    "method": "GameMethod",
    "field": "GameField",
    "asset": "GameAsset",
}

# 关系类型映射: graph 原始关系 → LightRAG 关系 + 权重
GRAPH_TO_LIGHTRAG_RELATION = {
    "game_contains_class": ("CONTAINS_CLASS", 1.0),
    "class_has_method": ("HAS_METHOD", 1.0),
    "class_has_field": ("HAS_FIELD", 1.0),
    "class_inherits": ("INHERITS_FROM", 1.0),
    "method_calls": ("CALLS_METHOD", 0.8),
    "code_uses_asset": ("USES_ASSET", 0.7),
    # same_game 跳过（81K 全连接无意义）
}


class LightRAGStore:
    """LightRAG 图谱存储管理器（Ollama + 本地 bge-m3）"""

    def __init__(
        self,
        working_dir: str = DEFAULT_WORKING_DIR,
        llm_model: str | None = None,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        entity_types: Optional[List[str]] = None,
    ):
        self.working_dir = working_dir
        self.llm_model = llm_model or config.rag_model
        self.embedding_model = embedding_model
        self.entity_types = entity_types or UNITY_ENTITY_TYPES
        self.rag = None
        self._initialized = False
        self._query_tasks = set()

    def _ensure_dir(self):
        """确保工作目录存在"""
        Path(self.working_dir).mkdir(parents=True, exist_ok=True)

    def _get_embedding_func(self):
        """获取本地 bge-m3 Embedding 函数（适配 LightRAG 的异步接口）"""
        import numpy as np
        from lightrag.utils import EmbeddingFunc
        from .embedding_manager import get_embedding_manager

        # 用闭包持有单例
        _mgr = None

        async def encode(texts: List[str]) -> np.ndarray:
            """返回 numpy 数组（LightRAG 内部需要 .size 属性）"""
            nonlocal _mgr
            if _mgr is None:
                _mgr = await asyncio.to_thread(get_embedding_manager)
            embeddings = await asyncio.to_thread(_mgr.encode, texts, show_progress_bar=False)
            # 确保返回 numpy 数组而非列表
            if isinstance(embeddings, list):
                embeddings = np.array(embeddings)
            return embeddings

        async def embedding_func(texts):
            task = asyncio.create_task(encode(texts))
            self._query_tasks.add(task)
            try:
                return await task
            finally:
                self._query_tasks.discard(task)

        return EmbeddingFunc(
            embedding_dim=1024,
            max_token_size=8192,
            func=embedding_func,
        )

    def _get_llm_func(self):
        """Call the configured Ollama endpoint without runtime package installation."""
        import re
        import httpx

        async def complete(prompt, system_prompt=None, history_messages=None, **kwargs):
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.extend(history_messages or [])
            messages.append({"role": "user", "content": prompt})
            payload = {"model": self.llm_model, "messages": messages, "stream": False}
            response_format = kwargs.get("response_format")
            if response_format:
                if hasattr(response_format, "model_json_schema"):
                    response_format = response_format.model_json_schema()
                payload["format"] = "json" if response_format == {"type": "json_object"} else response_format
            elif kwargs.get("keyword_extraction") or kwargs.get("entity_extraction"):
                payload["format"] = "json"
            if kwargs.get("options"):
                payload["options"] = kwargs["options"]
            async with httpx.AsyncClient(timeout=config.rag_timeout) as client:
                try:
                    response = await client.post(config.ollama_host.rstrip("/") + "/api/chat", json=payload)
                except httpx.ConnectError as exc:
                    raise ConnectionError(f"Ollama unavailable at {config.ollama_host}") from exc
                if response.status_code == 404:
                    raise FileNotFoundError(f"Ollama model unavailable: {self.llm_model}: {response.text}")
                response.raise_for_status()
                result = response.json()["message"]["content"]
            return re.sub(r"<think[\s\S]*?</think\s*>", "", result).strip()

        async def invoke(*args, **kwargs):
            task = asyncio.create_task(complete(*args, **kwargs))
            self._query_tasks.add(task)
            try:
                return await task
            finally:
                self._query_tasks.discard(task)

        return invoke

    def _create_rag(self):
        """初始化 LightRAG 实例（含异步存储初始化）"""
        if self._initialized and self.rag is not None:
            return

        try:
            from lightrag import LightRAG

            self._ensure_dir()

            # 关键：在 LightRAG 初始化之前预加载 embedding 模型
            # 避免 LightRAG 的 HTTP 客户端关闭 HuggingFace Hub 客户端
            logger.info("[LightRAG] 预加载 bge-m3 模型...")
            from .embedding_manager import get_embedding_manager
            _mgr = get_embedding_manager()
            # 触发模型加载（预热）
            _test = _mgr.encode(["warmup"], show_progress_bar=False)
            logger.info(f"[LightRAG] bge-m3 预加载完成, dim={_test.shape}")

            embedding_func = self._get_embedding_func()
            llm_func = self._get_llm_func()

            # ENTITY_TYPES 环境变量在新版 LightRAG 中已废弃，通过 addon_params 传入即可
            self.rag = LightRAG(
                working_dir=self.working_dir,
                # Shared in-memory namespaces must also be isolated by index path.
                # An absolute workspace preserves the existing on-disk file locations.
                workspace=os.path.normcase(str(Path(self.working_dir).resolve())),
                llm_model_func=llm_func,
                llm_model_name=self.llm_model,
                embedding_func=embedding_func,
                # 降低并发，Ollama 本地推理单线程即可避免 502 错误
                llm_model_max_async=1,
                embedding_func_max_async=2,
                # P0 优化: chunk 从 800 缩小到 400，降低 LLM 单次抽取负担
                chunk_token_size=400,
                chunk_overlap_token_size=100,
                # 注入实体类型，覆盖默认的 Person/Location/Organization/...
                addon_params={
                    "language": "English",
                    "entity_types": self.entity_types,
                },
            )

        except ImportError as e:
            logger.error(f"LightRAG not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"LightRAG init failed: {e}")
            raise

    def insert(self, texts: List[str]) -> Dict[str, Any]:
        """
        插入文本到知识图谱

        Args:
            texts: 待索引的文本列表

        Returns:
            插入结果统计
        """
        self.initialize()

        success = 0
        skipped = 0
        errors = 0

        for text in texts:
            try:
                result = self.rag.insert(text)
                if result:  # insert 返回 track_id 或空
                    success += 1
                else:
                    skipped += 1  # 返回空：可能是重复文档
            except Exception as e:
                errors += 1
                logger.error(f"LightRAG insert error: {e}")

        return {
            "inserted": success,
            "skipped": skipped,
            "errors": errors,
            "total": len(texts),
        }

    async def _run_on_background(self, query=None, mode="hybrid", only_need_context=False):
        global _query_gate
        if _query_gate is None:
            _query_gate = asyncio.Lock()
        async with _query_gate:
            if not self._initialized:
                # Retain the worker future across cancellation: a timed-out model load
                # must not start a second competing initialization.
                if not hasattr(self, "_creation_task"):
                    self._creation_task = asyncio.create_task(asyncio.to_thread(self._create_rag))
                try:
                    await asyncio.shield(self._creation_task)
                    await self.rag.initialize_storages()
                    self._initialized = True
                except asyncio.CancelledError:
                    raise
                except Exception:
                    del self._creation_task
                    raise
            if query is None:
                return None
            from lightrag import QueryParam
            rerank_enabled = os.getenv("UNITY_MCP_LIGHTRAG_RERANK_ENABLED", "0").strip().lower() in {
                "1", "true", "yes", "on"
            }
            try:
                params = dict(
                    mode=mode, only_need_context=only_need_context,
                    max_total_tokens=6000, max_entity_tokens=1500, max_relation_tokens=1500,
                    enable_rerank=rerank_enabled,
                )
                try:
                    return await self.rag.aquery(query, param=QueryParam(**params))
                except TypeError as exc:
                    # Older LightRAG versions do not expose enable_rerank.
                    # Remove only that optional field and keep the query usable.
                    if "enable_rerank" not in str(exc):
                        raise
                    params.pop("enable_rerank", None)
                    return await self.rag.aquery(query, param=QueryParam(**params))
                except Exception:
                    if not rerank_enabled:
                        raise
                    # The flag may exist while the installed reranker/model is
                    # unavailable. Preserve service availability by retrying.
                    logger.warning("LightRAG rerank failed; retrying without rerank", exc_info=True)
                    params["enable_rerank"] = False
                    return await self.rag.aquery(query, param=QueryParam(**params))
            finally:
                # LightRAG queues detach model calls from aquery cancellation.
                # Drain this store's active calls before releasing the query gate.
                pending = list(self._query_tasks)
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)


    def initialize(self):
        future = asyncio.run_coroutine_threadsafe(self._run_on_background(), _get_or_create_bg_loop())
        try:
            future.result(timeout=config.rag_timeout)
        except BaseException:
            future.cancel()
            raise

    async def aquery(self, query: str, mode: str = "hybrid", only_need_context: bool = False) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self._run_on_background(query, mode, only_need_context), _get_or_create_bg_loop()
        )
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), timeout=config.rag_timeout)
        except BaseException:
            future.cancel()
            raise

    def query(self, query: str, mode: str = "hybrid", only_need_context: bool = False) -> str:
        future = asyncio.run_coroutine_threadsafe(
            self._run_on_background(query, mode, only_need_context), _get_or_create_bg_loop()
        )
        try:
            return future.result(timeout=config.rag_timeout)
        except BaseException:
            future.cancel()
            raise

    def get_status(self) -> Dict[str, Any]:
        """获取 LightRAG 状态"""
        status = {
            "initialized": self._initialized,
            "working_dir": self.working_dir,
            "llm_model": self.llm_model,
            "embedding_model": self.embedding_model,
            "ollama_host": OLLAMA_HOST,
        }

        # Always check disk files, even when not initialized
        graph_path = Path(self.working_dir) / "graph_chunk_entity_relation.graphml"
        status["graph_exists"] = graph_path.exists()
        if graph_path.exists():
            status["graph_size_kb"] = graph_path.stat().st_size / 1024

        if self._initialized and self.rag is not None:
            try:
                # 检查图谱文件是否存在
                graph_path = Path(self.working_dir) / "graph_chunk_entity_relation.graphml"
                status["graph_exists"] = graph_path.exists()
                if graph_path.exists():
                    status["graph_size_kb"] = graph_path.stat().st_size / 1024

                # 检查向量存储
                kv_store_path = Path(self.working_dir) / "kv_store_full_docs.json"
                status["docs_indexed"] = kv_store_path.exists()
                if kv_store_path.exists():
                    try:
                        with open(kv_store_path, 'r', encoding='utf-8') as f:
                            docs = json.load(f)
                            status["doc_count"] = len(docs) if isinstance(docs, dict) else 0
                    except Exception:
                        status["doc_count"] = "unknown"

                # 检查实体存储
                graph_entity_path = Path(self.working_dir) / "vdb_entities.json"
                if graph_entity_path.exists():
                    status["entity_store_exists"] = True
            except Exception as e:
                status["error"] = str(e)

        return status

    def batch_insert_from_json_dir(
        self,
        json_dir: str,
        batch_size: int = 10,
        max_docs: int = 0,
    ) -> Dict[str, Any]:
        """
        从 JSON 目录批量导入数据到 LightRAG

        Args:
            json_dir: JSON 文件目录
            batch_size: 每批处理文档数
            max_docs: 最大文档数（0=不限制）

        Returns:
            导入结果统计
        """
        self.initialize()

        from .pdf_parser import api_data_to_text

        json_path = Path(json_dir)
        if not json_path.exists():
            return {"error": f"Directory not found: {json_dir}"}

        json_files = list(json_path.rglob("*.json"))
        if max_docs > 0:
            json_files = json_files[:max_docs]

        total = len(json_files)
        success = 0
        errors = 0

        batch_texts = []

        for i, jf in enumerate(json_files):
            try:
                with open(jf, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                text = api_data_to_text(data)
                if text.strip():
                    batch_texts.append(text)

                if len(batch_texts) >= batch_size:
                    result = self.insert(batch_texts)
                    success += result["inserted"]
                    errors += result["errors"]
                    batch_texts = []

                    if (i + 1) % 100 == 0:
                        logger.info(f"[LightRAG] Progress: {i+1}/{total}, OK:{success}, ERR:{errors}")

            except Exception as e:
                errors += 1
                logger.error(f"Error processing {jf}: {e}")

        if batch_texts:
            result = self.insert(batch_texts)
            success += result["inserted"]
            errors += result["errors"]

        return {
            "total_files": total,
            "inserted": success,
            "errors": errors,
        }

    # ── P2: 精确实体注入（绕过 LLM，直接从 JSON 构建实体/关系）───────

    def insert_structured_api(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将单个 Unity API JSON 文档精确注入知识图谱，**零 LLM 调用**。

        从 JSON 中提取类名、方法、属性、参数等结构化信息，
        直接构建实体和关系列表，通过 LightRAG 的 insert_custom_kg 接口注入。

        Args:
            api_data: Unity API JSON 文档 dict，包含 class_name, methods, properties 等字段

        Returns:
            注入结果: {"class_name": ..., "entities": N, "relationships": N, "status": "ok"/"error"}
        """
        self.initialize()

        try:
            class_name = api_data.get("class_name", "UnknownClass")
            namespace = api_data.get("namespace", "Unknown")
            api_type = api_data.get("type", "class")
            file_path = api_data.get("source_file", f"{class_name}.json")

            # 构建 source_id（唯一标识这个文档）
            source_id = f"structured:{class_name}"

            # ── 构建 chunk（文档内容摘要）──────────────────────────
            from .pdf_parser import api_data_to_text
            chunk_content = api_data_to_text(api_data)
            if not chunk_content.strip():
                chunk_content = f"Unity API: {class_name} in namespace {namespace}"

            # 截断过长的 chunk（LightRAG 有 token 限制）
            max_chunk_chars = 3000
            if len(chunk_content) > max_chunk_chars:
                # 保留开头和结尾
                half = max_chunk_chars // 2
                chunk_content = chunk_content[:half] + "\n... (truncated) ...\n" + chunk_content[-half:]

            chunks = [{
                "content": chunk_content,
                "source_id": source_id,
                "file_path": file_path,
                "chunk_order_index": 0,
            }]

            # ── 构建实体列表 ──────────────────────────────────────
            entities = []

            # 1. 类实体
            class_desc = api_data.get("description", f"{class_name} is a Unity {api_type}.")
            # 截断过长的描述
            if len(class_desc) > 500:
                class_desc = class_desc[:497] + "..."

            entities.append({
                "entity_name": class_name,
                "entity_type": "CSharpClass",
                "description": class_desc,
                "source_id": source_id,
                "file_path": file_path,
            })

            # 2. 命名空间实体
            if namespace and namespace != "Unknown":
                entities.append({
                    "entity_name": namespace,
                    "entity_type": "Namespace",
                    "description": f"{namespace} is a C# namespace containing Unity API types including {class_name}.",
                    "source_id": source_id,
                    "file_path": file_path,
                })

            # 3. 方法实体
            methods = api_data.get("methods", [])
            if isinstance(methods, list):
                for method in methods:
                    if isinstance(method, dict):
                        method_name = method.get("name", method.get("method_name", ""))
                    elif isinstance(method, str):
                        method_name = method
                    else:
                        continue

                    if not method_name:
                        continue

                    method_desc = method.get("description", "") if isinstance(method, dict) else ""
                    if not method_desc:
                        method_desc = f"{method_name} is a method of {class_name}."
                    if len(method_desc) > 400:
                        method_desc = method_desc[:397] + "..."

                    entities.append({
                        "entity_name": method_name,
                        "entity_type": "Method",
                        "description": method_desc,
                        "source_id": source_id,
                        "file_path": file_path,
                    })

            # 4. 属性/字段实体
            properties = api_data.get("properties", [])
            if isinstance(properties, list):
                for prop in properties:
                    if isinstance(prop, dict):
                        prop_name = prop.get("name", "")
                        prop_desc = prop.get("description", f"{prop_name} is a property of {class_name}.")
                    elif isinstance(prop, str):
                        prop_name = prop
                        prop_desc = f"{prop_name} is a property of {class_name}."
                    else:
                        continue

                    if not prop_name:
                        continue
                    if len(prop_desc) > 400:
                        prop_desc = prop_desc[:397] + "..."

                    entities.append({
                        "entity_name": prop_name,
                        "entity_type": "Property",
                        "description": prop_desc,
                        "source_id": source_id,
                        "file_path": file_path,
                    })

            # 5. 枚举实体
            enums = api_data.get("enums", api_data.get("enum_values", []))
            if isinstance(enums, list) and enums:
                for enum_val in enums:
                    if isinstance(enum_val, dict):
                        enum_name = enum_val.get("name", "")
                        enum_desc = enum_val.get("description", f"{enum_name} is an enum value.")
                    elif isinstance(enum_val, str):
                        enum_name = enum_val
                        enum_desc = f"{enum_name} is an enum value of {class_name}."
                    else:
                        continue

                    if not enum_name:
                        continue
                    if len(enum_desc) > 400:
                        enum_desc = enum_desc[:397] + "..."

                    entities.append({
                        "entity_name": enum_name,
                        "entity_type": "Enum",
                        "description": enum_desc,
                        "source_id": source_id,
                        "file_path": file_path,
                    })

            # ── 构建关系列表 ──────────────────────────────────────
            relationships = []

            # 类 → 命名空间
            if namespace and namespace != "Unknown":
                relationships.append({
                    "src_id": class_name,
                    "tgt_id": namespace,
                    "description": f"{class_name} belongs to the {namespace} namespace.",
                    "keywords": "belongs to, namespace membership",
                    "weight": 1.0,
                    "source_id": source_id,
                    "file_path": file_path,
                })

            # 类 → 方法（HAS_METHOD）
            method_names = []
            if isinstance(methods, list):
                for method in methods:
                    mn = method.get("name", method.get("method_name", "")) if isinstance(method, dict) else str(method)
                    if mn:
                        method_names.append(mn)
                        relationships.append({
                            "src_id": class_name,
                            "tgt_id": mn,
                            "description": f"{class_name} defines the {mn} method.",
                            "keywords": "defines method, HAS_METHOD",
                            "weight": 1.0,
                            "source_id": source_id,
                            "file_path": file_path,
                        })

            # 类 → 属性（HAS_PROPERTY）
            if isinstance(properties, list):
                for prop in properties:
                    pn = prop.get("name", "") if isinstance(prop, dict) else str(prop)
                    if pn:
                        relationships.append({
                            "src_id": class_name,
                            "tgt_id": pn,
                            "description": f"{class_name} has the {pn} property.",
                            "keywords": "has property, HAS_PROPERTY",
                            "weight": 1.0,
                            "source_id": source_id,
                            "file_path": file_path,
                        })

            # 方法 → 参数（ACCEPTS_PARAMETER）
            if isinstance(methods, list):
                for method in methods:
                    if not isinstance(method, dict):
                        continue
                    mn = method.get("name", method.get("method_name", ""))
                    params = method.get("parameters", method.get("params", []))
                    if isinstance(params, list):
                        for param in params:
                            if isinstance(param, dict):
                                param_name = param.get("name", "")
                                param_type = param.get("type", "")
                                param_desc = param.get("description", f"{param_name} is a parameter of {mn}.")
                            elif isinstance(param, str):
                                param_name = param
                                param_type = ""
                                param_desc = f"{param_name} is a parameter of {mn}."
                            else:
                                continue

                            if not param_name:
                                continue
                            if len(param_desc) > 400:
                                param_desc = param_desc[:397] + "..."

                            # 添加参数实体（如果还没添加）
                            param_entity_name = f"{param_type} {param_name}" if param_type else param_name
                            already_added = any(e["entity_name"] == param_entity_name for e in entities)
                            if not already_added:
                                entities.append({
                                    "entity_name": param_entity_name,
                                    "entity_type": "Parameter",
                                    "description": param_desc,
                                    "source_id": source_id,
                                    "file_path": file_path,
                                })

                            if mn:
                                relationships.append({
                                    "src_id": mn,
                                    "tgt_id": param_entity_name,
                                    "description": f"{mn} accepts {param_entity_name} as a parameter.",
                                    "keywords": "accepts parameter, HAS_PARAMETER",
                                    "weight": 1.0,
                                    "source_id": source_id,
                                    "file_path": file_path,
                                })

            # 继承关系（如果 API 数据包含）
            parent_class = api_data.get("parent_class", api_data.get("base_class", ""))
            if parent_class and parent_class.strip():
                relationships.append({
                    "src_id": class_name,
                    "tgt_id": parent_class,
                    "description": f"{class_name} inherits from {parent_class}.",
                    "keywords": "inherits from, INHERITS_FROM",
                    "weight": 1.0,
                    "source_id": source_id,
                    "file_path": file_path,
                })

            # ── 组装 custom_kg 并注入 ────────────────────────────
            custom_kg = {
                "chunks": chunks,
                "entities": entities,
                "relationships": relationships,
            }

            # 调用 LightRAG 的 insert_custom_kg（同步包装）
            self.rag.insert_custom_kg(custom_kg)

            return {
                "class_name": class_name,
                "namespace": namespace,
                "entities": len(entities),
                "relationships": len(relationships),
                "status": "ok",
            }

        except Exception as e:
            logger.error(f"insert_structured_api error for {api_data.get('class_name', 'unknown')}: {e}")
            return {
                "class_name": api_data.get("class_name", "unknown"),
                "status": "error",
                "error": str(e),
            }

    def batch_insert_structured(
        self,
        json_dir: str,
        max_docs: int = 0,
        filter_class: str = "",
    ) -> Dict[str, Any]:
        """
        批量从 JSON 目录精确注入实体到知识图谱（绕过 LLM）。

        Args:
            json_dir: JSON 文件目录
            max_docs: 最大文档数（0=不限制）
            filter_class: 仅处理包含此名称的类（如 "Camera"）

        Returns:
            注入结果统计
        """
        self.initialize()

        json_path = Path(json_dir)
        if not json_path.exists():
            return {"error": f"Directory not found: {json_dir}"}

        json_files = list(json_path.rglob("*.json"))
        total = len(json_files)

        # 过滤
        if filter_class:
            json_files = [f for f in json_files if filter_class.lower() in f.name.lower()]

        if max_docs > 0:
            json_files = json_files[:max_docs]

        total_entities = 0
        total_relationships = 0
        success = 0
        errors = 0

        logger.info(f"[StructuredInsert] Processing {len(json_files)} files (total: {total})")
        logger.info(f"[StructuredInsert] 开始精确注入: {len(json_files)} 个文档")

        for i, jf in enumerate(json_files):
            try:
                with open(jf, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                result = self.insert_structured_api(data)

                if result["status"] == "ok":
                    total_entities += result["entities"]
                    total_relationships += result["relationships"]
                    success += 1
                else:
                    errors += 1

                if (i + 1) % 50 == 0:
                    logger.info(
                        f"[StructuredInsert] Progress: {i+1}/{len(json_files)}, "
                        f"Entities:{total_entities}, Relations:{total_relationships}"
                    )
                    logger.info(f"  [{i+1}/{len(json_files)}] Entities:{total_entities} Relations:{total_relationships}")

            except Exception as e:
                errors += 1
                logger.error(f"Structured insert error for {jf}: {e}")

        return {
            "total_files": len(json_files),
            "success": success,
            "errors": errors,
            "total_entities": total_entities,
            "total_relationships": total_relationships,
            "avg_entities_per_doc": round(total_entities / max(success, 1), 1),
            "avg_relationships_per_doc": round(total_relationships / max(success, 1), 1),
        }


    # ── 游戏源码图谱注入（零 LLM 调用）─────────────────────────

    def insert_game_code_graph(
        self,
        graph_path: str,
        max_entities_per_batch: int = 200,
    ) -> Dict[str, Any]:
        """
        将 game_code_graph.json 注入 LightRAG 知识图谱（零 LLM 调用）。

        读取 nodes/edges → 按 game_name 分组 → 逐游戏构建 entities/relationships/chunks →
        批量调用 insert_custom_kg 注入。

        source_id 命名空间: game:{game_name}:{node_id}

        Args:
            graph_path: game_code_graph.json 的绝对路径
            max_entities_per_batch: 每批最多实体数（默认 200）

        Returns:
            {"games_processed": N, "total_entities": N, "total_relationships": N,
             "total_chunks": N, "skipped_same_game": N, "status": "ok"|"error"}
        """
        self.initialize()

        graph_data = self._load_game_code_graph(graph_path)
        nodes = graph_data["nodes"]
        edges = graph_data["edges"]

        # 建立 node_id → node 索引（O(1) 查找）
        node_index = {n["id"]: n for n in nodes}

        # 按 game_name 分组 nodes
        game_node_groups: Dict[str, List[dict]] = {}
        for n in nodes:
            gn = n.get("metadata", {}).get("game_name", "unknown")
            game_node_groups.setdefault(gn, []).append(n)

        total_entities = 0
        total_relationships = 0
        total_chunks = 0
        skipped_same_game = 0
        games_processed = 0

        game_names = sorted(game_node_groups.keys())
        logger.info(f"[GameCodeGraph] 共 {len(game_names)} 个游戏项目，{len(nodes)} 节点，{len(edges)} 边")

        for game_name in game_names:
            gnodes = game_node_groups[game_name]
            node_ids = {n["id"] for n in gnodes}

            logger.info(f"\n[GameCodeGraph] 处理 [{game_name}] ({len(gnodes)} 节点)...")

            # 构建该游戏的所有实体、chunks、关系
            entities = self._build_game_code_entities(gnodes, game_name, node_index)
            chunks = self._build_game_code_chunks(gnodes, game_name)
            relationships = self._build_game_code_relationships(
                edges, node_ids, node_index, game_name
            )

            # 统计跳过的 same_game 边
            game_edges = [e for e in edges
                         if e["source"] in node_ids and e["target"] in node_ids]
            skipped_same_game += sum(1 for e in game_edges
                                     if e.get("relation_type") == "same_game")

            # 分批注入（大游戏拆分子批）
            if len(entities) <= max_entities_per_batch:
                # 单批注入
                custom_kg = {
                    "chunks": chunks,
                    "entities": entities,
                    "relationships": relationships,
                }
                try:
                    self.rag.insert_custom_kg(custom_kg)
                    total_entities += len(entities)
                    total_relationships += len(relationships)
                    total_chunks += len(chunks)
                    logger.info(f"  [OK] Game injected: {len(entities)} entities, {len(relationships)} relations, {len(chunks)} chunks")
                except Exception as e:
                    logger.error(f"insert_custom_kg failed for {game_name}: {e}")
                    raise
            else:
                # 分多批注入
                for batch_start in range(0, len(entities), max_entities_per_batch):
                    batch_end = min(batch_start + max_entities_per_batch, len(entities))
                    batch_entities = entities[batch_start:batch_end]

                    # 收集本批涉及的 entity_names 和 source_ids
                    batch_entity_names = {e["entity_name"] for e in batch_entities}
                    batch_source_ids = {e["source_id"] for e in batch_entities}

                    # 过滤相关 chunks
                    batch_chunks = [c for c in chunks
                                   if c["source_id"] in batch_source_ids]
                    # 过滤相关 relationships（至少一端在本批实体中）
                    batch_rels = [r for r in relationships
                                 if r["src_id"] in batch_entity_names
                                 or r["tgt_id"] in batch_entity_names]

                    custom_kg = {
                        "chunks": batch_chunks,
                        "entities": batch_entities,
                        "relationships": batch_rels,
                    }
                    try:
                        self.rag.insert_custom_kg(custom_kg)
                        total_entities += len(batch_entities)
                        total_relationships += len(batch_rels)
                        total_chunks += len(batch_chunks)
                        logger.info(f"  [OK] batch [{batch_start}-{batch_end}]: "
                              f"{len(batch_entities)} entities, {len(batch_rels)} relations")
                    except Exception as e:
                        logger.error(f"Batch insert_custom_kg failed: {e}")
                        raise

            games_processed += 1

        return {
            "games_processed": games_processed,
            "total_entities": total_entities,
            "total_relationships": total_relationships,
            "total_chunks": total_chunks,
            "skipped_same_game": skipped_same_game,
            "status": "ok",
        }

    @staticmethod
    def _load_game_code_graph(graph_path: str) -> Dict[str, Any]:
        """读取 game_code_graph.json"""
        path = Path(graph_path)
        if not path.exists():
            raise FileNotFoundError(f"game_code_graph.json not found at: {graph_path}")

        logger.info(f"[GameCodeGraph] 加载 {graph_path} ({path.stat().st_size / 1024 / 1024:.1f} MB)...")
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"[GameCodeGraph] 加载完成: {len(data.get('nodes',[]))} 节点, "
              f"{len(data.get('edges',[]))} 边")
        return data

    @staticmethod
    def _build_game_code_entities(
        gnodes: List[dict],
        game_name: str,
        node_index: Dict[str, dict],
    ) -> List[dict]:
        """
        将 game_code_graph 的 nodes 转换为 LightRAG entities。

        命名空间规则:
        - source_id = game:{game_name}:{node_id}
        - entity_name = node["name"]（类名/方法名/文件名）
        """
        entities = []
        for node in gnodes:
            entity_type = GRAPH_TO_LIGHTRAG_TYPE.get(
                node.get("entity_type", ""), "GameClass"
            )

            # 构建稳定的 source_id
            source_id = f"game:{game_name}:{node['id']}"

            # 截断过长的描述
            desc = node.get("description", node.get("name", ""))
            if len(desc) > 500:
                desc = desc[:497] + "..."

            entities.append({
                "entity_name": node["name"],
                "entity_type": entity_type,
                "description": desc,
                "source_id": source_id,
                "file_path": node.get("metadata", {}).get("file_path", game_name),
                # 额外元数据（LightRAG 会保留到实体存储中）
                "metadata": json.dumps({
                    "game_name": game_name,
                    "original_id": node["id"],
                    "entity_type": node.get("entity_type", ""),
                    "file_path": node.get("metadata", {}).get("file_path", ""),
                }),
            })
        return entities

    @staticmethod
    def _build_game_code_relationships(
        edges: List[dict],
        node_ids: set,
        node_index: Dict[str, dict],
        game_name: str,
    ) -> List[dict]:
        """
        将 game_code_graph 的 edges 转换为 LightRAG relationships。

        规则:
        - 跳过 same_game 关系（81K 全连接无意义）
        - 跳过两端不全在本游戏 node_ids 中的边
        - src_id/tgt_id 使用 node["name"]（与 entity_name 一致）
        """
        relationships = []
        skipped = 0

        for edge in edges:
            rel_type = edge.get("relation_type", "")

            # 跳过 same_game
            if rel_type == "same_game":
                skipped += 1
                continue

            # 只处理两端都在本游戏中的边
            if edge["source"] not in node_ids or edge["target"] not in node_ids:
                continue

            # 查找映射关系
            rel_info = GRAPH_TO_LIGHTRAG_RELATION.get(rel_type)
            if rel_info is None:
                continue  # 未知关系类型，跳过

            lightrag_rel, default_weight = rel_info
            weight = edge.get("weight", default_weight)

            # 用 node name 作为关系端点（与 entity_name 一致）
            src_node = node_index.get(edge["source"])
            tgt_node = node_index.get(edge["target"])
            if not src_node or not tgt_node:
                continue

            src_name = src_node["name"]
            tgt_name = tgt_node["name"]

            # 构建描述
            src_type = src_node.get("entity_type", "?")
            tgt_type = tgt_node.get("entity_type", "?")
            description = f"{src_name} ({src_type}) {lightrag_rel} {tgt_name} ({tgt_type})"

            source_id = f"game:{game_name}:{edge['source']}"
            file_path = src_node.get("metadata", {}).get("file_path", game_name)

            relationships.append({
                "src_id": src_name,
                "tgt_id": tgt_name,
                "description": description,
                "keywords": f"{lightrag_rel.lower()}, {rel_type}",
                "weight": weight,
                "source_id": source_id,
                "file_path": file_path,
            })

        if skipped > 0:
            logger.debug(f"Skipped {skipped} same_game edges for {game_name}")

        return relationships

    @staticmethod
    def _build_game_code_chunks(
        gnodes: List[dict],
        game_name: str,
    ) -> List[dict]:
        """
        为 game_code_graph 的 nodes 生成 LightRAG chunks。

        策略：每个节点生成一个 chunk，包含其描述和元数据。
        """
        chunks = []
        for i, node in enumerate(gnodes):
            source_id = f"game:{game_name}:{node['id']}"

            # chunk 内容：实体描述 + 元数据摘要
            metadata = node.get("metadata", {})
            parts = [node.get("description", node.get("name", ""))]

            entity_type = node.get("entity_type", "")
            if entity_type == "class":
                base_classes = metadata.get("base_classes", [])
                if base_classes:
                    parts.append(f"  Inherits from: {', '.join(base_classes)}")
            elif entity_type == "method":
                return_type = metadata.get("return_type", "")
                if return_type:
                    parts.append(f"  Return type: {return_type}")

            chunk_content = "\n".join(parts)

            # 截断过长 chunk
            if len(chunk_content) > 2000:
                chunk_content = chunk_content[:1997] + "..."

            chunks.append({
                "content": chunk_content,
                "source_id": source_id,
                "file_path": metadata.get("file_path", game_name),
                "chunk_order_index": i,
            })
        return chunks


# 全局实例
_stores: dict[tuple[str, str], LightRAGStore] = {}
_stores_lock = threading.Lock()

def get_lightrag_store(working_dir: str = DEFAULT_WORKING_DIR) -> LightRAGStore:
    key = (os.path.normcase(str(Path(working_dir).resolve())), "api")
    with _stores_lock:
        if key not in _stores:
            _stores[key] = LightRAGStore(working_dir=key[0])
        return _stores[key]

def get_game_code_lightrag_store(working_dir: str = GAME_CODE_DEFAULT_WORKING_DIR) -> LightRAGStore:
    key = (os.path.normcase(str(Path(working_dir).resolve())), "game")
    with _stores_lock:
        if key not in _stores:
            _stores[key] = LightRAGStore(working_dir=key[0], entity_types=GAME_CODE_ENTITY_TYPES)
        return _stores[key]
