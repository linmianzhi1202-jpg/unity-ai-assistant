"""RAG 知识库服务模块"""

# 核心运行时模块（必需，无条件导入）
from .embedding_manager import EmbeddingManager, get_embedding_manager
from .vector_store import VectorStore, get_vector_store
from .lightrag_store import LightRAGStore, get_lightrag_store

# PDF 解析器（知识库构建工具，运行时非必需，使用 lazy import）
try:
    from .pdf_parser import UnityAPIParser, find_all_pdfs, batch_convert, convert_pdf_to_json, api_data_to_text
    _has_pdf_parser = True
except ImportError:
    _has_pdf_parser = False
    UnityAPIParser = None  # type: ignore
    find_all_pdfs = None   # type: ignore
    batch_convert = None   # type: ignore
    convert_pdf_to_json = None  # type: ignore
    api_data_to_text = None  # type: ignore

__all__ = [
    'EmbeddingManager', 'get_embedding_manager',
    'VectorStore', 'get_vector_store',
    'LightRAGStore', 'get_lightrag_store',
]

if _has_pdf_parser:
    __all__.extend([
        'UnityAPIParser', 'find_all_pdfs', 'batch_convert',
        'convert_pdf_to_json', 'api_data_to_text',
    ])
