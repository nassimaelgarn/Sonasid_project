import json
import os
import re
import urllib.request
import urllib.error


def _load_system_prompt():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(base_dir, "prompts", "system_sql.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


DB_SCHEMA_HINT = """
SQLite tables:
- "01_PAF"(CSO_DATE, CSO_SEMAINE, CSO_NUM_COULEE, CSO_GRADE, CSD_POIDS, FERR_NOM, CAT_Nom)
- "02_EAF"(HEATID, STEELGRADECODE_ACT, HEATDEPARTURE_ACT, TOTAL_ELEC_EGY, BURNER_TOTALOXY, BURNER_TOTALGAS, INJ_CARBON, TAPPING_WEIGHT)
- "03_LF"(HEATID, STEELGRADECODE_ACT, HEATDEPARTURE_ACT, ELEC_CONS_TOTAL)
- "04_CCM_Coulée"(HEATID, GRADE_CODE, LADLE_OPEN_TIME, LADLE_CLOSE_TIME)
- "05_CCM_Brame"(HEAT_STEEL_ID, PIECE_WEIGHT_MEAS, NOMINAL_THICKNESS, NOMINAL_WIDTH_HEAD, CUT_TIME)
- "EAF_Arrêts"(HEATID, DELAYSTART, DELAYEND, DURATION, SECTIONNAME)
"""


def is_llm_enabled():
    flag = os.getenv("USE_LLM", "false").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _build_prompt(question: str, *, extra_context: str = "") -> str:
    system_prompt = _load_system_prompt()
    ctx = (extra_context or "").strip()
    return f"""
{system_prompt}

Tu es un expert SQL industriel. Génère UNE requête SQL SQLite valide.
Contraintes:
- Retourner uniquement du SQL brut (pas de markdown, pas de commentaires).
- Une seule requête SELECT (ou WITH ... SELECT).
- Utiliser uniquement les tables/colonnes du schéma ci-dessous.
- Si la question est ambiguë, choisir l'interprétation KPI la plus probable.

{DB_SCHEMA_HINT}

Contexte (RAG):
{ctx if ctx else "(vide)"}

Question:
{question}
"""


def _extract_sql(text: str):
    if not text:
        return None
    cleaned = text.strip()
    cleaned = cleaned.replace("```sql", "").replace("```", "").strip()
    cleaned = cleaned.strip('"\'' " \n\t\r")

    # Keep first SELECT/CTE block.
    match = re.search(r"(?is)\b(with|select)\b.*", cleaned)
    if not match:
        return None
    sql = match.group(0).strip()
    sql = sql.strip('"\'' " \n\t\r")
    if ";" in sql:
        sql = sql.split(";", 1)[0].strip()
    sql = sql.strip('"\'' " \n\t\r")
    return sql


def _openrouter_generate(question: str, *, extra_context: str = ""):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return None, "OPENROUTER_API_KEY manquante"

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    model = os.getenv("OPENROUTER_MODEL", os.getenv("OPENROUTER_CHAT_FALLBACK", "openrouter/free")).strip()
    timeout_s = float(os.getenv("OPENROUTER_TIMEOUT", "120"))
    prompt = _build_prompt(question, extra_context=extra_context)

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Tu ne renvoies que du SQL brut."},
            {"role": "user", "content": prompt},
        ],
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
        content = None
        if choices:
            msg = (choices[0] or {}).get("message") or {}
            content = msg.get("content")
        sql = _extract_sql(content or "")
        if not sql:
            return None, "Aucun SQL exploitable renvoyé par OpenRouter"
        return sql, "OK"
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return None, f"Erreur OpenRouter HTTP {getattr(exc, 'code', '?')}: {detail}"
    except Exception as exc:
        return None, f"Erreur OpenRouter: {exc}"


def _normalize_ollama_endpoint(url: str) -> str:
    """Accepte http://127.0.0.1:11434 ou la route complète /api/generate."""
    u = (url or "").strip().rstrip("/")
    if not u:
        return "http://127.0.0.1:11434/api/generate"
    if "/api/" in u:
        return u
    return u + "/api/generate"


def _llama_generate(question: str, *, extra_context: str = ""):
    # Ollama par défaut : https://github.com/ollama/ollama/blob/main/docs/api.md
    endpoint = _normalize_ollama_endpoint(os.getenv("LLAMA_ENDPOINT", "http://127.0.0.1:11434/api/generate"))
    model = os.getenv("LLAMA_MODEL", "llama3.2:3b")
    timeout_s = float(os.getenv("LLAMA_TIMEOUT", "120"))
    prompt = _build_prompt(question, extra_context=extra_context)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        text = body.get("response", "")
        sql = _extract_sql(text)
        if not sql:
            return None, "Aucun SQL exploitable renvoyé par Llama"
        return sql, "OK"
    except Exception as exc:
        return None, f"Erreur Llama endpoint: {exc}"


def generate_sql_with_llm(question: str, *, extra_context: str = ""):
    """
    Returns:
      (sql: str | None, provider: str, reason: str)
    """
    provider = os.getenv("LLM_PROVIDER", "llama").strip().lower()

    profile = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if profile in {"sonasid", "shipping", "port"}:
        from backend.llm.sonasid_text_to_sql import generate_sonasid_sql_with_llm

        return generate_sonasid_sql_with_llm(question, extra_context=extra_context)

    if provider in ("llama", "ollama"):
        sql, reason = _llama_generate(question, extra_context=extra_context)
        return sql, "llama", reason

    if provider in ("openrouter", "or"):
        sql, reason = _openrouter_generate(question, extra_context=extra_context)
        return sql, "openrouter", reason

    return None, provider, "LLM_PROVIDER non supporté (utilise llama, ollama ou openrouter)"
