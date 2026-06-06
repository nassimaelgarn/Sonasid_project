"""Azure AI Foundry — API Inference (/models) pour Grok et modèles similaires."""

from __future__ import annotations

import os
from typing import Any, Optional

import requests


def _api_key() -> str:
    return (
        (os.getenv("AZURE_INFERENCE_API_KEY") or "").strip()
        or (os.getenv("AZURE_OPENAI_API_KEY") or "").strip()
    )


def azure_inference_configured() -> bool:
    return bool(_api_key() and (os.getenv("AZURE_INFERENCE_ENDPOINT") or "").strip())


def is_azure_inference_model_slug(slug: str) -> bool:
    return str(slug or "").strip().lower().startswith("azure-inference/")


def azure_inference_model_from_slug(slug: str) -> str:
    s = str(slug or "").strip()
    if not s.lower().startswith("azure-inference/"):
        return s
    return s.split("/", 1)[1].strip()


def invoke_azure_inference_chat(*, prompt: str, model: str, temperature: Optional[float] = None) -> str:
    api_key = _api_key()
    base_url = (os.getenv("AZURE_INFERENCE_ENDPOINT") or "").strip().rstrip("/")
    if not api_key or not base_url:
        raise RuntimeError("AZURE_INFERENCE_ENDPOINT ou clé Azure manquante")

    dep = (model or "").strip()
    if not dep:
        raise RuntimeError("Nom de modèle Azure Inference vide")

    temp = float(os.getenv("AZURE_INFERENCE_TEMPERATURE", "0.35")) if temperature is None else float(temperature)
    timeout_s = float(os.getenv("AZURE_INFERENCE_TIMEOUT", os.getenv("AZURE_OPENAI_TIMEOUT", "120")))

    payload: dict[str, Any] = {
        "model": dep,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temp,
    }

    api_version = (os.getenv("AZURE_INFERENCE_API_VERSION") or "2024-05-01-preview").strip()
    url = f"{base_url}/chat/completions"
    if api_version:
        url = f"{url}?api-version={api_version}"

    r = requests.post(
        url,
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout_s,
    )
    if r.status_code >= 400:
        detail = (r.text or "")[:400]
        raise RuntimeError(f"Azure Inference HTTP {r.status_code}: {detail}")

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
