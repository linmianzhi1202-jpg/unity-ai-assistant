"""Local sentence-transformer embedding management."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List

import numpy as np


DEFAULT_MODEL_NAME = "BAAI/bge-m3"


def _cached_model_path(model_name: str) -> Path | None:
    if Path(model_name).is_dir():
        return Path(model_name).resolve()
    cache_name = "models--" + model_name.replace("/", "--")
    snapshots = Path.home() / ".cache" / "huggingface" / "hub" / cache_name / "snapshots"
    if not snapshots.is_dir():
        return None
    candidates = sorted(
        (
            path
            for path in snapshots.iterdir()
            if path.is_dir()
            and (path / "config.json").is_file()
            and (path / "modules.json").is_file()
            and any(
                candidate.is_file()
                for pattern in ("*.safetensors", "pytorch_model*.bin")
                for candidate in path.glob(pattern)
            )
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


class EmbeddingManager:
    """Load one cached embedding model and expose normalized encodings."""

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        trust_remote_code: bool = False,
    ) -> None:
        self.model_name = model_name
        self.trust_remote_code = trust_remote_code
        self.model = None
        self._load_model()

    def _load_model(self) -> None:
        from sentence_transformers import SentenceTransformer

        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        os.environ.setdefault("TRANSFORMERS_NO_ADVISORY_WARNINGS", "1")
        cached = _cached_model_path(self.model_name)
        source = str(cached) if cached else self.model_name
        try:
            self.model = SentenceTransformer(
                source,
                trust_remote_code=self.trust_remote_code,
                local_files_only=cached is not None,
            )
        except TypeError:
            self.model = SentenceTransformer(
                source,
                trust_remote_code=self.trust_remote_code,
            )

    def encode(
        self,
        texts: List[str],
        batch_size: int = 32,
        show_progress_bar: bool = True,
    ) -> np.ndarray:
        if self.model is None:
            raise RuntimeError(f"Embedding model is unavailable: {self.model_name}")
        return np.asarray(
            self.model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=show_progress_bar,
                normalize_embeddings=True,
            ),
            dtype=np.float32,
        )

    def encode_query(self, query: str) -> np.ndarray:
        return self.encode([query], show_progress_bar=False)[0]

    def similarity(
        self,
        query_vector: np.ndarray,
        doc_vectors: np.ndarray,
    ) -> np.ndarray:
        query_norm = query_vector / max(float(np.linalg.norm(query_vector)), 1e-12)
        doc_norms = doc_vectors / np.maximum(
            np.linalg.norm(doc_vectors, axis=1, keepdims=True),
            1e-12,
        )
        return np.dot(doc_norms, query_norm)


_embedding_manager: EmbeddingManager | None = None
_embedding_lock = threading.Lock()


def get_embedding_manager() -> EmbeddingManager:
    global _embedding_manager
    with _embedding_lock:
        if _embedding_manager is None:
            _embedding_manager = EmbeddingManager()
    return _embedding_manager
