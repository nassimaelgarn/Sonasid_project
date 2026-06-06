"""Speech-to-text via OpenRouter (Whisper)."""

from __future__ import annotations

import base64
import os
from typing import Optional, Tuple

import requests


def transcribe_audio_bytes(
    data: bytes,
    *,
    fmt: str = "webm",
    language: str = "fr",
) -> Tuple[Optional[str], Optional[str]]:
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        return None, "OPENROUTER_API_KEY manquante (dictée serveur indisponible)."

    if not data:
        return None, "Audio vide."

    max_bytes = 25 * 1024 * 1024
    if len(data) > max_bytes:
        return None, "Enregistrement trop long (max 25 Mo)."

    model = (os.getenv("OPENROUTER_STT_MODEL") or "openai/whisper-large-v3").strip()
    base_url = (os.getenv("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1").strip().rstrip("/")
    timeout_s = float(os.getenv("OPENROUTER_STT_TIMEOUT", os.getenv("OPENROUTER_TIMEOUT", "90")))

    audio_fmt = (fmt or "webm").strip().lower().lstrip(".")
    b64 = base64.b64encode(data).decode("ascii")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    site_url = (os.getenv("OPENROUTER_SITE_URL") or "").strip()
    if site_url:
        headers["HTTP-Referer"] = site_url
    app_name = (os.getenv("OPENROUTER_APP_NAME") or "sonasid_project").strip()
    if app_name:
        headers["X-OpenRouter-Title"] = app_name

    payload = {
        "model": model,
        "input_audio": {"data": b64, "format": audio_fmt},
    }
    lang = (language or "").strip()
    if lang:
        payload["language"] = lang

    try:
        resp = requests.post(
            f"{base_url}/audio/transcriptions",
            headers=headers,
            json=payload,
            timeout=timeout_s,
        )
    except requests.RequestException as exc:
        return None, f"Transcription indisponible ({exc.__class__.__name__})."

    if resp.status_code >= 400:
        detail = ""
        try:
            body = resp.json()
            detail = str(body.get("error") or body.get("message") or "").strip()
        except Exception:
            detail = (resp.text or "").strip()[:200]
        return None, detail or f"Transcription refusée (HTTP {resp.status_code})."

    try:
        body = resp.json()
    except Exception:
        return None, "Réponse transcription invalide."

    text = str(body.get("text") or "").strip()
    if not text:
        return None, "Aucune voix détectée."
    return text, None
