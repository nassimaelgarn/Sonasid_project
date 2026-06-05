"""
Schéma et formules Sonasid pour Text-to-SQL (contexte LLM).
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


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


def is_schema_metadata_question(text: str) -> bool:
    """Question sur le schéma / tables / relations (sans chiffres KPI)."""
    if not _is_sonasid_profile():
        return False
    ql = (text or "").lower()
    if re.search(
        r"\b(noms?\s+des\s+tables|tables\s+et\s+leurs\s+relations|mod[eè]le\s+relationnel)\b", ql
    ):
        return True
    has_table = bool(
        re.search(r"\b(tables?|sch[eé]ma|dictionnaire|bdd|base\s+de\s+donn[eé]es)\b", ql)
    )
    has_meta = bool(
        re.search(
            r"\b(relations?|jointures?|structure|liens?|cl[eé]s?|foreign|fk|colonnes?|champs?|noms?)\b",
            ql,
        )
    )
    if has_table and has_meta:
        return True
    if re.search(
        r"\b(communiquer|donne|donner|affiche|montre|explique|citer|cite)\b.{0,50}\b(tables?|sch[eé]ma|relations?)\b",
        ql,
    ):
        return True
    if _wants_live_table_inventory(ql):
        return True
    return False


def _wants_live_table_inventory(ql: str) -> bool:
    if re.search(r"\b(nombre|combien|count|total)\b", ql) and re.search(r"\btables?\b", ql):
        return True
    if re.search(r"\b(citer|cite|communiquer|donne|donner)\b", ql) and re.search(
        r"\b(nombre|combien)\b.*\btables?\b|\btables?\b.*\b(nombre|combien)\b", ql
    ):
        return True
    if re.search(r"\b(liste|lister)\b", ql) and re.search(r"\btoutes?\s+les\s+tables?\b", ql):
        return True
    return False


def _query_live_tables() -> tuple[list[dict[str, str]] | None, str | None]:
    try:
        from backend.database.azure_sql import is_azure_provider, list_tables

        if not is_azure_provider():
            return None, "base locale (pas Azure SQL)"
        return list_tables(schema="dbo", limit=500), None
    except Exception as e:
        return None, str(e) or repr(e)


def build_table_inventory_message(question: str = "") -> str:
    ql = (question or "").lower()
    kpi_ref = sorted(allowed_table_names())
    tables, err = _query_live_tables()

    if tables is not None:
        names = [str(t.get("name") or "") for t in tables if t.get("name")]
        kpi_in_db = [n for n in names if n.upper() in kpi_ref]
        lines = [
            "**Inventaire tables (lecture directe Azure SQL, schéma dbo)**",
            "",
            f"- **Total tables** : **{len(names)}**",
            f"- **Tables métier POC Sonasid** présentes : **{len(kpi_in_db)}** "
            f"(sur {len(kpi_ref)} documentées)",
        ]
        if kpi_in_db:
            lines.append(f"- **KPI** : {', '.join(kpi_in_db)}")
        missing = [t for t in kpi_ref if t not in {n.upper() for n in names}]
        if missing:
            lines.append(f"- _Non trouvées en base_ : {', '.join(missing)}")
        wants_list = bool(
            re.search(r"\b(liste|lister|noms?|citer?|cite|affiche|montre|communiquer)\b", ql)
            or re.search(r"\btoutes?\s+les\s+tables?\b", ql)
        )
        if wants_list and names:
            lines.append("")
            if len(names) <= 35:
                lines.append("**Liste complète :**")
                lines.append(", ".join(names))
            else:
                lines.append("**Aperçu (35 premières) :**")
                lines.append(", ".join(names[:35]) + f" … (+{len(names) - 35})")
        lines.append("")
        lines.append(
            "_Source : `INFORMATION_SCHEMA.TABLES` sur la base connectée (pas le LLM)._"
        )
        return "\n".join(lines)

    lines = [
        "**Nombre de tables**",
        "",
        f"Impossible d’interroger Azure SQL pour l’instant ({err or 'erreur inconnue'}).",
        f"**Tables documentées dans le dictionnaire POC** : **{len(kpi_ref)}**",
        "",
        ", ".join(kpi_ref),
        "",
        "Vérifiez la connexion SQL (firewall VM, `DB_PROVIDER=azure`) puis réessayez.",
    ]
    return "\n".join(lines)


def _table_section_from_markdown(table: str) -> str:
    """Extrait la section ## dbo.TABLE du dictionnaire."""
    raw = load_schema_markdown()
    name = table.upper().replace("DBO.", "")
    pattern = rf"(?ms)^## dbo\.{re.escape(name)}\s*\n(.*?)(?=^## |\Z)"
    m = re.search(pattern, raw)
    if not m:
        return ""
    body = m.group(1).strip()
    if len(body) > 3500:
        body = body[:3500] + "\n\n… (section tronquée — demandez un sous-ensemble de champs)"
    return body


def build_schema_overview_message(question: str = "") -> str:
    ql = (question or "").lower()
    m_table = re.search(r"\b(?:table|dbo\.)\s*([A-Z_a-z][A-Z_a-z0-9_]*)\b", question or "", re.I)
    if m_table:
        section = _table_section_from_markdown(m_table.group(1))
        if section:
            return f"**Table dbo.{m_table.group(1).upper()}**\n\n{section}"

    lines = [
        "**Schéma Sonasid — port & arrivages**",
        "",
        "**Modèle relationnel**",
        "```",
        "ARRIVAGE (1) ──< COMMANDE (1) ──< TRANSFERT",
        "ARRIVAGE (1) ──< NOMINATION_NAVIRE >── NAVIRE",
        "                    ├── COMPAGNIE_MARITIME",
        "                    └── TRANSITAIRE",
        "ARRIVAGE (1) ──< SUIVI_DECHARGEMENT >── SHIFT",
        "```",
        "",
        "**Tables KPI (requêtes chatbot)**",
        "- **ARRIVAGE** — cycle arrivage, tonnage importé (`Arrivage_TonnageTotal`), déchargement",
        "- **COMMANDE** — commandes liées (`Commande_QualiteId`, `Commande_Tonnage`)",
        "- **TRANSFERT** — transferts (`Transfert_PoidsNet`, `Transfert_CommandeId`)",
        "- **NAVIRE** + **NOMINATION_NAVIRE** — navire rattaché à un arrivage",
        "- **QUALITE** — libellés matières (`Qualite_Libelle`)",
        "- **FOURNISSEUR** — fournisseurs (`Arrivage_FournisseurId`)",
        "- **SUIVI_DECHARGEMENT** — quantités déchargées par shift",
        "",
        "**Référentiels** : PORT, BANQUE, DEVISE, SHIFT, STATUT, UTILISATEUR, "
        "NATURE_MARCHANDISE, PRESTATAIRE, CONDUCTEUR, FLOTTE, …",
        "",
        "**Jointures usuelles**",
        "- Tonnage transféré : `TRANSFERT → COMMANDE → ARRIVAGE` (+ `QUALITE`)",
        "- Navire : `ARRIVAGE → NOMINATION_NAVIRE → NAVIRE`",
        "- Fournisseur : `ARRIVAGE → FOURNISSEUR`",
        "",
        "Pour le détail d’une table : « structure de la table COMMANDE » ou « champs ARRIVAGE ».",
    ]
    if re.search(r"\b(d[eé]tail|complet|toutes?\s+les\s+tables)\b", ql):
        raw = load_schema_markdown()
        if len(raw) < 8000:
            lines.append("")
            lines.append("---")
            lines.append(raw)
        else:
            lines.append("")
            lines.append(
                "_Le dictionnaire complet est dans `docs/dictionnaire_sonasid.md` "
                "(15+ tables documentées)._"
            )
    return "\n".join(lines)


def schema_metadata_reply(question: str) -> Dict[str, Any]:
    ql = (question or "").lower()
    if _wants_live_table_inventory(ql):
        message = build_table_inventory_message(question)
    else:
        message = build_schema_overview_message(question)
    return {
        "question": (question or "").strip(),
        "message": message,
        "source": "sonasid:schema",
    }


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
