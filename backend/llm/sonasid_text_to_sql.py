"""
Génération T-SQL Sonasid via LLM (questions ouvertes, hors règles KPI).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional, Tuple

from backend.llm.sonasid_schema import compact_schema_for_prompt, formulas_for_prompt


def _load_system_prompt() -> str:
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base, "prompts", "sonasid_system_sql.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _extract_sql(text: str) -> Optional[str]:
    if not text:
        return None
    cleaned = text.strip().replace("```sql", "").replace("```", "").strip()
    match = re.search(r"(?is)\b(with|select)\b.*", cleaned)
    if not match:
        return None
    sql = match.group(0).strip()
    if ";" in sql:
        sql = sql.split(";", 1)[0].strip()
    return sql


def _build_prompt(question: str, *, extra_context: str = "") -> str:
    system = _load_system_prompt()
    schema = compact_schema_for_prompt()
    formulas = formulas_for_prompt()
    ctx = (extra_context or "").strip()
    return f"""
{system}

=== SCHÉMA (dictionnaire Sonasid) ===
{schema}

=== FORMULES KPI OFFICIELLES (référence) ===
{formulas if formulas else "(voir schéma)"}

=== CONTEXTE RAG ===
{ctx if ctx else "(vide)"}

=== QUESTION UTILISATEUR ===
{question}
"""


def _openrouter_generate(question: str, *, extra_context: str = "") -> Tuple[Optional[str], str]:
    api_key = (os.getenv("OPENROUTER_API_KEY", "") or "").strip()
    if not api_key:
        return None, "OPENROUTER_API_KEY manquante"

    base_url = (os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") or "").strip().rstrip("/")
    model = (
        os.getenv("SONASID_SQL_MODEL", "")
        or os.getenv("OPENROUTER_MODEL", "")
        or os.getenv("OPENROUTER_CHAT_FALLBACK", "openrouter/free")
    ).strip()
    timeout_s = float(os.getenv("OPENROUTER_TIMEOUT", "120"))
    prompt = _build_prompt(question, extra_context=extra_context)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Tu ne renvoies que du T-SQL brut (SELECT)."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    site_url = (os.getenv("OPENROUTER_SITE_URL", "") or "").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    app_name = (os.getenv("OPENROUTER_APP_NAME", "sonasid_project") or "").strip()
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
        sql = _extract_sql(content)
        if not sql:
            return None, "Aucun T-SQL exploitable renvoyé par OpenRouter"
        return sql, "OK"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return None, f"Erreur OpenRouter HTTP {getattr(exc, 'code', '?')}: {detail}"
    except Exception as exc:
        return None, f"Erreur OpenRouter: {exc}"


def _ollama_generate(question: str, *, extra_context: str = "") -> Tuple[Optional[str], str]:
    endpoint = (os.getenv("LLAMA_ENDPOINT", "http://127.0.0.1:11434/api/generate") or "").strip()
    if "/api/" not in endpoint:
        endpoint = endpoint.rstrip("/") + "/api/generate"
    model = (os.getenv("LLAMA_MODEL", "llama3.2:3b") or "").strip()
    timeout_s = float(os.getenv("LLAMA_TIMEOUT", "120"))
    prompt = _build_prompt(question, extra_context=extra_context)
    payload = {"model": model, "prompt": prompt, "stream": False}
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        sql = _extract_sql(body.get("response", ""))
        if not sql:
            return None, "Aucun T-SQL exploitable renvoyé par Ollama"
        return sql, "OK"
    except Exception as exc:
        return None, f"Erreur Ollama: {exc}"


def generate_sonasid_sql_with_llm(
    question: str, *, extra_context: str = ""
) -> Tuple[Optional[str], str, str]:
    """
    Returns (sql, provider, reason).
    """
    provider = (os.getenv("LLM_PROVIDER", "openrouter") or "openrouter").strip().lower()
    if provider in {"llama", "ollama"}:
        sql, reason = _ollama_generate(question, extra_context=extra_context)
        return sql, "llama", reason
    if provider in {"openrouter", "or"}:
        sql, reason = _openrouter_generate(question, extra_context=extra_context)
        return sql, "openrouter", reason
    return None, provider, "LLM_PROVIDER non supporté (openrouter ou ollama)"
