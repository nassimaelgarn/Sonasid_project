"""
Reformulation LLM « dernier recours » : français libre → une phrase KPI canonique (sans SQL).

Deux backends :
- OpenRouter (cloud, clé API) — voir KPI_REWRITE_PROVIDER=openrouter ou auto si OPENROUTER_API_KEY
- Ollama (local) — voir KPI_REWRITE_PROVIDER=ollama ou auto en secours

Activé avec KPI_REWRITE_LLM=true (indépendant de USE_LLM / génération SQL).
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


def is_kpi_rewrite_enabled() -> bool:
    return os.getenv("KPI_REWRITE_LLM", "").strip().lower() in {"1", "true", "yes", "on"}


def _rewrite_provider_mode() -> str:
    v = (os.getenv("KPI_REWRITE_PROVIDER", "auto") or "auto").strip().lower()
    if v in {"openrouter", "or", "cloud"}:
        return "openrouter"
    if v in {"ollama", "llama", "local"}:
        return "ollama"
    return "auto"


def _build_rewrite_messages(*, user_question: str, extra_context: str) -> list:
    prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if prof in {"sonasid", "shipping", "port"}:
        from backend.llm.sonasid_prompts import sonasid_kpi_rewrite_domain

        sys = (
            sonasid_kpi_rewrite_domain()
            + "L'utilisateur écrit en français libre, souvent avec fautes d'orthographe — corrige-les mentalement.\n"
            "Tâche : reformuler en UNE phrase KPI claire que le moteur SQL comprend.\n"
            "Garde période (2025, 2025-01, janvier 2025), id fournisseur/navire, indicateur (tonnage importé, "
            "arrivages, navires actifs, déchargement, transfert, qualité…).\n"
            "Ne produis PAS de SQL ni d'explication.\n"
            'Réponds UNIQUEMENT en JSON : {"kpi_question":"..."}\n'
            'Si ce n\'est pas une demande de données port/arrivages : {"kpi_question":""}\n'
            "Exemples : « combien d arivages en 2025 » → tonnage/nombre arrivages en 2025 ; "
            "« tonage importé 2025 » → tonnage importé en 2025."
        )
    else:
        sys = (
            "Tu es un assistant pour un dashboard KPI d'aciérie.\n"
            "Tâche : reformuler la question utilisateur en UNE seule phrase courte, en français, "
            "compréhensible par un moteur de règles (mots-clés KPI + période si présente).\n"
            "Ignore les fautes d'orthographe.\n"
            "Ne produis PAS de SQL, pas de markdown, pas d'explication.\n"
            'Réponds UNIQUEMENT avec un JSON valide : {"kpi_question":"..."}\n'
            'Si ce n\'est pas une demande de KPI : {"kpi_question":""}\n'
            "KPI typiques : production, consommation électrique / oxygène / gpl / carbone, TD, TR, MTBF, MTTR, "
            "rendement, nombre de coulées, nombre de brames, poids ferrailles, etc.\n"
            "Préserve les dates (2025, 2025-01, du YYYY-MM-DD au YYYY-MM-DD)."
        )
    ctx = (extra_context or "").strip()
    user = f"Question utilisateur :\n{user_question.strip()}\n\nContexte (RAG, peut être vide) :\n{ctx or '(vide)'}\n"
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _parse_kpi_json(text: str) -> Optional[str]:
    if not text:
        return None
    s = text.strip()
    # Retirer fences éventuelles
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            q = data.get("kpi_question")
            if isinstance(q, str):
                q = q.strip()
                return q if q else None
    except Exception:
        pass
    m = re.search(r'\{\s*"kpi_question"\s*:\s*"([^"]*)"', s)
    if m:
        return m.group(1).strip() or None
    return None


def _openrouter_rewrite(
    user_question: str,
    *,
    extra_context: str,
) -> Tuple[Optional[str], str]:
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None, "OPENROUTER_API_KEY manquante"

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    model = (
        os.getenv("KPI_REWRITE_OPENROUTER_MODEL", "").strip()
        or os.getenv("OPENROUTER_KPI_REWRITE_MODEL", "").strip()
        or "stepfun/step-3.5-flash:free"
    )
    timeout_s = float(os.getenv("KPI_REWRITE_TIMEOUT_S", "45"))

    payload = {
        "model": model,
        "messages": _build_rewrite_messages(user_question=user_question, extra_context=extra_context),
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    site_url = os.getenv("OPENROUTER_SITE_URL", "").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    app_name = os.getenv("OPENROUTER_APP_NAME", "sonasid_project").strip()
    if app_name:
        headers["X-Title"] = app_name

    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        choices = body.get("choices") or []
        content = ""
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content") or ""
        kpi = _parse_kpi_json(content)
        if not kpi:
            return None, "OpenRouter: JSON kpi_question vide ou illisible"
        return kpi, "OK"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return None, f"OpenRouter HTTP {getattr(exc, 'code', '?')}: {detail}"
    except Exception as exc:
        return None, f"OpenRouter: {exc}"


def _ollama_chat_rewrite(
    user_question: str,
    *,
    extra_context: str,
) -> Tuple[Optional[str], str]:
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    model = (
        os.getenv("KPI_REWRITE_OLLAMA_MODEL", "").strip()
        or os.getenv("LLAMA_MODEL", "").strip()
        or "llama3.2:3b"
    )
    timeout_s = float(os.getenv("KPI_REWRITE_TIMEOUT_S", "45"))

    msgs = _build_rewrite_messages(user_question=user_question, extra_context=extra_context)
    # Ollama /api/chat attend roles system + user
    payload: Dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "stream": False,
    }
    req = urllib.request.Request(
        f"{base}/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        msg = (body.get("message") or {}) if isinstance(body, dict) else {}
        content = msg.get("content") or body.get("response") or ""
        kpi = _parse_kpi_json(str(content))
        if not kpi:
            return None, "Ollama: JSON kpi_question vide ou illisible"
        return kpi, "OK"
    except Exception as exc:
        return None, f"Ollama: {exc}"


def _llm_rewrite_json(
    user_question: str,
    *,
    extra_context: str,
    model_name: str = "",
) -> Tuple[Optional[str], str]:
    """Reformulation via invoke_chat_text (Azure / OpenRouter / Ollama)."""
    try:
        from backend.agent.llm import invoke_chat_text

        msgs = _build_rewrite_messages(user_question=user_question, extra_context=extra_context)
        prompt = "\n\n".join(f"{m['role'].upper()}:\n{m['content']}" for m in msgs)
        models: list[str] = []
        for mn in (
            (model_name or "").strip(),
            (os.getenv("SONASID_NARRATE_MODEL", "") or "").strip(),
            (os.getenv("SONASID_DEFAULT_CHAT_MODEL", "") or "").strip(),
            "kimi",
            "deepseek",
            "grok",
            "flash",
        ):
            if mn and mn not in models:
                models.append(mn)
        last_err = "aucun modèle"
        for mn in models:
            try:
                text = (
                    invoke_chat_text(
                        prompt=prompt,
                        model_name=mn,
                        temperature=0.0,
                    )
                    or ""
                ).strip()
                kpi = _parse_kpi_json(text)
                if kpi:
                    return kpi, f"llm:{mn}"
                last_err = f"{mn}: JSON vide"
            except Exception as e:
                last_err = f"{mn}: {e}"
        return None, last_err
    except Exception as exc:
        return None, str(exc)


def rewrite_kpi_question(
    user_question: str,
    *,
    extra_context: str = "",
    model_name: str = "",
) -> Tuple[Optional[str], str, str]:
    """
    Returns:
        (canonical_question_or_none, provider_used, reason)
    """
    mode = _rewrite_provider_mode()
    q = (user_question or "").strip()
    if not q:
        return None, "none", "question vide"

    # Priorité : modèle UI / Azure entreprise
    if model_name or (os.getenv("AZURE_OPENAI_API_KEY") or "").strip():
        kpi, reason = _llm_rewrite_json(q, extra_context=extra_context, model_name=model_name)
        if kpi:
            return kpi, reason.split(":", 1)[0] if ":" in reason else "llm", reason

    if mode == "openrouter":
        kpi, reason = _openrouter_rewrite(q, extra_context=extra_context)
        return kpi, "openrouter", reason

    if mode == "ollama":
        kpi, reason = _ollama_chat_rewrite(q, extra_context=extra_context)
        return kpi, "ollama", reason

    # auto
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        kpi, reason = _openrouter_rewrite(q, extra_context=extra_context)
        if kpi:
            return kpi, "openrouter", reason
        kpi2, reason2 = _ollama_chat_rewrite(q, extra_context=extra_context)
        if kpi2:
            return kpi2, "ollama", f"openrouter_fallback:{reason} -> {reason2}"
        return None, "openrouter+ollama", f"openrouter:{reason}; ollama:{reason2}"

    kpi, reason = _ollama_chat_rewrite(q, extra_context=extra_context)
    return kpi, "ollama", reason
