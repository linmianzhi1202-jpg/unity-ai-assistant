"""Game source code search module for the product MCP server.

This module is packaged under Server/data/game-rag-knowledge-base and no longer
relies on the old development-only rag-knowledge-base directory. It keeps the
public GameCodeSearcher/get_searcher API used by game_code_tools.py.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_SERVER_SRC = Path(__file__).resolve().parents[3] / "src"
_GAME_RAG_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVER_SRC) not in sys.path:
    sys.path.insert(0, str(_SERVER_SRC))

try:
    from services.rag.embedding_manager import EmbeddingManager
    from services.rag.lexical_index import SQLiteLexicalIndex, query_terms
    from services.rag.reranker import rerank
    _modules_loaded = True
except ImportError as exc:
    EmbeddingManager = None
    SQLiteLexicalIndex = None
    query_terms = None
    rerank = None
    _modules_loaded = False
    logger.warning("Game RAG embedding module unavailable: %s", exc)


def _resolve_config_paths(config: Optional[dict]) -> dict:
    """Resolve game-RAG paths relative to this packaged knowledge-base root."""
    resolved = dict(config or {})
    for section, key in (("vector_store", "persist_directory"), ("graph", "file_path"), ("retrieval", "lexical_index_path")):
        values = dict(resolved.get(section) or {})
        value = values.get(key)
        if value:
            path = Path(value)
            values[key] = str(path if path.is_absolute() else (_GAME_RAG_ROOT / path).resolve())
        resolved[section] = values
    return resolved


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
    dense_score: float = 0.0
    lexical_score: float = 0.0
    rrf_score: float = 0.0
    search_mode: str = "dense"
    rerank_score: float | None = None


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
        self.hybrid_enabled = bool(retrieval_config.get("hybrid_enabled", True))
        self.candidate_multiplier = max(2, int(retrieval_config.get("candidate_multiplier", 4) or 4))
        self.rrf_k = max(1, int(retrieval_config.get("rrf_k", 60) or 60))
        self.dense_weight = float(retrieval_config.get("dense_weight", 0.55) or 0.55)
        self.lexical_weight = float(retrieval_config.get("lexical_weight", 0.30) or 0.30)
        self.rrf_weight = float(retrieval_config.get("rrf_weight", 0.15) or 0.15)
        self.rerank_enabled = bool((retrieval_config.get("rerank", {}) or {}).get("enabled", False))
        self.rerank_model = (retrieval_config.get("rerank", {}) or {}).get("model_name")
        self.rerank_candidate_k = max(2, int((retrieval_config.get("rerank", {}) or {}).get("candidate_k", 30) or 30))
        self.lexical_index_path = retrieval_config.get("lexical_index_path") or str(
            Path(self.persist_directory).parent / "game_code_lexical.sqlite3"
        )
        self.client = None
        self.collection = None
        self.lexical_index = None
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
        if SQLiteLexicalIndex is not None:
            try:
                self.lexical_index = SQLiteLexicalIndex(self.lexical_index_path)
                if self.lexical_index.count() != self.collection.count():
                    logger.info(
                        "Rebuilding stale game lexical index (%s/%s).",
                        self.lexical_index.count(), self.collection.count(),
                    )
                    raw = self.collection.get(include=["documents", "metadatas"])
                    self.lexical_index.replace_all({
                        "id": item_id,
                        "document": (raw.get("documents") or [])[i] if i < len(raw.get("documents") or []) else "",
                        "metadata": (raw.get("metadatas") or [])[i] if i < len(raw.get("metadatas") or []) else {},
                    } for i, item_id in enumerate(raw.get("ids") or []))
            except Exception as exc:
                logger.warning("Game lexical index unavailable; using dense retrieval: %s", exc)
                self.lexical_index = None

    def count(self) -> int:
        return self.collection.count() if self.collection is not None else 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            "collection_name": self.collection_name,
            "document_count": self.count(),
            "persist_directory": self.persist_directory,
            "lexical_index_path": self.lexical_index_path,
            "lexical_index_count": self.lexical_index.count() if self.lexical_index else 0,
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
            # Chroma cosine distance is 1 - cosine similarity. Keep the
            # similarity scale and clamp negative similarity for relevance use.
            return round(max(0.0, min(1.0, 1.0 - float(distance))), 4)
        except Exception:
            return 0.0

    def search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        apply_threshold: bool = True,
    ) -> List[SearchResult]:
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
        if not apply_threshold or not self.score_threshold:
            return results

        filtered = [item for item in results if item.score >= self.score_threshold]
        return filtered or results

    @staticmethod
    def _lexical_terms(query: str) -> List[str]:
        if query_terms is not None:
            return query_terms(query)
        return [term for term in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", (query or "").lower()) if term]

    @classmethod
    def _lexical_score(cls, text: str, metadata: Dict[str, Any], terms: List[str]) -> float:
        # Kept as a compatibility fallback for indexes created before FTS5.
        if not terms:
            return 0.0
        metadata = metadata or {}
        haystack = " ".join(str(metadata.get(key, "")) for key in
                              ("class_name", "method_name", "namespace", "full_name"))
        haystack += " " + str(text or "")
        lowered = haystack.lower()
        matched = sum(1 for term in terms if term.lower() in lowered)
        return round(matched / len(terms), 4)

    def lexical_search(
        self,
        query: str,
        top_k: int = 20,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Search the SQLite FTS5 inverted index with BM25 ranking."""
        if self.count() <= 0 or not self._lexical_terms(query):
            return []
        if self.lexical_index is None:
            logger.warning("SQLite lexical index is unavailable; lexical search skipped")
            return []
        try:
            rows = self.lexical_index.search(query, limit=max(1, int(top_k or 20)), filters=filters)
        except Exception as exc:
            logger.warning("FTS5 lexical search failed: %s", exc)
            return []
        return [SearchResult(
            id=row["id"], text=row.get("document", ""), metadata=row.get("metadata") or {},
            score=float(row.get("score", 0.0)), lexical_score=float(row.get("score", 0.0)),
            search_mode="lexical",
        ) for row in rows]

    def _maybe_rerank(self, query: str, results: List[SearchResult]) -> List[SearchResult]:
        if rerank is None or not self.rerank_enabled or len(results) < 2:
            return results
        raw_items = [{"_result": item, "text": item.text} for item in results[:self.rerank_candidate_k]]
        ranked = rerank(
            query, raw_items, enabled=True, model_name=self.rerank_model,
            candidate_k=self.rerank_candidate_k, text_getter=lambda item: item["text"],
        )
        output = [item["_result"] for item in ranked]
        for raw_item in ranked:
            raw_item["_result"].rerank_score = raw_item.get("rerank_score")
        return output

    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        """Fuse broad dense and lexical candidates with reciprocal rank fusion."""
        final_k = max(1, int(top_k or 5))
        if not self.hybrid_enabled:
            return self.search(query, final_k, filters=filters)

        candidate_k = min(self.count(), max(final_k * self.candidate_multiplier, final_k))
        dense = self.search(query, candidate_k, filters=filters, apply_threshold=False)
        lexical = self.lexical_search(query, candidate_k, filters=filters)
        if not lexical:
            candidates = self._maybe_rerank(query, dense)[:final_k]
            if self.score_threshold:
                filtered = [item for item in candidates if item.score >= self.score_threshold]
                return filtered or candidates
            return candidates
        if not dense:
            candidates = self._maybe_rerank(query, lexical)[:final_k]
            if self.score_threshold:
                filtered = [item for item in candidates if item.score >= self.score_threshold]
                return filtered or candidates
            return candidates

        dense_by_id = {item.id: item for item in dense}
        lexical_by_id = {item.id: item for item in lexical}
        dense_rank = {item.id: rank for rank, item in enumerate(dense, 1)}
        lexical_rank = {item.id: rank for rank, item in enumerate(lexical, 1)}
        max_rrf = 2.0 / (self.rrf_k + 1.0)
        merged: List[SearchResult] = []
        all_ids = list(dict.fromkeys([item.id for item in dense] + [item.id for item in lexical]))
        for item_id in all_ids:
            dense_item = dense_by_id.get(item_id)
            lexical_item = lexical_by_id.get(item_id)
            rrf = 0.0
            if item_id in dense_rank:
                rrf += 1.0 / (self.rrf_k + dense_rank[item_id])
            if item_id in lexical_rank:
                rrf += 1.0 / (self.rrf_k + lexical_rank[item_id])
            rrf_score = min(1.0, rrf / max_rrf)
            dense_score = dense_item.score if dense_item else 0.0
            lexical_score = lexical_item.lexical_score if lexical_item else 0.0
            source = dense_item or lexical_item
            combined = (
                self.dense_weight * dense_score
                + self.lexical_weight * lexical_score
                + self.rrf_weight * rrf_score
            )
            merged.append(SearchResult(
                id=item_id,
                text=source.text,
                metadata=source.metadata,
                score=round(min(1.0, combined), 4),
                dense_score=round(dense_score, 4),
                lexical_score=round(lexical_score, 4),
                rrf_score=round(rrf_score, 4),
                search_mode="hybrid",
            ))
        merged.sort(key=lambda item: item.score, reverse=True)
        merged = self._maybe_rerank(query, merged)
        merged = merged[:final_k]
        if self.score_threshold:
            filtered = [item for item in merged if item.score >= self.score_threshold]
            return filtered or merged
        return merged

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
        results = self.hybrid_search(query=query, top_k=top_k)
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
        self.config = _resolve_config_paths(config)
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
            results = self.retriever.hybrid_search(
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
                    "dense_score": item.dense_score,
                    "lexical_score": item.lexical_score,
                    "rrf_score": item.rrf_score,
                    "search_mode": item.search_mode,
                    "rerank_score": item.rerank_score,
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
