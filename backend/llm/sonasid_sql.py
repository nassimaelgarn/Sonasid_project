"""
Requêtes KPI Sonasid (Azure son-db-prd) — formules métier officielles + navires / périodes.
Utilisé quand AZURE_SQL_PROFILE=sonasid (ou shipping/port).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.llm.llm_sql import (
    _extract_year_month_range,
    normalize_kpi_question,
    question_has_explicit_period,
)

T_NAVIRE = (os.getenv("AZURE_SQL_TABLE_NAVIRE", "dbo.NAVIRE") or "dbo.NAVIRE").strip()
T_ARRIVAGE = (os.getenv("AZURE_SQL_TABLE_ARRIVAGE", "dbo.ARRIVAGE") or "dbo.ARRIVAGE").strip()
T_COMMANDE = (os.getenv("AZURE_SQL_TABLE_COMMANDE", "dbo.COMMANDE") or "dbo.COMMANDE").strip()
T_QUALITE = (os.getenv("AZURE_SQL_TABLE_QUALITE", "dbo.QUALITE") or "dbo.QUALITE").strip()
T_TRANSFERT = (os.getenv("AZURE_SQL_TABLE_TRANSFERT", "dbo.TRANSFERT") or "dbo.TRANSFERT").strip()
T_FOURNISSEUR = (os.getenv("AZURE_SQL_TABLE_FOURNISSEUR", "dbo.FOURNISSEUR") or "dbo.FOURNISSEUR").strip()
T_NOMINATION = (
    os.getenv("AZURE_SQL_TABLE_NOMINATION_NAVIRE", "dbo.NOMINATION_NAVIRE") or "dbo.NOMINATION_NAVIRE"
).strip()
T_SUIVI_DECHARGEMENT = (
    os.getenv("AZURE_SQL_TABLE_SUIVI_DECHARGEMENT", "dbo.SUIVI_DECHARGEMENT") or "dbo.SUIVI_DECHARGEMENT"
).strip()

SonasidSqlResult = Union[str, Dict[str, Any]]

# Colonnes dates optionnelles (filtre si l'utilisateur précise une année / période)
DATE_FIELDS = {
    "creation": "Arrivage_DateCreation",
    "arrivee": "Arrivage_DateReelleArrivee",
    "accostage": "Arrivage_DateAccostage",
    "booking": "Arrivage_DateBooking",
}


def _sonasid_profile_active() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def _sonasid_auto_year_enabled() -> bool:
    return os.getenv("SONASID_AUTO_YEAR", "true").strip().lower() in {"1", "true", "yes", "on"}


def _default_calendar_year() -> int:
    raw = (os.getenv("SONASID_DEFAULT_YEAR", "") or "").strip()
    if re.match(r"^20\d{2}$", raw):
        return int(raw)
    return datetime.now().year


def _combine_where(*clauses: str) -> str:
    parts: List[str] = []
    for c in clauses:
        c = (c or "").strip()
        if not c:
            continue
        if c.upper().startswith("WHERE "):
            c = c[6:].strip()
        elif c.upper().startswith("AND "):
            c = c[4:].strip()
        if c:
            parts.append(f"({c})")
    if not parts:
        return ""
    return "WHERE " + " AND ".join(parts)


def _tsql_where_range(field: str, question: str, *, allow_default_year: bool = True) -> str:
    year, month, start_date, end_date = _extract_year_month_range(question)
    if start_date and end_date:
        return (
            f"WHERE {field} >= '{start_date}' AND {field} < DATEADD(day, 1, CAST('{end_date}' AS datetime2))"
        )
    if month:
        return f"WHERE {field} >= '{month}-01' AND {field} < DATEADD(month, 1, CAST('{month}-01' AS datetime2))"
    if year:
        try:
            y = int(year)
        except Exception:
            y = 0
        if y:
            return (
                f"WHERE {field} >= '{y:04d}-01-01' AND {field} < '{(y + 1):04d}-01-01'"
            )
    if question_has_explicit_period(question):
        try:
            from backend.llm.sonasid_brief import _normalize_ql_for_period, _relative_period_years

            rel = _relative_period_years(_normalize_ql_for_period(question))
            if rel and len(rel) == 1:
                y = rel[0]
                return f"WHERE {field} >= '{y:04d}-01-01' AND {field} < '{(y + 1):04d}-01-01'"
        except Exception:
            pass
    if allow_default_year and _sonasid_auto_year_enabled():
        y = _default_calendar_year()
        return f"WHERE {field} >= '{y:04d}-01-01' AND {field} < '{(y + 1):04d}-01-01'"
    return ""


def expand_sonasid_open_question(question: str) -> Tuple[str, Optional[str]]:
    """
    Reformulations déterministes pour questions ouvertes (tendance, mois, période relative).
    """
    q = normalize_kpi_question(question)
    ql = q.lower()
    notice: Optional[str] = None

    try:
        from backend.llm.sonasid_brief import _normalize_ql_for_period, _relative_period_years, _resolve_brief_years
    except Exception:
        return q, None

    orig_ql = _normalize_ql_for_period(question)
    rel = _relative_period_years(orig_ql)
    if rel and len(rel) == 1 and not re.search(r"\b20\d{2}\b", q):
        y = rel[0]
        q = f"{q} {y}"
        ql = q.lower()
        if re.search(r"dernier|dernière|last year", orig_ql, re.I):
            notice = f"Période interprétée : {y} (année dernière)."
        elif re.search(r"cette année|this year|année en cours", orig_ql, re.I):
            notice = f"Période interprétée : {y} (cette année)."
        else:
            notice = f"Période interprétée : {y}."

    if re.search(
        r"(augment|diminu|évolution|evolution|tendance|hausse|baisse|progress|plus\s+qu|moins\s+qu)",
        orig_ql,
    ) and re.search(r"\barrivages?\b", orig_ql):
        if not re.search(r"\bpar mois\b", ql):
            y = _resolve_brief_years(q)[0]
            q = f"nombre d'arrivages par mois en {y}"
            ql = q.lower()
            extra = f"Série mensuelle {y} pour juger la tendance."
            notice = f"{notice} {extra}".strip() if notice else extra

    if re.search(r"\b(qu['']est.ce qui|que s['']est.il|quoi s['']est.il)\b", orig_ql) or (
        re.search(r"\b(arrivé|arrive)\b", orig_ql)
        and re.search(
            r"\b(janvier|fevrier|février|mars|avril|mai|juin|juillet|aout|août|septembre|octobre|novembre|decembre|décembre|20\d{2})\b",
            orig_ql,
        )
    ):
        _, month, _, _ = _extract_year_month_range(q)
        if month:
            q = f"nombre d'arrivages en {month}"
            ql = q.lower()
            extra = f"Activité portuaire sur {month}."
            notice = f"{notice} {extra}".strip() if notice else extra

    return q.strip(), notice


def _is_sonasid_trend_question(text: str) -> bool:
    t = (text or "").lower()
    return bool(
        re.search(r"(augment|diminu|évolution|evolution|tendance|hausse|baisse)", t)
        and re.search(r"\barrivages?\b", t)
    )


def sonasid_trend_verdict(original_q: str, rows: List[Dict[str, Any]]) -> str:
    vals: List[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        v = row.get("nombre_arrivages")
        if v is None:
            v = row.get("value")
        if isinstance(v, (int, float)):
            vals.append(float(v))
    if len(vals) < 2:
        return ""
    first, last = vals[0], vals[-1]
    delta = last - first
    if delta > 0:
        return (
            f"**Tendance :** oui, les arrivages **augmentent** sur la période "
            f"({int(first) if first == int(first) else first} → {int(last) if last == int(last) else last}, +{int(delta) if delta == int(delta) else delta})."
        )
    if delta < 0:
        return (
            f"**Tendance :** non, les arrivages **diminuent** "
            f"({int(first) if first == int(first) else first} → {int(last) if last == int(last) else last}, {int(delta) if delta == int(delta) else delta})."
        )
    return f"**Tendance :** stable sur la période ({int(first) if first == int(first) else first} arrivages)."

def _optional_arrivage_period_clause(question: str, ql: str, alias: str = "a") -> str:
    """Filtre temporel optionnel (formules officielles sans date ; filtre si période dans la question)."""
    if not question_has_explicit_period(question) and not re.search(r"\b20\d{2}\b", ql):
        return ""
    df = _pick_arrivage_date_field(ql)
    col = f"{alias}.{df}" if alias else df
    w = _tsql_where_range(col, question, allow_default_year=False)
    if w.upper().startswith("WHERE "):
        return w[6:].strip()
    return ""


def pick_sonasid_default_year(allowed_years: Optional[Tuple[int, ...]] = None) -> int:
    pref = _default_calendar_year()
    if not allowed_years:
        return pref
    yrs = tuple(int(y) for y in allowed_years if isinstance(y, int))
    if not yrs:
        return pref
    if pref in yrs:
        return pref
    return max(yrs)


def augment_sonasid_question_period(
    question: str,
    *,
    allowed_years: Optional[Tuple[int, ...]] = None,
) -> Tuple[str, Optional[str]]:
    if not _sonasid_profile_active() or not _sonasid_auto_year_enabled():
        return question, None
    q = (question or "").strip()
    if not q or question_has_explicit_period(q):
        return question, None
    if not sonasid_kpi_requires_period(q):
        return question, None
    if not try_sonasid_kpi_sql(q):
        return question, None
    y = pick_sonasid_default_year(allowed_years)
    augmented = f"{q} {y}".strip()
    if try_sonasid_kpi_sql(augmented):
        return augmented, f"Période par défaut : année {y}."
    return question, None


def _is_dechargement_question(ql: str) -> bool:
    return bool(re.search(r"\bd[eéè]charg", ql, re.I))


def _arrivage_en_dechargement_clause(*, alias: str = "a") -> str:
    """Arrivage commencé et non clôturé (FinDechargementFlag = 0, début réel renseigné)."""
    return (
        f"(({alias}.Arrivage_FinDechargementFlag = 0 OR {alias}.Arrivage_FinDechargementFlag IS NULL) "
        f"AND {alias}.Arrivage_DateDebutReelleDechargement IS NOT NULL)"
    )


def _pick_arrivage_date_field(q_lower: str) -> str:
    if _is_dechargement_question(q_lower):
        return "Arrivage_DateDebutReelleDechargement"
    if re.search(r"\b(arrivée|arrivee|réelle\s+arriv)\b", q_lower):
        return DATE_FIELDS["arrivee"]
    if re.search(r"\baccostage\b", q_lower):
        return DATE_FIELDS["accostage"]
    if re.search(r"\bbooking\b", q_lower):
        return DATE_FIELDS["booking"]
    return DATE_FIELDS["creation"]


def _needs_fournisseur_param(ql: str) -> bool:
    if _is_fournisseur_ranking_question(ql):
        return False
    return bool(re.search(r"\bfournisseurs?\b", ql))


def _is_fournisseur_ranking_question(ql: str) -> bool:
    if not re.search(r"\bfournisseurs?\b", ql):
        return False
    if _fournisseur_predicate(ql):
        return False
    return bool(
        re.search(r"\b(quels?|quelles?|top|classement|ranking|principal|principaux|meilleur)\b", ql)
        or re.search(r"\b(plus|moins|maximum|maxi)\b", ql)
        or re.search(r"\bpar fournisseur\b", ql)
        or re.search(r"\blist(e|er)\b", ql)
        or re.search(r"\b(cite|citer|communiquer|donne|donner|affiche|montre)\b", ql)
        or (re.search(r"\btous(\s+les)?\b", ql) and re.search(r"\bfournisseurs?\b", ql))
    )


def _is_navire_ranking_question(ql: str) -> bool:
    if not re.search(r"\bnavires?\b", ql):
        return False
    if _navire_predicate(ql):
        return False
    return bool(
        re.search(r"\b(quels?|quelles?|top|classement|ranking|principal|principaux|meilleur)\b", ql)
        or re.search(r"\b(plus|moins|maximum|maxi)\b", ql)
        or re.search(r"\bpar navire\b", ql)
        or re.search(r"\blist(e|er)\b", ql)
    )


def _extract_top_n(ql: str, *, default: int = 10) -> int:
    if re.search(r"\btous(\s+les)?\b", ql) and re.search(r"\bfournisseurs?\b", ql):
        return 50
    m = re.search(r"\btop\s*(\d+)\b", ql)
    if m:
        try:
            return max(1, min(50, int(m.group(1))))
        except ValueError:
            pass
    return default


def _wants_transfert_qualite_detail(ql: str) -> bool:
    """Formule officielle ligne à ligne ; par défaut POC = agrégat par qualité (lisible)."""
    return bool(
        re.search(r"\b(détail|detail|ligne par ligne)\b", ql, re.I)
        or re.search(r"\bpar\s+(commande|transfert)\b", ql, re.I)
    )


def _is_tonnage_importe_question(ql: str) -> bool:
    has_import = bool(re.search(r"\bimport", ql, re.I))
    if has_import and re.search(r"\btonnage\b", ql):
        return True
    if has_import and re.search(r"\b(marchandise|marchandises)\b", ql, re.I):
        return True
    if re.search(r"\b(valeur|valeurs)\b", ql, re.I) and re.search(
        r"\b(marchandise|marchandises)\b", ql, re.I
    ):
        return True
    if re.search(r"\b(valeur|valeurs)\b", ql, re.I) and has_import:
        return True
    return False


def _needs_navire_param(ql: str) -> bool:
    if _is_navire_ranking_question(ql):
        return False
    return bool(
        re.search(r"\bnavire\b", ql)
        and re.search(r"\btransf", ql)
        and re.search(r"\bqual", ql)
    )


def _fournisseur_predicate(ql: str, *, alias: str = "") -> Optional[str]:
    col = f"{alias}.Arrivage_FournisseurId" if alias else "Arrivage_FournisseurId"
    m_id = re.search(r"\bfournisseur\s*(?:id\s*)?(\d+)\b", ql)
    if m_id:
        return f"{col} = {int(m_id.group(1))}"
    m_name = re.search(
        r"\bfournisseur\s+([a-zA-Z0-9][a-zA-Z0-9 \-'']+?)(?:\s+(?:en|pour|de|du|\d{4})|\s*$)",
        ql,
        re.I,
    )
    if m_name:
        name = m_name.group(1).strip().replace("'", "''")
        return (
            f"{col} IN (SELECT Fournisseur_Id FROM {T_FOURNISSEUR} "
            f"WHERE Fournisseur_Nom LIKE N'%{name}%')"
        )
    return None


def _navire_predicate(ql: str) -> Optional[str]:
    m_id = re.search(r"\bnavire\s*(?:id\s*)?(\d+)\b", ql)
    if m_id:
        return f"nv.Navire_Id = {int(m_id.group(1))}"
    if re.search(r"\bnavire\s+(?:en|pour|de|du)\s+(?:20\d{2}|\d)", ql, re.I):
        return None
    m_name = re.search(
        r"\bnavire\s+(?!id\s*\d)([a-zA-Z][a-zA-Z0-9 \-''&]{2,}?)\s+(?:en|pour|de|du|\d{4})",
        ql,
        re.I,
    )
    if not m_name:
        m_name = re.search(r"\bnavire\s+(?!id\s*\d)([a-zA-Z][a-zA-Z0-9 \-''&]{2,})\s*$", ql, re.I)
    if m_name:
        name = m_name.group(1).strip()
        if len(name) < 3 or name.lower() in {"des", "les", "par", "une", "aux", "sur"}:
            return None
        name = name.replace("'", "''")
        return f"nv.Navire_Nom LIKE N'%{name}%'"
    return None


def _need_fournisseur_response() -> Dict[str, Any]:
    return {
        "type": "need_fournisseur",
        "message": (
            "Pour ce KPI, il me manque le **fournisseur**.\n"
            "Précise par exemple :\n"
            "- nombre d'arrivages fournisseur 3\n"
            "- tonnage importé fournisseur id 12\n"
            "- tonnage par qualité fournisseur ACME"
        ),
    }


def _need_navire_response() -> Dict[str, Any]:
    return {
        "type": "need_navire",
        "message": (
            "Pour ce KPI, il me manque le **navire**.\n"
            "Précise par exemple :\n"
            "- tonnage transféré par qualité navire id 5\n"
            "- tonnage transféré par qualité navire ATLANTIC STAR"
        ),
    }


def list_sonasid_kpi_catalog() -> List[Dict[str, str]]:
    y = str(_default_calendar_year())
    return [
        {"name": "Navires actifs", "question": "nombre de navires actifs"},
        {"name": "Navires actifs par mois", "question": f"nombre de navires actifs par mois en {y}"},
        {"name": "Navires en déchargement", "question": "nombre de navires en déchargement"},
        {"name": "Liste navires en déchargement", "question": "liste des navires en déchargement"},
        {"name": "Tonnage déchargé (en cours)", "question": "tonnage déchargé en déchargement"},
        {"name": "Tonnage restant à décharger", "question": "tonnage restant à décharger"},
        {"name": "Taux de déchargement moyen", "question": "taux de déchargement en déchargement"},
        {"name": f"Tonnage déchargé par mois", "question": f"tonnage déchargé par mois en {y}"},
        {"name": "Nombre des arrivages (total)", "question": "nombre des arrivages"},
        {"name": "Arrivages par fournisseur", "question": "nombre d'arrivages fournisseur id 1"},
        {"name": "Tonnage importé par fournisseur", "question": "tonnage importé fournisseur id 1"},
        {"name": "Liste des qualités", "question": "liste des qualités"},
        {"name": "Valeur marchandises importées", "question": f"valeur des marchandises importées en {y}"},
        {"name": "Tonnage importé (année)", "question": "tonnage importé en 2026"},
        {"name": "Arrivages par qualité", "question": f"arrivages par qualité en {y}"},
        {"name": "Tonnage importé par qualité", "question": f"tonnage importé par qualité en {y}"},
        {"name": "Tonnage importé par qualité par mois", "question": f"tonnage importé par qualité par mois en {y}"},
        {"name": "Tonnage commandé par qualité", "question": f"tonnage commandé par qualité en {y}"},
        {"name": "Tonnage par qualité par fournisseur", "question": "tonnage par qualité fournisseur id 40 en 2026"},
        {"name": "Tonnage transféré par qualité (répartition)", "question": f"tonnage transféré par qualité en {y}"},
        {"name": "Tonnage transféré par qualité (détail)", "question": "tonnage transféré par qualité détail en 2026"},
        {"name": "Tonnage transféré par qualité par navire", "question": "tonnage transféré par qualité navire id 79 en 2026"},
        {"name": "Arrivages par mois", "question": f"arrivages par mois en {y}"},
    ]


def sonasid_kpi_requires_period(question: str) -> bool:
    """Formules officielles sans date : pas de période obligatoire sauf séries temporelles."""
    if not _sonasid_profile_active():
        return True
    ql = normalize_kpi_question(question).lower()
    if _is_dechargement_question(ql):
        if re.search(r"\b(par mois|mensuel)\b", ql):
            return True
        if re.search(r"\b(restant|reste|tonnage décharg|tonnage decharg)\b", ql) and not re.search(
            r"\b20\d{2}\b", ql
        ):
            if not question_has_explicit_period(question):
                return False
        if re.search(r"\b(navires?|arrivages?)\b", ql) and re.search(
            r"\b(nombre|combien|count|liste)\b", ql
        ):
            return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
        if re.search(r"\btonnage\b", ql) or re.search(r"\btaux\b", ql):
            return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
    if re.search(r"\bnavires?\b", ql) and not re.search(r"\barrivages?\b", ql):
        if re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql):
            return True
        return False
    if re.search(r"\b(par mois|mensuel|chaque mois|mois par mois|par semaine|par jour)\b", ql):
        return True
    if _needs_fournisseur_param(ql) or re.search(r"\btransf", ql):
        return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
    if re.search(r"\barrivages?\b", ql) and re.search(r"\b(nombre|combien|total|count)\b", ql):
        return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
    if re.search(r"\btonnage\b", ql) or _is_tonnage_importe_question(ql):
        return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
    if re.search(r"\barrivages?\b", ql) and re.search(r"\bqualit", ql):
        return bool(question_has_explicit_period(question) or re.search(r"\b20\d{2}\b", ql))
    return True


def try_sonasid_kpi_sql(question: str) -> Optional[SonasidSqlResult]:
    """
    Retourne une chaîne T-SQL (SELECT …), un dict need_* (paramètre manquant), ou None.
    """
    if not _sonasid_profile_active():
        return None

    q = normalize_kpi_question(question)
    ql = q.lower()

    # --- Déchargement : navires / arrivages en cours (snapshot port) ---
    if _is_dechargement_question(ql):
        dech = _arrivage_en_dechargement_clause(alias="a")
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        # Période explicite (année / plage) sans filtre « en cours » → historique SUIVI / début déchargement
        hist_only = bool(
            (question_has_explicit_period(q) or re.search(r"\b20\d{2}\b", ql))
            and not re.search(r"\b(en cours|actuellement|actuel)\b", ql)
        )
        if hist_only:
            df = "Arrivage_DateDebutReelleDechargement"
            w = _tsql_where_range(df, q, allow_default_year=not question_has_explicit_period(q))
            where = w if w else ""
        else:
            where = _combine_where(dech, period)
        joins = (
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
        )
        suivi_apply = (
            f"OUTER APPLY ("
            f"SELECT TOP 1 s.SuiviDechargement_QuantiteRestante AS quantite_restante "
            f"FROM {T_SUIVI_DECHARGEMENT} s "
            f"WHERE s.SuiviDechargement_ArrivageId = a.Arrivage_Id "
            f"ORDER BY s.SuiviDechargement_Id DESC"
            f") sd "
        )
        nav = _navire_predicate(ql) if re.search(r"\bnavire\b", ql) else None
        if re.search(r"\bnavire\b", ql) and re.search(r"\btransf", ql):
            nav = None

        # Séries : tonnage déchargé par mois (shifts cumulés, filtre arrivage)
        if re.search(r"\b(par mois|mensuel|chaque mois)\b", ql) and re.search(
            r"\b(tonnage|quantité|quantite)\b", ql
        ):
            df = "a.Arrivage_DateDebutReelleDechargement"
            w = _tsql_where_range(df, q, allow_default_year=not question_has_explicit_period(q))
            if not hist_only:
                w = _combine_where(w, dech)
            if nav:
                w = _combine_where(w, nav)
            return (
                f"SELECT CONVERT(char(7), {df}, 126) AS periode, "
                f"SUM(s.SuiviDechargement_QuantiteDecharge) AS tonnage_decharge "
                f"FROM {T_SUIVI_DECHARGEMENT} s "
                f"INNER JOIN {T_ARRIVAGE} a ON s.SuiviDechargement_ArrivageId = a.Arrivage_Id "
                f"{joins if nav else ''}"
                f"{w} "
                f"GROUP BY CONVERT(char(7), {df}, 126) ORDER BY periode;"
            )

        # Taux de déchargement (contractuel arrivage, t/j)
        if re.search(r"\btaux\b", ql):
            w = _combine_where(where, nav) if nav else where
            if re.search(r"\b(liste|détail|detail|par navire)\b", ql) or (
                re.search(r"\bnavires?\b", ql) and not re.search(r"\b(nombre|combien|moyen|moyenne)\b", ql)
            ):
                return (
                    f"SELECT nv.Navire_Nom, a.Arrivage_Id, a.Arrivage_TauxDechargement AS taux_dechargement "
                    f"FROM {T_ARRIVAGE} a {joins}{w} "
                    f"ORDER BY nv.Navire_Nom;"
                )
            return (
                f"SELECT AVG(a.Arrivage_TauxDechargement) AS taux_dechargement_moyen "
                f"FROM {T_ARRIVAGE} a {joins if nav else ''}{w};"
            )

        # Tonnage restant (dernier shift par arrivage en cours)
        if re.search(r"\b(restant|reste)\b", ql):
            w = _combine_where(where, nav) if nav else where
            return (
                f"SELECT SUM(sd.quantite_restante) AS tonnage_restant "
                f"FROM {T_ARRIVAGE} a {joins if nav else ''}{suivi_apply}{w};"
            )

        # Tonnage déchargé (cumul shifts SUIVI_DECHARGEMENT)
        if re.search(r"\btonnage\b", ql) or (
            re.search(r"\b(quantité|quantite)\b", ql) and re.search(r"\bd[eéè]charg", ql, re.I)
        ):
            w = _combine_where(where, nav) if nav else where
            join_nav = joins if nav else ""
            return (
                f"SELECT SUM(s.SuiviDechargement_QuantiteDecharge) AS tonnage_decharge "
                f"FROM {T_SUIVI_DECHARGEMENT} s "
                f"INNER JOIN {T_ARRIVAGE} a ON s.SuiviDechargement_ArrivageId = a.Arrivage_Id "
                f"{join_nav}{w};"
            )

        if re.search(r"\bnavires?\b", ql):
            wants_list = bool(re.search(r"\b(liste|détail|detail|quels|quelles)\b", ql))
            if re.search(r"\b(par mois|mensuel|chaque mois)\b", ql) and re.search(
                r"\b(nombre|combien|count|total)\b", ql
            ):
                df = "a.Arrivage_DateDebutReelleDechargement"
                w = _tsql_where_range(df, q, allow_default_year=not question_has_explicit_period(q))
                w = _combine_where(w, f"{df} IS NOT NULL")
                if nav:
                    w = _combine_where(w, nav)
                return (
                    f"SELECT CONVERT(char(7), {df}, 126) AS periode, "
                    f"COUNT(DISTINCT nv.Navire_Id) AS nombre_navires_en_dechargement "
                    f"FROM {T_ARRIVAGE} a {joins}{w} "
                    f"GROUP BY CONVERT(char(7), {df}, 126) ORDER BY periode;"
                )
            if wants_list or not re.search(r"\b(nombre|combien|count|total)\b", ql):
                return (
                    f"SELECT nv.Navire_Nom, a.Arrivage_Id, a.Arrivage_DateDebutReelleDechargement, "
                    f"a.Arrivage_TonnageTotal, sd.quantite_restante "
                    f"FROM {T_ARRIVAGE} a {joins}{suivi_apply}{where} "
                    f"ORDER BY nv.Navire_Nom, a.Arrivage_Id;"
                )
            return (
                f"SELECT COUNT(DISTINCT nv.Navire_Id) AS nombre_navires_en_dechargement "
                f"FROM {T_ARRIVAGE} a {joins}{where};"
            )
        if re.search(r"\barrivages?\b", ql) and re.search(r"\b(nombre|combien|count|total)\b", ql):
            return (
                f"SELECT COUNT(DISTINCT a.Arrivage_Id) AS nombre_arrivages_en_dechargement "
                f"FROM {T_ARRIVAGE} a {where};"
            )

    # --- Arrivages par qualité (répartition — pas confondre avec « navire » seul) ---
    if (
        re.search(r"\barrivages?\b", ql)
        and re.search(r"\bqualit", ql)
        and not re.search(r"\btransf", ql)
        and not _is_tonnage_importe_question(ql)
    ):
        df = _pick_arrivage_date_field(ql)
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        w = _tsql_where_range(
            f"a.{df}", q, allow_default_year=not question_has_explicit_period(q)
        )
        where = _combine_where(w, period)
        if re.search(r"\b(par mois|mensuel|chaque mois)\b", ql):
            return (
                f"SELECT CONVERT(char(7), a.{df}, 126) AS periode, q.Qualite_Libelle, "
                f"COUNT(DISTINCT a.Arrivage_Id) AS nombre_arrivages "
                f"FROM {T_ARRIVAGE} a "
                f"INNER JOIN {T_COMMANDE} c ON c.Commande_ArrivageId = a.Arrivage_Id "
                f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
                f"{where} "
                f"GROUP BY CONVERT(char(7), a.{df}, 126), q.Qualite_Libelle "
                f"ORDER BY periode, q.Qualite_Libelle;"
            )
        return (
            f"SELECT q.Qualite_Id, q.Qualite_Libelle, COUNT(DISTINCT a.Arrivage_Id) AS nombre_arrivages "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_COMMANDE} c ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"{where} "
            f"GROUP BY q.Qualite_Id, q.Qualite_Libelle "
            f"ORDER BY nombre_arrivages DESC, q.Qualite_Libelle;"
        )

    # --- Navires ---
    if re.search(r"\bnavires?\b", ql) and re.search(
        r"\b(nombre|combien|count|total|liste)\b", ql
    ):
        if not re.search(r"\bqualit", ql) and not re.search(r"\btransf", ql) and not _is_dechargement_question(ql):
            nav_joins = (
                f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
                f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
            )
            if re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql) and re.search(
                r"\b(nombre|combien|count|total)\b", ql
            ):
                df = _pick_arrivage_date_field(ql)
                col = f"a.{df}"
                w = _tsql_where_range(col, q, allow_default_year=not question_has_explicit_period(q))
                if re.search(r"\bactifs?\b", ql):
                    w = _combine_where(w, "nv.Navire_Active = 1")
                alias = (
                    "nombre_navires_actifs"
                    if re.search(r"\bactifs?\b", ql)
                    else "nombre_navires"
                )
                return (
                    f"SELECT CONVERT(char(7), {col}, 126) AS periode, "
                    f"COUNT(DISTINCT nv.Navire_Id) AS {alias} "
                    f"FROM {T_ARRIVAGE} a {nav_joins}{w} "
                    f"GROUP BY CONVERT(char(7), {col}, 126) ORDER BY periode;"
                )
            where = "WHERE Navire_Active = 1" if re.search(r"\bactifs?\b", ql) else ""
            return f"SELECT COUNT(*) AS nombre_navires FROM {T_NAVIRE} {where};".strip()

    # --- Qualité : référentiel & tonnage commandé ---
    if re.search(r"\bqualit", ql) and re.search(r"\b(liste|quelles|catalogue|référentiel|referentiel)\b", ql):
        active_only = not re.search(r"\b(toutes|inactives?|archiv)\b", ql)
        w = "WHERE Qualite_Active = 1" if active_only else ""
        return (
            f"SELECT TOP 80 q.Qualite_Id, q.Qualite_Libelle, q.Qualite_Active "
            f"FROM {T_QUALITE} q {w} ORDER BY q.Qualite_Libelle;"
        )

    if re.search(r"\bqualit", ql) and re.search(r"\b(nombre|combien|count)\b", ql):
        if not re.search(r"\b(transf|tonnage|fournisseur|navire|arrivage)\b", ql):
            w = "WHERE Qualite_Active = 1" if re.search(r"\bactives?\b", ql) else ""
            return f"SELECT COUNT(*) AS nombre_qualites FROM {T_QUALITE} {w};".strip()

    # --- Tonnage importé par qualité (répartition commandes / qualité — POC) ---
    if (
        _is_tonnage_importe_question(ql)
        and re.search(r"\bqual", ql)
        and not re.search(r"\bfournisseur\b", ql)
        and not re.search(r"\btransf", ql)
    ):
        df = "a.Arrivage_DateCreation"
        w = _tsql_where_range(df, q, allow_default_year=not question_has_explicit_period(q))
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        if not period and w:
            period = w[6:].strip() if w.upper().startswith("WHERE ") else ""
        where = _combine_where(period)
        if re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql):
            return (
                f"SELECT CONVERT(char(7), {df}, 126) AS periode, q.Qualite_Libelle, "
                f"SUM(c.Commande_Tonnage) AS tonnage_importe "
                f"FROM {T_COMMANDE} c "
                f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
                f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
                f"{where} "
                f"GROUP BY CONVERT(char(7), {df}, 126), q.Qualite_Libelle "
                f"ORDER BY periode, q.Qualite_Libelle;"
            )
        return (
            f"SELECT c.Commande_QualiteId, q.Qualite_Libelle, SUM(c.Commande_Tonnage) AS tonnage_importe "
            f"FROM {T_COMMANDE} c "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"{where} "
            f"GROUP BY c.Commande_QualiteId, q.Qualite_Libelle "
            f"ORDER BY tonnage_importe DESC, q.Qualite_Libelle;"
        )

    if (
        re.search(r"\btonnage\b", ql)
        and re.search(r"\bqual", ql)
        and not re.search(r"\bfournisseur\b", ql)
        and not re.search(r"\btransf", ql)
        and not _is_tonnage_importe_question(ql)
    ):
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        if not period and re.search(r"\b20\d{2}\b", ql):
            df = _pick_arrivage_date_field(ql)
            w = _tsql_where_range(df, q, allow_default_year=False)
            period = w[6:].strip() if w.upper().startswith("WHERE ") else ""
        where = _combine_where(period)
        return (
            f"SELECT c.Commande_QualiteId, q.Qualite_Libelle, SUM(c.Commande_Tonnage) AS tonnage "
            f"FROM {T_COMMANDE} c "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"{where} "
            f"GROUP BY c.Commande_QualiteId, q.Qualite_Libelle "
            f"ORDER BY tonnage DESC, q.Qualite_Libelle;"
        )

    # --- Tonnage transféré par qualité par navire (formule officielle) ---
    if re.search(r"\btransf", ql) and re.search(r"\bqual", ql) and re.search(r"\bnavires?\b", ql):
        nav = _navire_predicate(ql)
        if not nav:
            return _need_navire_response()
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        where = _combine_where(nav, period)
        return (
            f"SELECT a.Arrivage_Id, nv.Navire_Nom, c.Commande_QualiteId, q.Qualite_Libelle, "
            f"SUM(t.Transfert_PoidsNet) AS tonnage_transfere "
            f"FROM {T_TRANSFERT} t "
            f"INNER JOIN {T_COMMANDE} c ON t.Transfert_CommandeId = c.Commande_Id "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
            f"{where} "
            f"GROUP BY a.Arrivage_Id, nv.Navire_Nom, c.Commande_QualiteId, q.Qualite_Libelle "
            f"ORDER BY nv.Navire_Nom, q.Qualite_Libelle;"
        )

    # --- Tonnage transféré par qualité (agrégat par défaut ; détail = formule officielle) ---
    if re.search(r"\btransf", ql) and re.search(r"\bqual", ql):
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        if not period and re.search(r"\b20\d{2}\b", ql):
            df = _pick_arrivage_date_field(ql)
            w = _tsql_where_range(df, q, allow_default_year=False)
            period = w[6:].strip() if w.upper().startswith("WHERE ") else ""
        fourn = _fournisseur_predicate(ql, alias="a") if _needs_fournisseur_param(ql) else None
        if _needs_fournisseur_param(ql) and not fourn:
            return _need_fournisseur_response()
        where = _combine_where(period, fourn)
        join_arrivage = f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
        if _wants_transfert_qualite_detail(ql):
            return (
                f"SELECT TOP 500 q.Qualite_Libelle, c.Commande_QualiteId, t.Transfert_PoidsNet "
                f"FROM {T_TRANSFERT} t "
                f"INNER JOIN {T_COMMANDE} c ON t.Transfert_CommandeId = c.Commande_Id "
                f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
                f"{join_arrivage}"
                f"{where} "
                f"ORDER BY q.Qualite_Libelle, c.Commande_QualiteId;"
            )
        return (
            f"SELECT c.Commande_QualiteId, q.Qualite_Libelle, "
            f"SUM(t.Transfert_PoidsNet) AS tonnage_transfere "
            f"FROM {T_TRANSFERT} t "
            f"INNER JOIN {T_COMMANDE} c ON t.Transfert_CommandeId = c.Commande_Id "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"{join_arrivage}"
            f"{where} "
            f"GROUP BY c.Commande_QualiteId, q.Qualite_Libelle "
            f"ORDER BY tonnage_transfere DESC, q.Qualite_Libelle;"
        )

    # --- Tonnage par qualité par fournisseur (formule officielle ; GROUP BY sans Commande_Tonnage) ---
    if re.search(r"\btonnage\b", ql) and re.search(r"\bqual", ql) and re.search(r"\bfournisseur\b", ql):
        fourn = _fournisseur_predicate(ql, alias="a")
        if not fourn:
            return _need_fournisseur_response()
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        where = _combine_where(fourn, period)
        return (
            f"SELECT c.Commande_QualiteId, q.Qualite_Libelle, SUM(c.Commande_Tonnage) AS tonnage "
            f"FROM {T_COMMANDE} c "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"{where} "
            f"GROUP BY c.Commande_QualiteId, q.Qualite_Libelle "
            f"ORDER BY q.Qualite_Libelle;"
        )

    # --- Tonnage importé par fournisseur (formule officielle) ---
    if re.search(r"\btonnage\b", ql) and re.search(r"\bfournisseur\b", ql):
        fourn = _fournisseur_predicate(ql)
        if not fourn:
            return _need_fournisseur_response()
        period = _optional_arrivage_period_clause(q, ql, alias="")
        where = _combine_where(fourn, period)
        return (
            f"SELECT SUM(Arrivage_TonnageTotal) AS tonnage_importe "
            f"FROM {T_ARRIVAGE} {where};"
        )

    # --- Séries par mois (courbes) — arrivages / tonnage, filtre fournisseur optionnel ---
    if re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql) and (
        re.search(r"\barrivages?\b", ql) or re.search(r"\btonnage\b", ql)
    ):
        df = _pick_arrivage_date_field(ql)
        w = _tsql_where_range(df, q, allow_default_year=not question_has_explicit_period(q))
        fourn = _fournisseur_predicate(ql) if re.search(r"\bfournisseur\b", ql) else None
        if re.search(r"\bfournisseur\b", ql) and not fourn:
            return _need_fournisseur_response()
        period_extra = _optional_arrivage_period_clause(q, ql, alias="")
        where = _combine_where(w, fourn, period_extra)
        if re.search(r"\btonnage\b", ql):
            expr = "SUM(Arrivage_TonnageTotal)"
            alias = "tonnage_importe" if _is_tonnage_importe_question(ql) else "tonnage_total"
        else:
            expr = "COUNT(*)"
            alias = "nombre_arrivages"
        return (
            f"SELECT CONVERT(char(7), {df}, 126) AS periode, {expr} AS {alias} "
            f"FROM {T_ARRIVAGE} {where} "
            f"GROUP BY CONVERT(char(7), {df}, 126) "
            f"ORDER BY periode;"
        )

    # --- Classement navires (top tonnage transféré) ---
    if _is_navire_ranking_question(ql) and re.search(r"\btransf", ql):
        top_n = _extract_top_n(ql)
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        if not period and re.search(r"\b20\d{2}\b", ql):
            df = _pick_arrivage_date_field(ql)
            w = _tsql_where_range(df, q, allow_default_year=False)
            period = w[6:].strip() if w.upper().startswith("WHERE ") else ""
        where = _combine_where(period, "t.Transfert_Actif = 1")
        return (
            f"SELECT TOP {top_n} nv.Navire_Id, nv.Navire_Nom, "
            f"SUM(t.Transfert_PoidsNet) AS tonnage_transfere "
            f"FROM {T_TRANSFERT} t "
            f"INNER JOIN {T_COMMANDE} c ON t.Transfert_CommandeId = c.Commande_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
            f"{where} "
            f"GROUP BY nv.Navire_Id, nv.Navire_Nom "
            f"ORDER BY tonnage_transfere DESC, nv.Navire_Nom;"
        )

    # --- Classement navires (top tonnage importé, sans mot « transféré ») ---
    if (
        _is_navire_ranking_question(ql)
        and re.search(r"\btonnage\b", ql)
        and not re.search(r"\btransf", ql)
        and not re.search(r"\bqual", ql)
    ):
        top_n = _extract_top_n(ql)
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        where = _combine_where(period, "a.Arrivage_Actif = 1")
        return (
            f"SELECT TOP {top_n} nv.Navire_Id, nv.Navire_Nom, "
            f"SUM(COALESCE(a.Arrivage_TonnageTotal, 0)) AS tonnage_importe "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
            f"{where} "
            f"GROUP BY nv.Navire_Id, nv.Navire_Nom "
            f"ORDER BY tonnage_importe DESC, nv.Navire_Nom;"
        )

    # --- Classement fournisseurs (top arrivages / tonnage) ---
    if _is_fournisseur_ranking_question(ql):
        top_n = _extract_top_n(ql)
        period = _optional_arrivage_period_clause(q, ql, alias="a")
        where = _combine_where(period, "a.Arrivage_Actif = 1")
        order = "nombre_arrivages DESC, tonnage_total DESC"
        if re.search(r"\btonnage\b", ql) and not re.search(r"\barrivages?\b", ql):
            order = "tonnage_total DESC, nombre_arrivages DESC"
        return (
            f"SELECT TOP {top_n} f.Fournisseur_Id, f.Fournisseur_Nom, "
            f"COUNT(DISTINCT a.Arrivage_Id) AS nombre_arrivages, "
            f"SUM(COALESCE(a.Arrivage_TonnageTotal, 0)) AS tonnage_total "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_FOURNISSEUR} f ON a.Arrivage_FournisseurId = f.Fournisseur_Id "
            f"{where} "
            f"GROUP BY f.Fournisseur_Id, f.Fournisseur_Nom "
            f"ORDER BY {order};"
        )

    # --- Nombre des arrivages par fournisseur (id ou nom requis) ---
    if re.search(r"\barrivages?\b", ql) and re.search(r"\bfournisseurs?\b", ql):
        fourn = _fournisseur_predicate(ql)
        if not fourn:
            return _need_fournisseur_response()
        period = _optional_arrivage_period_clause(q, ql, alias="")
        where = _combine_where(fourn, period)
        return f"SELECT COUNT(*) AS nombre_arrivages FROM {T_ARRIVAGE} {where};"

    # --- Arrivages avec année ou mois explicite (total, pas classement fournisseur) ---
    if (
        re.search(r"\barrivages?\b", ql)
        and (re.search(r"\b20\d{2}\b", ql) or _extract_year_month_range(q)[1])
        and not re.search(r"\bfournisseurs?\b", ql)
    ):
        if not re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql):
            if not re.search(r"\btonnage\b", ql):
                df = _pick_arrivage_date_field(ql)
                w = _tsql_where_range(df, q, allow_default_year=False)
                _, month, _, _ = _extract_year_month_range(q)
                if month or re.search(
                    r"\b(qu['']est|arrivé|arrive|passé|passe|activité|activite)\b", ql
                ):
                    return (
                        f"SELECT COUNT(*) AS nombre_arrivages, "
                        f"SUM(COALESCE(Arrivage_TonnageTotal, 0)) AS tonnage_total "
                        f"FROM {T_ARRIVAGE} {w};"
                    )
                return f"SELECT COUNT(*) AS nombre_arrivages FROM {T_ARRIVAGE} {w};"

    # --- Tonnage importé global (Arrivage_TonnageTotal) ---
    if _is_tonnage_importe_question(ql) and not re.search(r"\bqual", ql) and not re.search(
        r"\bfournisseur\b", ql
    ):
        df = _pick_arrivage_date_field(ql)
        w = _tsql_where_range(
            df,
            q,
            allow_default_year=not question_has_explicit_period(q),
        )
        if re.search(r"\b(par mois|mensuel)\b", ql):
            return (
                f"SELECT CONVERT(char(7), {df}, 126) AS periode, "
                f"SUM(COALESCE(Arrivage_TonnageTotal, 0)) AS tonnage_importe "
                f"FROM {T_ARRIVAGE} {w} "
                f"GROUP BY CONVERT(char(7), {df}, 126) ORDER BY periode;"
            )
        return (
            f"SELECT SUM(COALESCE(Arrivage_TonnageTotal, 0)) AS tonnage_importe "
            f"FROM {T_ARRIVAGE} {w};"
        )

    # --- Tonnage global avec période (POC) ---
    if (
        re.search(r"\btonnage\b", ql)
        and not re.search(r"\bfournisseur\b", ql)
        and not re.search(r"\bqual", ql)
        and not re.search(r"\btransf", ql)
        and not _is_navire_ranking_question(ql)
    ):
        df = _pick_arrivage_date_field(ql)
        w = _tsql_where_range(
            df,
            q,
            allow_default_year=bool(question_has_explicit_period(q) or re.search(r"\b20\d{2}\b", ql)),
        )
        if re.search(r"\bpar mois\b", ql):
            return (
                f"SELECT CONVERT(char(7), {df}, 126) AS periode, "
                f"SUM(COALESCE(Arrivage_TonnageTotal, 0)) AS tonnage_total "
                f"FROM {T_ARRIVAGE} {w} "
                f"GROUP BY CONVERT(char(7), {df}, 126) ORDER BY periode;"
            )
        if w:
            return (
                f"SELECT SUM(COALESCE(Arrivage_TonnageTotal, 0)) AS tonnage_total "
                f"FROM {T_ARRIVAGE} {w};"
            )

    # --- Nombre des arrivages (formule officielle : COUNT(*) sans filtre date) ---
    if re.search(r"\barrivages?\b", ql) and re.search(
        r"\b(nombre|combien|count|total|combien de)\b", ql
    ):
        period = _optional_arrivage_period_clause(q, ql, alias="")
        where = _combine_where(period)
        return f"SELECT COUNT(*) AS nombre_arrivages FROM {T_ARRIVAGE} {where};"

    return None
