"""
Schéma et formules Sonasid pour Text-to-SQL (contexte LLM).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


@lru_cache(maxsize=1)
def load_schema_markdown() -> str:
    docs = _project_root() / "docs" / "dictionnaire_sonasid.md"
    if docs.is_file():
        try:
            return docs.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return _FALLBACK_SCHEMA


@lru_cache(maxsize=1)
def load_formulas_sql() -> str:
    p = _project_root() / "docs" / "formules_kpi_officielles.sql"
    if p.is_file():
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass
    return ""


def compact_schema_for_prompt(*, max_chars: int = 14000) -> str:
    raw = load_schema_markdown()
    if len(raw) <= max_chars:
        return raw
    return raw[: max_chars - 80] + "\n\n… (schéma tronqué — voir docs/dictionnaire_sonasid.md)"


def formulas_for_prompt() -> str:
    return load_formulas_sql().strip()


def allowed_table_names() -> frozenset[str]:
    """Noms de tables autorisés (sans préfixe dbo.)."""
    defaults = {
        "ARRIVAGE",
        "COMMANDE",
        "TRANSFERT",
        "NAVIRE",
        "QUALITE",
        "NOMINATION_NAVIRE",
        "SUIVI_DECHARGEMENT",
        "FOURNISSEUR",
        "BANQUE",
        "PORT",
        "DEVISE",
        "SHIFT",
        "STATUT",
        "UTILISATEUR",
        "COMPAGNIE_MARITIME",
        "TRANSITAIRE",
        "NATURE_MARCHANDISE",
        "PRESTATAIRE",
        "CONDUCTEUR",
        "FLOTTE",
    }
    env_keys = (
        "AZURE_SQL_TABLE_ARRIVAGE",
        "AZURE_SQL_TABLE_COMMANDE",
        "AZURE_SQL_TABLE_TRANSFERT",
        "AZURE_SQL_TABLE_NAVIRE",
        "AZURE_SQL_TABLE_QUALITE",
        "AZURE_SQL_TABLE_NOMINATION_NAVIRE",
        "AZURE_SQL_TABLE_SUIVI_DECHARGEMENT",
        "AZURE_SQL_TABLE_FOURNISSEUR",
    )
    names = set(defaults)
    for ek in env_keys:
        val = (os.getenv(ek, "") or "").strip()
        if not val:
            continue
        base = val.split(".")[-1].upper()
        if base:
            names.add(base)
    return frozenset(names)


def guess_formula_hint(question: str) -> str:
    """Indication métier courte pour l'utilisateur (pas le SQL)."""
    ql = (question or "").lower()
    if re.search(r"\bsurestar|demurrage|d[eéè]murrage", ql):
        return "Surestaries : champs Arrivage_Demurrage / Arrivage_SurestarieCalcule ou NominationNavire_DemurrageRate."
    if re.search(r"\btransf", ql) and re.search(r"\bqual", ql):
        return "Tonnage transféré par qualité : SUM(Transfert_PoidsNet) via TRANSFERT → COMMANDE → QUALITE."
    if re.search(r"\bimport|marchandise|valeur", ql) and re.search(r"\bprix|valeur", ql):
        return "Valeur : SUM(Commande_Tonnage × Commande_PrixUnitaireFinal) ou SUM(Arrivage_TonnageTotal) selon le grain demandé."
    if re.search(r"\bfournisseur", ql) and re.search(r"\b(quels?|top|plus|classement)\b", ql):
        return "Classement fournisseurs : COUNT(DISTINCT Arrivage_Id) + SUM(Arrivage_TonnageTotal) GROUP BY FOURNISSEUR."
    if re.search(r"\bimport|marchandise", ql):
        return "Tonnage importé : SUM(Arrivage_TonnageTotal) sur ARRIVAGE (filtrer par dates si période)."
    if re.search(r"\bd[eéè]charg", ql):
        return "Déchargement : SUIVI_DECHARGEMENT (quantités par shift) ou snapshot ARRIVAGE (FinDechargementFlag)."
    if re.search(r"\bnavires?\b", ql) and re.search(r"\bactifs?\b", ql):
        return "Navires actifs (référentiel) : COUNT(*) FROM NAVIRE WHERE Navire_Active = 1."
    if re.search(r"\barrivages?\b", ql):
        return "Arrivages : COUNT(*) ou agrégats sur dbo.ARRIVAGE (dates = Arrivage_DateCreation par défaut)."
    return "Requête générée à partir du dictionnaire Sonasid (tables port / arrivages)."


_FALLBACK_SCHEMA = """
Tables principales: dbo.ARRIVAGE, dbo.COMMANDE, dbo.TRANSFERT, dbo.NAVIRE, dbo.QUALITE,
dbo.NOMINATION_NAVIRE, dbo.SUIVI_DECHARGEMENT, dbo.FOURNISSEUR.
Voir docs/dictionnaire_sonasid.md pour le détail des colonnes.
"""
