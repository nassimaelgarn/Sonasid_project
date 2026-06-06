"""
Routage intelligent Sonasid — reformulation LLM (Azure) avant échec / guidance.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional


def _sonasid_active() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def is_smart_routing_enabled() -> bool:
    if not _sonasid_active():
        return False
    v = (os.getenv("SONASID_SMART_ROUTING", "true") or "true").strip().lower()
    return v in {"1", "true", "yes", "on"}


def _is_pipeline_failure(out: Dict[str, Any]) -> bool:
    if not isinstance(out, dict):
        return True
    err = str(out.get("error") or "")
    if err in {"NEED_REPHRASE", "NEED_PERIOD"}:
        return True
    src = str(out.get("source") or "")
    if src == "sonasid:guidance":
        return True
    msg = str(out.get("message") or "")
    if err == "NEED_REPHRASE" or "Je n'ai pas compris quel KPI" in msg:
        return True
    if out.get("result") == 1 and not out.get("nombre_arrivages") and not out.get("message"):
        return True
    return False


def retry_question_via_llm(question: str, *, model_name: str = "") -> Optional[Dict[str, Any]]:
    """
    Reformule via LLM (Kimi/Grok/DeepSeek) puis ré-exécute le pipeline KPI.
    """
    if not is_smart_routing_enabled():
        return None
    q = (question or "").strip()
    if not q:
        return None
    try:
        from backend.llm.llm_sql import is_contextual_data_followup_text, should_skip_kpi_rewrite

        if is_contextual_data_followup_text(q) or should_skip_kpi_rewrite(q):
            return None
    except Exception:
        pass
    try:
        from backend.llm.kpi_rewrite import rewrite_kpi_question
        from backend.llm.llm_sql import normalize_kpi_question

        rw, prov, _reason = rewrite_kpi_question(q, model_name=model_name or "")
        if not rw:
            return None
        q2 = normalize_kpi_question(rw.strip())
        if not q2 or q2.lower() == q.lower():
            return None
        from backend.pipeline.pipeline import process_question

        out = process_question(q2, model_name=model_name or "")
        if _is_pipeline_failure(out):
            return None
        if isinstance(out, dict):
            out = dict(out)
            out.setdefault("notice", f"Question interprétée : « {q2} » ({prov}).")
            meta = out.get("kpi_rewrite") if isinstance(out.get("kpi_rewrite"), dict) else {}
            if not meta:
                out["kpi_rewrite"] = {
                    "used": True,
                    "provider": prov,
                    "canonical_question": q2,
                }
        return out
    except Exception:
        return None
