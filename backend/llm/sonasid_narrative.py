"""
Réponses enrichies Sonasid : formule, SQL, synthèse courte (sans inventer de chiffres).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from backend.llm.kpi_analyse_fallback import deterministic_kpi_analyse_from_dict
from backend.llm.sonasid_schema import guess_formula_hint


def _is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def enrich_sonasid_response(
    out: Dict[str, Any],
    *,
    question: str,
    sql: Optional[str] = None,
) -> Dict[str, Any]:
    if not _is_sonasid_profile() or not isinstance(out, dict):
        return out
    if out.get("error"):
        return out

    formula = guess_formula_hint(question)
    if formula and not out.get("formula"):
        out["formula"] = formula

    if sql and not out.get("tsql") and not out.get("sql"):
        out["tsql"] = sql

    auto = (os.getenv("SONASID_AUTO_NARRATIVE", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not auto:
        return out

    synth = deterministic_kpi_analyse_from_dict(out)
    if not synth:
        synth = _minimal_sonasid_synth(out)

    parts = []
    if formula:
        parts.append(f"**Formule / logique :** {formula}")
    if sql and _user_wants_sql(question):
        parts.append(f"**Requête T-SQL :**\n```sql\n{sql.strip()}\n```")
    if synth:
        parts.append(synth)

    if parts and not out.get("message"):
        out["message"] = "\n\n".join(parts)
    elif out.get("message"):
        extra = []
        if formula and formula not in str(out.get("message")):
            extra.append(f"**Formule / logique :** {formula}")
        if sql and _user_wants_sql(question) and sql.strip() not in str(out.get("message")):
            extra.append(f"**Requête T-SQL :**\n```sql\n{sql.strip()}\n```")
        if synth and synth not in str(out.get("message")):
            extra.append(synth)
        if extra:
            out["message"] = str(out["message"]) + "\n\n" + "\n\n".join(extra)

    return out


def _user_wants_sql(question: str) -> bool:
    ql = (question or "").lower()
    return bool(
        re.search(r"\b(requête|requete|sql|query)\b", ql)
        or re.search(r"\b(montre|affiche|donne).{0,20}\b(sql|requête|requete)\b", ql)
    )


def _minimal_sonasid_synth(out: Dict[str, Any]) -> str:
    r = out.get("result")
    if isinstance(r, list) and r:
        n = len(r)
        if n == 1 and isinstance(r[0], dict):
            return f"**Résultat :** 1 ligne retournée."
        return f"**Résultat :** {n} ligne(s)."
    if isinstance(r, (int, float)):
        return f"**Résultat :** {r}"
    for k in (
        "tonnage_importe",
        "tonnage_total",
        "nombre_arrivages",
        "nombre_navires",
        "tonnage_decharge",
    ):
        v = out.get(k)
        if isinstance(v, (int, float)):
            return f"**{k.replace('_', ' ').title()} :** {v}"
    return ""
