from __future__ import annotations

import os
from typing import Optional

from backend.rag.store import (
    RagHit,
    search_docs,
    search_docs_embeddings,
    search_chat_feedback,
    search_memory,
    search_memory_embeddings,
)


def _render_hits(title: str, hits: list[RagHit], *, max_chars: int = 2500) -> str:
    if not hits:
        return ""
    lines = [f"{title}:"]
    used = 0
    for h in hits:
        snippet = (h.content or "").strip()
        if not snippet:
            continue
        block = f"- source={h.source} score={h.score:.3f}\n{snippet}"
        if used + len(block) > max_chars:
            break
        lines.append(block)
        used += len(block)
    return "\n".join(lines).strip()


def build_rag_context(*, question: str, session_id: Optional[str], k_docs: int = 5, k_mem: int = 6) -> str:
    """
    "RAG contextuel" = retrieval sur (docs projet + mémoire session).
    """
    q = (question or "").strip()
    if not q:
        return ""

    mode = (os.getenv("RAG_MODE", "") or "").strip().lower() or "fts"  # fts | embeddings | hybrid

    if mode == "embeddings":
        docs = search_docs_embeddings(q, k=k_docs)
        mem = search_memory_embeddings(session_id or "default", q, k=k_mem) if session_id else []
        fb = search_chat_feedback(q, k=4, session_id=session_id, rating=-1)
    elif mode == "hybrid":
        docs_fts = search_docs(q, k=k_docs)
        docs_emb = search_docs_embeddings(q, k=k_docs)
        # Deduplicate by (source, content)
        seen = set()
        docs: list[RagHit] = []
        for h in (docs_fts + docs_emb):
            key = (h.source, (h.content or "")[:200])
            if key in seen:
                continue
            seen.add(key)
            docs.append(h)
            if len(docs) >= max(k_docs, 1) * 2:
                break

        mem_fts = search_memory(session_id or "default", q, k=k_mem) if session_id else []
        mem_emb = search_memory_embeddings(session_id or "default", q, k=k_mem) if session_id else []
        seen_m = set()
        mem: list[RagHit] = []
        for h in (mem_fts + mem_emb):
            key = ((h.meta or {}).get("role"), (h.content or "")[:200])
            if key in seen_m:
                continue
            seen_m.add(key)
            mem.append(h)
            if len(mem) >= max(k_mem, 1) * 2:
                break
        fb = search_chat_feedback(q, k=4, session_id=session_id, rating=-1)
    else:
        docs = search_docs(q, k=k_docs)
        mem = search_memory(session_id or "default", q, k=k_mem) if session_id else []
        fb = search_chat_feedback(q, k=4, session_id=session_id, rating=-1)

    parts = []
    if fb:
        parts.append(_render_hits("Feedback négatif (à éviter)", fb, max_chars=2000))
    if mem:
        parts.append(_render_hits("Mémoire (session)", mem))
    if docs:
        parts.append(_render_hits("Connaissances projet", docs))

    return "\n\n".join([p for p in parts if p]).strip()

