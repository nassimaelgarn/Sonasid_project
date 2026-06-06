"""
Réponses conversationnelles (hors KPI SQL) pour le chat Sonasid / aciérie.
Utilisé quand USE_AGENT=false ou en secours.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

from backend.security.access_control import looks_like_kpi_question

_GREETING_ONLY = re.compile(
    r"^\s*(bonjour|salut|hello|hi|hey|coucou|bonsoir|bonne\s+journée|bonne\s+journee)"
    r"(\s+[!.,…]*)?\s*$",
    re.I,
)

_SMALL_TALK = re.compile(
    r"^\s*(bonjour|salut|hello|coucou|bonsoir|merci|thanks|ok|d'accord|dac)\s*[!.,…]*\s*$",
    re.I,
)

_WELLBEING = re.compile(r"^\s*(ça\s+va|ca\s+va|cava|cv)\s*[!?.,…]*\s*$", re.I)


def is_pure_greeting(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_GREETING_ONLY.match(t) or _SMALL_TALK.match(t) or _WELLBEING.match(t))


def should_use_kpi_pipeline(text: str) -> bool:
    """True → exécuter process_question / SQL ; False → conversation LLM."""
    from backend.llm.llm_sql import is_same_kpi_followup_text, normalize_user_question

    t = normalize_user_question((text or "").strip())
    if not t:
        return False
    if is_pure_greeting(t):
        return False
    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question, is_sonasid_company_question

        if is_schema_metadata_question(t):
            return False
        if is_sonasid_company_question(t):
            return False
    except Exception:
        pass
    if is_same_kpi_followup_text(t):
        return True
    try:
        from backend.llm.sonasid_open import is_sonasid_profile, looks_like_sonasid_data_question

        if is_sonasid_profile() and looks_like_sonasid_data_question(t):
            return True
    except Exception:
        pass
    if looks_like_kpi_question(t):
        return True
    tl = t.lower()
    if re.search(r"\b(résumé|resume|recap|récap|synthèse|synthese)\b", tl) and re.search(
        r"\b(kpi|kip|indicateurs?|tous|ensemble|20\d{2})\b", tl
    ):
        return True
    if re.search(r"\b(sql|requête|requete|tsql|query)\b", tl) and re.search(
        r"\b(arrivage|navire|tonnage|kpi|fournisseur|transfert|commande)\b", tl
    ):
        return True
    if re.search(r"\b(donne|donner|affiche|afficher|montre|montrez)\b", tl) and re.search(
        r"\b(sql|requête|requete)\b", tl
    ):
        return True
    if re.search(r"\b(arrivé|arrive)\b", tl) and re.search(
        r"\b(janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre|20\d{2})\b",
        tl,
    ):
        return True
    if re.search(r"\b(augment|diminu|évolution|evolution|tendance|hausse|baisse)\b", tl) and re.search(
        r"\barrivages?\b", tl
    ):
        return True
    return False


def _greeting_message(actor_name: str) -> str:
    name = (actor_name or "").strip()
    first = name.split()[0] if name else ""
    prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if prof in {"sonasid", "shipping", "port"}:
        if first:
            return (
                f"Bonjour {first}, bienvenue dans l'assistant IA Sonasid. "
                "Je serai ravi de t'aider — que veux-tu savoir ?"
            )
        return (
            "Bonjour, bienvenue dans l'assistant IA Sonasid. "
            "Je serai ravi de t'aider — que veux-tu savoir ?"
        )
    if first:
        return (
            f"Bonjour {first}, bienvenue dans l'assistant IA. "
            "Je serai ravi de t'aider — que veux-tu savoir ?"
        )
    return "Bonjour, bienvenue. Je serai ravi de t'aider — que veux-tu savoir ?"


def _wellbeing_message(actor_name: str) -> str:
    name = (actor_name or "").strip()
    first = name.split()[0] if name else ""
    if first:
        return f"Ça va très bien, merci {first} ! Et toi ? Que veux-tu analyser ?"
    return "Ça va très bien, merci ! Que veux-tu analyser ?"


def conversational_reply(
    question: str,
    *,
    actor_name: str = "",
    session_id: Optional[str] = None,
    model_name: str = "",
) -> Dict[str, Any]:
    """
    Réponse naturelle sans SQL. Ne lève pas d'exception vers l'API.
    """
    q = (question or "").strip()
    ql = q.lower()

    if is_pure_greeting(q):
        if _WELLBEING.match(q):
            text = _wellbeing_message(actor_name)
        else:
            text = _greeting_message(actor_name)
        return {
            "question": q,
            "message": text,
            "source": "conversational:greeting",
        }

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

    rag = ""
    try:
        from backend.rag.store import build_rag_context

        rag = build_rag_context(question=q, session_id=session_id)
    except Exception:
        rag = ""

    prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if prof in {"sonasid", "shipping", "port"}:
        domain = (
            "Tu es l’assistant décisionnel Sonasid (port & arrivages de matières premières). "
            "Comportement type ChatGPT : tolère les fautes, devine l'intention, réponds avec intelligence métier (port, arrivages, tonnages).\n"
            "Pour les chiffres : oriente vers un KPI avec période (ex. tonnage importé en 2025) — n'invente jamais de chiffres.\n"
        )
    else:
        domain = (
            "Tu es l’assistant KPI d’une aciérie. Réponds en français, de façon claire.\n"
            "Pour les chiffres, l’utilisateur doit demander un KPI avec une période.\n"
        )

    name = (actor_name or "").strip()
    if name:
        domain += f"L’utilisateur connecté s’appelle **{name}** ; tu peux le saluer par son prénom si c’est naturel.\n"

    sys = (
        domain
        + "Réponds en français avec clarté et intelligence (3 à 6 phrases ou puces courtes si utile).\n"
        + "Interprète la question même si elle est mal formulée. Sois pertinent, nuancé, professionnel.\n"
        + "Ne termine pas systématiquement par une question. Ne réponds jamais par « Résultat: 1 ». N’exécute pas de SQL.\n"
    )
    prompt = f"{sys}\n\nQuestion:\n{q}\n\nContexte (RAG, optionnel):\n{rag or '(vide)'}\n"

    text = ""
    last_err = ""
    from backend.agent.llm import invoke_chat_text

    models = []
    preferred = (model_name or "").strip().lower()
    if preferred in {"trinity", "mistral"}:
        for mn in ("flash", preferred):
            if mn not in models:
                models.append(mn)
    for mn in (
        (model_name or "").strip(),
        (os.getenv("SONASID_DEFAULT_CHAT_MODEL", "") or "").strip(),
        "kimi",
        "deepseek",
        "grok",
        (os.getenv("OPENROUTER_CHAT_FALLBACK", "") or "").strip(),
        "flash",
        (os.getenv("OPENROUTER_MODEL", "") or "").strip(),
    ):
        if mn and mn not in models:
            models.append(mn)

    for mn in models:
        if not mn:
            continue
        try:
            text = (invoke_chat_text(
                prompt=prompt,
                model_name=mn,
                temperature=float(os.getenv("SONASID_CHAT_TEMPERATURE", "0.35")),
            ) or "").strip()
        except Exception as e:
            last_err = str(e) or repr(e)
            text = ""
        if text:
            break

    if not text:
        try:
            from backend.llm.sonasid_smart_route import retry_question_via_llm

            retried = retry_question_via_llm(q, model_name=model_name or "")
            if retried and retried.get("message"):
                return retried
        except Exception:
            pass
        try:
            from backend.llm.sonasid_resilience import build_guidance_reply

            if not is_pure_greeting(q):
                return build_guidance_reply(q)
        except Exception:
            pass
        if not is_pure_greeting(q):
            text = (
                "Je n’ai pas pu produire une réponse fiable pour l’instant. "
                "Précise période et indicateur (ex. tonnage importé en 2025), "
                "ou demande le schéma des tables."
            )
        else:
            text = _greeting_message(actor_name)
        if last_err and is_pure_greeting(q):
            text += (
                "\n\n_(Modèle cloud indisponible — essaie **Flash**.)_"
            )

    max_sent = 5
    try:
        max_sent = int(os.getenv("SONASID_CHAT_MAX_SENTENCES", "5") or "5")
    except ValueError:
        pass
    text = _clamp_reply_length(text, max_sentences=max(3, max_sent))

    return {
        "question": q,
        "message": text,
        "source": "conversational:llm",
    }


def _clamp_reply_length(text: str, *, max_sentences: int = 3) -> str:
    """Évite les pavés du modèle cloud sur les réponses conversationnelles."""
    t = (text or "").strip()
    if not t:
        return t
    parts = re.split(r"(?<=[.!?…])\s+", t)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) <= max_sentences:
        return t
    return " ".join(parts[:max_sentences]).strip()
