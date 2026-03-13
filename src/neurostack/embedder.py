"""Ollama embedding client."""

import json
from typing import Optional

import httpx

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from .config import get_config

_cfg = get_config()
DEFAULT_EMBED_URL = _cfg.embed_url
EMBED_MODEL = _cfg.embed_model
EMBED_DIM = _cfg.embed_dim


def get_embedding(
    text: str,
    base_url: str = DEFAULT_EMBED_URL,
    model: str = EMBED_MODEL,
) -> "np.ndarray":
    """Get embedding vector for a single text."""
    if not HAS_NUMPY:
        raise ImportError(
            "Embedding functions require numpy. "
            "Install with: pip install neurostack[full]"
        )
    resp = httpx.post(
        f"{base_url}/api/embed",
        json={"model": model, "input": text},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return np.array(data["embeddings"][0], dtype=np.float32)


def get_embeddings_batch(
    texts: list[str],
    base_url: str = DEFAULT_EMBED_URL,
    model: str = EMBED_MODEL,
    batch_size: int = 50,
) -> "list[np.ndarray]":
    """Get embeddings for multiple texts in batches."""
    if not HAS_NUMPY:
        raise ImportError(
            "Embedding functions require numpy. "
            "Install with: pip install neurostack[full]"
        )
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = httpx.post(
            f"{base_url}/api/embed",
            json={"model": model, "input": batch},
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        for emb in data["embeddings"]:
            all_embeddings.append(np.array(emb, dtype=np.float32))
    return all_embeddings


def embedding_to_blob(vec: "np.ndarray") -> bytes:
    """Convert numpy array to SQLite BLOB."""
    return vec.tobytes()


def blob_to_embedding(blob: bytes) -> "np.ndarray":
    """Convert SQLite BLOB back to numpy array."""
    return np.frombuffer(blob, dtype=np.float32)


def build_chunk_context(
    title: str,
    frontmatter_json: str,
    summary: Optional[str],
    chunk_text: str,
) -> str:
    """Build contextualized text for embedding by prepending note metadata and summary.

    Only this combined string goes to the embed model. The stored chunk content
    remains the original text — context is used at embed time only.
    """
    header = f"Note: {title}"
    try:
        fm = json.loads(frontmatter_json) if frontmatter_json else {}
        if fm.get("type"):
            header += f" | Type: {fm['type']}"
        tags = fm.get("tags") or fm.get("tag")
        if tags:
            if isinstance(tags, list):
                header += f" | Tags: {', '.join(str(t) for t in tags)}"
            else:
                header += f" | Tags: {tags}"
    except Exception:
        pass

    parts = [header]
    if summary:
        parts.append(f"Summary: {summary}")
    parts.append("---")
    parts.append(chunk_text)
    return "\n".join(parts)


def cosine_similarity(a: "np.ndarray", b: "np.ndarray") -> float:
    """Compute cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


def cosine_similarity_batch(query: "np.ndarray", matrix: "np.ndarray") -> "np.ndarray":
    """Compute cosine similarity between query and matrix of vectors."""
    query_norm = query / (np.linalg.norm(query) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    matrix_norm = matrix / norms
    return matrix_norm @ query_norm
