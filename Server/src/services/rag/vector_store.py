"""
ChromaDB 向量存储（V3 — 持久化 + 支持外部 Embedding）
"""

import logging
import os
import threading
logger = logging.getLogger(__name__)
from pathlib import Path
from typing import List, Dict, Any, Optional

from .embedding_manager import get_embedding_manager
from .lexical_index import SQLiteLexicalIndex
from .reranker import rerank


class VectorStore:
    """ChromaDB 向量存储管理器"""
    
    def __init__(self, collection_name: str = "unity_api_v3", persist_directory: str = None):
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        
        self.embedding_manager = None
        self.client = None
        self.collection = None
        self.lexical_index = None
        self.lexical_index_path = (
            Path(self.persist_directory).parent / f"{self.collection_name}_lexical.sqlite3"
            if self.persist_directory else None
        )
        self._initialize()
    
    def _initialize(self):
        import chromadb
        self.client = (chromadb.PersistentClient(path=self.persist_directory)
                       if self.persist_directory else chromadb.Client())
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
        if self.lexical_index_path is not None:
            try:
                self.lexical_index = SQLiteLexicalIndex(self.lexical_index_path)
                if self.lexical_index.count() != self.collection.count():
                    logger.info(
                        "Rebuilding stale lexical index for %s (%s/%s).",
                        self.collection_name, self.lexical_index.count(), self.collection.count(),
                    )
                    raw = self.collection.get(include=["documents", "metadatas"])
                    self.lexical_index.replace_all({
                        "id": item_id,
                        "document": (raw.get("documents") or [])[i] if i < len(raw.get("documents") or []) else "",
                        "metadata": (raw.get("metadatas") or [])[i] if i < len(raw.get("metadatas") or []) else {},
                    } for i, item_id in enumerate(raw.get("ids") or []))
            except Exception as exc:
                logger.warning("SQLite lexical index unavailable for %s: %s", self.collection_name, exc)
        logger.info("Loaded collection %s (%s documents)", self.collection_name, self.collection.count())

    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """添加文档（自动生成 Embedding）"""
        embeddings = get_embedding_manager().encode(documents)
        self.add_documents_with_embeddings(documents, embeddings.tolist(), metadatas, ids)
    
    def add_documents_with_embeddings(
        self, 
        documents: List[str], 
        embeddings: List[List[float]], 
        metadatas: List[Dict[str, Any]], 
        ids: List[str]
    ):
        """添加文档（使用预计算的 Embedding）— 直接 upsert 避免ID冲突"""
        self.collection.upsert(embeddings=embeddings, documents=documents, metadatas=metadatas, ids=ids)
        if self.lexical_index is not None:
            try:
                self.lexical_index.upsert(
                    {"id": doc_id, "document": document, "metadata": metadata}
                    for doc_id, document, metadata in zip(ids, documents, metadatas)
                )
            except Exception as exc:
                logger.warning("Failed to update lexical index for %s: %s", self.collection_name, exc)

    @staticmethod
    def _distance_to_score(distance: Any) -> float:
        if distance is None:
            return 0.0
        try:
            # Chroma cosine distance is 1 - cosine similarity. Keep the
            # similarity scale and clamp negative similarity for relevance use.
            return max(0.0, min(1.0, 1.0 - float(distance)))
        except (TypeError, ValueError):
            return 0.0

    def search(self, query: str, n_results: int = 5, where: Dict = None) -> List[Dict[str, Any]]:
        """Hybrid retrieval: dense candidates + SQLite FTS5/BM25 + RRF."""
        total = self.collection.count()
        if total <= 0:
            return []
        final_k = max(1, int(n_results or 5))
        candidate_k = min(total, max(final_k * 4, final_k))
        query_embedding = get_embedding_manager().encode_query(query)
        kwargs = {
            "query_embeddings": [query_embedding.tolist()],
            "n_results": candidate_k,
        }
        if where:
            kwargs["where"] = where
        try:
            raw = self.collection.query(**kwargs)
        except Exception as exc:
            if not where:
                raise
            logger.warning("Filtered dense search failed, retrying without filters: %s", exc)
            kwargs.pop("where", None)
            raw = self.collection.query(**kwargs)

        dense: list[dict[str, Any]] = []
        ids = raw.get("ids", [[]])[0] if raw else []
        documents = raw.get("documents", [[]])[0] if raw else []
        metadatas = raw.get("metadatas", [[]])[0] if raw else []
        distances = raw.get("distances", [[]])[0] if raw else []
        for i, item_id in enumerate(ids):
            distance = distances[i] if i < len(distances) else None
            dense.append({
                "id": item_id,
                "document": documents[i] if i < len(documents) else "",
                "metadata": metadatas[i] if i < len(metadatas) and metadatas[i] else {},
                "distance": distance,
                "dense_score": self._distance_to_score(distance),
            })
        lexical = []
        if self.lexical_index is not None:
            try:
                lexical = self.lexical_index.search(query, limit=candidate_k, filters=where)
            except Exception as exc:
                logger.warning("FTS5 search failed for %s: %s", self.collection_name, exc)

        if not lexical:
            dense_results = [{**item, "score": round(item["dense_score"], 4), "search_mode": "dense"}
                            for item in dense]
            if os.getenv("UNITY_MCP_RERANK_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}:
                dense_results = rerank(query, dense_results, enabled=True, candidate_k=min(30, len(dense_results)))
            return dense_results[:final_k]
        dense_by_id = {item["id"]: item for item in dense}
        lexical_by_id = {item["id"]: item for item in lexical}
        dense_rank = {item["id"]: rank for rank, item in enumerate(dense, 1)}
        lexical_rank = {item["id"]: rank for rank, item in enumerate(lexical, 1)}
        rrf_k = 60.0
        max_rrf = 2.0 / (rrf_k + 1.0)
        merged = []
        for item_id in dict.fromkeys([*dense_rank, *lexical_rank]):
            d = dense_by_id.get(item_id)
            l = lexical_by_id.get(item_id)
            rrf = (1.0 / (rrf_k + dense_rank[item_id]) if d else 0.0)
            rrf += (1.0 / (rrf_k + lexical_rank[item_id]) if l else 0.0)
            rrf_score = min(1.0, rrf / max_rrf)
            source = d or l
            item = {
                "id": item_id, "document": source.get("document", ""),
                "metadata": source.get("metadata") or {},
                "distance": d.get("distance") if d else None,
                "dense_score": d.get("dense_score", 0.0) if d else 0.0,
                "lexical_score": l.get("score", 0.0) if l else 0.0,
                "rrf_score": rrf_score,
            }
            item["score"] = round(0.55 * item["dense_score"] + 0.30 * item["lexical_score"] + 0.15 * rrf_score, 4)
            item["search_mode"] = "hybrid"
            merged.append(item)
        merged.sort(key=lambda item: item["score"], reverse=True)
        if os.getenv("UNITY_MCP_RERANK_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}:
            ranked = rerank(
                query, merged, enabled=True,
                candidate_k=min(30, max(final_k * 4, final_k)),
            )
            merged = ranked
        return merged[:final_k]

    def get_count(self) -> int:
        return self.collection.count()

    def delete_collection(self):
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.create_collection(name=self.collection_name)
        if self.lexical_index is not None:
            self.lexical_index.replace_all([])


_vector_stores: dict[tuple[str, str | None], VectorStore] = {}
_store_lock = threading.Lock()

def get_vector_store(collection_name: str = "unity_api_v3", persist_directory: str = None) -> VectorStore:
    key = (collection_name, os.path.normcase(str(Path(persist_directory).resolve())) if persist_directory else None)
    with _store_lock:
        if key not in _vector_stores:
            _vector_stores[key] = VectorStore(collection_name=key[0], persist_directory=key[1])
        return _vector_stores[key]
