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


def _user_wants_formula(question: str) -> bool:
    ql = (question or "").lower()
    return bool(
        re.search(r"\b(formule|formules|logic|logique)\b", ql)
        or re.search(r"\b(comment|commment)\s+(calcul|est calcul)", ql)
        or re.search(r"\b(montre|affiche|donne).{0,24}\b(formule|logic|logique)\b", ql)
        or re.search(r"\bformule\s+(utilis|officiel|metier|métier)\b", ql)
    )


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
    if str(out.get("source") or "").startswith("sonasid:brief"):
        return out

    formula = guess_formula_hint(question) if _user_wants_formula(question) else None
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
        out.pop("formula", None)
        return out

    synth = deterministic_kpi_analyse_from_dict(out)
    if not synth:
        synth = _minimal_sonasid_synth(out)

    parts = []
    if formula:
        parts.append(f"**Formule / logique :** {formula}")
    if sql and _user_wants_sql(question):
        parts.append(f"**Requête T-SQL :**\n```sql\n{sql.strip()}\n```")
    if synth and not out.get("message"):
        parts.append(synth)

    if parts and not out.get("message"):
        out["message"] = "\n\n".join(parts)
    elif out.get("message"):
        extra = []
        if formula and formula not in str(out.get("message")):
            extra.append(f"**Formule / logique :** {formula}")
        if sql and _user_wants_sql(question) and sql.strip() not in str(out.get("message")):
            extra.append(f"**Requête T-SQL :**\n```sql\n{sql.strip()}\n```")
        if (
            synth
            and synth not in str(out.get("message"))
            and _should_append_auto_synth(out)
        ):
            extra.append(synth)
        if extra:
            out["message"] = str(out["message"]) + "\n\n" + "\n\n".join(extra)

    if not _user_wants_formula(question):
        out.pop("formula", None)

    return out


def _should_append_auto_synth(out: Dict[str, Any]) -> bool:
    """Ne pas empiler la synthèse auto sur une réponse déjà lisible."""
    if out.get("message") and str(out.get("source") or "").startswith("sql:sonasid"):
        return False
    rows = out.get("result")
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        if "period" in rows[0] or "periode" in rows[0]:
            return False
    if out.get("nombre_arrivages") is not None and isinstance(out.get("result"), (int, float)):
        return False
    if str(out.get("source") or "").startswith("sonasid:brief"):
        return False
    return True


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
