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


class VectorStore:
    """ChromaDB 向量存储管理器"""
    
    def __init__(self, collection_name: str = "unity_api_v3", persist_directory: str = None):
        self.collection_name = collection_name
        self.persist_directory = persist_directory
        
        self.embedding_manager = None
        self.client = None
        self.collection = None
        
        self._initialize()
    
    def _initialize(self):
        import chromadb
        self.client = (chromadb.PersistentClient(path=self.persist_directory)
                       if self.persist_directory else chromadb.Client())
        self.collection = self.client.get_or_create_collection(name=self.collection_name)
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

    def search(self, query: str, n_results: int = 5, where: Dict = None) -> List[Dict[str, Any]]:
        """搜索相似文档"""
        if self.collection.count() > 0:
            query_embedding = get_embedding_manager().encode_query(query)
            
            kwargs = {
                'query_embeddings': [query_embedding.tolist()],
                'n_results': min(n_results, self.collection.count()),
            }
            if where:
                kwargs['where'] = where
            
            results = self.collection.query(**kwargs)
            
            formatted = []
            if results and 'ids' in results and len(results['ids']) > 0:
                for i in range(len(results['ids'][0])):
                    item = {
                        'id': results['ids'][0][i],
                        'document': results['documents'][0][i] if results.get('documents') else '',
                        'metadata': results['metadatas'][0][i] if results.get('metadatas') else {},
                        'distance': results['distances'][0][i] if results.get('distances') else None,
                    }
                    formatted.append(item)
            return formatted
        return []

    def get_count(self) -> int:
        return self.collection.count()

    def delete_collection(self):
        self.client.delete_collection(name=self.collection_name)
        self.collection = self.client.create_collection(name=self.collection_name)


_vector_stores: dict[tuple[str, str | None], VectorStore] = {}
_store_lock = threading.Lock()

def get_vector_store(collection_name: str = "unity_api_v3", persist_directory: str = None) -> VectorStore:
    key = (collection_name, os.path.normcase(str(Path(persist_directory).resolve())) if persist_directory else None)
    with _store_lock:
        if key not in _vector_stores:
            _vector_stores[key] = VectorStore(collection_name=key[0], persist_directory=key[1])
        return _vector_stores[key]
