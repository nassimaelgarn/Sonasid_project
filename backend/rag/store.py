import json
import re
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.rag.embeddings import embed_query, embed_texts, embeddings_available


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RAG_DB_PATH = os.path.join(BASE_DIR, "db", "rag.db")


def _ensure_rag_db_dir() -> None:
    db_dir = os.path.dirname(RAG_DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


@dataclass
class RagHit:
    source: str
    content: str
    score: float
    meta: Dict[str, Any]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(RAG_DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_rag_db() -> None:
    _ensure_rag_db_dir()
    conn = _connect()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          source TEXT NOT NULL,
          content TEXT NOT NULL,
          meta_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts
        USING fts5(content, source UNINDEXED, chunk_id UNINDEXED)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doc_vec (
          chunk_id INTEGER PRIMARY KEY,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          vec_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          FOREIGN KEY(chunk_id) REFERENCES doc_chunks(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          content TEXT NOT NULL,
          created_at REAL NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
        USING fts5(content, session_id UNINDEXED, role UNINDEXED, chunk_id UNINDEXED)
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_vec (
          chunk_id INTEGER PRIMARY KEY,
          session_id TEXT NOT NULL,
          role TEXT NOT NULL,
          model TEXT NOT NULL,
          dim INTEGER NOT NULL,
          vec_json TEXT NOT NULL,
          created_at REAL NOT NULL,
          FOREIGN KEY(chunk_id) REFERENCES memory_chunks(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_feedback (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          rating INTEGER NOT NULL,
          user_question TEXT NOT NULL,
          assistant_content TEXT NOT NULL,
          meta_json TEXT NOT NULL DEFAULT '{}',
          created_at REAL NOT NULL,
          CHECK(rating IN (-1, 1))
        )
        """
    )
    cur.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chat_feedback_fts
        USING fts5(
          user_question,
          assistant_content,
          session_id UNINDEXED,
          rating UNINDEXED,
          fb_id UNINDEXED
        )
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_feedback_session ON chat_feedback(session_id)"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_feedback_created ON chat_feedback(created_at)"
    )

    conn.commit()
    conn.close()


def _chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> List[str]:
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        return []

    paras = [p.strip() for p in cleaned.split("\n\n") if p.strip()]
    chunks: List[str] = []
    buf = ""
    for p in paras:
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf = buf + "\n\n" + p
        else:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap > 0 else ""
            buf = (tail + "\n\n" + p).strip()
    if buf:
        chunks.append(buf)
    return chunks


def upsert_document(*, source: str, text: str, meta: Optional[Dict[str, Any]] = None) -> int:
    """
    Simple "replace by source" strategy: deletes old chunks for that source then re-inserts.
    Returns number of chunks inserted.
    """
    init_rag_db()
    meta = meta or {}
    chunks = _chunk_text(text)
    now = time.time()

    conn = _connect()
    cur = conn.cursor()

    # Find existing chunk ids for this source (to delete from FTS too).
    cur.execute("SELECT id FROM doc_chunks WHERE source = ?", (source,))
    old_ids = [r[0] for r in cur.fetchall()]
    if old_ids:
        cur.execute("DELETE FROM doc_chunks WHERE source = ?", (source,))
        cur.execute(
            f"DELETE FROM doc_fts WHERE chunk_id IN ({','.join(['?'] * len(old_ids))})",
            tuple(old_ids),
        )
        cur.execute(
            f"DELETE FROM doc_vec WHERE chunk_id IN ({','.join(['?'] * len(old_ids))})",
            tuple(old_ids),
        )

    inserted = 0
    inserted_ids: List[int] = []
    inserted_texts: List[str] = []
    for c in chunks:
        cur.execute(
            "INSERT INTO doc_chunks(source, content, meta_json, created_at) VALUES (?,?,?,?)",
            (source, c, json.dumps(meta, ensure_ascii=False), now),
        )
        chunk_id = cur.lastrowid
        cur.execute(
            "INSERT INTO doc_fts(content, source, chunk_id) VALUES (?,?,?)",
            (c, source, chunk_id),
        )
        inserted += 1
        inserted_ids.append(int(chunk_id))
        inserted_texts.append(c)

    # Optional embeddings indexing (hybrid mode uses this, but we keep it safe).
    rag_mode = (os.getenv("RAG_MODE", "") or "").strip().lower() or "fts"
    if rag_mode in {"embeddings", "hybrid"} and embeddings_available() and inserted_ids:
        try:
            vecs = embed_texts(inserted_texts)
            model = (os.getenv("OPENROUTER_EMBEDDING_MODEL", "") or "").strip() or "text-embedding-3-small"
            for cid, v in zip(inserted_ids, vecs):
                cur.execute(
                    "INSERT OR REPLACE INTO doc_vec(chunk_id, model, dim, vec_json, created_at) VALUES (?,?,?,?,?)",
                    (cid, model, int(len(v)), json.dumps(v), now),
                )
        except Exception:
            # If embeddings fail (quota/model), keep FTS5 working.
            pass

    conn.commit()
    conn.close()
    return inserted


def add_memory(*, session_id: str, role: str, content: str) -> None:
    init_rag_db()
    sid = (session_id or "").strip() or "default"
    role = (role or "").strip() or "user"
    content = (content or "").strip()
    if not content:
        return
    now = time.time()

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO memory_chunks(session_id, role, content, created_at) VALUES (?,?,?,?)",
        (sid, role, content, now),
    )
    chunk_id = cur.lastrowid
    cur.execute(
        "INSERT INTO memory_fts(content, session_id, role, chunk_id) VALUES (?,?,?,?)",
        (content, sid, role, chunk_id),
    )

    rag_mode = (os.getenv("RAG_MODE", "") or "").strip().lower() or "fts"
    if rag_mode in {"embeddings", "hybrid"} and embeddings_available():
        try:
            v = embed_texts([content])[0]
            model = (os.getenv("OPENROUTER_EMBEDDING_MODEL", "") or "").strip() or "text-embedding-3-small"
            cur.execute(
                "INSERT OR REPLACE INTO memory_vec(chunk_id, session_id, role, model, dim, vec_json, created_at) VALUES (?,?,?,?,?,?,?)",
                (int(chunk_id), sid, role, model, int(len(v)), json.dumps(v), now),
            )
        except Exception:
            pass

    conn.commit()
    conn.close()


def _fts_search(
    *,
    table: str,
    query: str,
    where_args: Tuple[Any, ...],
    limit: int,
) -> List[Tuple[int, float]]:
    """
    Returns list of (chunk_id, score). Lower score = better in bm25.
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or 8), 50))

    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT chunk_id, bm25({table}) as score
        FROM {table}
        WHERE {table} MATCH ?
        {('AND ' + where_args[0]) if where_args and isinstance(where_args[0], str) else ''}
        ORDER BY score
        LIMIT ?
        """,
        tuple([q] + list(where_args[1:]) + [limit]) if where_args and isinstance(where_args[0], str) else (q, limit),
    )
    rows = [(int(r[0]), float(r[1])) for r in cur.fetchall() if r and r[0] is not None]
    conn.close()
    return rows


def search_docs(query: str, *, k: int = 6) -> List[RagHit]:
    init_rag_db()
    ids = _fts_search(table="doc_fts", query=query, where_args=tuple(), limit=k)
    if not ids:
        return []

    conn = _connect()
    cur = conn.cursor()
    out: List[RagHit] = []
    for chunk_id, score in ids:
        cur.execute("SELECT source, content, meta_json FROM doc_chunks WHERE id = ?", (chunk_id,))
        row = cur.fetchone()
        if not row:
            continue
        source, content, meta_json = row
        meta = {}
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:
            meta = {}
        out.append(RagHit(source=source, content=content, score=score, meta=meta))
    conn.close()
    return out


def search_memory(session_id: str, query: str, *, k: int = 6) -> List[RagHit]:
    init_rag_db()
    sid = (session_id or "").strip() or "default"
    ids = _fts_search(
        table="memory_fts",
        query=query,
        where_args=("session_id = ?", sid),
        limit=k,
    )
    if not ids:
        return []

    conn = _connect()
    cur = conn.cursor()
    out: List[RagHit] = []
    for chunk_id, score in ids:
        cur.execute("SELECT role, content, created_at FROM memory_chunks WHERE id = ?", (chunk_id,))
        row = cur.fetchone()
        if not row:
            continue
        role, content, created_at = row
        out.append(
            RagHit(
                source=f"memory:{sid}",
                content=f"[{role}] {content}",
                score=score,
                meta={"created_at": created_at, "role": role},
            )
        )
    conn.close()
    return out


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    # Safe cosine similarity without numpy.
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        x = float(a[i])
        y = float(b[i])
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


def search_docs_embeddings(query: str, *, k: int = 6) -> List[RagHit]:
    """
    Embeddings search over doc_vec (brute-force cosine). Returns RagHit with score=(1-sim) (lower is better).
    Requires OPENROUTER_API_KEY.
    """
    init_rag_db()
    q = (query or "").strip()
    if not q:
        return []
    if not embeddings_available():
        return []
    try:
        qv = embed_query(q)
    except Exception:
        return []

    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT chunk_id, vec_json FROM doc_vec")
    rows = cur.fetchall() or []
    scored: List[Tuple[int, float]] = []
    for cid, vec_json in rows:
        try:
            v = json.loads(vec_json or "[]")
            sim = _cosine_similarity(qv, v)
            scored.append((int(cid), 1.0 - float(sim)))
        except Exception:
            continue
    scored.sort(key=lambda t: t[1])
    top = scored[: max(1, min(int(k or 6), 50))]
    out: List[RagHit] = []
    for chunk_id, score in top:
        cur.execute("SELECT source, content, meta_json FROM doc_chunks WHERE id = ?", (chunk_id,))
        row = cur.fetchone()
        if not row:
            continue
        source, content, meta_json = row
        meta = {}
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:
            meta = {}
        out.append(RagHit(source=source, content=content, score=float(score), meta=meta))
    conn.close()
    return out


def search_memory_embeddings(session_id: str, query: str, *, k: int = 6) -> List[RagHit]:
    init_rag_db()
    sid = (session_id or "").strip() or "default"
    q = (query or "").strip()
    if not q:
        return []
    if not embeddings_available():
        return []
    try:
        qv = embed_query(q)
    except Exception:
        return []

    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT chunk_id, role, vec_json, created_at FROM memory_vec WHERE session_id = ?", (sid,))
    rows = cur.fetchall() or []
    scored: List[Tuple[int, str, float, float]] = []
    for cid, role, vec_json, created_at in rows:
        try:
            v = json.loads(vec_json or "[]")
            sim = _cosine_similarity(qv, v)
            scored.append((int(cid), str(role), 1.0 - float(sim), float(created_at or 0)))
        except Exception:
            continue
    scored.sort(key=lambda t: t[2])
    top = scored[: max(1, min(int(k or 6), 50))]
    out: List[RagHit] = []
    for chunk_id, role, score, created_at in top:
        cur.execute("SELECT content FROM memory_chunks WHERE id = ?", (chunk_id,))
        row = cur.fetchone()
        if not row:
            continue
        content = row[0]
        out.append(
            RagHit(
                source=f"memory:{sid}",
                content=f"[{role}] {content}",
                score=float(score),
                meta={"created_at": created_at, "role": role},
            )
        )
    conn.close()
    return out


def list_conversations(*, limit: int = 50, session_prefix: str = "") -> List[Dict[str, Any]]:
    """
    Returns a list of conversations (session_id) with a simple title and updated_at.
    """
    init_rag_db()
    limit = max(1, min(int(limit or 50), 200))
    conn = _connect()
    cur = conn.cursor()

    where = ""
    args: List[Any] = []
    pref = (session_prefix or "").strip()
    if pref:
        where = "WHERE session_id LIKE ?"
        args.append(pref + "%")
    cur.execute(
        f"""
        SELECT session_id, MAX(created_at) AS updated_at
        FROM memory_chunks
        {where}
        GROUP BY session_id
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        tuple(args + [limit]),
    )
    rows = cur.fetchall() or []
    out: List[Dict[str, Any]] = []

    def _clean_title(t: str) -> str:
        s = (t or "").strip().replace("\n", " ")
        # Backward-compat: older builds prefixed messages with an actor tag.
        s = re.sub(r"(?i)^\[acteur:[^\]]+\]\s*", "", s).strip()
        # Remove common "chatty" prefixes to keep titles short/professional.
        s = re.sub(
            r"(?i)^(je\s+veux\s+(?:savoir|voir|connai(?:tre|̂tre))|je\s+voudrais|j['’]aimerais|donne\s+moi|peux[-\s]*tu|tu\s+peux|svp|s['’]il\s+te\s+pla[iî]t|stp)\s+",
            "",
            s,
        ).strip()
        s = re.sub(r"(?i)^(la|le|les|un|une|des)\s+", "", s).strip()
        # Sentence case (keep acronyms like KPI/TD/TR as-is).
        if s:
            s = s[0].upper() + s[1:]
        return s

    for sid, updated_at in rows:
        # title: first user message if possible
        cur.execute(
            """
            SELECT content
            FROM memory_chunks
            WHERE session_id = ? AND role = 'user'
            ORDER BY created_at ASC
            LIMIT 1
            """,
            (sid,),
        )
        r2 = cur.fetchone()
        title = _clean_title((r2[0] if r2 else sid) or sid) or sid
        if len(title) > 60:
            title = title[:57] + "..."
        out.append({"session_id": sid, "title": title, "updated_at": float(updated_at or 0)})

    conn.close()
    return out


def get_conversation_history(*, session_id: str, limit: int = 200) -> List[Dict[str, Any]]:
    init_rag_db()
    sid = (session_id or "").strip() or "default"
    limit = max(1, min(int(limit or 200), 1000))
    conn = _connect()
    cur = conn.cursor()
    # Derniers `limit` messages (pas les plus anciens : ASC+LIMIT coupait la fin de l’historique).
    cur.execute(
        """
        SELECT role, content, created_at
        FROM (
            SELECT role, content, created_at, id
            FROM memory_chunks
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        ) AS tail
        ORDER BY tail.created_at ASC, tail.id ASC
        """,
        (sid, limit),
    )
    rows = cur.fetchall() or []
    conn.close()
    out: List[Dict[str, Any]] = []
    for (r, c, ts) in rows:
        content = c
        if r == "user":
            # Hide audit-only actor tag in UI/history.
            # Older builds stored: "[acteur:Name] question". We now just strip the tag.
            content = re.sub(r"(?i)^\[acteur:[^\]]+\]\s*", "", content or "").strip()
        out.append({"role": r, "content": content, "created_at": float(ts or 0)})
    return out


def delete_conversation(*, session_id: str) -> None:
    init_rag_db()
    sid = (session_id or "").strip() or "default"
    conn = _connect()
    cur = conn.cursor()
    cur.execute("SELECT id FROM memory_chunks WHERE session_id = ?", (sid,))
    ids = [r[0] for r in cur.fetchall() or []]
    if ids:
        cur.execute("DELETE FROM memory_chunks WHERE session_id = ?", (sid,))
        cur.execute(
            f"DELETE FROM memory_fts WHERE chunk_id IN ({','.join(['?'] * len(ids))})",
            tuple(ids),
        )
        cur.execute(
            f"DELETE FROM memory_vec WHERE chunk_id IN ({','.join(['?'] * len(ids))})",
            tuple(ids),
        )
    conn.commit()
    conn.close()


def add_chat_feedback(
    *,
    session_id: str,
    rating: int,
    user_question: str,
    assistant_content: str,
    meta: Optional[Dict[str, Any]] = None,
) -> int:
    """
    Enregistre un retour utilisateur (1 = pertinent, -1 = non pertinent) pour analyse / futur affinage.

    Returns inserted row id.
    """
    init_rag_db()
    if rating not in (-1, 1):
        raise ValueError("rating must be -1 or 1")
    sid = (session_id or "").strip() or "default"
    uq = (user_question or "").strip()
    ac = (assistant_content or "").strip()
    if not uq or not ac:
        raise ValueError("user_question and assistant_content are required")
    cap_q = 12_000
    cap_a = 24_000
    if len(uq) > cap_q:
        uq = uq[:cap_q]
    if len(ac) > cap_a:
        ac = ac[:cap_a]
    now = time.time()
    meta = meta or {}
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO chat_feedback(session_id, rating, user_question, assistant_content, meta_json, created_at)
        VALUES (?,?,?,?,?,?)
        """,
        (sid, int(rating), uq, ac, json.dumps(meta, ensure_ascii=False), now),
    )
    rid = cur.lastrowid
    try:
        cur.execute(
            "INSERT INTO chat_feedback_fts(user_question, assistant_content, session_id, rating, fb_id) VALUES (?,?,?,?,?)",
            (uq, ac, sid, int(rating), int(rid or 0)),
        )
    except Exception:
        # If FTS insert fails for any reason, keep the feedback row.
        pass
    conn.commit()
    conn.close()
    return int(rid or 0)


def search_chat_feedback(
    query: str,
    *,
    k: int = 6,
    session_id: Optional[str] = None,
    rating: Optional[int] = -1,
) -> List[RagHit]:
    """
    Search feedback (by default: negative feedback only) to help the assistant avoid repeating mistakes.

    Returns RagHit entries whose content is a compact Q/A pair.
    """
    init_rag_db()
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(k or 6), 50))

    where = []
    args: List[Any] = []
    if session_id:
        sid = (session_id or "").strip() or "default"
        where.append("session_id = ?")
        args.append(sid)
    if rating in (-1, 1):
        where.append("rating = ?")
        args.append(int(rating))
    where_sql = " AND ".join(where) if where else ""
    where_args: Tuple[Any, ...] = tuple([where_sql] + args) if where_sql else tuple()

    ids = _fts_search(table="chat_feedback_fts", query=q, where_args=where_args, limit=limit)
    if not ids:
        return []

    conn = _connect()
    cur = conn.cursor()
    out: List[RagHit] = []
    for fb_id, score in ids:
        cur.execute(
            "SELECT session_id, rating, user_question, assistant_content, meta_json, created_at FROM chat_feedback WHERE id = ?",
            (int(fb_id),),
        )
        row = cur.fetchone()
        if not row:
            continue
        sid, r, uq, ac, meta_json, created_at = row
        meta: Dict[str, Any] = {}
        try:
            meta = json.loads(meta_json or "{}")
        except Exception:
            meta = {}
        content = f"[rating={int(r)}]\nQ: {str(uq).strip()}\nA: {str(ac).strip()}"
        out.append(
            RagHit(
                source=f"feedback:{sid}",
                content=content,
                score=float(score),
                meta={**meta, "fb_id": int(fb_id), "created_at": float(created_at or 0), "rating": int(r)},
            )
        )
    conn.close()
    return out

