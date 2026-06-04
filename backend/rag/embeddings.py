from __future__ import annotations

import os
from typing import List


def embeddings_available() -> bool:
    """
    Embeddings are optional in this project.

    The default RAG mode is FTS, so keeping this conservative avoids startup
    failures when API keys / models are not configured.
    """
    # Only enable if the user explicitly configured it.
    mode = (os.getenv("RAG_MODE", "") or "").strip().lower()
    if mode not in {"embeddings", "hybrid"}:
        return False

    # Require at least one API key to be present.
    return bool((os.getenv("OPENAI_API_KEY") or "").strip() or (os.getenv("OPENROUTER_API_KEY") or "").strip())


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Placeholder embedding implementation.

    This project can run purely with FTS retrieval (RAG_MODE=fts). If you want
    embeddings, wire an embeddings provider here and set RAG_MODE accordingly.
    """
    raise RuntimeError(
        "Embeddings not configured. Set RAG_MODE=fts (recommended) "
        "or implement embed_texts()/embed_query() in backend/rag/embeddings.py."
    )


def embed_query(text: str) -> List[float]:
    # Keep a separate function for store.py API compatibility.
    return embed_texts([text])[0]
