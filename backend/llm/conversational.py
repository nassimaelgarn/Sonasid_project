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
    t = (text or "").strip()
    if not t:
        return False
    if is_pure_greeting(t):
        return False
    if looks_like_kpi_question(t):
        return True
    tl = t.lower()
    if re.search(r"\b(sql|requête|requete|tsql|query)\b", tl) and re.search(
        r"\b(arrivage|navire|tonnage|kpi|fournisseur|transfert|commande)\b", tl
    ):
        return True
    if re.search(r"\b(donne|donner|affiche|afficher|montre|montrez)\b", tl) and re.search(
        r"\b(sql|requête|requete)\b", tl
    ):
        return True
    return False


def _greeting_message(actor_name: str) -> str:
    name = (actor_name or "").strip()
    first = name.split()[0] if name else ""
    prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if prof in {"sonasid", "shipping", "port"}:
        if first:
            return f"Bonjour {first}. Que souhaitez-vous analyser sur le port et les arrivages ?"
        return "Bonjour. Que souhaitez-vous analyser sur le port et les arrivages ?"
    if first:
        return f"Bonjour {first}. Quel indicateur souhaitez-vous consulter ?"
    return "Bonjour. Quel indicateur souhaitez-vous consulter ?"


def _wellbeing_message(actor_name: str) -> str:
    name = (actor_name or "").strip()
    first = name.split()[0] if name else ""
    if first:
        return f"Très bien, merci {first}. Comment puis-je vous aider ?"
    return "Très bien, merci. Comment puis-je vous aider ?"


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
            "Ton registre est professionnel, concis et orienté métier (logistique portuaire, supply chain).\n"
            "Tu peux évoquer la logistique, le maritime ou la douane sans inventer de chiffres : "
            "pour les données chiffrées, invite à formuler une question avec période et indicateur.\n"
            "Ne liste pas d’exemples techniques sauf si l’utilisateur le demande.\n"
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
        + "Réponds en **1 à 2 phrases courtes**, ton professionnel. Pas de listes.\n"
        + "Ne termine pas systématiquement par une question.\n"
        + "Ne réponds jamais par « Résultat: 1 ». N’exécute pas de SQL.\n"
    )
    prompt = f"{sys}\n\nQuestion:\n{q}\n\nContexte (RAG, optionnel):\n{rag or '(vide)'}\n"

    text = ""
    last_err = ""
    from backend.agent.llm import invoke_chat_text

    models = []
    for mn in (
        (model_name or "").strip(),
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
            text = (invoke_chat_text(prompt=prompt, model_name=mn) or "").strip()
        except Exception as e:
            last_err = str(e) or repr(e)
            text = ""
        if text:
            break

    if not text:
        text = _greeting_message(actor_name)
        if last_err:
            text += (
                "\n\n_(Le modèle cloud est momentanément indisponible ; "
                "réessaie Flash ou vérifie OPENROUTER_API_KEY.)_"
            )

    text = _clamp_reply_length(text, max_sentences=3)

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
