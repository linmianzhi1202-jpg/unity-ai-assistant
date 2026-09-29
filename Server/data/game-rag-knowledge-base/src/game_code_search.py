"""Game source code search module for the product MCP server.

This module is packaged under Server/data/game-rag-knowledge-base and no longer
relies on the old development-only rag-knowledge-base directory. It keeps the
public GameCodeSearcher/get_searcher API used by game_code_tools.py.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

_SERVER_SRC = Path(__file__).resolve().parents[3] / "src"
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

try:
    from services.rag.embedding_manager import EmbeddingManager
    _modules_loaded = True
except ImportError as exc:
    EmbeddingManager = None
    _modules_loaded = False
    print(f"?????????? RAG embedding ??: {exc}")

logger = logging.getLogger(__name__)

try:
    from code_graph_extractor import GameCodeGraph, load_graph as _load_game_graph
    _graph_module = True
except ImportError:
    GameCodeGraph = None
    _load_game_graph = None
    _graph_module = False


@dataclass
class SearchResult:
    id: str
    text: str
    metadata: Dict[str, Any]
    score: float


class GameCodeRetriever:
    """Lightweight Chroma retriever for the packaged game code knowledge base."""

    def __init__(self, config: dict, embedding_manager_factory):
        self.config = config or {}
        self.embedding_manager_factory = embedding_manager_factory
        self._embedding_manager = None
        vector_config = self.config.get("vector_store", {}) or {}
        retrieval_config = self.config.get("retrieval", {}) or {}
        self.collection_name = vector_config.get("collection_name", "game_source_code")
        self.persist_directory = vector_config.get("persist_directory", "")
        self.score_threshold = float(retrieval_config.get("score_threshold", 0.0) or 0.0)
        self.client = None
        self.collection = None
        self._initialize()

    @property
    def embedding_manager(self):
        if self._embedding_manager is None:
            self._embedding_manager = self.embedding_manager_factory()
        return self._embedding_manager

    def _initialize(self) -> None:
        if not self.persist_directory or not os.path.isdir(self.persist_directory):
            raise FileNotFoundError(f"ChromaDB directory not found: {self.persist_directory}")
        import chromadb

        self.client = chromadb.PersistentClient(path=self.persist_directory)
        try:
            self.collection = self.client.get_collection(name=self.collection_name)
        except Exception as exc:
            raise RuntimeError(
                f"Chroma collection '{self.collection_name}' not found in "
                f"{self.persist_directory}. Run build_game_rag.py to build the game code index."
            ) from exc

    def count(self) -> int:
        return self.collection.count() if self.collection is not None else 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "document_count": self.count(),
            "persist_directory": self.persist_directory,
        }

    def _build_where(self, filters: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not filters:
            return None
        clean = [{key: value} for key, value in filters.items() if value not in (None, "")]
        if not clean:
            return None
        if len(clean) == 1:
            return clean[0]
        return {"$and": clean}

    @staticmethod
    def _distance_to_score(distance: Any) -> float:
        if distance is None:
            return 0.0
        try:
            return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)
        except Exception:
            return 0.0

    def search(self, query: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        count = self.count()
        if count <= 0:
            return []

        query_embedding = self.embedding_manager.encode_query(query)
        query_top_k = min(max(1, int(top_k or 5)), count)
        kwargs = {
            "query_embeddings": [query_embedding.tolist()],
            "n_results": query_top_k,
        }
        where = self._build_where(filters)
        if where:
            kwargs["where"] = where

        try:
            raw = self.collection.query(**kwargs)
        except Exception as exc:
            if where:
                logger.warning(f"Filtered game code search failed, retrying without filters: {exc}")
                kwargs.pop("where", None)
                raw = self.collection.query(**kwargs)
            else:
                raise

        results = self._format_results(raw)
        if not self.score_threshold:
            return results

        filtered = [item for item in results if item.score >= self.score_threshold]
        return filtered or results

    def _format_results(self, raw: Dict[str, Any]) -> List[SearchResult]:
        output: List[SearchResult] = []
        ids = raw.get("ids", [[]])[0] if raw else []
        documents = raw.get("documents", [[]])[0] if raw else []
        metadatas = raw.get("metadatas", [[]])[0] if raw else []
        distances = raw.get("distances", [[]])[0] if raw else []
        for index, item_id in enumerate(ids):
            output.append(SearchResult(
                id=item_id,
                text=documents[index] if index < len(documents) else "",
                metadata=metadatas[index] if index < len(metadatas) and metadatas[index] else {},
                score=self._distance_to_score(distances[index] if index < len(distances) else None),
            ))
        return output

    def get_context(self, query: str, max_tokens: int = 3000) -> str:
        top_k = self.config.get("retrieval", {}).get("top_k", 5)
        results = self.search(query=query, top_k=top_k)
        parts: List[str] = []
        current_length = 0
        for result in results:
            meta = result.metadata or {}
            header = f"[{meta.get('game_name', 'unknown')}::{meta.get('class_name', '')}.{meta.get('method_name', '')}]"
            chunk = f"{header}\n{result.text}\n"
            if current_length + len(chunk) > max_tokens:
                break
            parts.append(chunk)
            current_length += len(chunk)
        return "\n".join(parts)


class GameCodeSearcher:
    """Searches the packaged reference game source code KB."""

    # Default code types returned by search (excludes asset types: scene, material, asset, packages)
    CODE_TYPES = ["class_overview", "struct_overview", "enum_overview", "method_detail", "full_file"]

    DEFAULT_EMBEDDING_CONFIG = {
        "provider": "local",
        "local": {
            "model_name": "BAAI/bge-small-zh-v1.5",
            "device": "cpu",
        },
    }

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self._embedding_manager = None
        self._retriever: Optional[GameCodeRetriever] = None
        self._retriever_error: str | None = None
        self._graph = None
        self._initialized = False
        self._load_graph()

    def _load_graph(self) -> None:
        if not _graph_module:
            logger.debug("Graph module not available; skipping graph load.")
            return

        graph_path = self.config.get("graph", {}).get("file_path", "")
        if not graph_path:
            persist_dir = self.config.get("vector_store", {}).get("persist_directory", "")
            if persist_dir:
                graph_path = os.path.join(os.path.dirname(persist_dir), "game_code_graph.json")

        if graph_path and os.path.exists(graph_path):
            try:
                self._graph = _load_game_graph(graph_path)
                logger.info(f"Loaded game code graph: {self._graph.stats.get('entity_count', 0)} entities")
            except Exception as exc:
                logger.warning(f"Failed to load game code graph: {exc}")
        else:
            logger.debug(f"Game code graph not found: {graph_path}")

    def _get_embedding_model_name(self) -> str:
        embedding_config = self.config.get("embedding", {}) or {}
        local_config = embedding_config.get("local", {}) or {}
        return local_config.get("model_name") or self.DEFAULT_EMBEDDING_CONFIG["local"]["model_name"]

    def _get_embedding_trust_remote_code(self) -> bool:
        embedding_config = self.config.get("embedding", {}) or {}
        local_config = embedding_config.get("local", {}) or {}
        return bool(local_config.get("trust_remote_code", False))

    @property
    def embedding_manager(self):
        if self._embedding_manager is None and _modules_loaded:
            self._embedding_manager = EmbeddingManager(
                model_name=self._get_embedding_model_name(),
                trust_remote_code=self._get_embedding_trust_remote_code(),
            )
        return self._embedding_manager

    @property
    def retriever(self) -> Optional[GameCodeRetriever]:
        if self._retriever_error:
            return None
        if self._retriever is None and _modules_loaded:
            try:
                self._retriever = GameCodeRetriever(
                    self.config,
                    embedding_manager_factory=lambda: self.embedding_manager,
                )
                self._initialized = True
            except Exception as exc:
                self._retriever_error = str(exc)
                logger.error(f"Failed to initialize game code retriever: {exc}")
                self._retriever = None
        return self._retriever

    def search(
        self,
        query: str,
        top_k: int = 5,
        game_name: str = None,
        class_name: str = None,
        code_type: str = None,
        include_assets: bool = False,
    ) -> List[Dict[str, Any]]:
        if not self.retriever:
            return [{"error": "Game code retriever is not initialized.", "action": "cd Server/data/game-rag-knowledge-base && python build_game_rag.py --stats  # Check status first; if empty, run: python build_game_rag.py"}]

        filters: Dict[str, Any] = {}
        if game_name:
            filters["game_name"] = game_name
        if class_name:
            filters["class_name"] = class_name
        if code_type:
            filters["code_type"] = code_type
        elif not include_assets:
            filters["code_type"] = {"$in": self.CODE_TYPES}

        try:
            results = self.retriever.search(
                query=query,
                top_k=top_k,
                filters=filters if filters else None,
            )
            output = [
                {
                    "id": item.id,
                    "text": item.text,
                    "metadata": item.metadata,
                    "score": item.score,
                }
                for item in results
            ]
            logger.info(f"Game code search '{query[:50]}...' returned {len(output)} results")
            return output
        except Exception as exc:
            logger.error(f"Game code search failed: {exc}")
            return [{"error": str(exc)}]

    def get_context(self, query: str, max_tokens: int = 3000) -> str:
        if not self.retriever:
            return ""
        try:
            return self.retriever.get_context(query, max_tokens)
        except Exception as exc:
            logger.error(f"Failed to get game code context: {exc}")
            return ""

    def get_stats(self) -> Dict[str, Any]:
        stats: Dict[str, Any] = {}
        if self.retriever:
            try:
                retriever_stats = self.retriever.get_stats()
                stats.update({
                    "status": "ready",
                    "collection_name": retriever_stats.get("collection_name", ""),
                    "document_count": retriever_stats.get("document_count", 0),
                    "persist_directory": retriever_stats.get("persist_directory", ""),
                })
            except Exception as exc:
                stats.update({"status": "error", "error": str(exc)})
        else:
            stats.update({
                "status": "not_initialized",
                "hint": self._retriever_error or "Run: cd Server/data/game-rag-knowledge-base && python build_game_rag.py",
                "collection_name": self.config.get("vector_store", {}).get("collection_name", "unknown"),
            })

        if self._graph:
            stats["graph"] = {
                "loaded": True,
                "entity_count": self._graph.stats.get("entity_count", 0),
                "relation_count": self._graph.stats.get("relation_count", 0),
            }
        else:
            stats["graph"] = {"loaded": False, "hint": "Graph is not loaded. Run build_game_rag.py first."}
        return stats

    def search_graph(
        self,
        query: str,
        top_k: int = 5,
        game_name: str = None,
        class_name: str = None,
        traverse_depth: int = 1,
        include_assets: bool = False,
    ) -> Dict[str, Any]:
        result = {
            "vector_results": [],
            "graph_results": [],
            "call_chain": [],
        }

        vector_results = self.search(query=query, top_k=top_k, game_name=game_name, class_name=class_name, include_assets=include_assets)
        result["vector_results"] = vector_results

        if not self._graph:
            result["graph_results"] = [{"info": "Graph is not loaded."}]
            return result

        seen_entities: Set[str] = set()
        methods_to_traverse: List[Tuple[str, float]] = []

        for hit in vector_results:
            if hit.get("error"):
                continue
            meta = hit.get("metadata", {}) or {}
            class_name_value = meta.get("class_name", "")
            method_name = meta.get("method_name", "")
            code_type = meta.get("code_type", "")

            if class_name_value:
                class_id = f"class:{class_name_value}"
                if class_id in self._graph.nodes and class_id not in seen_entities:
                    node = self._graph.nodes[class_id]
                    result["graph_results"].append({
                        "entity": node,
                        "relations": self._graph.get_relations(class_id),
                        "neighbors": self._graph.get_neighbors(class_id) if traverse_depth > 0 else [],
                    })
                    seen_entities.add(class_id)
                    for neighbor in self._graph.get_neighbors(class_id, "class_has_method"):
                        methods_to_traverse.append((neighbor["id"], hit.get("score", 0.5)))

            if code_type == "method_detail" and method_name and class_name_value:
                method_id = f"method:{class_name_value}.{method_name}"
                if method_id in self._graph.nodes:
                    methods_to_traverse.append((method_id, hit.get("score", 0.5)))

        methods_to_traverse.sort(key=lambda item: item[1], reverse=True)
        traversed_methods: Set[str] = set()
        for method_id, _score in methods_to_traverse[:3]:
            for node in self._build_call_chain(method_id, max_depth=traverse_depth):
                if node["id"] not in traversed_methods:
                    traversed_methods.add(node["id"])
                    result["call_chain"].append(node)
        return result

    def _build_call_chain(self, start_id: str, max_depth: int = 2) -> List[dict]:
        if not self._graph:
            return []
        chain: List[dict] = []
        visited = {start_id}
        queue: List[Tuple[str, int]] = [(start_id, 0)]

        start_node = self._graph.nodes.get(start_id)
        if start_node:
            chain.append(start_node)

        while queue:
            current, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for relation in self._graph.get_relations(current, "method_calls"):
                target_id = relation["target"]
                node = self._graph.nodes.get(target_id)
                if node and target_id not in visited:
                    visited.add(target_id)
                    chain.append(node)
                    queue.append((target_id, depth + 1))
        return chain


_searcher_instance = None


def get_searcher(config: Optional[dict] = None) -> GameCodeSearcher:
    global _searcher_instance
    if _searcher_instance is None:
        _searcher_instance = GameCodeSearcher(config)
    return _searcher_instance


def reset_searcher():
    global _searcher_instance
    _searcher_instance = None
