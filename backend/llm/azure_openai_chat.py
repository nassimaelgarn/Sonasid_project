"""Azure AI Foundry / Azure OpenAI — API compatible OpenAI v1."""

from __future__ import annotations

import os
from typing import Any, Optional

import requests


def azure_openai_configured() -> bool:
    return bool(
        (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
        and (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip()
    )


def is_azure_model_slug(slug: str) -> bool:
    return str(slug or "").strip().lower().startswith("azure/")


def azure_deployment_from_slug(slug: str) -> str:
    s = str(slug or "").strip()
    if not s.lower().startswith("azure/"):
        return s
    return s.split("/", 1)[1].strip()


def invoke_azure_chat(*, prompt: str, deployment: str, temperature: Optional[float] = None) -> str:
    api_key = (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    base_url = (os.getenv("AZURE_OPENAI_ENDPOINT") or "").strip().rstrip("/")
    if not api_key or not base_url:
        raise RuntimeError("AZURE_OPENAI_API_KEY ou AZURE_OPENAI_ENDPOINT manquant")

    dep = (deployment or "").strip()
    if not dep:
        raise RuntimeError("Nom de déploiement Azure vide")

    temp = float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.35")) if temperature is None else float(temperature)
    timeout_s = float(os.getenv("AZURE_OPENAI_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "120")))

    payload: dict[str, Any] = {
        "model": dep,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp,
    }

    r = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_s,
    )
    if r.status_code >= 400:
        detail = (r.text or "")[:400]
        raise RuntimeError(f"Azure OpenAI HTTP {r.status_code}: {detail}")

    data = r.json() or {}
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("text"):
                parts.append(str(block["text"]))
        return "".join(parts).strip()
    return str(content or "").strip()
