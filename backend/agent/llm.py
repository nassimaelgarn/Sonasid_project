import os
from typing import Any, Optional

from langchain_openai import ChatOpenAI
import requests

from backend.llm.azure_inference_chat import (
    azure_inference_model_from_slug,
    invoke_azure_inference_chat,
    is_azure_inference_model_slug,
)
from backend.llm.azure_openai_chat import (
    azure_deployment_from_slug,
    invoke_azure_chat,
    is_azure_model_slug,
)
from backend.llm.model_registry import _fallback_slug, resolve_chat_model

OPENROUTER_CHAT_FALLBACK = _fallback_slug()


def resolve_model_name(name: str) -> str:
    return resolve_chat_model(name)


def get_openrouter_chat_model(*, streaming: bool = False, model_name: str = "", temperature: Optional[float] = None):
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY manquante")

    base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip().rstrip("/")
    model = resolve_model_name(model_name) or os.getenv("OPENROUTER_MODEL", OPENROUTER_CHAT_FALLBACK).strip()
    temp = float(os.getenv("AGENT_TEMPERATURE", "0")) if temperature is None else float(temperature)

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=temp,
        streaming=streaming,
    )


def _is_ollama(model_name: str) -> bool:
    n = (model_name or "").strip().lower()
    if n in {"ollama", "local"}:
        return True
    if resolve_model_name(model_name) == "ollama":
        return True
    slug = resolve_model_name(model_name)
    if is_azure_model_slug(slug) or is_azure_inference_model_slug(slug):
        return False
    if ":" in n and not n.startswith("http"):
        return True
    return False


def _ollama_model_name(model_name: str) -> str:
    n = (model_name or "").strip()
    if not n or n.strip().lower() in {"ollama", "local"}:
        return os.getenv("OLLAMA_MODEL", "llama3.1:8b").strip() or "llama3.1:8b"
    return n


def _normalize_message_content(content: Any) -> str:
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


def invoke_chat_text(*, prompt: str, model_name: str = "", temperature: Optional[float] = None) -> str:
    if _is_ollama(model_name):
        return invoke_ollama_chat(prompt=prompt, model_name=model_name)

    primary = resolve_model_name(model_name) or os.getenv("OPENROUTER_MODEL", OPENROUTER_CHAT_FALLBACK).strip()
    chain = [primary]
    fb = OPENROUTER_CHAT_FALLBACK
    if fb and fb not in chain and not is_azure_model_slug(primary) and not is_azure_inference_model_slug(primary):
        chain.append(fb)

    last_err: Optional[Exception] = None
    tried: list[str] = []
    for slug in chain:
        if not slug or slug in tried:
            continue
        tried.append(slug)
        try:
            if is_azure_inference_model_slug(slug):
                text = invoke_azure_inference_chat(
                    prompt=prompt,
                    model=azure_inference_model_from_slug(slug),
                    temperature=temperature,
                )
            elif is_azure_model_slug(slug):
                text = invoke_azure_chat(
                    prompt=prompt,
                    deployment=azure_deployment_from_slug(slug),
                    temperature=temperature,
                )
            else:
                model = get_openrouter_chat_model(streaming=False, model_name=slug, temperature=temperature)
                resp = model.invoke([{"role": "user", "content": prompt}])
                text = _normalize_message_content(getattr(resp, "content", None))
            if text:
                return text
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if is_azure_model_slug(slug) or is_azure_inference_model_slug(slug):
                continue
            if "404" not in msg and "no endpoints found" not in msg and "not found" not in msg:
                raise
    if last_err:
        raise last_err
    return ""
