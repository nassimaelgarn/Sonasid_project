import os
from typing import Any

from langchain_openai import ChatOpenAI
import requests


# OpenRouter free slugs change often; arcee-ai/trinity and stepfun/step-3.5-flash return 404 as of 2026.
OPENROUTER_CHAT_FALLBACK = (os.getenv("OPENROUTER_CHAT_FALLBACK", "openrouter/free") or "openrouter/free").strip()

MODEL_PRESETS = {
    # UI labels kept for compatibility; all map to a working OpenRouter model.
    "trinity": OPENROUTER_CHAT_FALLBACK,
    "flash": OPENROUTER_CHAT_FALLBACK,
    "mistral": OPENROUTER_CHAT_FALLBACK,
    "ollama": "ollama",
}


def resolve_model_name(name: str) -> str:
    n = (name or "").strip().lower()
    if not n:
        return ""
    return MODEL_PRESETS.get(n, name.strip())


def get_openrouter_chat_model(*, streaming: bool = False, model_name: str = ""):
    """
    OpenRouter uses an OpenAI-compatible API.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY manquante")

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    model = resolve_model_name(model_name) or os.getenv("OPENROUTER_MODEL", OPENROUTER_CHAT_FALLBACK).strip()

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=float(os.getenv("AGENT_TEMPERATURE", "0")),
        streaming=streaming,
    )


def _is_ollama(model_name: str) -> bool:
    n = (model_name or "").strip().lower()
    if n in {"ollama", "local"}:
        return True
    # Allow passing a direct Ollama model id like "llama3.1:8b"
    if ":" in n and not n.startswith("http"):
        return True
    return False


def _ollama_model_name(model_name: str) -> str:
    n = (model_name or "").strip()
    if not n or n.strip().lower() in {"ollama", "local"}:
        return os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip() or "llama3.1:8b"
    return n


def _normalize_message_content(content: Any) -> str:
    """
    OpenRouter / certains modèles renvoient parfois une liste de blocs ({type,text}) au lieu d'une chaîne.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
                elif "text" in block:
                    parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
    return str(content).strip()


def invoke_ollama_chat(*, prompt: str, model_name: str = "") -> str:
    """
    Minimal Ollama chat call (no LangChain dependency).
    Requires Ollama running locally (default http://127.0.0.1:11434).
    """
    base = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    model = _ollama_model_name(model_name)
    r = requests.post(
        f"{base}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        },
        timeout=float(os.getenv("OLLAMA_TIMEOUT_S", "30")),
    )
    r.raise_for_status()
    data = r.json() or {}
    msg = (data.get("message") or {}) if isinstance(data, dict) else {}
    return (msg.get("content") or "").strip()


def invoke_chat_text(*, prompt: str, model_name: str = "") -> str:
    """
    Unified text invocation for the agent router/chat.
    - model_name='trinity'/'flash'/custom OpenRouter slug -> OpenRouter
    - model_name='ollama' or 'llama3.1:8b' -> Ollama local
    Tries the requested model, then OPENROUTER_CHAT_FALLBACK on 404/endpoint errors.
    """
    if _is_ollama(model_name):
        return invoke_ollama_chat(prompt=prompt, model_name=model_name)

    tried: list[str] = []
    primary = resolve_model_name(model_name) or os.getenv("OPENROUTER_MODEL", OPENROUTER_CHAT_FALLBACK).strip()
    chain = [primary]
    if OPENROUTER_CHAT_FALLBACK not in chain:
        chain.append(OPENROUTER_CHAT_FALLBACK)

    last_err: Optional[Exception] = None
    for slug in chain:
        if not slug or slug in tried:
            continue
        tried.append(slug)
        try:
            model = get_openrouter_chat_model(streaming=False, model_name=slug)
            resp = model.invoke([{"role": "user", "content": prompt}])
            text = _normalize_message_content(getattr(resp, "content", None))
            if text:
                return text
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            # Only retry fallback on missing model / endpoint; don't mask auth errors.
            if "404" not in msg and "no endpoints found" not in msg and "not found" not in msg:
                raise
    if last_err:
        raise last_err
    return ""

