"""Optional second-stage reranking.

The module is deliberately lazy and dependency tolerant: the MCP server starts
without sentence-transformers/CrossEncoder, and any model loading or prediction exception
returns the original candidate order.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)
_model_lock = threading.Lock()
# CrossEncoder.predict is not guaranteed to be thread-safe across all backends.
# Serialize inference separately from model-cache access while allowing
# unrelated retrieval work to continue concurrently.
_predict_lock = threading.RLock()
_models: dict[str, Any] = {}


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def rerank(
    query: str,
    items: list[dict[str, Any]],
    *,
    text_getter: Callable[[dict[str, Any]], str] | None = None,
    enabled: bool | None = None,
    model_name: str | None = None,
    candidate_k: int = 30,
) -> list[dict[str, Any]]:
    """Rerank at most candidate_k items; preserve input on any failure."""
    if enabled is None:
        enabled = _truthy(os.getenv("UNITY_MCP_RERANK_ENABLED", "0"))
    if not enabled or len(items) < 2:
        return items
    model_name = model_name or os.getenv(
        "UNITY_MCP_RERANK_MODEL", "BAAI/bge-reranker-v2-m3"
    )
    candidates = list(items[:max(2, int(candidate_k or 30))])
    getter = text_getter or (lambda item: str(item.get("document", item.get("text", "")) or ""))
    try:
        with _model_lock:
            model = _models.get(model_name)
            if model is None:
                from sentence_transformers import CrossEncoder
                model = CrossEncoder(model_name)
                _models[model_name] = model
        pairs = [(query, getter(item)) for item in candidates]
        with _predict_lock:
            scores = model.predict(pairs, show_progress_bar=False)
        for item, score in zip(candidates, scores):
            item["rerank_score"] = round(float(score), 6)
        candidates.sort(key=lambda item: item.get("rerank_score", float("-inf")), reverse=True)
        return candidates + items[len(candidates):]
    except Exception as exc:
        logger.warning("Reranker unavailable; keeping retrieval order: %s", exc)
        return items
