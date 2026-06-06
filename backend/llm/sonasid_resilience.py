"""
Sonasid — essayer toutes les pistes fiables avant une erreur ou un message générique.
Ordre : schéma / inventaire BDD → brief / règles KPI → (pipeline + LLM) → guide métier.
"""
from __future__ import annotations

import os
import random
import re
from typing import Any, Dict, Optional


def _sonasid_active() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def try_deterministic_sonasid_reply(question: str) -> Optional[Dict[str, Any]]:
    """Réponses sans LLM ni SQL métier (schéma, nombre de tables, etc.)."""
    if not _sonasid_active():
        return None
    q = (question or "").strip()
    if not q:
        return None
    try:
        from backend.llm.sonasid_schema import (
            company_overview_reply,
            is_schema_metadata_question,
            is_sonasid_company_question,
            schema_metadata_reply,
        )

        if is_schema_metadata_question(q):
            return schema_metadata_reply(q)
        if is_sonasid_company_question(q):
            return company_overview_reply(q)
    except Exception:
        pass
    return None


def should_force_kpi_pipeline(question: str) -> bool:
    """
    True si les règles / brief Sonasid peuvent traiter la question
    (même si should_use_kpi_pipeline l'a manquée).
    """
    if not _sonasid_active():
        return False
    q = (question or "").strip()
    if not q:
        return False
    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question

        if is_schema_metadata_question(q):
            return False
    except Exception:
        pass
    try:
        from backend.llm.sonasid_brief import detect_sonasid_brief
        from backend.llm.sonasid_sql import expand_sonasid_open_question, try_sonasid_kpi_sql

        expanded, _ = expand_sonasid_open_question(q)
        q_eff = expanded or q
        if detect_sonasid_brief(q_eff):
            return True
        raw = try_sonasid_kpi_sql(q_eff)
        if isinstance(raw, str) and raw.strip():
            return True
        if isinstance(raw, dict) and raw.get("type") in {
            "need_navire",
            "need_fournisseur",
        }:
            return True
    except Exception:
        pass
    return False


def build_guidance_reply(question: str) -> Dict[str, Any]:
    """Dernière étape : pas de chiffre inventé, exemples réels du catalogue."""
    q = (question or "").strip()
    ql = q.lower()
    lines = [
        "Je n’ai pas trouvé de réponse fiable automatique pour cette formulation exacte.",
        "",
    ]
    try:
        from backend.llm.sonasid_sql import list_sonasid_kpi_catalog

        catalog = list_sonasid_kpi_catalog()
        picks = []
        for item in catalog:
            ex = item.get("question") or ""
            if not ex:
                continue
            el = ex.lower()
            if any(w in ql for w in ("navire", "navires")) and "navire" in el:
                picks.append(ex)
            elif any(w in ql for w in ("table", "tables", "schéma", "schema", "base")):
                break
            elif any(w in ql for w in ("fournisseur",)) and "fournisseur" in el:
                picks.append(ex)
            elif any(w in ql for w in ("décharg", "decharg")) and "décharg" in el:
                picks.append(ex)
            elif any(w in ql for w in ("tonnage", "import", "marchandise")) and "tonnage" in el:
                picks.append(ex)
        if not picks:
            all_q = [item.get("question", "") for item in catalog if item.get("question")]
            picks = random.sample(all_q, min(5, len(all_q))) if all_q else []
        else:
            random.shuffle(picks)
            picks = picks[:5]
        if picks:
            lines.append("**Questions que je sais traiter** (données réelles en base) :")
            for ex in picks:
                lines.append(f"- {ex}")
            lines.append("")
    except Exception:
        pass

    if re.search(r"\b(table|sch[eé]ma|base|relation)\b", ql):
        lines.append(
            "Pour la structure : « noms des tables et relations », "
            "« cite le nombre des tables », ou « structure table ARRIVAGE »."
        )
    else:
        lines.append(
            "Précise **période** (ex. 2025) + **indicateur** (arrivages, tonnage, navires, fournisseurs…), "
            "ou demande un « récap 2025 » / « analyse arrivages 2025 »."
        )
    lines.append("")
    lines.append("_Aucun chiffre n’est affiché tant qu’une requête validée n’a pas été exécutée._")

    return {
        "question": q,
        "message": "\n".join(lines),
        "source": "sonasid:guidance",
    }


def soften_pipeline_failure(
    out: Dict[str, Any],
    question: str,
    *,
    model_name: str = "",
) -> Dict[str, Any]:
    """Enrichit NEED_REPHRASE / erreurs vides — ne pas laisser « Résultat: 1 »."""
    if not isinstance(out, dict):
        return out
    err = str(out.get("error") or "")
    if err in {"NEED_REPHRASE", "NEED_PERIOD"} or (err and not out.get("message")):
        try:
            from backend.llm.sonasid_smart_route import retry_question_via_llm

            retried = retry_question_via_llm(question, model_name=model_name or "")
            if retried:
                return retried
        except Exception:
            pass
    if err not in {"NEED_REPHRASE", "NEED_PERIOD"} and out.get("message"):
        return out
    if out.get("message") and err != "NEED_REPHRASE":
        return out
    guided = build_guidance_reply(question)
    merged = dict(out)
    merged["message"] = guided.get("message") or merged.get("message")
    merged["source"] = "sonasid:guidance"
    return merged
