from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
import re

from backend.pipeline.pipeline import process_question
from backend.rag.contextualizer import build_rag_context


def tool_rag_context(*, question: str, session_id: Optional[str]) -> str:
    return build_rag_context(question=question, session_id=session_id)


def tool_kpi_answer(*, question: str) -> Dict[str, Any]:
    res = process_question(question)
    if isinstance(res, dict):
        return res
    return {"question": question, "error": "Réponse pipeline invalide"}


def _extract_numeric(res: Dict[str, Any]) -> Optional[Tuple[str, float]]:
    """
    Extract a primary numeric KPI value from pipeline responses.
    Returns (label, value) or None.
    """
    if not isinstance(res, dict):
        return None
    # Prefer common KPI keys
    for k in ["TD_percent", "TR_percent", "Rendement_percent", "MTBF_secondes", "MTTR_secondes"]:
        v = res.get(k)
        if isinstance(v, (int, float)):
            return (k, float(v))
    # Consumption keys (pipeline dict results)
    for k in [
        "Consommation_Totale",
        "Consommation_MWh",
        "Consommation_EAF",
        "Consommation_LF",
        "Consommation_Oxygène",
        "Consommation_Carbon",
        "Consommation_GPL",
    ]:
        v = res.get(k)
        if isinstance(v, (int, float)):
            return (k, float(v))
    # Fallback: scalar result
    v = res.get("result")
    if isinstance(v, (int, float)):
        return ("result", float(v))
    return None


def tool_compare_periods(*, question: str, period_a: str, period_b: str) -> Dict[str, Any]:
    """
    Compare the same KPI question across two date ranges.
    period_* format: "YYYY-MM-DD..YYYY-MM-DD"
    """
    q = (question or "").strip()
    if not q:
        return {"question": question, "error": "Question vide"}

    def parse(p: str) -> Optional[Tuple[str, str]]:
        m = re.match(r"^\s*(\d{4}-\d{2}-\d{2})\s*\.\.\s*(\d{4}-\d{2}-\d{2})\s*$", p or "")
        if not m:
            return None
        return (m.group(1), m.group(2))

    pa = parse(period_a)
    pb = parse(period_b)
    if not pa or not pb:
        return {
            "question": q,
            "error": "BAD_PERIOD",
            "message": "Format période invalide. Utilise 'YYYY-MM-DD..YYYY-MM-DD'.",
        }

    qa = f"{q} du {pa[0]} au {pa[1]}"
    qb = f"{q} du {pb[0]} au {pb[1]}"
    ra = process_question(qa)
    rb = process_question(qb)
    if not isinstance(ra, dict) or not isinstance(rb, dict):
        return {"question": q, "error": "Réponse pipeline invalide"}

    na = _extract_numeric(ra) or ("value", 0.0)
    nb = _extract_numeric(rb) or ("value", 0.0)
    delta = nb[1] - na[1]
    pct = (delta / na[1] * 100.0) if na[1] not in (0, 0.0) else None
    return {
        "question": q,
        "source": "agent:compare_periods",
        "metric": na[0] if na[0] == nb[0] else f"{na[0]} vs {nb[0]}",
        "period_a": {"range": f"{pa[0]}..{pa[1]}", "value": na[1], "raw": ra},
        "period_b": {"range": f"{pb[0]}..{pb[1]}", "value": nb[1], "raw": rb},
        "delta": delta,
        "delta_percent": pct,
    }

