import os
from typing import Dict, List, Tuple

from backend.rag.store import upsert_document


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _read_text_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def ingest_default_corpus() -> Dict[str, int]:
    """
    Indexe un petit corpus local utile pour le SQL:
    - prompts/system_sql.txt
    - backend/llm/llm_sql.py (règles KPI)
    - backend/llm/llm_router.py (schéma DB hint)
    """
    docs: List[Tuple[str, str, Dict]] = []

    prompts = os.path.join(BASE_DIR, "prompts", "system_sql.txt")
    docs.append(("prompts/system_sql.txt", _read_text_file(prompts), {"kind": "prompt"}))

    rules = os.path.join(BASE_DIR, "backend", "llm", "llm_sql.py")
    docs.append(("backend/llm/llm_sql.py", _read_text_file(rules), {"kind": "rules"}))

    router = os.path.join(BASE_DIR, "backend", "llm", "llm_router.py")
    docs.append(("backend/llm/llm_router.py", _read_text_file(router), {"kind": "schema"}))

    out: Dict[str, int] = {}
    for source, text, meta in docs:
        if not text.strip():
            continue
        out[source] = upsert_document(source=source, text=text, meta=meta)
    return out

