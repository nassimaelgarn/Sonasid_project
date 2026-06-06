"""
Mode Sonasid ouvert : questions libres → LLM Text-to-SQL + réponse naturelle.
Les règles KPI restent un accélérateur (fallback), pas le routeur principal.
"""
from __future__ import annotations

import os
import re


def is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def is_sonasid_open_mode() -> bool:
    if not is_sonasid_profile():
        return False
    return (os.getenv("SONASID_OPEN_LLM", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_sonasid_llm_available() -> bool:
    if (os.getenv("USE_LLM", "false") or "false").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    if (os.getenv("OPENROUTER_API_KEY", "") or "").strip():
        return True
    if (os.getenv("AZURE_OPENAI_API_KEY", "") or "").strip():
        return True
    return False


def is_sonasid_llm_first() -> bool:
    """LLM avant les règles KPI (défaut : non — règles d'abord, LLM en secours)."""
    if not is_sonasid_open_mode() or not is_sonasid_llm_available():
        return False
    v = (os.getenv("SONASID_LLM_FIRST", "false") or "false").strip().lower()
    return v in {"1", "true", "yes", "on"}


def is_sonasid_llm_narrate() -> bool:
    if not is_sonasid_profile():
        return False
    v = (os.getenv("SONASID_LLM_NARRATE", "true") or "true").strip().lower()
    return v in {"1", "true", "yes", "on"} and is_sonasid_llm_available()


def is_sonasid_kpi_rewrite_enabled() -> bool:
    """Reformulation LLM avant échec KPI — activée par défaut si Azure ou KPI_REWRITE_LLM."""
    from backend.llm.kpi_rewrite import is_kpi_rewrite_enabled

    if is_sonasid_open_mode():
        v = (os.getenv("SONASID_KPI_REWRITE", "") or "").strip().lower()
        if v in {"0", "false", "no", "off"}:
            return False
        if v in {"1", "true", "yes", "on"}:
            return True
        if (os.getenv("AZURE_OPENAI_API_KEY") or "").strip():
            return True
        return is_kpi_rewrite_enabled()
    return is_kpi_rewrite_enabled()


_SONASID_DOMAIN = re.compile(
    r"\b("
    r"port|arrivage|arrivages|arrivé|arrive|navire|navires|tonnage|marchandise|marchandises|"
    r"import|importé|importe|fournisseur|qualité|qualite|transfert|commande|déchargement|"
    r"dechargement|accostage|demurrage|démurrage|surestarie|surestaries|kpi|kip|"
    r"cargo|matière|matiere|booking|shift|douane|licence|banque|devise"
    r")\b",
    re.I,
)


def looks_like_sonasid_data_question(text: str) -> bool:
    """True si la question touche probablement la base port / arrivages."""
    if not is_sonasid_profile():
        return False
    t = (text or "").strip()
    if not t or len(t) < 3:
        return False
    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question, is_sonasid_company_question

        if is_schema_metadata_question(t):
            return False
        if is_sonasid_company_question(t):
            return False
    except Exception:
        pass
    try:
        from backend.llm.sonasid_typo import fuzzy_contains

        tl = t.lower()
        for kw in (
            "navire",
            "arrivage",
            "tonnage",
            "fournisseur",
            "transfert",
            "dechargement",
            "import",
            "qualite",
            "commande",
            "port",
            "kpi",
        ):
            if fuzzy_contains(tl, kw):
                return True
    except Exception:
        pass
    if _SONASID_DOMAIN.search(t):
        return True
    if re.search(r"\b(combien|nombre|total|liste|top|quels|quelles|compare|évolution|evolution|tendance)\b", t, re.I):
        return True
    if re.search(r"\b(20\d{2}|janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre)\b", t, re.I):
        if re.search(r"\b(port|sonasid|maritime|cargo|terminal)\b", t, re.I):
            return True
    return False
