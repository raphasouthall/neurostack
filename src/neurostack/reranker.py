# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""Cross-encoder reranking for NeuroStack search results."""
from __future__ import annotations

import logging
import os

# Suppress noisy HuggingFace Hub warnings and progress bars
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

logger = logging.getLogger(__name__)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_model = None  # None = not loaded yet; False = load attempted but unavailable


def _load_model():
    global _model
    if _model is None:
        try:
            import transformers
            transformers.logging.set_verbosity_error()
            from sentence_transformers.cross_encoder import CrossEncoder
            _model = CrossEncoder(_MODEL_NAME)
            logger.info("Loaded cross-encoder: %s", _MODEL_NAME)
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; cross-encoder reranking disabled. "
                "Install with: pip install neurostack[full]"
            )
            _model = False
    return _model if _model else None


def rerank(
    query: str,
    candidates: list[dict],
    text_key: str = "content",
    top_k: int | None = None,
) -> list[dict]:
    """Rerank candidates using cross-encoder scores.

    Writes cross-encoder scores back to candidates["score"] in place so the
    rest of the pipeline is unaffected.  Falls back to original order if
    sentence-transformers is not installed.

    Args:
        query: The search query.
        candidates: Raw result dicts (must contain text_key).
        text_key: Field to use as the passage text (max 512 chars used).
        top_k: Truncate to top-k after reranking (None = return all).

    Returns:
        Reranked (and optionally truncated) candidates list.
    """
    if not candidates:
        return candidates

    model = _load_model()
    if model is None:
        return candidates[:top_k] if top_k is not None else candidates

    pairs = [(query, (c.get(text_key) or "")[:512]) for c in candidates]
    scores = model.predict(pairs)

    for c, s in zip(candidates, scores):
        c["score"] = float(s)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k] if top_k is not None else candidates
