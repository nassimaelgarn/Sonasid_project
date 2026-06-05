"""
Briefs Sonasid : résumé multi-KPI et analyses multi-axes (questions ouvertes POC).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from backend.database.run_query import run_query
from backend.llm.llm_sql import normalize_kpi_question
from backend.llm.sonasid_answer import friendly_db_error
from backend.llm.sonasid_sql import (
    T_ARRIVAGE,
    T_COMMANDE,
    T_FOURNISSEUR,
    T_NAVIRE,
    T_NOMINATION,
    T_QUALITE,
    T_TRANSFERT,
    _sonasid_profile_active,
)


def _fmt_num(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(x - round(x)) < 1e-6:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:,.2f}".replace(",", " ").replace(".", ",")


def _scalar(sql: str) -> Tuple[Optional[float], Optional[str]]:
    res = run_query(sql)
    if isinstance(res, str):
        return None, res
    if not res or not res[0]:
        return 0.0, None
    v = res[0][0]
    if v is None:
        return 0.0, None
    try:
        return float(v), None
    except (TypeError, ValueError):
        return None, None


def _rows(sql: str) -> Tuple[List[tuple], Optional[str]]:
    res = run_query(sql)
    if isinstance(res, str):
        return [], res
    return list(res or []), None


def _extract_years(question: str) -> List[int]:
    yrs = sorted({int(y) for y in re.findall(r"\b(20\d{2})\b", question or "")})
    return yrs


def _normalize_ql_for_period(question: str) -> str:
    ql = re.sub(r"\s+", " ", (question or "").lower()).strip()
    for ch in ("\u2019", "\u2018", "`", "\u00b4"):
        ql = ql.replace(ch, "'")
    ql = re.sub(r"\blan dernier\b", "l'an dernier", ql)
    ql = re.sub(r"\bl an dernier\b", "l'an dernier", ql)
    return ql


def _relative_period_years(ql: str) -> Optional[List[int]]:
    from datetime import datetime

    now = datetime.now()
    if re.search(
        r"\b(l'an dernier|l'année dernière|l année dernière|annee derniere|année dernière|année passée|"
        r"annee passee|dernière année|derniere annee|last year|an passé|an passe)\b",
        ql,
    ):
        return [now.year - 1]
    if re.search(r"\b(cette année|annee en cours|année en cours|cette annee|this year|an en cours)\b", ql):
        return [now.year]
    if re.search(r"\b(récemment|recemment|derniers mois|derniers temps|recent)\b", ql):
        return [now.year]
    return None


def _resolve_brief_years(question: str) -> List[int]:
    """Expressions relatives (l'an dernier…) prioritaires sur une année explicite ou le défaut."""
    ql = _normalize_ql_for_period(question)
    rel = _relative_period_years(ql)
    if rel:
        return rel
    yrs = _extract_years(ql)
    if yrs:
        return yrs
    from datetime import datetime

    return [datetime.now().year]


def _is_specific_kpi_question(ql: str) -> bool:
    """KPI ciblé (id, métrique, dimension) — ne pas remplacer par un brief générique."""
    if re.search(r"\b(navire|fournisseur)\s*(?:id\s*)?\d+\b", ql):
        return True
    if re.search(r"\b(navire|fournisseur)\s+[a-zA-Z0-9]", ql) and not re.search(
        r"\b(analyse|axes|synthèse|synthese|résumé|resume|récap|recap|situation)\b", ql
    ):
        return True
    if re.search(r"\b(transf[eé]r|d[eéè]charg|command[eé]|accostage|demurrage|surestarie)\b", ql):
        return True
    if re.search(r"\b(par mois|mensuel|par semaine|par jour|top\s*\d+)\b", ql):
        return True
    if re.search(r"\b(quels?|quelles?|classement|ranking|liste des)\b", ql):
        return True
    if re.search(r"\b(d[eé]tail|ligne par ligne)\b", ql):
        return True
    if re.search(r"\b(tonnage|arrivages?)\b", ql) and re.search(r"\b(par|pour chaque|chaque)\b", ql):
        if re.search(r"\b(qualit|fournisseur|navire|mois)\b", ql):
            return True
    if re.search(
        r"\b(nombre|combien|count)\b.*\b(arrivages?|navires?|tonnage|transf)\b", ql
    ) or re.search(r"\b(arrivages?|navires?|tonnage)\b.*\b(nombre|combien|count)\b", ql):
        if not re.search(r"\b(analyse|axes|synthèse|synthese|résumé|resume|récap|recap|situation)\b", ql):
            return True
    return False


def _is_vague_port_overview(ql: str) -> bool:
    """Question ouverte port / arrivages sans KPI explicite (pas une requête technique)."""
    if re.search(r"\b(formule|requete|requête|sql|query)\b", ql):
        return False
    if re.search(r"\b(par mois|par jour|par semaine|top\s*\d+|fournisseur\s+id|navire\s+id)\b", ql):
        return False
    if re.search(r"\b(combien|nombre|count|total|liste des|classement|top)\b", ql) and not re.search(
        r"\b(situation|recap|récap|résumé|resume|synthèse|synthese|comment|dis[- ]?moi)\b", ql
    ):
        return False

    domain = bool(
        re.search(
            r"\b(port|arrivages?|sonasid|marchandises?|import|navires?|tonnage|d[eéè]chargement|accostage)\b",
            ql,
        )
    )
    vague_open = (
        r"\b(situation|état|etat|bilan|panorama|vue d'ensemble|vue globale)\b",
        r"\b(c'est quoi|cest quoi|comment ça va|comment ca va|à quoi ressemble|a quoi ressemble)\b",
        r"\b(ce qui s['']?est passé|qu'est-il arrivé|quest il arrive|quoi de neuf)\b",
        r"\b(comment ça se présente|comment ca se presente|comment se presente)\b",
        r"\b(petit|un|mini|le)?\s*(recap|récap|recapitulatif|résumé|resume|synthèse|synthese)\b",
        r"\b(dis[- ]?moi|explique|raconte|parle moi|fais moi)\b",
        r"\bniveau\b.*\b(marchandises?|import|arrivages?|port|tonnage)\b",
        r"\b(marchandises?|import|arrivages?|port)\b.*\b(récemment|recemment|cette année|l'an dernier)\b",
        r"\b(récemment|recemment|derniers mois|derniers temps)\b.*\b(marchandises?|import|arrivages?|port)\b",
    )
    if any(re.search(p, ql) for p in vague_open):
        if domain:
            return True
        if re.search(r"\b(recap|récap|résumé|resume|synthèse|synthese)\b", ql) and re.search(
            r"\b(20\d{2}|cette année|l'an dernier|année)\b", ql
        ):
            return True
    if re.search(r"\b(situation|état|etat|bilan)\b", ql) and re.search(
        r"\b(port|cette année|20\d{2}|arrivages?)\b", ql
    ):
        return True
    return False


def _year_clause(field: str, year: int) -> str:
    return f"{field} >= '{year:04d}-01-01' AND {field} < '{year + 1:04d}-01-01'"


def _active_arrivage(extra: str = "") -> str:
    base = "Arrivage_Actif = 1"
    return f"{base} AND {extra}" if extra else base


def detect_sonasid_brief(question: str) -> Optional[Dict[str, str]]:
    if not _sonasid_profile_active():
        return None
    from backend.llm.llm_sql import normalize_user_question

    ql = re.sub(r"\s+", " ", normalize_user_question(question or "").lower()).strip()

    if _is_specific_kpi_question(ql):
        return None

    if _is_vague_port_overview(ql):
        if re.search(r"\b(analyse|analyser|axes|multi|d[eéè]taill)\b", ql) or (
            re.search(r"\barrivages?\b", ql)
            and re.search(r"\b(passé|passe|c[oô]t[eé]|historique|l'an dernier|année dernière)\b", ql)
        ):
            return {"kind": "arrivages_analysis"}
        return {"kind": "dashboard"}

    if re.search(r"\b(kpi|kip|indicateurs?)\b", ql) and re.search(
        r"\b(résumé|resume|recap|récap|synthèse|synthese|tableau de bord|donne|donne-moi|tous|ensemble|global|principaux?|l'ensemble)\b",
        ql,
    ):
        return {"kind": "dashboard"}

    if re.search(r"\b(résumé|resume|recap|récap|synthèse|synthese)\b", ql) and re.search(
        r"\b(port|arrivages?|sonasid|marchandises?)\b", ql
    ):
        return {"kind": "dashboard"}

    if re.search(r"\barrivages?\b", ql) or (
        re.search(r"\bnavires?\b", ql) and re.search(r"\barrivages?\b", ql)
    ):
        triggers = (
            r"\b(analyse|analyser|résumé|resume|synthèse|synthese)\b",
            r"\baxes?\s+d['']?analyse\b",
            r"\b(tous|plusieurs|complet|complète|global|détaill|different|différent)\b.*\b(axes?|dimensions?)\b",
            r"\btonnage\b.*\bqualit",
            r"\bqualit.*\btonnage\b",
            r"\b(2025|2026).*(2025|2026)\b",
        )
        if any(re.search(p, ql) for p in triggers):
            return {"kind": "arrivages_analysis"}

    return None


def execute_sonasid_brief(question: str, kind: str) -> Dict[str, Any]:
    q = normalize_kpi_question(question)
    years = _resolve_brief_years(q)

    if kind == "dashboard":
        return _run_dashboard(q, years)
    return _run_arrivages_analysis(q, years)


def _run_dashboard(question: str, years: List[int]) -> Dict[str, Any]:
    period_label = ", ".join(str(y) for y in years)
    lines: List[str] = [
        f"**Résumé port & arrivages — {period_label}**",
        "",
        "Voici une synthèse des principaux indicateurs port & arrivages.",
        "",
    ]
    all_rows: List[Dict[str, Any]] = []

    for year in years:
        df = "Arrivage_DateCreation"
        w_year = _year_clause(f"a.{df}", year)
        w_arr = f"WHERE a.{_active_arrivage(w_year)}"

        nav_actifs, _ = _scalar(f"SELECT COUNT(*) FROM {T_NAVIRE} WHERE Navire_Active = 1")
        n_arr, err = _scalar(f"SELECT COUNT(*) FROM {T_ARRIVAGE} a {w_arr}")
        ton, _ = _scalar(
            f"SELECT SUM(a.Arrivage_TonnageTotal) FROM {T_ARRIVAGE} a {w_arr}"
        )
        nav_dist, _ = _scalar(
            f"SELECT COUNT(DISTINCT nn.NominationNavire_NavireId) "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"{w_arr}"
        )
        ton_trans, _ = _scalar(
            f"SELECT SUM(t.Transfert_PoidsNet) "
            f"FROM {T_TRANSFERT} t "
            f"INNER JOIN {T_COMMANDE} c ON t.Transfert_CommandeId = c.Commande_Id "
            f"INNER JOIN {T_ARRIVAGE} a ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"{w_arr} AND t.Transfert_Actif = 1"
        )

        lines.append(f"### Année {year}")
        if err:
            lines.append(friendly_db_error(err))
            return {
                "question": question,
                "source": "sonasid:brief",
                "brief_kind": "dashboard",
                "years": years,
                "error": "DB_FIREWALL" if "40615" in str(err) or "not allowed" in str(err).lower() else "DB_ERROR",
                "message": "\n".join(lines).strip(),
            }
        lines.extend(
            [
                f"- **Navires actifs (référentiel)** : {_fmt_num(nav_actifs or 0)}",
                f"- **Arrivages** : {_fmt_num(n_arr or 0)}",
                f"- **Navires distincts ayant accosté** : {_fmt_num(nav_dist or 0)}",
                f"- **Tonnage importé** : {_fmt_num(ton or 0)} t",
                f"- **Tonnage transféré** : {_fmt_num(ton_trans or 0)} t",
                "",
            ]
        )
        all_rows.append(
            {
                "annee": year,
                "navires_actifs": nav_actifs or 0,
                "arrivages": n_arr or 0,
                "navires_distincts": nav_dist or 0,
                "tonnage_importe": ton or 0,
                "tonnage_transfere": ton_trans or 0,
            }
        )

        qual_sql = (
            f"SELECT TOP 8 q.Qualite_Libelle, COUNT(DISTINCT a.Arrivage_Id) AS n, "
            f"SUM(c.Commande_Tonnage) AS tonnage "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_COMMANDE} c ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"{w_arr} "
            f"GROUP BY q.Qualite_Libelle ORDER BY tonnage DESC"
        )
        qual_rows, _ = _rows(qual_sql)
        if qual_rows:
            lines.append("**Top qualités (arrivages / tonnage commandé)**")
            for lib, n, t in qual_rows:
                lines.append(f"- {lib} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t commandées")
                all_rows.append(
                    {
                        "annee": year,
                        "qualite": lib,
                        "arrivages": n,
                        "tonnage_commande": t or 0,
                    }
                )
            lines.append("")

        mo_sql = (
            f"SELECT CONVERT(char(7), a.{df}, 126) AS mois, COUNT(*) AS n "
            f"FROM {T_ARRIVAGE} a {w_arr} "
            f"GROUP BY CONVERT(char(7), a.{df}, 126) ORDER BY mois"
        )
        mo_rows, _ = _rows(mo_sql)
        if mo_rows:
            vals = [float(r[1] or 0) for r in mo_rows]
            lines.append(
                f"**Arrivages par mois** : min {_fmt_num(min(vals))} · max {_fmt_num(max(vals))} · "
                f"total {_fmt_num(sum(vals))} ({len(mo_rows)} mois)"
            )
            for mo, n in mo_rows[-3:]:
                lines.append(f"- {mo} : {_fmt_num(n)}")
            lines.append("")

    return {
        "question": question,
        "source": "sonasid:brief",
        "brief_kind": "dashboard",
        "years": years,
        "result": all_rows,
        "message": "\n".join(lines).strip(),
    }


def _run_arrivages_analysis(question: str, years: List[int]) -> Dict[str, Any]:
    lines: List[str] = [
        f"**Analyse arrivages & navires — {', '.join(str(y) for y in years)}**",
        "",
        "Vue multi-axes : globale, mensuelle, par qualité, par fournisseur, tonnage.",
        "",
    ]
    all_rows: List[Dict[str, Any]] = []
    series_monthly: List[Dict[str, Any]] = []

    for year in years:
        df = "Arrivage_DateCreation"
        w_year = _year_clause(f"a.{df}", year)
        w_arr = f"WHERE a.{_active_arrivage(w_year)}"

        n_arr, err = _scalar(f"SELECT COUNT(*) FROM {T_ARRIVAGE} a {w_arr}")
        ton, _ = _scalar(
            f"SELECT SUM(a.Arrivage_TonnageTotal) FROM {T_ARRIVAGE} a {w_arr}"
        )
        nav_dist, _ = _scalar(
            f"SELECT COUNT(DISTINCT nn.NominationNavire_NavireId) "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"{w_arr}"
        )

        lines.append(f"### {year} — vue globale")
        if err:
            return {
                "question": question,
                "source": "sonasid:brief",
                "brief_kind": "arrivages_analysis",
                "years": years,
                "error": "DB_FIREWALL" if "40615" in str(err) or "not allowed" in str(err).lower() else "DB_ERROR",
                "message": "\n".join(
                    lines
                    + ["", friendly_db_error(err)]
                ).strip(),
            }
        lines.extend(
            [
                f"- **Arrivages** : {_fmt_num(n_arr or 0)}",
                f"- **Tonnage importé** : {_fmt_num(ton or 0)} t",
                f"- **Navires distincts** : {_fmt_num(nav_dist or 0)}",
                "",
            ]
        )

        mo_sql = (
            f"SELECT CONVERT(char(7), a.{df}, 126) AS mois, COUNT(*) AS n, "
            f"SUM(a.Arrivage_TonnageTotal) AS tonnage "
            f"FROM {T_ARRIVAGE} a {w_arr} "
            f"GROUP BY CONVERT(char(7), a.{df}, 126) ORDER BY mois"
        )
        mo_rows, _ = _rows(mo_sql)
        if mo_rows:
            lines.append(f"**Par mois ({year})**")
            vals_n = [float(r[1] or 0) for r in mo_rows]
            vals_t = [float(r[2] or 0) for r in mo_rows]
            lines.append(
                f"- Arrivages : min {_fmt_num(min(vals_n))} · max {_fmt_num(max(vals_n))} · "
                f"somme {_fmt_num(sum(vals_n))}"
            )
            lines.append(
                f"- Tonnage : min {_fmt_num(min(vals_t))} · max {_fmt_num(max(vals_t))} · "
                f"somme {_fmt_num(sum(vals_t))} t"
            )
            for mo, n, t in mo_rows:
                series_monthly.append({"period": mo, "value": n, "tonnage": t, "annee": year})
                all_rows.append(
                    {"annee": year, "mois": mo, "arrivages": n, "tonnage": t or 0}
                )
            lines.append("")

        qual_sql = (
            f"SELECT q.Qualite_Libelle, COUNT(DISTINCT a.Arrivage_Id) AS n, "
            f"SUM(c.Commande_Tonnage) AS tonnage_cmd "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_COMMANDE} c ON c.Commande_ArrivageId = a.Arrivage_Id "
            f"INNER JOIN {T_QUALITE} q ON c.Commande_QualiteId = q.Qualite_Id "
            f"{w_arr} "
            f"GROUP BY q.Qualite_Libelle ORDER BY tonnage_cmd DESC"
        )
        qual_rows, _ = _rows(qual_sql)
        if qual_rows:
            lines.append(f"**Par qualité ({year})**")
            for lib, n, t in qual_rows:
                lines.append(f"- {lib} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t commandées")
                all_rows.append(
                    {
                        "annee": year,
                        "qualite": lib,
                        "arrivages": n,
                        "tonnage_commande": t or 0,
                    }
                )
            lines.append("")

        fourn_sql = (
            f"SELECT TOP 10 f.Fournisseur_Nom, COUNT(DISTINCT a.Arrivage_Id) AS n, "
            f"SUM(a.Arrivage_TonnageTotal) AS tonnage "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_FOURNISSEUR} f ON a.Arrivage_FournisseurId = f.Fournisseur_Id "
            f"{w_arr} "
            f"GROUP BY f.Fournisseur_Nom ORDER BY tonnage DESC"
        )
        fourn_rows, _ = _rows(fourn_sql)
        if fourn_rows:
            lines.append(f"**Top fournisseurs ({year})**")
            for nom, n, t in fourn_rows[:5]:
                lines.append(f"- {nom} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t")
                all_rows.append(
                    {
                        "annee": year,
                        "fournisseur": nom,
                        "arrivages": n,
                        "tonnage": t or 0,
                    }
                )
            lines.append("")

    out: Dict[str, Any] = {
        "question": question,
        "source": "sonasid:brief",
        "brief_kind": "arrivages_analysis",
        "years": years,
        "result": series_monthly if series_monthly else all_rows,
        "sections": all_rows,
        "message": "\n".join(lines).strip(),
    }
    if series_monthly:
        out["nombre_arrivages"] = sum(float(r.get("value") or 0) for r in series_monthly)
    return out
