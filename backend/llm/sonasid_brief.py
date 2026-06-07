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


def _is_all_arrivages_overview(ql: str) -> bool:
    """« Parle moi de tous les arrivages en 2026 » → brief multi-axes complet."""
    if not re.search(r"\barrivages?\b", ql):
        return False
    if re.search(r"\btous(\s+les)?\s+arrivages?\b", ql):
        return True
    if re.search(r"\b(tous|ensemble|global|complet|complète|intégral|integral)\b", ql) and re.search(
        r"\b(parle|dis|raconte|explique|fais|donne|donner|parle moi|dis moi)\b", ql
    ):
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


def is_dashboard_analysis_request(ql: str) -> bool:
    """Demande d'interprétation / lecture métier du dashboard (pas une recréation)."""
    if not re.search(r"\b(dashboard|dash\s*board|tableau\s+de\s+bord|tableau\s+bord)\b", ql):
        return False
    return bool(
        re.search(
            r"\b(analyse|analyser|interpréter|interpreter|comment|explique|expliquer|"
            r"lecture|insights?|interprétation|interpretation|synthèse|synthese)\b",
            ql,
        )
    )


def is_explicit_dashboard_request(ql: str) -> bool:
    """Demande explicite de dashboard / visualisation (prioritaire sur un KPI isolé)."""
    if is_dashboard_analysis_request(ql):
        return False
    if re.search(r"\b(dashboard|dash\s*board|tableau\s+de\s+bord|tableau\s+bord)\b", ql):
        return True
    if re.search(
        r"\b(cree|créer|creer|fais|genere|génère|generer|construis|construire|affiche|afficher|montre|montrer)\b",
        ql,
    ) and re.search(r"\b(dashboard|tableau\s+de\s+bord|tableau\s+bord)\b", ql):
        return True
    if re.search(r"\b(petit|mini|un|le)\s+(dashboard|tableau\s+de\s+bord)\b", ql):
        return True
    if re.search(r"\b(visualis|graphique|courbe|histogramme|charts?)\b", ql) and re.search(
        r"\b(kpi|kip|indicateurs?|arrivages?|port|tonnage)\b", ql
    ):
        return True
    return False


def is_dashboard_context_followup(ql: str) -> bool:
    """Relance dashboard / analyse dashboard sans période explicite."""
    if is_dashboard_analysis_request(ql):
        return True
    if not is_explicit_dashboard_request(ql):
        return False
    return bool(
        re.search(
            r"\b(ces|cette|cela|ça|ca|les|analyse|analyser|kpi|kip|indicateurs?)\b",
            ql,
        )
    )


def enrich_dashboard_question_from_history(
    question: str,
    prior_messages: Optional[List[Dict[str, Any]]],
) -> str:
    """Complète une demande dashboard avec l'année du fil récent si absente."""
    q = (question or "").strip()
    if not q or re.search(r"\b(20\d{2})\b", q):
        return q
    if not is_dashboard_context_followup(q.lower()):
        return q
    try:
        from backend.llm.llm_sql import _extract_year_from_messages

        year = _extract_year_from_messages(prior_messages)
        if year:
            return f"{q} en {year}"
    except Exception:
        pass
    return q


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

    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question

        if is_schema_metadata_question(ql):
            return None
    except Exception:
        pass

    if is_dashboard_analysis_request(ql):
        return {"kind": "dashboard", "with_analysis": True}

    if is_explicit_dashboard_request(ql):
        return {"kind": "dashboard"}

    if _is_specific_kpi_question(ql):
        return None

    try:
        from backend.llm.llm_sql import is_kpi_catalog_table_request

        if is_kpi_catalog_table_request(ql):
            return None
    except Exception:
        pass

    if _is_vague_port_overview(ql):
        if (
            _is_all_arrivages_overview(ql)
            or re.search(r"\b(analyse|analyser|axes|multi|d[eéè]taill)\b", ql)
            or (
                re.search(r"\barrivages?\b", ql)
                and re.search(r"\b(passé|passe|c[oô]t[eé]|historique|l'an dernier|année dernière)\b", ql)
            )
        ):
            return {"kind": "arrivages_analysis"}
        return {"kind": "dashboard"}

    if _is_all_arrivages_overview(ql):
        return {"kind": "arrivages_analysis"}

    if re.search(r"\b(kpi|kip|indicateurs?)\b", ql) and re.search(
        r"\b(résumé|resume|recap|récap|synthèse|synthese|tableau de bord|dashboard|donne|donne-moi|tous|ensemble|global|principaux?|l'ensemble|analyse|analyser)\b",
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


def execute_sonasid_brief(question: str, kind: str, *, with_analysis: bool = False) -> Dict[str, Any]:
    q = normalize_kpi_question(question)
    years = _resolve_brief_years(q)

    if kind == "dashboard":
        out = _run_dashboard(q, years)
        if with_analysis:
            out = dict(out)
            out["dashboard_analysis_requested"] = True
        return out
    return _run_arrivages_analysis(q, years)


def _exec_kpi_scalar(question: str) -> Tuple[Optional[float], Optional[str]]:
    """Exécute un KPI Sonasid déterministe et retourne un scalaire."""
    try:
        from backend.llm.sonasid_sql import try_sonasid_kpi_sql

        sql_res = try_sonasid_kpi_sql(question)
        if not sql_res or isinstance(sql_res, dict):
            return None, None
        return _scalar(str(sql_res))
    except Exception:
        return None, None


def _is_all_kpi_dashboard_request(ql: str) -> bool:
    return bool(
        re.search(
            r"\b(tous les kpi|tous les kpis|tous les indicateurs|kpi presents|kpi présents|"
            r"indicateurs disponibles|indicateurs en base)\b",
            ql,
        )
    )


def _deterministic_dashboard_analysis(out: Dict[str, Any]) -> str:
    """Lecture métier déterministe à partir des cartes / séries du dashboard."""
    dash = out.get("dashboard") if isinstance(out.get("dashboard"), dict) else {}
    kpis = dash.get("kpis") if isinstance(dash.get("kpis"), list) else []
    charts = dash.get("charts") if isinstance(dash.get("charts"), list) else []
    if not kpis:
        return ""

    by_year: Dict[Any, Dict[str, float]] = {}
    for k in kpis:
        if not isinstance(k, dict):
            continue
        year = k.get("year")
        label = str(k.get("label") or "").strip()
        val = k.get("value")
        if label and isinstance(val, (int, float)):
            by_year.setdefault(year, {})[label] = float(val)

    lines: List[str] = ["**Lecture métier**", ""]
    for year in sorted(by_year.keys(), key=lambda y: (y is None, y)):
        m = by_year[year]
        year_lbl = f"**{year}**" if year is not None else "**Période**"
        lines.append(year_lbl)
        arr = m.get("Arrivages")
        nav_d = m.get("Navires distincts")
        ton_imp = m.get("Tonnage importé")
        ton_trans = m.get("Tonnage transféré")
        ton_dech = m.get("Tonnage déchargé")
        if isinstance(arr, float) and isinstance(nav_d, float) and nav_d > 0:
            lines.append(
                f"- **Activité portuaire :** {_fmt_num(arr)} arrivages pour "
                f"{_fmt_num(nav_d)} navires distincts "
                f"(≈ {arr / nav_d:.1f} arrivage/navire)."
            )
        if isinstance(ton_imp, float) and ton_imp > 0 and isinstance(ton_trans, float):
            pct = ton_trans / ton_imp * 100.0
            lines.append(
                f"- **Transferts :** {_fmt_num(ton_trans)} t transférées sur "
                f"{_fmt_num(ton_imp)} t importées (≈ {pct:.1f} %)."
            )
        if isinstance(ton_dech, float) and isinstance(ton_imp, float) and ton_imp > 0:
            pct_d = ton_dech / ton_imp * 100.0
            lines.append(
                f"- **Déchargement :** {_fmt_num(ton_dech)} t déchargées "
                f"(≈ {pct_d:.1f} % du tonnage importé)."
            )
        if isinstance(ton_trans, float) and isinstance(ton_dech, float):
            ecart = ton_dech - ton_trans
            if abs(ecart) > 1:
                sens = "supérieur" if ecart > 0 else "inférieur"
                lines.append(
                    f"- **Écart déchargement / transfert :** le déchargé est {sens} "
                    f"de {_fmt_num(abs(ecart))} t — à croiser avec les opérations en cours."
                )
        lines.append("")

    for ch in charts:
        title = str(ch.get("title") or "").lower()
        series = ch.get("result") if isinstance(ch.get("result"), list) else []
        if not series or "par mois" not in title:
            continue
        vals = [float(r.get("value") or 0) for r in series if isinstance(r, dict)]
        if len(vals) < 2:
            continue
        peak_i = max(range(len(vals)), key=lambda i: vals[i])
        low_i = min(range(len(vals)), key=lambda i: vals[i])
        labels = [str(r.get("period") or "") for r in series if isinstance(r, dict)]
        peak_l = labels[peak_i] if peak_i < len(labels) else "?"
        low_l = labels[low_i] if low_i < len(labels) else "?"
        metric = "arrivages" if "arrivage" in title else "tonnage"
        lines.append(
            f"- **Saisonnalité ({metric}) :** pic en {peak_l} ({_fmt_num(vals[peak_i])}), "
            f"creux en {low_l} ({_fmt_num(vals[low_i])}) sur {len(vals)} mois."
        )
        break

    lines.append(
        "- **Points d'attention :** croiser volumes importés, transferts et déchargements "
        "pour repérer retards logistiques ou navires encore en opération."
    )
    return "\n".join(lines).strip()


def _run_dashboard(question: str, years: List[int]) -> Dict[str, Any]:
    import os

    ql = re.sub(r"\s+", " ", normalize_kpi_question(question or "").lower()).strip()
    monthly_focus = bool(re.search(r"\b(par mois|mensuel|chaque mois|mois par mois)\b", ql))
    all_kpi = _is_all_kpi_dashboard_request(ql)
    period_label = ", ".join(str(y) for y in years)
    t_suivi = (
        os.getenv("AZURE_SQL_TABLE_SUIVI_DECHARGEMENT", "dbo.SUIVI_DECHARGEMENT")
        or "dbo.SUIVI_DECHARGEMENT"
    )

    lines: List[str] = [
        f"**Dashboard{' KPI' if all_kpi else ''} port & arrivages — {period_label}**",
        "",
        "Synthèse visuelle des indicateurs clés (cartes KPI + graphiques ci-dessous).",
        "",
    ]
    all_rows: List[Dict[str, Any]] = []
    kpi_cards: List[Dict[str, Any]] = []
    charts: List[Dict[str, Any]] = []

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
        ton_dech, _ = _scalar(
            f"SELECT SUM(s.SuiviDechargement_QuantiteDecharge) "
            f"FROM {t_suivi} s "
            f"INNER JOIN {T_ARRIVAGE} a ON s.SuiviDechargement_ArrivageId = a.Arrivage_Id "
            f"{w_arr}"
        )

        if err:
            lines.append(f"### Année {year}")
            lines.append(friendly_db_error(err))
            return {
                "question": question,
                "source": "sonasid:brief",
                "brief_kind": "dashboard",
                "years": years,
                "error": "DB_FIREWALL" if "40615" in str(err) or "not allowed" in str(err).lower() else "DB_ERROR",
                "message": "\n".join(lines).strip(),
            }

        year_cards = [
            {"label": "Arrivages", "value": n_arr or 0, "unit": "", "year": year},
            {"label": "Tonnage importé", "value": ton or 0, "unit": "t", "year": year},
            {"label": "Tonnage transféré", "value": ton_trans or 0, "unit": "t", "year": year},
            {"label": "Tonnage déchargé", "value": ton_dech or 0, "unit": "t", "year": year},
            {"label": "Navires actifs", "value": nav_actifs or 0, "unit": "", "year": year},
            {"label": "Navires distincts", "value": nav_dist or 0, "unit": "", "year": year},
        ]
        kpi_cards.extend(year_cards)

        lines.append(f"### Année {year}")
        for card in year_cards:
            unit = f" {card['unit']}" if card.get("unit") else ""
            lines.append(f"- **{card['label']}** : {_fmt_num(card['value'])}{unit}")

        if all_kpi:
            for label, q_tpl, unit in (
                ("Navires en déchargement", "nombre de navires en déchargement", ""),
                ("Tonnage déchargé (en cours)", "tonnage déchargé en déchargement", "t"),
                ("Tonnage restant à décharger", "tonnage restant à décharger", "t"),
                ("Valeur marchandises importées", f"valeur des marchandises importées en {year}", "t"),
            ):
                val, _ = _exec_kpi_scalar(q_tpl)
                if val is not None:
                    card = {"label": label, "value": val, "unit": unit, "year": year}
                    kpi_cards.append(card)
                    u = f" {unit}" if unit else ""
                    lines.append(f"- **{label}** : {_fmt_num(val)}{u}")

        lines.append("")

        all_rows.append(
            {
                "annee": year,
                "navires_actifs": nav_actifs or 0,
                "arrivages": n_arr or 0,
                "navires_distincts": nav_dist or 0,
                "tonnage_importe": ton or 0,
                "tonnage_transfere": ton_trans or 0,
                "tonnage_decharge": ton_dech or 0,
            }
        )

        mo_sql = (
            f"SELECT CONVERT(char(7), a.{df}, 126) AS mois, COUNT(*) AS n, "
            f"SUM(a.Arrivage_TonnageTotal) AS tonnage "
            f"FROM {T_ARRIVAGE} a {w_arr} "
            f"GROUP BY CONVERT(char(7), a.{df}, 126) ORDER BY mois"
        )
        mo_rows, _ = _rows(mo_sql)
        if mo_rows:
            arr_series = [{"period": str(mo), "value": float(n or 0)} for mo, n, _t in mo_rows]
            ton_series = [{"period": str(mo), "value": float(t or 0)} for mo, _n, t in mo_rows]
            charts.append(
                {
                    "title": f"Arrivages par mois ({year})",
                    "kind": "line",
                    "question": f"arrivages par mois en {year}",
                    "result": arr_series,
                }
            )
            charts.append(
                {
                    "title": f"Tonnage importé par mois ({year})",
                    "kind": "line",
                    "question": f"tonnage importé par mois en {year}",
                    "result": ton_series,
                }
            )
            for mo, n, t in mo_rows:
                all_rows.append({"annee": year, "mois": mo, "arrivages": n, "tonnage": t or 0})

        dech_sql = (
            f"SELECT CONVERT(char(7), a.{df}, 126) AS mois, "
            f"SUM(s.SuiviDechargement_QuantiteDecharge) AS tonnage "
            f"FROM {t_suivi} s "
            f"INNER JOIN {T_ARRIVAGE} a ON s.SuiviDechargement_ArrivageId = a.Arrivage_Id "
            f"{w_arr} "
            f"GROUP BY CONVERT(char(7), a.{df}, 126) ORDER BY mois"
        )
        dech_rows, _ = _rows(dech_sql)
        if dech_rows:
            charts.append(
                {
                    "title": f"Tonnage déchargé par mois ({year})",
                    "kind": "line",
                    "question": f"tonnage déchargé par mois en {year}",
                    "result": [{"period": str(mo), "value": float(t or 0)} for mo, t in dech_rows],
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
            charts.append(
                {
                    "title": f"Top qualités — tonnage ({year})",
                    "kind": "bar",
                    "question": f"top qualités tonnage en {year}",
                    "result": [
                        {"qualite": str(lib), "value": float(t or 0)} for lib, _n, t in qual_rows
                    ],
                }
            )
            for lib, n, t in qual_rows:
                all_rows.append(
                    {
                        "annee": year,
                        "qualite": lib,
                        "arrivages": n,
                        "tonnage_commande": t or 0,
                    }
                )

    primary_result: Any = all_rows
    if monthly_focus and charts:
        for ch in charts:
            if "par mois" in str(ch.get("title") or "").lower() and "arrivages" in str(ch.get("title") or "").lower():
                primary_result = ch.get("result") or all_rows
                break
    elif charts:
        primary_result = charts[0].get("result") or all_rows

    dashboard = {
        "title": f"Dashboard port & arrivages — {period_label}",
        "monthly": monthly_focus,
        "kpis": kpi_cards,
        "charts": charts,
    }

    return {
        "question": question,
        "source": "sonasid:brief",
        "brief_kind": "dashboard",
        "years": years,
        "dashboard": dashboard,
        "result": primary_result,
        "message": "\n".join(lines).strip(),
    }


def _run_arrivages_analysis(question: str, years: List[int]) -> Dict[str, Any]:
    ql = re.sub(r"\s+", " ", normalize_kpi_question(question or "").lower()).strip()
    overview = _is_all_arrivages_overview(ql)
    period_label = ", ".join(str(y) for y in years)
    if overview:
        lines: List[str] = [
            f"**Vue complète des arrivages — {period_label}**",
            "",
            "Synthèse port & arrivages : totaux, évolution mensuelle, qualités, fournisseurs et navires.",
            "",
        ]
    else:
        lines = [
            f"**Analyse arrivages & navires — {period_label}**",
            "",
            "Vue multi-axes : globale, mensuelle, par qualité, par fournisseur, tonnage.",
            "",
        ]
    all_rows: List[Dict[str, Any]] = []
    series_monthly: List[Dict[str, Any]] = []
    fournisseurs_table: List[Dict[str, Any]] = []
    top_n = 50 if overview else 10

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
                f"- **Arrivages (total)** : {_fmt_num(n_arr or 0)}",
                f"- **Tonnage importé** : {_fmt_num(ton or 0)} t",
                f"- **Navires actifs (référentiel)** : {_fmt_num(nav_actifs or 0)}",
                f"- **Navires distincts ayant accosté** : {_fmt_num(nav_dist or 0)}",
                f"- **Tonnage transféré** : {_fmt_num(ton_trans or 0)} t",
                "",
            ]
        )
        all_rows.append(
            {
                "annee": year,
                "arrivages": n_arr or 0,
                "tonnage_importe": ton or 0,
                "navires_actifs": nav_actifs or 0,
                "navires_distincts": nav_dist or 0,
                "tonnage_transfere": ton_trans or 0,
            }
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
                if overview:
                    lines.append(f"- {mo} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t")
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
            f"SELECT TOP {top_n} f.Fournisseur_Nom, COUNT(DISTINCT a.Arrivage_Id) AS n, "
            f"SUM(a.Arrivage_TonnageTotal) AS tonnage "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_FOURNISSEUR} f ON a.Arrivage_FournisseurId = f.Fournisseur_Id "
            f"{w_arr} "
            f"GROUP BY f.Fournisseur_Nom ORDER BY n DESC, tonnage DESC"
        )
        fourn_rows, _ = _rows(fourn_sql)
        if fourn_rows:
            label = f"Fournisseurs ({year})" if overview else f"Top fournisseurs ({year})"
            lines.append(f"**{label}**")
            show_fourn = fourn_rows if overview else fourn_rows[:5]
            for nom, n, t in show_fourn:
                lines.append(f"- {nom} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t")
                row = {
                    "annee": year,
                    "fournisseur": nom,
                    "nombre_arrivages": n,
                    "tonnage_total": t or 0,
                    "arrivages": n,
                    "tonnage": t or 0,
                }
                all_rows.append(row)
                if overview:
                    fournisseurs_table.append(
                        {
                            "fournisseur": nom,
                            "nombre_arrivages": n,
                            "tonnage_total": t or 0,
                        }
                    )
            lines.append("")

        nav_sql = (
            f"SELECT TOP {top_n} nv.Navire_Nom, COUNT(DISTINCT a.Arrivage_Id) AS n, "
            f"SUM(a.Arrivage_TonnageTotal) AS tonnage "
            f"FROM {T_ARRIVAGE} a "
            f"INNER JOIN {T_NOMINATION} nn ON a.Arrivage_Id = nn.NominationNavire_ArrivageId "
            f"INNER JOIN {T_NAVIRE} nv ON nn.NominationNavire_NavireId = nv.Navire_Id "
            f"{w_arr} "
            f"GROUP BY nv.Navire_Nom ORDER BY n DESC, tonnage DESC"
        )
        nav_rows, _ = _rows(nav_sql)
        if nav_rows:
            label = f"Navires ({year})" if overview else f"Top navires ({year})"
            lines.append(f"**{label}**")
            show_nav = nav_rows if overview else nav_rows[:5]
            for nom, n, t in show_nav:
                lines.append(f"- {nom} : {_fmt_num(n)} arrivages · {_fmt_num(t or 0)} t")
                all_rows.append(
                    {
                        "annee": year,
                        "navire": nom,
                        "nombre_arrivages": n,
                        "tonnage_total": t or 0,
                    }
                )
            lines.append("")

    out: Dict[str, Any] = {
        "question": question,
        "source": "sonasid:brief",
        "brief_kind": "arrivages_analysis",
        "years": years,
        "sections": all_rows,
        "message": "\n".join(lines).strip(),
    }
    if overview and fournisseurs_table:
        out["result"] = fournisseurs_table
        out["fournisseurs_table"] = fournisseurs_table
        if series_monthly:
            out["series_monthly"] = series_monthly
            out["nombre_arrivages"] = sum(float(r.get("value") or 0) for r in series_monthly)
    elif series_monthly:
        out["result"] = series_monthly
        out["nombre_arrivages"] = sum(float(r.get("value") or 0) for r in series_monthly)
    else:
        out["result"] = all_rows
    if not out.get("nombre_arrivages") and overview:
        for row in all_rows:
            if isinstance(row, dict) and row.get("arrivages") and row.get("annee") and not row.get("mois"):
                out["nombre_arrivages"] = row.get("arrivages")
                break
    return out
