"""
Registre des modèles chat Sonasid — OpenRouter, Azure OpenAI, Ollama.

Format SONASID_CHAT_MODELS (pipe-separated) :
  id:slug:Label:Hint

Slugs :
  - OpenRouter : openai/gpt-4o, openrouter/free, …
  - Azure      : azure/Kimi-K2.6  (déploiement sur AZURE_OPENAI_ENDPOINT)
  - Local      : ollama

Exemple Azure :
  kimi:azure/Kimi-K2.6:Kimi K2.6:Azure · entreprise|gpt4o:azure/Gpt-4o:GPT-4o:Azure
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List


def _fallback_slug() -> str:
    return (os.getenv("OPENROUTER_CHAT_FALLBACK", "openai/gpt-4o-mini") or "openai/gpt-4o-mini").strip()


@dataclass(frozen=True)
class ChatModelSpec:
    id: str
    slug: str
    label: str
    hint: str


def _azure_default_specs() -> List[ChatModelSpec]:
    """3 déploiements Azure (même endpoint / clé) si configurés."""
    from backend.llm.azure_openai_chat import azure_openai_configured

    if not azure_openai_configured():
        return []

    specs: List[ChatModelSpec] = []
    defaults = [
        ("kimi", "Kimi-K2.6", "Kimi K2.6", "Azure · Kimi"),
        ("azure2", "", "Modèle Azure 2", "Azure · entreprise"),
        ("azure3", "", "Modèle Azure 3", "Azure · entreprise"),
    ]
    for i, (mid, default_dep, label, hint) in enumerate(defaults, start=1):
        dep = (
            (os.getenv(f"AZURE_OPENAI_DEPLOYMENT_{i}") or "").strip()
            or (default_dep if i == 1 else "").strip()
        )
        lbl = (os.getenv(f"AZURE_OPENAI_LABEL_{i}") or label).strip()
        if dep:
            specs.append(ChatModelSpec(mid, f"azure/{dep}", lbl, hint))
    return specs


def _openrouter_default_specs() -> List[ChatModelSpec]:
    fb = _fallback_slug()
    return [
        ChatModelSpec("gpt4o", os.getenv("OPENROUTER_MODEL_GPT4O", "openai/gpt-4o").strip(), "GPT-4o", "OpenRouter"),
        ChatModelSpec("gpt41", os.getenv("OPENROUTER_MODEL_GPT41", "openai/gpt-4.1").strip(), "GPT-4.1", "OpenRouter"),
        ChatModelSpec("o3mini", os.getenv("OPENROUTER_MODEL_O3MINI", "openai/o3-mini").strip(), "O3 mini", "OpenRouter"),
        ChatModelSpec("flash", os.getenv("OPENROUTER_MODEL_FLASH", fb).strip() or fb, "Flash", "OpenRouter · rapide"),
        ChatModelSpec("trinity", fb, "Trinity", "Legacy"),
    ]


def _default_specs() -> List[ChatModelSpec]:
    azure = _azure_default_specs()
    if azure:
        out = list(azure)
        fb = _fallback_slug()
        if (os.getenv("OPENROUTER_API_KEY") or "").strip():
            out.append(ChatModelSpec("flash", fb, "Flash", "OpenRouter · secours"))
        out.append(ChatModelSpec("ollama", "ollama", "Llama3.1", "Local · Ollama"))
        return out
    specs = _openrouter_default_specs()
    specs.append(ChatModelSpec("ollama", "ollama", "Llama3.1", "Local · Ollama"))
    return specs


def _parse_env_models(raw: str) -> List[ChatModelSpec]:
    out: List[ChatModelSpec] = []
    for chunk in (raw or "").split("|"):
        part = chunk.strip()
        if not part:
            continue
        fields = part.split(":", 3)
        if len(fields) < 2:
            continue
        mid = fields[0].strip().lower()
        slug = fields[1].strip()
        label = fields[2].strip() if len(fields) > 2 else mid
        hint = fields[3].strip() if len(fields) > 3 else ""
        if mid and slug:
            out.append(ChatModelSpec(id=mid, slug=slug, label=label or mid, hint=hint))
    return out


def list_chat_models() -> List[ChatModelSpec]:
    raw = (os.getenv("SONASID_CHAT_MODELS") or "").strip()
    if raw:
        parsed = _parse_env_models(raw)
        if parsed:
            return parsed
    return _default_specs()


def chat_model_map() -> Dict[str, str]:
    m: Dict[str, str] = {}
    for spec in list_chat_models():
        m[spec.id] = spec.slug
    fb = _fallback_slug()
    m.setdefault("mistral", m.get("flash", fb))
    return m


def default_chat_model_id() -> str:
    d = (os.getenv("SONASID_DEFAULT_CHAT_MODEL", "") or "").strip().lower()
    if d and d in chat_model_map():
        return d
    for preferred in ("kimi", "gpt4o", "gpt41", "flash"):
        if preferred in chat_model_map():
            return preferred
    specs = list_chat_models()
    return specs[0].id if specs else "flash"


def resolve_chat_model(name: str) -> str:
    n = (name or "").strip().lower()
    if not n:
        return ""
    mapped = chat_model_map().get(n)
    if mapped:
        return mapped
    return (name or "").strip()


def chat_models_for_api() -> List[Dict[str, str]]:
    dots = ("bg-rose-500", "bg-sky-500", "bg-violet-500", "bg-amber-500", "bg-fuchsia-500", "bg-emerald-500")
    rows: List[Dict[str, str]] = []
    for i, spec in enumerate(list_chat_models()):
        rows.append(
            {
                "id": spec.id,
                "label": spec.label,
                "hint": spec.hint,
                "slug": spec.slug,
                "dot": dots[i % len(dots)],
            }
        )
    return rows
