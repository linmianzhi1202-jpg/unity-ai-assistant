"""Knowledge tools: shared stores, asynchronous retrieval and explicit source status."""
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from services.rag.vector_store import get_vector_store
from core.config import config

logger = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_BASE_KB_DIR = _DATA_DIR / "base_kb"
_EXT_KB_DIR = _DATA_DIR / "ext_kb"
_UNIFIED_CHROMA_DIR = str(_BASE_KB_DIR / "chroma_db_v3")
_UNIFIED_LIGHTRAG_DIR = str(_BASE_KB_DIR / "lightrag_db_v3_structured")
_UNIFIED_GAME_CODE_LIGHTRAG_DIR = str(_BASE_KB_DIR / "lightrag_db_game_code")

def _get_unified_vector_store():
    return get_vector_store("unity_api_v3", _UNIFIED_CHROMA_DIR)

def _get_unified_lightrag_store():
    from services.rag.lightrag_store import get_lightrag_store
    return get_lightrag_store(_UNIFIED_LIGHTRAG_DIR)

def _get_unified_game_code_lightrag_store():
    from services.rag.lightrag_store import get_game_code_lightrag_store
    return get_game_code_lightrag_store(_UNIFIED_GAME_CODE_LIGHTRAG_DIR)

def _search_vector(query, count, search_type="all", include_full_content=False):
    store = _get_unified_vector_store()
    total = store.get_count()
    where = {"type": search_type} if search_type in {"class", "method"} else None
    items = store.search(query, n_results=max(1, min(20, count)), where=where) if total else []
    results = []
    for item in items:
        metadata = item.get("metadata") or {}
        text = item.get("document") or ""
        result = {
            "source": "vector", "id": item.get("id", ""),
            "document_id": item.get("id", ""),
            "type": metadata.get("type", ""), "class_name": metadata.get("class_name", ""),
            "distance": round(item["distance"], 4) if item.get("distance") is not None else None,
            "content_preview": text[:600],
            "source_path": metadata.get("source_path", metadata.get("source", "")),
            "source_url": metadata.get("source_url", metadata.get("url", "")),
            "unity_version": metadata.get("unity_version", ""),
        }
        for key in ("method_name", "full_name"):
            if metadata.get(key):
                result[key] = metadata[key]
        if include_full_content:
            result["content"] = text
        results.append(result)
    return results, total

async def arun_knowledge_unified_search(query: str, sources: list | None = None, vector_results: int = 3,
                                       graph_mode: str = "local", include_graph_context: bool | None = None,
                                       include_full_content: bool = False) -> dict[str, Any]:
    if sources is None:
        sources = ["vector", "api_graph"] if include_graph_context is True else ["vector"]
    sources = list(dict.fromkeys(sources))
    valid = {"vector", "api_graph", "game_code_graph"}
    if not sources or any(source not in valid for source in sources):
        return {"status": "error", "query": query, "error": "Invalid sources", "source_breakdown": {}}
    result = {
        "status": "ok", "query": query, "search_method": "unified", "sources_used": sources,
        "source_breakdown": {}, "vector_results": [], "api_graph_context": None,
        "game_code_context": None, "merged_answer": "",
    }

    async def retrieve(source):
        try:
            if source == "vector":
                items, total = await asyncio.wait_for(asyncio.to_thread(
                    _search_vector, query, max(1, min(10, vector_results)), "all", include_full_content
                ), config.rag_timeout)
                result["vector_results"] = items
                return {"status": "ok" if items else "empty", "result_count": len(items), "total_indexed": total}
            store = _get_unified_lightrag_store() if source == "api_graph" else _get_unified_game_code_lightrag_store()
            status = store.get_status()
            if not status.get("graph_exists"):
                return {"status": "unavailable", "message": "Knowledge graph is not built"}
            mode = graph_mode if graph_mode in {"local", "global", "hybrid"} else "local"
            context = await store.aquery(query, mode=mode, only_need_context=True)
            result["api_graph_context" if source == "api_graph" else "game_code_context"] = context
            return {"status": "ok" if context else "empty", "mode": mode,
                    "graph_size_kb": status.get("graph_size_kb", 0), "doc_count": status.get("doc_count", 0)}
        except asyncio.TimeoutError:
            return {"status": "timeout", "message": f"Retrieval exceeded {config.rag_timeout}s"}
        except (ImportError, FileNotFoundError, ConnectionError) as exc:
            return {"status": "unavailable", "message": str(exc)}
        except Exception as exc:
            logger.warning("Knowledge source %s failed: %s", source, exc)
            return {"status": "error", "message": str(exc)}

    statuses = await asyncio.gather(*(retrieve(source) for source in sources))
    result["source_breakdown"] = dict(zip(sources, statuses))
    good = sum(item["status"] in {"ok", "empty"} for item in statuses)
    result["status"] = "error" if good == 0 else "partial" if good < len(sources) else "ok"
    parts = []
    for item in result["vector_results"]:
        parts.append(f"[vector:{item['id']}]\n{item.get('content', item['content_preview'])}")
    for key in ("api_graph_context", "game_code_context"):
        if result[key]:
            parts.append(f"[{key}]\n{result[key]}")
    result["merged_answer"] = "\n\n".join(parts) or "No results found from enabled sources."
    return result

def run_knowledge_unified_search(*args, **kwargs):
    """CLI entry point; async services use arun_knowledge_unified_search."""
    return asyncio.run(arun_knowledge_unified_search(*args, **kwargs))

def _load_knowledge_catalog() -> Dict[str, Any]:
    """加载知识库模块清单"""
    catalog_path = _DATA_DIR / "knowledge_catalog.json"
    if catalog_path.exists():
        try:
            with open(catalog_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load knowledge catalog: {e}")
    return {"version": "0.0.0", "modules": {}}

def _get_installed_ext_modules() -> List[Dict[str, Any]]:
    """扫描 ext_kb/ 目录，返回已安装的扩展模块列表"""
    modules = []
    if not _EXT_KB_DIR.exists():
        return modules
    for item in _EXT_KB_DIR.iterdir():
        if item.is_dir() and not item.name.startswith('.') and not item.name.startswith('_'):
            manifest_path = item / "manifest.json"
            manifest = {}
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'r', encoding='utf-8') as f:
                        manifest = json.load(f)
                except Exception:
                    pass
            modules.append({
                "id": item.name,
                "path": str(item),
                "name": manifest.get("name", item.name),
                "version": manifest.get("version", "unknown"),
                "description": manifest.get("description", ""),
            })
    return modules

def register_rag_tools(mcp) -> None:
    @mcp.tool(tags={"group:rag"})
    async def knowledge_search(query: str, n_results: int = 5, search_type: str = "all",
                               include_full_content: bool = False) -> str:
        """Search Unity API vectors. Set include_full_content to read complete selected documents."""
        try:
            items, total = await asyncio.wait_for(asyncio.to_thread(
                _search_vector, query, n_results, search_type, include_full_content), config.rag_timeout)
            return json.dumps({"status": "ok" if items else "empty", "query": query,
                               "total_indexed": total, "results_count": len(items), "results": items}, ensure_ascii=False)
        except asyncio.TimeoutError:
            return json.dumps({"status": "timeout", "error": "Vector retrieval timed out", "query": query})
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc), "query": query})

    @mcp.tool(tags={"group:rag"})
    async def knowledge_unified_search(query: str, sources: list = None, vector_results: int = 3,
                                       graph_mode: str = "local", include_graph_context: bool | None = None,
                                       include_full_content: bool = False) -> str:
        """Fast vector retrieval by default. Use sources=['api_graph', 'game_code_graph'] for graph relationships."""
        return json.dumps(await arun_knowledge_unified_search(query, sources, vector_results, graph_mode,
                          include_graph_context, include_full_content), ensure_ascii=False)

    async def graph_search(query, mode, only_need_context, game=False):
        source = "game_code_graph" if game else "api_graph"
        store = _get_unified_game_code_lightrag_store() if game else _get_unified_lightrag_store()
        try:
            status = store.get_status()
            if not status.get("graph_exists"):
                return {"status": "unavailable", "query": query, "error": "Knowledge graph is not built",
                        "source_breakdown": {source: {"status": "unavailable"}}}
            text = await store.aquery(query, mode=mode if mode in {"local", "global", "hybrid", "naive"} else "hybrid",
                                      only_need_context=only_need_context)
            return {"status": "ok" if text else "empty", "query": query, "mode": mode,
                    "result": text, "graph_status": status,
                    "source_breakdown": {source: {"status": "ok" if text else "empty"}}}
        except asyncio.TimeoutError:
            return {"status": "timeout", "query": query, "error": "Graph retrieval timed out",
                    "source_breakdown": {source: {"status": "timeout"}}}
        except (ImportError, FileNotFoundError, ConnectionError) as exc:
            return {"status": "unavailable", "query": query, "error": str(exc),
                    "source_breakdown": {source: {"status": "unavailable", "message": str(exc)}}}
        except Exception as exc:
            return {"status": "error", "query": query, "error": str(exc),
                    "source_breakdown": {source: {"status": "error", "message": str(exc)}}}

    @mcp.tool(tags={"group:rag"})
    async def knowledge_graph_search(query: str, mode: str = "hybrid", only_need_context: bool = False) -> str:
        """Explicit Unity API graph search; only_need_context skips answer generation."""
        return json.dumps(await graph_search(query, mode, only_need_context), ensure_ascii=False)

    @mcp.tool(tags={"group:rag"})
    async def knowledge_graph_search_game_code(query: str, mode: str = "hybrid", only_need_context: bool = True) -> str:
        """Explicit game code graph search."""
        return json.dumps(await graph_search(query, mode, only_need_context, game=True), ensure_ascii=False)

    @mcp.tool(
        name="knowledge_index",
        description="""Index Unity API documentation into the RAG knowledge base.

This tool indexes PDF documents or JSON files into the ChromaDB vector store
for semantic search. Use this after converting new PDFs to JSON.

Supports:
- Indexing from a directory of JSON files
- Re-indexing specific documents
- Checking index status""",
        tags={"group:rag"},
    )
    def knowledge_index(
        action: str = "status",
        json_dir: str = "",
        collection_name: str = "unity_api_v3",
    ) -> str:
        """
        Manage the RAG knowledge base index.

        Args:
            action: Action to perform:
                - "status": Get current index status
                - "index": Index JSON files from a directory
                - "rebuild": Delete and rebuild the entire index
            json_dir: Directory containing JSON files (required for "index" action)
            collection_name: ChromaDB collection name (default: unity_api_v3)
        """
        try:
            vs = get_vector_store(collection_name, _UNIFIED_CHROMA_DIR)

            if action == "status":
                count = vs.get_count()
                status = "ready" if count > 0 else "empty"
                return json.dumps({
                    "status": status,
                    "collection": collection_name,
                    "document_count": count,
                    "persist_directory": _UNIFIED_CHROMA_DIR,
                }, ensure_ascii=False, indent=2)

            elif action == "index":
                if not json_dir:
                    return json.dumps({"error": "json_dir is required for index action"}, ensure_ascii=False)

                from services.rag.pdf_parser import api_data_to_text
                from services.rag.embedding_manager import get_embedding_manager

                json_path = Path(json_dir)
                if not json_path.exists():
                    return json.dumps({"error": f"Directory not found: {json_dir}"}, ensure_ascii=False)

                json_files = list(json_path.rglob("*.json"))
                if not json_files:
                    return json.dumps({"error": f"No JSON files found in {json_dir}"}, ensure_ascii=False)

                embedding_mgr = get_embedding_manager()
                indexed = 0
                errors = 0

                for json_file in json_files:
                    try:
                        with open(json_file, 'r', encoding='utf-8') as f:
                            api_data = json.load(f)

                        text = api_data_to_text(api_data)
                        if not text.strip():
                            continue

                        api_type = api_data.get('type', 'class')
                        doc_id = api_data.get('full_name', api_data.get('class_name', json_file.stem))

                        metadata = {
                            'type': api_type,
                            'class_name': api_data.get('class_name', ''),
                        }
                        if api_type == 'method':
                            metadata['method_name'] = api_data.get('method_name', '')
                            metadata['full_name'] = api_data.get('full_name', '')

                        embedding = embedding_mgr.encode([text])
                        vs.add_documents_with_embeddings(
                            documents=[text],
                            embeddings=embedding.tolist(),
                            metadatas=[metadata],
                            ids=[doc_id],
                        )
                        indexed += 1
                    except Exception as e:
                        errors += 1
                        logger.error(f"Index error for {json_file}: {e}")

                return json.dumps({
                    "action": "index",
                    "indexed": indexed,
                    "errors": errors,
                    "total_documents": vs.get_count(),
                }, ensure_ascii=False, indent=2)

            elif action == "rebuild":
                vs.delete_collection()
                return json.dumps({
                    "action": "rebuild",
                    "status": "collection_deleted",
                    "message": "Collection deleted. Run 'index' action to rebuild.",
                }, ensure_ascii=False, indent=2)

            else:
                return json.dumps({"error": f"Unknown action: {action}"}, ensure_ascii=False)

        except Exception as e:
            logger.error(f"knowledge_index error: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)

    @mcp.tool(tags={"group:rag"})
    def knowledge_modules() -> str:
        """List knowledge base modules and status."""
        try:
            catalog = _load_knowledge_catalog()
            ext_mods = _get_installed_ext_modules()

            result = {
                "catalog_version": catalog.get("version", "unknown"),
                "rag_model": config.rag_model,
                "rag_timeout_seconds": config.rag_timeout,
                "embedding_model": "BAAI/bge-m3",
                "last_updated": catalog.get("last_updated", "unknown"),
                "installed_modules": [],
                "available_modules": [],
            }

            # 内置基础模块
            catalog_modules = catalog.get("modules", {})
            base_path = _BASE_KB_DIR
            for mod_id, mod_info in catalog_modules.items():
                module_entry = {
                    "id": mod_id,
                    "name": mod_info.get("name", mod_id),
                    "version": mod_info.get("version"),
                    "description": mod_info.get("description", ""),
                    "builtin": mod_info.get("builtin", False),
                    "required": mod_info.get("required", False),
                    "installed": mod_info.get("builtin", False),
                }

                if mod_info.get("builtin"):
                    # 检查基础模块是否真的存在
                    if base_path.exists():
                        module_entry["size_mb"] = mod_info.get("size_mb", 0)
                        module_entry["status"] = "active"
                    else:
                        module_entry["status"] = "missing"
                        module_entry["installed"] = False
                    result["installed_modules"].append(module_entry)
                else:
                    # 检查扩展模块是否已安装
                    ext_match = [m for m in ext_mods if m["id"] == mod_id]
                    if ext_match:
                        module_entry.update(ext_match[0])
                        module_entry["installed"] = True
                        module_entry["status"] = "active"
                        result["installed_modules"].append(module_entry)
                    else:
                        module_entry["installed"] = False
                        module_entry["status"] = "not_installed"
                        module_entry["estimated_size_mb"] = mod_info.get("estimated_size_mb")
                        result["available_modules"].append(module_entry)

            # 检查 ext_kb/ 中是否有不在 catalog 中的模块
            catalog_ids = set(catalog_modules.keys())
            for ext_mod in ext_mods:
                if ext_mod["id"] not in catalog_ids:
                    result["installed_modules"].append({
                        "id": ext_mod["id"],
                        "name": ext_mod["name"],
                        "version": ext_mod["version"],
                        "description": ext_mod.get("description", ""),
                        "installed": True,
                        "status": "active_uncataloged",
                    })

            result["total_installed"] = len(result["installed_modules"])
            result["total_available"] = len(result["available_modules"])

            try:
                from services.tools.game_code_tools import get_game_code_module_status

                result["game_source_code"] = get_game_code_module_status()
            except Exception as game_exc:
                result["game_source_code"] = {
                    "id": "game_source_code",
                    "status": "error",
                    "error": str(game_exc),
                }

            # ── 游戏源码 LightRAG 图谱状态 ──────────────────────────
            try:
                from services.rag.lightrag_store import (
                    get_game_code_lightrag_store,
                    GAME_CODE_DEFAULT_WORKING_DIR,
                )
                gc_store = get_game_code_lightrag_store(
                    working_dir=GAME_CODE_DEFAULT_WORKING_DIR
                )
                gc_status = gc_store.get_status()

                result["game_code_lightrag"] = {
                    "id": "game_code_lightrag",
                    "name": "游戏源码 LightRAG 知识图谱",
                    "description": "跨游戏项目代码关系推理图谱",
                    "status": "active" if gc_status.get("graph_exists") else "not_built",
                    "working_dir": GAME_CODE_DEFAULT_WORKING_DIR,
                    "graph_exists": gc_status.get("graph_exists", False),
                    "graph_size_kb": gc_status.get("graph_size_kb", 0) if gc_status.get("graph_exists") else 0,
                    "doc_count": gc_status.get("doc_count", 0),
                    "llm_model": gc_status.get("llm_model", ""),
                }
            except Exception as gc_exc:
                result["game_code_lightrag"] = {
                    "id": "game_code_lightrag",
                    "status": "error",
                    "error": str(gc_exc),
                }

            return json.dumps(result, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.error(f"knowledge_modules error: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
