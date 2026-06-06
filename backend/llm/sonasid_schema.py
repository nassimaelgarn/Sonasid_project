"""
Schéma et formules Sonasid pour Text-to-SQL (contexte LLM).
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar


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
    # « structure / champs de la table NAVIRE » — table métier connue
    known = "|".join(re.escape(t) for t in sorted(allowed_table_names(), key=len, reverse=True))
    if known and re.search(
        rf"\b(structure|champs|colonnes|d[eé]finition|description|d[eé]tail)\b.{0,80}\b(?:table|dbo\.)\s*({known})\b",
        ql,
        re.I,
    ):
        return True
    if known and re.search(
        rf"\b(?:table|dbo\.)\s*({known})\b.{0,60}\b(structure|champs|colonnes|d[eé]finition|description|d[eé]tail)\b",
        ql,
        re.I,
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
    if re.search(r"\b(r[eé]sum[eé]|r[eé]cap|recap|inventaire|aper[cç]u|pr[eé]sentation)\b", ql) and has_table:
        return True
    if re.search(r"\b(toutes?|tout)\s+les?\s+tables?\b", ql):
        return True
    if _wants_live_table_inventory(ql):
        return True
    return False


def is_sonasid_company_question(text: str) -> bool:
    """Question sur Sonasid / l'activité métier (pas un KPI chiffré)."""
    if not _is_sonasid_profile():
        return False
    if is_schema_metadata_question(text):
        return False
    ql = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not ql:
        return False
    if re.search(
        r"\b(qu['']est|quest ce|c['']est quoi|parle|presente|présente|explique|decris|décris)\b",
        ql,
    ) and re.search(r"\b(sonasid|entreprise|soci[eé]t[eé]|activit[eé]|m[eé]tier)\b", ql):
        return True
    if re.search(r"\bsonasid\b", ql) and re.search(
        r"\b(entreprise|soci[eé]t[eé]|activit[eé]|m[eé]tier|id[eé]e|contexte|pr[eé]sentation)\b",
        ql,
    ):
        return True
    if re.search(r"\b(id[eé]e|avoir une id[eé]e|une id[eé]e sur)\b", ql) and re.search(
        r"\b(entreprise|soci[eé]t[eé]|sonasid)\b", ql
    ):
        return True
    if re.search(r"\b(que fait|ce que fait|à quoi sert|a quoi sert)\b", ql) and re.search(
        r"\b(sonasid|entreprise|soci[eé]t[eé]|assistant|chatbot|application)\b", ql
    ):
        return True
    return False


def _fmt_overview_num(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def build_company_overview_message(question: str = "") -> str:
    """Présentation Sonasid + aperçu chiffré depuis Azure SQL (si connecté)."""
    from backend.database.run_query import run_query
    from backend.llm.sonasid_sql import T_ARRIVAGE, T_NAVIRE

    kpi_ref = sorted(allowed_table_names())
    live_lines: list[str] = []
    try:
        tables, err = _query_live_tables()
        if tables is not None:
            names = [str(t.get("name") or "") for t in tables if t.get("name")]
            kpi_in_db = [n for n in names if n.upper() in kpi_ref]
            live_lines.append(f"- **Tables en base** : **{len(names)}** ({len(kpi_in_db)} métier POC)")
        elif err:
            live_lines.append(f"- _Connexion SQL indisponible_ ({str(err)[:80]})")
    except Exception:
        pass

    def _scalar(sql: str) -> Optional[float]:
        try:
            res = run_query(sql)
            if isinstance(res, str) or not res or not res[0]:
                return None
            v = res[0][0]
            return float(v) if v is not None else None
        except Exception:
            return None

    nav = _scalar(f"SELECT COUNT(*) FROM {T_NAVIRE} WHERE Navire_Active = 1")
    arr = _scalar(f"SELECT COUNT(*) FROM {T_ARRIVAGE} WHERE Arrivage_Actif = 1")
    ton = _scalar(
        f"SELECT SUM(COALESCE(Arrivage_TonnageTotal, 0)) FROM {T_ARRIVAGE} WHERE Arrivage_Actif = 1"
    )
    if nav is not None:
        live_lines.append(f"- **Navires actifs** (référentiel) : **{_fmt_overview_num(nav)}**")
    if arr is not None:
        live_lines.append(f"- **Arrivages enregistrés** : **{_fmt_overview_num(arr)}**")
    if ton is not None:
        live_lines.append(f"- **Tonnage importé cumulé** : **{_fmt_overview_num(ton)}** t")

    lines = [
        "**Sonasid — activité couverte par cet assistant**",
        "",
        "**Sonasid** est un grand groupe sidérurgique marocain. Ce POC se concentre sur la "
        "**logistique portuaire & maritime** : arrivée des navires cargo, importation de matières "
        "premières, suivi des déchargements, tonnages, fournisseurs, qualités et flotte camions.",
        "",
        "**Chaîne métier modélisée en base**",
        "- **NAVIRE** — bateaux cargo (nom, IMO, compagnie…)",
        "- **ARRIVAGE** — cycle portuaire, tonnage importé, déchargement",
        "- **COMMANDE** / **QUALITE** — matières commandées par qualité",
        "- **TRANSFERT** / **FLOTTE** — camions et tonnage transféré",
        "- **FOURNISSEUR** — origine des importations",
        "",
    ]
    if live_lines:
        lines.extend(["**Aperçu depuis la base connectée**", ""])
        lines.extend(live_lines)
        lines.append("")
        lines.append("_Chiffres lus directement sur Azure SQL — aucune invention._")
    else:
        lines.append(
            "_Connectez la base Azure (`DB_PROVIDER=azure`) pour afficher les volumes réels._"
        )
        lines.append("")
    lines.extend(
        [
            "**Pour aller plus loin**",
            "- `un petit récap sur 2025` — synthèse multi-KPI",
            "- `tonnage importé en 2025` — indicateur avec période",
            "- `nombre de navires actifs` — référentiel maritime",
            "- `résumé sur toutes les tables de la base` — inventaire schéma",
        ]
    )
    return "\n".join(lines)


def company_overview_reply(question: str) -> Dict[str, Any]:
    return {
        "question": (question or "").strip(),
        "message": build_company_overview_message(question),
        "source": "sonasid:company",
    }


def _schema_live_timeout_s() -> float:
    try:
        return float(os.getenv("AZURE_SQL_SCHEMA_TIMEOUT", "8") or "8")
    except (TypeError, ValueError):
        return 8.0


T = TypeVar("T")


def _azure_call_timed(fn: Callable[[], T], *, timeout_s: Optional[float] = None) -> tuple[T | None, str | None]:
    """Exécute un appel Azure avec timeout — évite de bloquer /chat (Load failed)."""
    lim = timeout_s if timeout_s is not None else _schema_live_timeout_s()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(fn)
            return fut.result(timeout=max(2.0, lim)), None
    except FuturesTimeout:
        return None, f"délai dépassé ({lim:.0f}s)"
    except Exception as e:
        return None, str(e) or repr(e)


def _schema_introspection_timeout_s() -> int:
    return max(3, int(_schema_live_timeout_s()))


def _wants_live_table_inventory(ql: str) -> bool:
    if re.search(r"\b(nombre|combien|count|total)\b", ql) and re.search(r"\btables?\b", ql):
        return True
    if re.search(r"\b(citer|cite|communiquer|donne|donner)\b", ql) and re.search(
        r"\b(nombre|combien)\b.*\btables?\b|\btables?\b.*\b(nombre|combien)\b", ql
    ):
        return True
    if re.search(r"\b(liste|lister)\b", ql) and re.search(r"\btoutes?\s+les\s+tables?\b", ql):
        return True
    if re.search(r"\b(r[eé]sum[eé]|r[eé]cap|recap|inventaire|aper[cç]u)\b", ql) and re.search(
        r"\btables?\b", ql
    ):
        return True
    if re.search(r"\b(toutes?|tout)\s+les?\s+tables?\b", ql):
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


def extract_table_name_from_question(question: str) -> Optional[str]:
    """Nom de table métier reconnu dans la question (NAVIRE, ARRIVAGE…)."""
    q = (question or "").strip()
    if not q:
        return None
    known = sorted(allowed_table_names(), key=len, reverse=True)
    pat = "|".join(re.escape(t) for t in known)
    m = re.search(
        rf"\b(?:table|dbo\.)\s*({pat})\b",
        q,
        re.I,
    )
    if m:
        return m.group(1).upper()
    m2 = re.search(rf"\b({pat})\b", q, re.I)
    if m2 and re.search(r"\b(structure|champs|colonnes|sch[eé]ma|relations?)\b", q, re.I):
        return m2.group(1).upper()
    return None


def _query_live_columns(table: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        from backend.database.azure_sql import is_azure_provider, list_columns

        if not is_azure_provider():
            return None, "base locale"
        tmo = _schema_introspection_timeout_s()

        def _run():
            return list_columns(table=table, schema="dbo", connection_timeout_s=tmo)

        return _azure_call_timed(_run)
    except Exception as e:
        return None, str(e) or repr(e)


def _query_live_foreign_keys(table: str = "") -> tuple[list[dict[str, str]] | None, str | None]:
    try:
        from backend.database.azure_sql import is_azure_provider, list_foreign_keys

        if not is_azure_provider():
            return None, "base locale"
        tmo = _schema_introspection_timeout_s()

        def _run():
            return list_foreign_keys(table=table, schema="dbo", connection_timeout_s=tmo)

        return _azure_call_timed(_run)
    except Exception as e:
        return None, str(e) or repr(e)


def build_live_table_structure_message(table: str, question: str = "") -> str:
    """Dictionnaire + colonnes live Azure + FK — sans LLM."""
    name = (table or "").strip().upper().replace("DBO.", "")
    if not name:
        return build_schema_overview_message(question)

    doc = _table_section_from_markdown(name)
    cols, col_err = _query_live_columns(name)
    fks, fk_err = _query_live_foreign_keys(name)

    lines = [f"**Table dbo.{name}**", ""]

    if doc:
        lines.append("### Dictionnaire métier (POC)")
        lines.append(doc)
        lines.append("")

    if cols is not None:
        lines.append(f"### Colonnes live Azure SQL ({len(cols)} champs)")
        lines.append("")
        lines.append("| Colonne | Type | Nullable | Identity |")
        lines.append("|---------|------|----------|----------|")
        for c in cols[:60]:
            lines.append(
                f"| `{c.get('name')}` | {c.get('type')} | "
                f"{'oui' if c.get('nullable') else 'non'} | "
                f"{'oui' if c.get('identity') else 'non'} |"
            )
        if len(cols) > 60:
            lines.append(f"\n_… et {len(cols) - 60} colonnes supplémentaires._")
        lines.append("")
        lines.append("_Source : `INFORMATION_SCHEMA.COLUMNS` sur la base connectée._")
    elif col_err:
        lines.append(f"_Colonnes live indisponibles ({col_err})._")

    if fks is not None and fks:
        lines.append("")
        lines.append("### Relations (clés étrangères live)")
        lines.append("")
        for fk in fks[:25]:
            lines.append(
                f"- `{fk.get('from_table')}.{fk.get('from_column')}` → "
                f"`{fk.get('to_table')}.{fk.get('to_column')}`"
            )
        if len(fks) > 25:
            lines.append(f"_… et {len(fks) - 25} relations supplémentaires._")
        lines.append("")
        lines.append("_Source : `sys.foreign_keys` sur Azure SQL._")
    elif fk_err and not fks:
        pass

    if not doc and cols is None:
        return build_schema_overview_message(question, _from_live_fallback=True)

    ql = (question or "").lower()
    if re.search(r"\b(par mois|mensuel)\b", ql) and re.search(
        r"\b(structure|champs|colonnes|table)\b", ql
    ):
        lines.append("")
        lines.append(
            "_Note : la structure d’une table ne varie pas « par mois ». "
            "Pour une série mensuelle (ex. navires actifs par mois), demandez un **KPI** avec période._"
        )

    return "\n".join(lines)


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
            re.search(
                r"\b(liste|lister|noms?|citer?|cite|affiche|montre|communiquer|r[eé]sum[eé]|r[eé]cap|recap|inventaire)\b",
                ql,
            )
            or re.search(r"\b(toutes?|tout)\s+les?\s+tables?\b", ql)
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


def build_schema_overview_message(question: str = "", *, _from_live_fallback: bool = False) -> str:
    ql = (question or "").lower()
    if not _from_live_fallback:
        table = extract_table_name_from_question(question or "")
        if table:
            return build_live_table_structure_message(table, question)

    m_table = re.search(r"\b(?:table|dbo\.)\s*([A-Z_a-z][A-Z_a-z0-9_]*)\b", question or "", re.I)
    if m_table and not _from_live_fallback:
        section = _table_section_from_markdown(m_table.group(1))
        if section:
            return build_live_table_structure_message(m_table.group(1).upper(), question)

    lines = [
        "**Schéma Sonasid — port & arrivages**",
        "",
        "**Modèle relationnel**",
        "```",
        "ARRIVAGE (1) ──< COMMANDE (1) ──< TRANSFERT >── FLOTTE",
        "                    └── QUALITE",
        "ARRIVAGE (1) ──< NOMINATION_NAVIRE >── NAVIRE",
        "                    ├── COMPAGNIE_MARITIME",
        "                    └── TRANSITAIRE",
        "ARRIVAGE (1) ──< SUIVI_DECHARGEMENT >── SHIFT",
        "```",
        "",
        "**Tables KPI (requêtes chatbot)**",
        "- **ARRIVAGE** — cycle arrivage, tonnage importé (`Arrivage_TonnageTotal`), déchargement",
        "- **COMMANDE** — commandes liées (`Commande_QualiteId`, `Commande_Tonnage`)",
        "- **TRANSFERT** — transferts (`Transfert_PoidsNet`, `Transfert_CommandeId`, `Transfert_FlotteId`)",
        "- **NAVIRE** + **NOMINATION_NAVIRE** — navire rattaché à un arrivage (`Navire_Nom`, `Navire_Active`)",
        "- **QUALITE** — libellés matières (`Qualite_Libelle`, `Qualite_Active`)",
        "- **FLOTTE** — véhicules transfert (`Flotte_Immatriculation`, conducteur embarqué)",
        "- **FOURNISSEUR** — fournisseurs (`Arrivage_FournisseurId`)",
        "- **SUIVI_DECHARGEMENT** — quantités déchargées par shift",
        "",
        "**Référentiels** : PORT, BANQUE, DEVISE, SHIFT, STATUT, UTILISATEUR, "
        "NATURE_MARCHANDISE, PRESTATAIRE, CONDUCTEUR, …",
        "",
        "**Jointures usuelles**",
        "- Tonnage transféré : `TRANSFERT → COMMANDE → ARRIVAGE` (+ `QUALITE`)",
        "- Navire : `ARRIVAGE → NOMINATION_NAVIRE → NAVIRE`",
        "- Camion / flotte : `TRANSFERT → FLOTTE`",
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
                "(8 tables cœur documentées + référentiels)._"
            )
    return "\n".join(lines)


def schema_metadata_reply(question: str) -> Dict[str, Any]:
    q = (question or "").strip()
    try:
        ql = q.lower()
        if _wants_live_table_inventory(ql):
            message = build_table_inventory_message(q)
        else:
            message = build_schema_overview_message(q)
    except Exception as e:
        message = (
            f"Impossible de charger le schéma pour l’instant ({str(e) or repr(e)}).\n\n"
            "Réessayez ou consultez `docs/dictionnaire_sonasid.md` sur le serveur."
        )
    return {
        "question": q,
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
