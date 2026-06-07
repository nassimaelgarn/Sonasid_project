import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.llm.llm_sql import (
    KPI_ANALYSE_MARKER,
    NEED_PERIOD_ASSISTANT_PREFIX,
    extract_sql,
    generate_sql,
    is_kpi_analyse_message,
    list_kpi_catalog,
    normalize_kpi_question,
    question_has_explicit_period,
)
from backend.llm.kpi_rewrite import is_kpi_rewrite_enabled, rewrite_kpi_question
from backend.database.run_query import run_query
from backend.database import run_query as run_query_mod
from backend.llm.llm_router import is_llm_enabled, generate_sql_with_llm
from backend.llm.sql_guard import validate_select_sql
from backend.llm.kpi_analyse_fallback import (
    build_kpi_analyse_body,
    deterministic_kpi_analyse_text,
    extract_kpi_payload_from_analyse_body,
    is_analysis_text_grounded,
)
from backend.rag.contextualizer import build_rag_context
from backend.rag.ingest import ingest_default_corpus
from backend.rag.store import add_memory


def get_scalar(res):
    return res[0][0] if res and len(res) > 0 and len(res[0]) > 0 and res[0][0] is not None else 0


def _clean_num(v):
    """
    Make DB floats display-friendly:
    - if v is almost an integer -> int
    - else keep 2 decimals max
    """
    try:
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return v
        if isinstance(v, float):
            if abs(v - round(v)) < 1e-6:
                return int(round(v))
            return round(v, 2)
        if hasattr(v, "__float__"):
            x = float(v)
            if abs(x - round(x)) < 1e-6:
                return int(round(x))
            return round(x, 2)
    except Exception:
        pass
    return v


def _kwh_to_mwh(kwh: float) -> float:
    """
    Convert electricity totals to MWh.
    Dataset convention is usually kWh; override via ELECTRIC_ENERGY_UNIT.
    - kwh -> /1000
    - wh -> /1_000_000
    """
    unit = (os.getenv("ELECTRIC_ENERGY_UNIT", "kwh") or "kwh").strip().lower()
    try:
        x = float(kwh)
    except Exception:
        return 0.0
    if unit in {"wh", "watt-hour", "watt-hours"}:
        return x / 1_000_000.0
    # default: kWh
    return x / 1000.0


def _is_single_aggregate_row(result, sql: str) -> bool:
    """Une seule ligne COUNT/SUM sans GROUP BY — pas une série temporelle."""
    if not result or len(result) != 1:
        return False
    row = result[0]
    if not isinstance(row, (list, tuple)):
        return False
    sql_low = (sql or "").lower()
    if re.search(r"\bgroup by\b", sql_low):
        return False
    if re.search(r"\b(periode|convert\s*\(\s*char\s*\(\s*7)", sql_low):
        return False
    return bool(re.search(r"\b(count|sum)\s*\(", sql_low))


def _period_label_from_question(question: str) -> str:
    from backend.llm.llm_sql import _extract_year_month_range

    _, month, _, _ = _extract_year_month_range(question or "")
    if month:
        try:
            y, m = month.split("-", 1)
            names = (
                "janvier",
                "février",
                "mars",
                "avril",
                "mai",
                "juin",
                "juillet",
                "août",
                "septembre",
                "octobre",
                "novembre",
                "décembre",
            )
            mi = int(m)
            if 1 <= mi <= 12:
                return f"{names[mi - 1]} {y}"
        except (TypeError, ValueError):
            pass
        return month
    m_year = re.search(r"\b(20\d{2})\b", question or "")
    if m_year:
        return m_year.group(1)
    return "Période demandée"


def _navire_label_from_question(ql: str) -> str:
    m_id = re.search(r"\bnavire\s*(?:id\s*)?(\d+)\b", ql, re.I)
    if m_id:
        return f"navire id {m_id.group(1)}"
    m_name = re.search(
        r"\bnavire\s+([a-zA-Z0-9][a-zA-Z0-9 \-'']{2,}?)(?:\s+(?:en|pour|de|du|\d{4})|\s*$)",
        ql,
        re.I,
    )
    if m_name:
        return f"navire {m_name.group(1).strip()}"
    return "navire demandé"


_MONTH_FR = (
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)


def _label_period_bucket(p: str) -> str:
    p = str(p or "").strip()
    m = re.match(r"^(20\d{2})-(\d{2})$", p)
    if m:
        try:
            mi = int(m.group(2))
            if 1 <= mi <= 12:
                return f"{_MONTH_FR[mi - 1]} {m.group(1)}"
        except ValueError:
            pass
    return p


def _build_monthly_series_message(
    question: str,
    rows: List[Dict[str, Any]],
    *,
    metric_label: str,
) -> str:
    periods: List[str] = []
    vals: List[float] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        p = row.get("period") or row.get("periode") or row.get("mois")
        v = row.get("value")
        if v is None:
            v = row.get("nombre_arrivages") or row.get("nombre_navires_actifs") or row.get("tonnage_importe")
        if p is None or not isinstance(v, (int, float)):
            continue
        periods.append(str(p))
        vals.append(float(v))
    if not vals:
        return f"**{metric_label} par mois** — aucune donnée sur la période."

    y_match = re.search(r"\b(20\d{2})\b", question or "")
    year = y_match.group(1) if y_match else ""
    title = f"**{metric_label} par mois"
    if year:
        title += f" en {year}"
    title += "**"

    def _fmt(v: float) -> str:
        return str(int(v)) if v == int(v) else f"{v:.2f}"

    span_label = ""
    if periods:
        first = _label_period_bucket(periods[0])
        last = _label_period_bucket(periods[-1])
        if len(periods) == 1 or periods[0] == periods[-1]:
            span_label = first
        elif year and periods[0].startswith(f"{year}-01") and periods[-1].startswith(f"{year}-12"):
            span_label = f"{first} → {last}"
        else:
            span_label = f"de {first} à {last}"

    parts = [title]
    if len(vals) == 1:
        parts.append(f"- **Période :** {span_label or _label_period_bucket(periods[0])}")
        parts.append(f"- **Valeur :** {_fmt(vals[0])}")
    else:
        parts.append(f"- **Périodes :** {len(vals)}" + (f" ({span_label})" if span_label else ""))
        parts.append(f"- **Min / max :** {_fmt(min(vals))} / {_fmt(max(vals))}")
        parts.append(f"- **Total sur la série :** {_fmt(sum(vals))}")
        if len(vals) >= 2:
            delta = vals[-1] - vals[0]
            sign = "+" if delta > 0 else ""
            parts.append(
                f"- **Tendance :** {sign}{_fmt(delta)} "
                f"({_fmt(vals[0])} → {_fmt(vals[-1])}, {span_label or ''})"
            )
    return "\n".join(parts)


def _build_dechargement_list_message(question: str, formatted: List[Dict[str, Any]]) -> str:
    n = len(formatted)
    lines = [f"**Navires en déchargement** — {n} navire(s) / arrivage(s)", ""]
    for row in formatted[:15]:
        nom = row.get("navire") or "—"
        arr = row.get("arrivage_id")
        ton = row.get("tonnage_arrivage")
        rest = row.get("quantite_restante")
        chunk = f"- **{nom}**"
        if arr is not None:
            chunk += f" (arrivage {arr})"
        parts = []
        if isinstance(ton, (int, float)):
            parts.append(f"{_clean_num(ton)} t à bord")
        if isinstance(rest, (int, float)):
            parts.append(f"{_clean_num(rest)} t restantes")
        if parts:
            chunk += " · ".join(parts)
        lines.append(chunk)
    if n > 15:
        lines.append(f"\n… et {n - 15} autres lignes (bouton « Voir les lignes »).")
    return "\n".join(lines)


def _format_rows(question_lower: str, rows):
    """
    Format SQLite rows for display:
    - 2+ columns: list of dicts (grade/value if query mentions grade, else categorie/poids)
    - 1 column with multiple rows: list of values
    """
    if not rows:
        return 0

    first = rows[0]
    if isinstance(first, (list, tuple)) and len(first) >= 2:
        if "par jour" in question_lower or "par semaine" in question_lower or "par mois" in question_lower or "par annee" in question_lower or "par année" in question_lower:
            if len(first) == 2:
                return [{"period": r[0], "value": r[1]} for r in rows]
            if len(first) == 3:
                # period + (largeur/epaisseur/categorie) + value
                if "largeur" in question_lower:
                    return [{"period": r[0], "largeur": r[1], "value": r[2]} for r in rows]
                if "épaisseur" in question_lower or "epaisseur" in question_lower:
                    return [{"period": r[0], "epaisseur": r[1], "value": r[2]} for r in rows]
                if "qualit" in question_lower:
                    return [{"period": r[0], "qualite": r[1], "value": r[2]} for r in rows]
                return [{"period": r[0], "categorie": r[1], "value": r[2]} for r in rows]
            if len(first) >= 4:
                # period + largeur + epaisseur + value (brames/dimensions)
                return [{"period": r[0], "largeur": r[1], "epaisseur": r[2], "value": r[3]} for r in rows]
        if "grade" in question_lower:
            return [{"grade": r[0], "value": r[1]} for r in rows]
        if ("largeur" in question_lower or "épaisseur" in question_lower or "epaisseur" in question_lower) and len(first) >= 3:
            return [{"largeur": r[0], "epaisseur": r[1], "value": r[2]} for r in rows]
        if "largeur" in question_lower and len(first) == 2:
            return [{"largeur": r[0], "value": r[1]} for r in rows]
        if ("épaisseur" in question_lower or "epaisseur" in question_lower) and len(first) == 2:
            return [{"epaisseur": r[0], "value": r[1]} for r in rows]
        if ("qualite" in question_lower or "qualité" in question_lower) and len(first) == 2:
            return [{"qualite": r[0], "value": r[1]} for r in rows]
        if ("qualite" in question_lower or "qualité" in question_lower) and len(first) == 3:
            # Par fournisseur / commandé / transfert agrégé : Qualite_Id, Libelle, tonnage
            if isinstance(first[0], (int, float)) and isinstance(first[1], str):
                if re.search(r"\btransf", question_lower):
                    key = "tonnage_transfere"
                elif re.search(r"\bimport", question_lower):
                    key = "tonnage_importe"
                else:
                    key = "tonnage"
                return [
                    {"qualite_id": r[0], "qualite": r[1], key: r[2], "value": r[2]}
                    for r in rows
                ]
            # Liste référentiel : id, libellé, actif
            if isinstance(first[0], (int, float)) and isinstance(first[2], (int, float, bool)):
                return [
                    {
                        "qualite_id": r[0],
                        "qualite": r[1],
                        "active": bool(r[2]) if r[2] is not None else None,
                    }
                    for r in rows
                ]
            # Transfert officiel : Qualite_Libelle, Commande_QualiteId, Transfert_PoidsNet
            return [{"qualite": r[0], "qualite_id": r[1], "poids_net": r[2]} for r in rows]
        if ("qualite" in question_lower or "qualité" in question_lower) and len(first) >= 5:
            rows_out = []
            for r in rows:
                row_out: Dict[str, Any] = {
                    "arrivage_id": r[0],
                    "navire": r[1],
                    "qualite_id": r[2],
                    "qualite": r[3],
                    "value": r[4],
                }
                if re.search(r"\btransf", question_lower):
                    row_out["tonnage_transfere"] = r[4]
                rows_out.append(row_out)
            return rows_out
        if re.search(r"\bd[eéè]charg", question_lower, re.I) and len(first) >= 4:
            return [
                {
                    "navire": r[0],
                    "arrivage_id": r[1],
                    "debut_dechargement": r[2],
                    "tonnage_arrivage": r[3],
                    "quantite_restante": r[4],
                }
                for r in rows
            ]
        if re.search(r"\bd[eéè]charg", question_lower, re.I) and len(first) == 3:
            if isinstance(first[1], (int, float)) and re.search(r"\btaux\b", question_lower):
                return [
                    {"navire": r[0], "arrivage_id": r[1], "taux_dechargement": r[2]}
                    for r in rows
                ]
            if isinstance(first[0], str) and isinstance(first[1], (int, float)):
                return [
                    {"periode": r[0], "tonnage_decharge": r[1], "value": r[1]}
                    for r in rows
                ]
        if re.search(r"\bfournisseur", question_lower) and len(first) >= 3:
            if isinstance(first[0], (int, float)) and isinstance(first[1], str):
                formatted: List[Dict[str, Any]] = []
                for r in rows:
                    row: Dict[str, Any] = {
                        "fournisseur_id": r[0],
                        "fournisseur": r[1],
                        "nombre_arrivages": r[2],
                        "value": r[2],
                    }
                    if len(r) > 3:
                        row["tonnage_total"] = r[3]
                    formatted.append(row)
                return formatted
        if re.search(r"\bnavires?\b", question_lower) and len(first) >= 3:
            if isinstance(first[0], (int, float)) and isinstance(first[1], str):
                nav_rows: List[Dict[str, Any]] = []
                for r in rows:
                    nav_row: Dict[str, Any] = {
                        "navire_id": r[0],
                        "navire": r[1],
                        "value": r[2],
                    }
                    if re.search(r"\btransf", question_lower):
                        nav_row["tonnage_transfere"] = r[2]
                    else:
                        nav_row["tonnage_importe"] = r[2]
                    nav_rows.append(nav_row)
                return nav_rows
        if len(first) == 3 and re.search(r"\bqualit", question_lower):
            return [
                {"qualite": r[0], "arrivages": r[1], "tonnage": r[2], "value": r[2]}
                for r in rows
            ]
        if len(first) >= 3:
            return [{"dim1": r[0], "dim2": r[1], "value": r[2]} for r in rows]
        return [{"categorie": r[0], "poids": r[1]} for r in rows]

    if isinstance(first, (list, tuple)) and len(first) == 1 and len(rows) > 1:
        return [r[0] for r in rows]

    return get_scalar(rows)


def _quote_known_tables(sql: str) -> str:
    """
    SQLite nécessite souvent des guillemets pour les tables commençant par un chiffre (ex: 02_EAF).
    Cette fonction essaie de corriger un SQL LLM en ajoutant des guillemets autour des tables connues.
    """
    if not sql:
        return sql

    # Remplacements simples et sûrs sur mots entiers.
    replacements = [
        "01_PAF",
        "02_EAF",
        "03_LF",
        "04_CCM_Coulée",
        "05_CCM_Brame",
        "CCM_Analyse",
        "Défauts_Brame",
        "EAF_Analyses",
        "EAF_Arrêts",
        "LF_Analyse",
    ]

    fixed = sql
    for t in replacements:
        # Remplace "FROM 02_EAF" -> 'FROM "02_EAF"' (et JOIN idem)
        fixed = re.sub(
            rf'(?i)\b(from|join)\s+{re.escape(t)}\b',
            lambda m, _t=t: f'{m.group(1)} "{_t}"',
            fixed,
        )
    return fixed


def _strip_inline_analysis_verbs(text: str) -> str:
    """Retire « analyse / résume / explique … » en tête pour que le moteur KPI reconnaisse la question."""
    t = (text or "").strip()
    return re.sub(
        r"(?is)^\s*(analyse(r|z)?|analysons|résumé|résume|resumé|resume|resumer|interprète|interprete|explique)\s+",
        "",
        t,
    ).strip()


def _fetch_conso_monthly_series_for_analysis(canon_q: str) -> Optional[List[Dict[str, Any]]]:
    """
    Quand la réponse KPI n'est qu'un total (sans série), récupère la même conso « par mois »
    pour alimenter une vraie analyse (tendances, pics, répartition EAF/LF).
    """
    q0 = _strip_inline_analysis_verbs(canon_q)
    if not q0:
        return None
    ql = q0.lower()
    if any(
        x in ql
        for x in (
            "par mois",
            "par jour",
            "par semaine",
            "par année",
            "par annee",
            "par an ",
            "par an\n",
        )
    ):
        return None
    if "consomm" not in ql and "conso" not in ql:
        return None
    # If the user selected a short custom range (e.g. "du 2025-01-01 au 2025-01-16"),
    # a monthly series collapses to one bucket and looks "wrong". Prefer daily series.
    granularity = "par mois"
    try:
        from datetime import date as _date

        m = re.search(r"(?i)\bdu\s+(\d{4}-\d{2}-\d{2})\s+(?:au|a|à)\s+(\d{4}-\d{2}-\d{2})\b", q0)
        if m:
            a = _date.fromisoformat(m.group(1))
            b = _date.fromisoformat(m.group(2))
            if (b - a).days <= 40:
                granularity = "par jour"
    except Exception:
        pass

    q2 = normalize_kpi_question(f"{q0} {granularity}")
    raw = generate_sql(q2)
    if not isinstance(raw, dict) or "eaf" not in raw or "lf" not in raw:
        return None
    try:
        eaf_result = run_query(raw["eaf"])
        lf_result = run_query(raw["lf"])
        eaf_fmt = _format_rows(q2.lower(), eaf_result)
        lf_fmt = _format_rows(q2.lower(), lf_result)
        is_series = (
            isinstance(eaf_fmt, list)
            and len(eaf_fmt) > 0
            and isinstance(eaf_fmt[0], dict)
            and "period" in eaf_fmt[0]
            and ("value" in eaf_fmt[0] or "poids" in eaf_fmt[0])
        )
        if not is_series:
            return None
        by_period: Dict[Any, Dict[str, Any]] = {}
        for r in eaf_fmt:
            p = r.get("period")
            if p is None:
                continue
            by_period.setdefault(p, {"period": p, "eaf": 0.0, "lf": 0.0})
            by_period[p]["eaf"] += float(r.get("value") or 0)
        if (
            isinstance(lf_fmt, list)
            and len(lf_fmt) > 0
            and isinstance(lf_fmt[0], dict)
            and "period" in lf_fmt[0]
        ):
            for r in lf_fmt:
                p = r.get("period")
                if p is None:
                    continue
                by_period.setdefault(p, {"period": p, "eaf": 0.0, "lf": 0.0})
                by_period[p]["lf"] += float(r.get("value") or 0)
        rows: List[Dict[str, Any]] = []
        for p in sorted(by_period.keys()):
            rec = by_period[p]
            total = float(rec["eaf"]) + float(rec["lf"])
            rows.append({"period": p, "value": total, "eaf": rec["eaf"], "lf": rec["lf"]})
        return rows or None
    except Exception:
        return None


def _fetch_sonasid_monthly_series_for_analysis(canon_q: str) -> Optional[List[Dict[str, Any]]]:
    """Série mensuelle Sonasid (tonnage, arrivages…) pour alimenter une analyse LLM."""
    q0 = _strip_inline_analysis_verbs(canon_q)
    if not q0:
        return None
    ql = q0.lower()
    if any(x in ql for x in ("par mois", "par jour", "par semaine", "mensuel")):
        return None
    if not re.search(r"\b(tonnage|arrivages?|navires?|transfert|commande)\b", ql):
        return None
    q2 = normalize_kpi_question(f"{q0} par mois")
    raw = generate_sql(q2)
    sql = extract_sql(raw) if not isinstance(raw, dict) else None
    if not sql:
        return None
    try:
        result = run_query(sql)
        if isinstance(result, str) or not result:
            return None
        formatted = _format_rows(ql, result)
        if (
            isinstance(formatted, list)
            and formatted
            and isinstance(formatted[0], dict)
            and formatted[0].get("period") is not None
        ):
            return formatted
    except Exception:
        return None
    return None


def process_question(question, model_name: str = "", session_id: Optional[str] = None):
    # Ensure default corpus is indexed (idempotent, small).
    # This enables RAG even on first run without manual ingest.
    try:
        ingest_default_corpus()
    except Exception:
        pass

    q_in = (question or "").strip()
    try:
        from backend.llm.llm_sql import (
            is_contextual_data_followup_text,
            merge_table_format_followup_from_history,
        )
        from backend.llm.sonasid_brief import enrich_dashboard_question_from_history, is_explicit_dashboard_request

        if session_id:
            from backend.rag.store import get_conversation_history

            prior = get_conversation_history(session_id=session_id, limit=80)
            if is_explicit_dashboard_request(q_in.lower()):
                enriched = enrich_dashboard_question_from_history(q_in, prior)
                if enriched and enriched.strip() != q_in:
                    q_in = enriched.strip()
                    question = q_in
            if is_contextual_data_followup_text(q_in):
                merged = merge_table_format_followup_from_history(q_in, prior)
                if merged and merged.strip() and merged.strip() != q_in:
                    q_in = merged.strip()
                    question = q_in
    except Exception:
        pass
    _open_expanded = False
    _expand_notice: Optional[str] = None
    try:
        from backend.llm.sonasid_schema import is_schema_metadata_question, schema_metadata_reply

        if is_schema_metadata_question(q_in):
            return schema_metadata_reply(q_in)
    except Exception:
        pass
    try:
        from backend.llm.sonasid_sql import expand_sonasid_open_question

        _before_expand = q_in
        q_in, _expand_notice = expand_sonasid_open_question(q_in)
        _open_expanded = q_in.strip() != _before_expand.strip()
    except Exception:
        pass
    ql_in = q_in.lower()
    # NOTE: We intentionally do NOT short-circuit greetings here.
    # General conversation should be handled by the agent/LLM to stay natural.

    if is_kpi_analyse_message(q_in):
        body = q_in[len(KPI_ANALYSE_MARKER) :].lstrip()
        payload = extract_kpi_payload_from_analyse_body(body) or {}
        if not isinstance(payload, dict) or not payload:
            return {
                "question": q_in,
                "message": (
                    "Je ne peux pas faire une analyse sans données chiffrées.\n"
                    "Exécute d’abord un KPI (avec période), puis clique sur **Analyser** sous le résultat."
                ),
                "source": "pipeline:analyse:need_data",
            }
        rag_ctx = ""
        try:
            head = (body or "")[:1200]
            rag_ctx = build_rag_context(question=head, session_id=session_id)
        except Exception:
            pass
        _prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
        if _prof in {"sonasid", "shipping", "port"}:
            from backend.llm.sonasid_prompts import sonasid_analyst_domain

            _domain = sonasid_analyst_domain()
        else:
            _domain = "Tu es un analyste KPI pour une aciérie.\n"
        sys = (
            _domain
            + "Des résultats chiffrés du dashboard viennent d’être calculés ; tu dois les interpréter.\n"
            "Réponds en français, de façon concise (listes à puces courtes si utile).\n"
            "N’invente aucune valeur absente des données fournies. Ne propose pas de nouvelle requête SQL.\n"
        )
        prompt = f"{sys}\n\nConsigne et données:\n{body}\n\nContexte complémentaire:\n{rag_ctx or '(vide)'}\n"
        from backend.agent.llm import invoke_chat_text

        model_hint = (os.getenv("PIPELINE_CHAT_MODEL", "") or os.getenv("OPENROUTER_MODEL", "") or "").strip()
        text = ""
        last_err: Optional[str] = None
        for mn in (model_hint, "flash"):
            if not mn:
                continue
            try:
                text = (invoke_chat_text(prompt=prompt, model_name=mn) or "").strip()
            except Exception as e:
                last_err = str(e) or repr(e)
                text = ""
            if text:
                break
        if not text:
            fb = deterministic_kpi_analyse_text(body)
            if not fb and isinstance(payload, dict):
                from backend.llm.kpi_analyse_fallback import deterministic_kpi_analyse_from_dict

                fb = deterministic_kpi_analyse_from_dict(payload)
            if fb:
                note = ""
                if last_err and re.search(r"\b(401|402|429|User not found|insufficient credits)\b", last_err, re.I):
                    note = "\n\n_(Synthèse automatique — le modèle cloud est indisponible ; basculez sur **Flash** pour une analyse IA.)_"
                else:
                    note = "\n\n_(Synthèse automatique.)_"
                return {
                    "question": q_in,
                    "message": fb + note,
                    "source": "pipeline:analyse+fallback",
                }
            msg = "Je n’ai pas pu produire d’analyse à partir de ces données."
            if last_err and re.search(r"\b(401|402|User not found)\b", last_err, re.I):
                msg = (
                    "Le modèle sélectionné n’est pas accessible avec la clé API actuelle.\n"
                    "Choisis le modèle **Flash** dans le panneau de gauche, ou relance l’analyse."
                )
            elif last_err:
                msg = f"Analyse indisponible pour le moment.\n\nDétail technique : {last_err}"
            return {"question": q_in, "message": msg, "source": "pipeline:analyse:error"}
        # Reject generic answers that don't cite any number from data.
        if not is_analysis_text_grounded(text, payload):
            fb = deterministic_kpi_analyse_text(body)
            if fb:
                text = fb
            else:
                return {
                    "question": q_in,
                    "message": (
                        "Je ne peux pas produire une analyse fiable sans chiffres exploitables dans les données.\n"
                        "Exécute d’abord un KPI (avec période), puis clique sur **Analyser** sous le résultat."
                    ),
                    "source": "pipeline:analyse:need_data",
                }
        return {"question": q_in, "message": text, "source": "pipeline:analyse"}

    kpi_rewrite_box: Dict[str, Any] = {}
    sonasid_period_notice: Optional[str] = _expand_notice

    def _user_requests_inline_analysis(text: str) -> bool:
        t = (text or "").strip().lower()
        if re.search(r"\b(tableau|tableaux|tabulaire)\b", t) and not re.search(
            r"\b(analyse|analyser|résumé|resume|interprète|explique)\b", t
        ):
            return False
        return bool(
            re.search(
                r"\b(analyse(r|z)?|analysons|résumé|résume|resumé|resume|resumer|interprète|interprete|explique)\b",
                t,
            )
        )

    def _user_requests_table_format(text: str) -> bool:
        t = (text or "").strip().lower()
        return bool(re.search(r"\b(tableau|tableaux|tabulaire|colonnes|grille)\b", t))

    def _has_interpretable_kpi_payload(d: Dict[str, Any]) -> bool:
        if not isinstance(d, dict) or d.get("error"):
            return False
        if d.get("source") == "pipeline:need_period":
            return False
        if d.get("sql") or d.get("sqls"):
            return False
        if d.get("interpretation"):
            return False
        if isinstance(d.get("result"), list):
            return True
        if isinstance(d.get("result"), (int, float)):
            return True
        for k in (
            "Consommation_Totale",
            "Consommation_MWh",
            "Consommation_EAF",
            "Consommation_LF",
            "Consommation_Oxygène",
            "Consommation_Carbon",
            "Consommation_GPL",
            "TD_percent",
            "TR_percent",
            "MTBF_secondes",
            "MTTR_secondes",
            "Rendement_percent",
        ):
            if k in d and isinstance(d.get(k), (int, float)):
                return True
        if isinstance(d.get("period_a"), dict) and isinstance(d.get("period_b"), dict):
            return True
        return False

    chat_model = (model_name or os.getenv("SONASID_NARRATE_MODEL", "") or "").strip()

    def _maybe_add_interpretation(original_q: str, d: Dict[str, Any]) -> Dict[str, Any]:
        """
        Quand l'utilisateur demande explicitement une analyse / résumé dans la même phrase qu'un KPI,
        attache une interprétation (LLM + repli déterministe).

        Si la réponse n'est que des totaux de consommation, on enrichit avec la série **par mois**
        (une requête KPI supplémentaire) pour pouvoir parler de tendances et de répartition EAF/LF.
        """
        if not _user_requests_inline_analysis(original_q):
            return d
        if not _has_interpretable_kpi_payload(d):
            return d
        from backend.agent.llm import invoke_chat_text

        cq = str(d.get("question") or original_q or "").strip()
        enriched: Dict[str, Any] = dict(d)
        if not isinstance(enriched.get("result"), list):
            has_scalar_conso = any(
                isinstance(enriched.get(k), (int, float))
                for k in enriched
                if isinstance(k, str) and k.startswith("Consommation_")
            )
            if has_scalar_conso:
                series = _fetch_conso_monthly_series_for_analysis(cq)
                if series:
                    enriched["result"] = series
                    enriched["_rows_total"] = len(series)
            elif _sonasid_pipe and isinstance(enriched.get("result"), (int, float)):
                series = _fetch_sonasid_monthly_series_for_analysis(cq)
                if series:
                    enriched["result"] = series
                    enriched["_rows_total"] = len(series)

        body = build_kpi_analyse_body(canonical_question=cq, raw=enriched)
        if not body:
            return d
        payload = extract_kpi_payload_from_analyse_body(body) or {}
        if not isinstance(payload, dict) or not payload:
            # No numbers/series in payload → refuse to narrate.
            out = dict(d)
            out["interpretation"] = (
                "Je ne peux pas produire une analyse fiable sans données chiffrées exploitables.\n"
                "Exécute d’abord le KPI (avec période), puis clique sur **Analyser** sous le résultat."
            )
            return out
        from backend.llm.sonasid_prompts import sonasid_analyst_domain

        sys = (
            sonasid_analyst_domain()
            + "Tu dois INTERPRÉTER les chiffres : tendance dans le temps, mois forts/faibles, saisonnalité, "
            "points d'attention logistiques.\n"
            + "Ne te contente pas de recopier les totaux : tire des insights métier à partir des données JSON.\n"
            + "Réponds en français (4 à 8 phrases ou puces courtes).\n"
            + "Ne propose pas de nouvelle requête SQL.\n"
        )
        prompt = f"{sys}\n\nConsigne et données:\n{body}\n"
        model_hint = (
            chat_model
            or (os.getenv("PIPELINE_CHAT_MODEL", "") or os.getenv("OPENROUTER_MODEL", "") or "").strip()
        )
        text = ""
        last_err: Optional[str] = None
        for mn in (model_hint, (os.getenv("SONASID_NARRATE_MODEL", "") or "").strip(), "flash"):
            if not mn:
                continue
            try:
                text = (
                    invoke_chat_text(
                        prompt=prompt,
                        model_name=mn,
                        temperature=float(os.getenv("SONASID_NARRATE_TEMPERATURE", "0.4")),
                    )
                    or ""
                ).strip()
            except Exception as e:
                last_err = str(e) or repr(e)
                text = ""
            if text:
                break
        if not text:
            text = (deterministic_kpi_analyse_text(body) or "").strip()
        if not text and last_err:
            text = (
                "Je n’ai pas pu générer l’analyse textuelle (modèle indisponible).\n"
                f"Détail : {last_err}\n"
                "Tu peux quand même utiliser le bouton **Analyser** sous le résultat, ou choisir le modèle **Flash**."
            )
        if not text:
            return d
        if not is_analysis_text_grounded(text, payload):
            fb = (deterministic_kpi_analyse_text(body) or "").strip()
            if fb:
                text = fb
            else:
                text = (
                    "Je ne peux pas produire une analyse fiable sans chiffres exploitables dans les données.\n"
                    "Exécute d’abord le KPI (avec période), puis clique sur **Analyser** sous le résultat."
                )
        out = dict(d)
        out["interpretation"] = text
        return out

    def attach_rewrite(d: Dict[str, Any]) -> Dict[str, Any]:
        out = _maybe_add_interpretation(q_in, dict(d))
        if sonasid_period_notice and not out.get("notice"):
            out = dict(out)
            out["notice"] = sonasid_period_notice
        meta = kpi_rewrite_box.get("meta")
        if meta:
            out = dict(out)
            out["kpi_rewrite"] = meta
        try:
            _prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
            if _prof in {"sonasid", "shipping", "port"}:
                from backend.llm.sonasid_narrative import enrich_sonasid_response
                from backend.llm.sonasid_answer import finalize_user_response

                sql_used = out.get("tsql") or out.get("sql") or out.get("llm_sql") or ""
                out = enrich_sonasid_response(
                    out,
                    question=str(out.get("question") or question),
                    sql=str(sql_used) if sql_used else None,
                )
                out = finalize_user_response(out, q_in, model_name=chat_model)
        except Exception:
            pass
        return out

    _prof_pipe = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    _sonasid_pipe = _prof_pipe in {"sonasid", "shipping", "port"}

    if _sonasid_pipe:
        try:
            from backend.llm.sonasid_brief import detect_sonasid_brief, execute_sonasid_brief

            brief_hint = detect_sonasid_brief(q_in)
            if brief_hint:
                return attach_rewrite(execute_sonasid_brief(q_in, brief_hint["kind"]))
        except Exception:
            pass
        try:
            from backend.llm.llm_sql import is_kpi_catalog_table_request, kpi_catalog_table_reply

            if is_kpi_catalog_table_request(q_in):
                return attach_rewrite(kpi_catalog_table_reply(q_in))
        except Exception:
            pass

    q_for_sql = _strip_inline_analysis_verbs(q_in) if _sonasid_pipe else q_in
    question = normalize_kpi_question(q_for_sql)
    try:
        from backend.llm.sonasid_sql import augment_sonasid_question_period

        question, sonasid_period_notice = augment_sonasid_question_period(question)
    except Exception:
        pass
    raw = generate_sql(question)
    llm_meta = None

    # If user asked for "consommation" without specifying the type, ask a single clarification.
    if isinstance(raw, dict) and raw.get("type") == "need_conso_type":
        return attach_rewrite(
            {
                "question": question,
                "source": "pipeline:need_conso_type",
                "message": (
                    "Tu veux la **consommation** de quel type ?\n"
                    "Exemples :\n"
                    "- consommation **électrique** en 2025-01\n"
                    "- consommation **oxygène** en 2025-01\n"
                    "- consommation **GPL** en 2025-01\n"
                    "- consommation **carbone** en 2025-01\n"
                    "- consommation **par ferraille** en 2025-01"
                ),
            }
        )

    if isinstance(raw, dict) and raw.get("type") == "need_fournisseur":
        return attach_rewrite(
            {
                "question": question,
                "source": "pipeline:need_fournisseur",
                "message": raw.get("message")
                or "Précise le fournisseur (id ou nom) pour ce KPI.",
            }
        )

    if isinstance(raw, dict) and raw.get("type") == "need_navire":
        return attach_rewrite(
            {
                "question": question,
                "source": "pipeline:need_navire",
                "message": raw.get("message")
                or "Précise le navire (id ou nom) pour ce KPI.",
            }
        )

    # Reformulation LLM (aciérie) — désactivée par défaut en mode Sonasid ouvert.
    try:
        from backend.llm.sonasid_open import is_sonasid_kpi_rewrite_enabled

        _rewrite_on = is_sonasid_kpi_rewrite_enabled()
    except Exception:
        _rewrite_on = is_kpi_rewrite_enabled()
    if (
        isinstance(raw, str)
        and extract_sql(raw).strip().upper() == "SELECT 1"
        and _rewrite_on
        and not _open_expanded
    ):
        try:
            from backend.llm.llm_sql import should_skip_kpi_rewrite

            if should_skip_kpi_rewrite(question):
                _rewrite_on = False
        except Exception:
            pass
    if (
        isinstance(raw, str)
        and extract_sql(raw).strip().upper() == "SELECT 1"
        and _rewrite_on
        and not _open_expanded
    ):
        rag_ctx = ""
        try:
            rag_ctx = build_rag_context(question=question, session_id=session_id)
        except Exception:
            pass
        rw, prov, rw_reason = rewrite_kpi_question(
            question,
            extra_context=rag_ctx,
            model_name=(model_name or "").strip(),
        )
        if rw:
            q2 = normalize_kpi_question(rw.strip())
            raw2 = generate_sql(q2)
            sql2 = extract_sql(raw2).strip().upper() if isinstance(raw2, str) else ""
            if not (isinstance(raw2, str) and sql2 == "SELECT 1"):
                question = q2
                raw = raw2
                kpi_rewrite_box["meta"] = {
                    "used": True,
                    "provider": prov,
                    "canonical_question": q2,
                    "note": rw_reason if rw_reason != "OK" else None,
                }

    def _kpi_raw_executable(raw_sql: Any) -> bool:
        if isinstance(raw_sql, dict) and ("eaf" in raw_sql or "lf" in raw_sql):
            return True
        if isinstance(raw_sql, str) and extract_sql(raw_sql).strip().upper() != "SELECT 1":
            return True
        return False

    # Sans période dans la question : ne pas exécuter un KPI sur toute la base (sauf si injecté côté UI : du … au …).
    _needs_period = True
    try:
        from backend.llm.sonasid_sql import sonasid_kpi_requires_period

        _needs_period = sonasid_kpi_requires_period(question)
    except Exception:
        pass
    try:
        from backend.llm.sonasid_open import is_sonasid_llm_first

        _llm_first = is_sonasid_llm_first()
    except Exception:
        _llm_first = False
    if (
        os.getenv("KPI_REQUIRE_EXPLICIT_PERIOD", "true").strip().lower() in {"1", "true", "yes", "on"}
        and _kpi_raw_executable(raw)
        and _needs_period
        and not question_has_explicit_period(question)
        and not _llm_first
        and not _open_expanded
    ):
        _y = datetime.now().year
        _sonasid = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower() in {
            "sonasid",
            "shipping",
            "port",
        }
        _period_help = (
            f"Précise par exemple : une année ({_y} ou 2025), un mois ({_y}-01), ou une plage "
            f"« du {_y}-01-01 au {_y}-01-31 ».\n"
            f"Exemples Sonasid : nombre d'arrivages en {_y}, arrivages par mois en 2025, "
            f"tonnage total des arrivages 2025.\n"
            "(La base contient des arrivages en 2025 et en 2026.)\n"
            "Tu peux aussi choisir un preset à gauche (7j / 30j / mois / YTD / personnalisé) : "
            "la période sera ajoutée automatiquement à ta question."
            if _sonasid
            else f"Précise par exemple : une année ({_y}), un mois ({_y}-01), ou une plage "
            f"« du {_y}-01-01 au {_y}-01-31 ».\n"
            "Tu peux aussi choisir un preset à gauche (7j / 30j / mois / YTD / personnalisé) : "
            "la période sera ajoutée automatiquement à ta question."
        )
        return attach_rewrite(
            {
                "question": question,
                "source": "pipeline:need_period",
                "message": f"{NEED_PERIOD_ASSISTANT_PREFIX}.\n{_period_help}",
            }
        )

    def _is_sql_request(text: str) -> bool:
        t = (text or "").lower()
        # User intent: ask for the SQL query itself, not the computed value.
        # Covers French + common shorthand.
        return any(
            k in t
            for k in [
                "requete sql",
                "requête sql",
                "requete",
                "requête",
                "query sql",
                "sql ?",
                "sql pour",
                "donne moi le sql",
                "donne-moi le sql",
                "quelle est la requete",
                "quelle est la requête",
                "montre le sql",
                "affiche le sql",
            ]
        )

    def _is_sql_catalog_request(text: str) -> bool:
        t = (text or "").lower()
        return _is_sql_request(text) and any(
            k in t
            for k in [
                "tous les kpi",
                "toutes les kpi",
                "tous les kpis",
                "toutes les kpis",
                "liste des kpi",
                "catalogue kpi",
                "tous les indicateurs",
                "toutes les indicateurs",
            ]
        )

    # If the user asks for SQL, return the query/queries without executing them.
    if _is_sql_catalog_request(question):
        provider = (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()
        items = list_kpi_catalog()
        rows = []
        for it in items:
            name = str(it.get("name") or "").strip()
            qcat = str(it.get("question") or "").strip()
            if not name or not qcat:
                continue
            raw_cat = generate_sql(qcat)
            if isinstance(raw_cat, dict) and "eaf" in raw_cat and "lf" in raw_cat:
                try:
                    tsql_eaf = run_query_mod._sqlite_to_tsql(str(raw_cat.get("eaf") or "").strip())
                    tsql_lf = run_query_mod._sqlite_to_tsql(str(raw_cat.get("lf") or "").strip())
                    # Prefer a single runnable query that returns EAF + LF + TOTAL.
                    # If the converted queries are complex (CTE/UNION/etc.), fall back to two statements.
                    te = (tsql_eaf or "").strip().rstrip(";").strip()
                    tl = (tsql_lf or "").strip().rstrip(";").strip()

                    def _simple_scalar_select(s: str) -> bool:
                        if not s:
                            return False
                        if re.match(r"(?is)^\s*with\b", s):
                            return False
                        if not re.match(r"(?is)^\s*select\b", s):
                            return False
                        # Very conservative: treat as non-simple if it contains another statement separator.
                        if ";" in s:
                            return False
                        return True

                    if _simple_scalar_select(te) and _simple_scalar_select(tl):
                        rows.append(
                            {
                                "kpi": name,
                                "tsql": (
                                    "SELECT\n"
                                    f"  COALESCE(({te}), 0) AS conso_eaf,\n"
                                    f"  COALESCE(({tl}), 0) AS conso_lf,\n"
                                    f"  COALESCE(({te}), 0) + COALESCE(({tl}), 0) AS conso_totale;"
                                ),
                            }
                        )
                    else:
                        # Keep it copy/paste runnable in Azure Data Studio.
                        rows.append({"kpi": name, "tsql": f"{te};\n\n{tl};"})
                except Exception as e:
                    rows.append({"kpi": name, "tsql": f"-- erreur conversion T-SQL: {e}"})
            elif isinstance(raw_cat, str):
                sql_only = extract_sql(raw_cat).strip()
                if sql_only.upper() == "SELECT 1":
                    rows.append({"kpi": name, "tsql": "-- KPI non reconnu (SELECT 1)"})
                else:
                    try:
                        tsql = run_query_mod._sqlite_to_tsql(sql_only) if provider in {"azure", "mssql", "sqlserver"} else sql_only
                        rows.append({"kpi": name, "tsql": tsql})
                    except Exception as e:
                        rows.append({"kpi": name, "tsql": f"-- erreur conversion T-SQL: {e}\n\n{sql_only}"})
        # Azure-only: return T-SQL in a table-like payload.
        return attach_rewrite(
            {
                "question": question,
                "message": f"D’accord — voici les requêtes SQL Azure de tous les KPIs ({len(rows)}).",
                "result": rows,
                "source": "sql:kpi_catalog",
            }
        )

    if _is_sql_request(question):
        provider = (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()
        if isinstance(raw, dict) and "eaf" in raw and "lf" in raw:
            sqls = {"eaf": str(raw.get("eaf") or "").strip(), "lf": str(raw.get("lf") or "").strip()}
            out: Dict[str, Any] = {
                "question": question,
                "message": "Voici les requêtes SQL utilisées (EAF + LF).",
                "sqls": sqls,
                "source": "sql:rule_engine",
            }
            if provider in {"azure", "mssql", "sqlserver"}:
                try:
                    out["tsqls"] = {
                        "eaf": run_query_mod._sqlite_to_tsql(sqls["eaf"]),
                        "lf": run_query_mod._sqlite_to_tsql(sqls["lf"]),
                    }
                except Exception:
                    pass
            return attach_rewrite(
                out
            )
        if isinstance(raw, str):
            sql_only = extract_sql(raw).strip()
            if sql_only.upper() == "SELECT 1":
                return attach_rewrite(
                    {
                        "question": question,
                        "error": "NEED_REPHRASE",
                        "message": (
                            "Je ne peux pas générer une requête SQL pour cette demande (KPI non reconnu).\n"
                            "Peux-tu reformuler en précisant le KPI et la période ?\n"
                            "Exemples : production 2025, consommation électrique 2025, TD du 2025-01-01 au 2025-01-31."
                        ),
                    }
                )
            return attach_rewrite(
                {
                    "question": question,
                    "message": "Voici la requête SQL utilisée.",
                    "sql": sql_only,
                    **(
                        {"tsql": run_query_mod._sqlite_to_tsql(sql_only)}
                        if provider in {"azure", "mssql", "sqlserver"}
                        else {}
                    ),
                    "source": "sql:rule_engine",
                }
            )
        return attach_rewrite({"question": question, "error": "Réponse pipeline invalide"})

    # ========== CAS 0 : FALLBACK LLM (si règle non trouvée) ==========
    try:
        from backend.llm.sonasid_open import is_sonasid_llm_available

        _llm_ok = is_llm_enabled() or is_sonasid_llm_available()
    except Exception:
        _llm_ok = is_llm_enabled()
    if isinstance(raw, str) and extract_sql(raw).strip().upper() == "SELECT 1" and _llm_ok:
        rag_ctx = ""
        try:
            rag_ctx = build_rag_context(question=question, session_id=session_id)
        except Exception:
            rag_ctx = ""
        last_reason = ""
        last_sql = ""
        for attempt in range(2):
            extra = rag_ctx
            if attempt == 1:
                extra = (
                    rag_ctx
                    + "\n\n---\n"
                    + "Tentative précédente invalide. Corrige le SQL.\n"
                    + (f"SQL précédent:\n{last_sql}\n" if last_sql else "")
                    + (f"Erreur/raison:\n{last_reason}\n" if last_reason else "")
                )
            llm_sql, provider, llm_reason = generate_sql_with_llm(question, extra_context=extra)
            if not llm_sql:
                last_reason = llm_reason or "llm_failed"
                continue

            llm_sql_fixed = _quote_known_tables(llm_sql)
            valid, guard_reason = validate_select_sql(llm_sql_fixed)
            if not valid:
                last_reason = guard_reason
                last_sql = llm_sql_fixed
                llm_meta = {
                    "llm_status": "sql_rejected",
                    "llm_reason": guard_reason,
                    "llm_sql": llm_sql_fixed,
                    "llm_provider": provider,
                }
                continue

            llm_result = run_query(llm_sql_fixed)
            if isinstance(llm_result, str):
                last_reason = llm_result
                last_sql = llm_sql_fixed
                llm_meta = {
                    "llm_status": "execution_error",
                    "llm_reason": llm_result,
                    "llm_sql": llm_sql_fixed,
                    "llm_provider": provider,
                }
                continue

            try:
                add_memory(session_id=session_id or "default", role="user", content=question)
                add_memory(
                    session_id=session_id or "default",
                    role="assistant",
                    content=f"SQL: {llm_sql_fixed}\nRESULT: {_format_rows(question.lower(), llm_result)}",
                )
            except Exception:
                pass
            formatted = _format_rows(question.lower(), llm_result)
            llm_out: Dict[str, Any] = {
                "question": question,
                "result": formatted,
                "tsql": llm_sql_fixed,
                "source": f"llm:{provider}",
                "llm_attempts": attempt + 1,
            }
            return attach_rewrite(llm_out)

        if not llm_meta:
            llm_meta = {"llm_status": "llm_failed", "llm_reason": last_reason, "llm_provider": provider if 'provider' in locals() else None}

    # ========== CAS 1 : CONSOMMATIONS (EAF + LF ou EAF seul) ==========
    if isinstance(raw, dict):

        ql = question.lower()
        eaf_result = run_query(raw["eaf"])
        lf_result = run_query(raw["lf"])

        # If the query is a time series (par jour/semaine/mois/année), return a series instead of a scalar total.
        try:
            eaf_fmt = _format_rows(ql, eaf_result)
            lf_fmt = _format_rows(ql, lf_result)
            is_series = (
                isinstance(eaf_fmt, list)
                and len(eaf_fmt) > 0
                and isinstance(eaf_fmt[0], dict)
                and "period" in eaf_fmt[0]
                and ("value" in eaf_fmt[0] or "poids" in eaf_fmt[0])
            )
            if is_series:
                by_period = {}
                for r in eaf_fmt:
                    p = r.get("period")
                    if p is None:
                        continue
                    by_period.setdefault(p, {"period": p, "eaf": 0.0, "lf": 0.0})
                    by_period[p]["eaf"] += float(r.get("value") or 0)

                if (
                    isinstance(lf_fmt, list)
                    and len(lf_fmt) > 0
                    and isinstance(lf_fmt[0], dict)
                    and "period" in lf_fmt[0]
                ):
                    for r in lf_fmt:
                        p = r.get("period")
                        if p is None:
                            continue
                        by_period.setdefault(p, {"period": p, "eaf": 0.0, "lf": 0.0})
                        by_period[p]["lf"] += float(r.get("value") or 0)

                rows = []
                for p in sorted(by_period.keys()):
                    rec = by_period[p]
                    total = rec["eaf"] + rec["lf"]
                    rows.append({"period": p, "value": total, "eaf": rec["eaf"], "lf": rec["lf"]})

                if not rows:
                    return attach_rewrite({"question": question, "message": "Aucune donnée disponible pour ce filtre"})

                # Keep type info for UI/table; chart will use period/value.
                out = {"question": question, "result": rows, "source": "pipeline:conso_series"}
                out["type"] = raw.get("type", "conso_elec")
                return attach_rewrite(out)
        except Exception:
            pass

        eaf = get_scalar(eaf_result)
        lf = get_scalar(lf_result)

        total = eaf + lf

        if total == 0:
            return attach_rewrite(
                {
                    "question": question,
                    "message": "Aucune donnée disponible pour ce filtre",
                }
            )

        conso_type = raw.get("type", "conso_elec")
        base = {"question": question}

        if conso_type == "conso_elec":
            base["Consommation_EAF"] = _clean_num(eaf)
            base["Consommation_LF"] = _clean_num(lf)
            base["Consommation_Totale"] = _clean_num(total)
            base["Consommation_MWh"] = round(_kwh_to_mwh(float(total)), 2)
        elif conso_type == "conso_oxygene":
            base["Consommation_Oxygène"] = _clean_num(total)
        elif conso_type == "conso_carbon":
            base["Consommation_Carbon"] = _clean_num(total)
        elif conso_type == "conso_gpl":
            base["Consommation_GPL"] = _clean_num(total)
        else:
            base["Consommation_Totale"] = _clean_num(total)

        return attach_rewrite(base)

    # ========== CAS 2 : REQUÊTES SQL CLASSIQUES ==========
    sql = extract_sql(raw)
    result = run_query(sql)

    if isinstance(result, str):
        provider = (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()
        err_text = result
        out: Dict[str, Any] = {
            "question": question,
            "error": err_text,
            "source": "pipeline:db_error",
        }
        if provider in {"azure", "mssql", "sqlserver"}:
            out["tsql"] = sql
            low = err_text.lower()
            if "40615" in err_text or "not allowed to access" in low or "firewall" in low:
                m_ip = re.search(r"IP address '([\d.]+)'", err_text)
                ip_hint = m_ip.group(1) if m_ip else "votre IP publique actuelle"
                srv = os.getenv("AZURE_SQL_SERVER", "sql-son-prd.database.windows.net")
                out["error"] = "DB_FIREWALL"
                out["message"] = (
                    "**Connexion à la base de données impossible**\n\n"
                    f"Le serveur Azure SQL `{srv}` refuse la connexion depuis l’adresse **{ip_hint}** "
                    "(pare-feu non autorisé).\n\n"
                    "**Ce que cela signifie :**\n"
                    "- La requête a bien été générée (logique métier OK).\n"
                    "- Seule l’exécution sur Azure SQL est bloquée.\n\n"
                    "**Solutions :**\n"
                    "1. **POC prod** — utilise l’application déployée sur la VM "
                    "(`sonasid-alexsys.westeurope.cloudapp.azure.com:5175`) : le backend y est déjà autorisé.\n"
                    f"2. **Test local** — un admin Azure doit ajouter **{ip_hint}** dans "
                    f"Portail Azure → SQL Server `sql-son-prd` → Mise en réseau → règle pare-feu.\n"
                    "3. Attendre ~5 minutes après l’ajout, puis réessayer."
                )
        else:
            out["sql"] = sql
        return attach_rewrite(out)

    ql = question.lower()

    # If query returned a time series/table (period/value), prefer returning the rows
    # rather than treating the first cell (often a date string) as a scalar KPI.
    if (
        result
        and len(result) > 0
        and isinstance(result[0], (list, tuple))
        and len(result[0]) >= 2
        and not _is_single_aggregate_row(result, sql)
    ):
        formatted = _format_rows(ql, result)
        series_out: Dict[str, Any] = {
            "question": question,
            "result": formatted,
            "source": "sql:sonasid",
        }
        is_monthly = bool(
            any(x in ql for x in ["par mois", "mensuel", "chaque mois"])
            or re.search(r"\bperiode\b", (sql or ""), re.I)
            or re.search(r"convert\s*\(\s*char\s*\(\s*7", (sql or ""), re.I)
        )
        if is_monthly and isinstance(formatted, list) and formatted:
            if re.search(r"\bnavires?\b", ql):
                label = "Navires actifs" if re.search(r"\bactifs?\b", ql) else "Navires"
                series_out["message"] = _build_monthly_series_message(
                    question, formatted, metric_label=label
                )
            elif re.search(r"\barrivages?\b", ql):
                series_out["message"] = _build_monthly_series_message(
                    question, formatted, metric_label="Arrivages"
                )
            elif re.search(r"\btonnage\b", ql):
                series_out["message"] = _build_monthly_series_message(
                    question, formatted, metric_label="Tonnage"
                )
        elif (
            re.search(r"\bd[eéè]charg", ql, re.I)
            and re.search(r"\b(liste|détail|detail|quels|quelles)\b", ql)
            and isinstance(formatted, list)
            and formatted
            and isinstance(formatted[0], dict)
            and formatted[0].get("navire") is not None
        ):
            series_out["message"] = _build_dechargement_list_message(question, formatted)
        return attach_rewrite(series_out)

    if (
        re.search(r"\bd[eéè]charg", ql, re.I)
        and re.search(r"\b(liste|détail|detail|quels|quelles)\b", ql)
        and re.search(r"\bnavires?\b", ql)
        and isinstance(result, list)
        and not result
    ):
        return attach_rewrite(
            {
                "question": question,
                "result": [],
                "source": "sql:sonasid",
                "message": "**Aucun navire en déchargement** actuellement (port à l’arrêt ou filtres trop stricts).",
            }
        )

    if _is_single_aggregate_row(result, sql) and re.search(
        r"\bnombre_arrivages\b", (sql or ""), re.I
    ):
        row = result[0]
        try:
            n = row[0]
            ton = float(row[1]) if len(row) > 1 and row[1] is not None else None
            label = _period_label_from_question(question)
            msg = f"**{label}** : {int(n) if isinstance(n, float) and n == int(n) else n} arrivages"
            if ton is not None:
                msg += f" · {round(ton, 2)} t importées"
            msg += "."
            payload: Dict[str, Any] = {
                "question": question,
                "nombre_arrivages": n,
                "result": n,
                "message": msg,
                "source": "sql:sonasid",
            }
            if ton is not None:
                payload["tonnage_total"] = ton
            return attach_rewrite(payload)
        except (TypeError, ValueError, IndexError):
            pass

    value = get_scalar(result)

    # Friendly explanation when a COUNT KPI returns 0 for an explicit year.
    # (Otherwise the UI shows "Résultat: 0" which looks like a bug.)
    try:
        sql_up = (sql or "").upper()
        m_year = re.search(r"\b(20\d{2})\b", ql)
        if (
            (value in (0, 0.0))
            and m_year
            and ("coulée" in ql or "coulee" in ql)
            and ("COUNT(DISTINCT HEATID)" in sql_up)
            and ('FROM "02_EAF"' in sql_up)
        ):
            y = m_year.group(1)
            return attach_rewrite(
                {
                    "question": question,
                    "result": 0,
                    "message": (
                        f"Je ne trouve aucune coulée sur {y} dans les données disponibles.\n"
                        "Si tu t’attends à des données, vérifie que l’année est bien chargée dans la table EAF "
                        "(colonne `HEATDEPARTURE_ACT`) et que tu as sélectionné la bonne période."
                    ),
                    "source": "pipeline:count:empty",
                }
            )
    except Exception:
        pass

    # TD
    if "disponibilite" in ql or "disponibilité" in ql or " td " in ql or ql.strip().endswith("td"):
        return attach_rewrite({"question": question, "TD_percent": round(value * 100, 2)})

    # TR (clamp si données multi-périodes sans filtre date)
    if "temps requis" in ql or (" tr " in ql and "mtbf" not in ql and "mttr" not in ql) or (ql.strip().endswith(" tr") and "mtbf" not in ql):
        return attach_rewrite({"question": question, "TR_percent": round(max(0, min(100, value)), 2)})

    # MTBF (en secondes, clamp à 0 si négatif)
    if "mtbf" in ql:
        return attach_rewrite({"question": question, "MTBF_secondes": round(max(0, value), 2)})

    # MTTR (en secondes)
    if "mttr" in ql:
        return attach_rewrite({"question": question, "MTTR_secondes": round(max(0, value), 2)})

    # Rendement : 100 * brames / ferrailles (PAF). Un % très grand = souvent unités kg/t ou PAF sous-déclaré.
    if "rendement" in ql or "r [%]" in ql:
        # If user asked for a time series ("par mois/semaine/jour/année"), keep the table/series format
        # so the UI can draw a chart. Do NOT collapse to a scalar Rendement_percent.
        if any(x in ql for x in ["par jour", "par semaine", "par mois", "par an", "par année"]):
            return attach_rewrite({"question": question, "result": _format_rows(ql, result)})
        v = round(float(value), 2)
        max_plausible = float(os.getenv("RENDEMENT_PERCENT_MAX", "250") or "250")
        if v < 0 or v > max_plausible:
            return attach_rewrite(
                {
                    "question": question,
                    "message": (
                        f"Rendement calculé hors plage crédible ({v} %, plafond indicatif {max_plausible:g} %). "
                        "Formule : 100 × (somme poids brames) / (somme poids ferrailles PAF). "
                        "Causes fréquentes : peu de lignes PAF sur la période, ou unités différentes entre "
                        "`05_CCM_Brame.PIECE_WEIGHT_MEAS` (kg) et `01_PAF.CSD_POIDS` (tonnes dans ce jeu de données) "
                        "— variables SCRAP_UNIT et SLAB_UNIT (`kg` ou `t`, défaut t + kg)."
                    ),
                    "Rendement_percent": v,
                    "data_quality": "suspect",
                }
            )
        return attach_rewrite({"question": question, "Rendement_percent": v})

    # Libellés Sonasid (navires / arrivages / tonnage)
    if re.search(r"\bqualit", ql, re.I) and re.search(r"\bnombre_qualites\b", (sql or ""), re.I):
        n = int(value) if value == int(value) else value
        return attach_rewrite(
            {
                "question": question,
                "nombre_qualites": n,
                "result": n,
                "message": f"Nombre de qualités : {n}",
                "source": "sql:sonasid",
            }
        )
    if re.search(r"\bd[eéè]charg", ql, re.I) and re.search(
        r"\btonnage_decharge\b", (sql or ""), re.I
    ):
        v = _clean_num(value)
        return attach_rewrite(
            {
                "question": question,
                "tonnage_decharge": v,
                "result": v,
                "message": f"Tonnage déchargé : {v} t",
                "source": "sql:sonasid",
            }
        )
    if re.search(r"\bd[eéè]charg", ql, re.I) and re.search(
        r"\btonnage_restant\b", (sql or ""), re.I
    ):
        v = _clean_num(value)
        return attach_rewrite(
            {
                "question": question,
                "tonnage_restant": v,
                "result": v,
                "message": f"Tonnage restant à décharger : {v} t",
                "source": "sql:sonasid",
            }
        )
    if re.search(r"\bd[eéè]charg", ql, re.I) and re.search(
        r"\btaux_dechargement_moyen\b", (sql or ""), re.I
    ):
        v = _clean_num(value)
        return attach_rewrite(
            {
                "question": question,
                "taux_dechargement_moyen": v,
                "result": v,
                "message": f"Taux de déchargement moyen : {v} t/j",
                "source": "sql:sonasid",
            }
        )
    if re.search(r"\bd[eéè]charg", ql, re.I) and re.search(r"\bnavires?\b", ql) and (
        re.search(r"\bnombre_navires_en_dechargement\b", (sql or ""), re.I)
        or re.search(r"\bpar mois\b", ql)
    ):
        if "par mois" in ql and isinstance(result, list):
            out = {"question": question, "result": _format_rows(ql, result), "source": "sql:sonasid"}
            if re.search(r"\bpar mois\b", ql) and not re.search(r"\b20\d{2}\b", ql):
                out["notice"] = (
                    "Série mensuelle : navires ayant démarré un déchargement ce mois-là "
                    "(date de début réelle). Précisez une année (ex. en 2026) pour filtrer."
                )
            return attach_rewrite(out)
        n = int(value) if value == int(value) else value
        return attach_rewrite(
            {
                "question": question,
                "nombre_navires_en_dechargement": n,
                "result": n,
                "message": f"Navires en déchargement (actuellement) : {n}",
                "source": "sql:sonasid",
            }
        )
    if re.search(r"\bd[eéè]charg", ql, re.I) and re.search(r"\barrivages?\b", ql) and re.search(
        r"\bnombre_arrivages_en_dechargement\b", (sql or ""), re.I
    ):
        n = int(value) if value == int(value) else value
        return attach_rewrite(
            {
                "question": question,
                "nombre_arrivages_en_dechargement": n,
                "result": n,
                "message": f"Arrivages en déchargement : {n}",
                "source": "sql:sonasid",
            }
            )
    if (
        re.search(r"\bnavires?\b", ql)
        and re.search(r"\btransf", ql)
        and re.search(r"\bqualit", ql, re.I)
    ):
        year_m = re.search(r"\b(20\d{2})\b", ql)
        yr = year_m.group(1) if year_m else "la période demandée"
        nav_label = _navire_label_from_question(ql)
        if isinstance(result, list) and not result:
            return attach_rewrite(
                {
                    "question": question,
                    "result": [],
                    "source": "sql:sonasid",
                    "message": (
                        f"Aucun tonnage transféré trouvé pour **{nav_label}** en **{yr}**.\n"
                        "Vérifiez l’identifiant ou le nom du navire, ou élargissez la période."
                    ),
                }
            )
        if isinstance(result, list) and result and isinstance(result[0], (list, tuple)):
            formatted = _format_rows(ql, result)
            if isinstance(formatted, list) and formatted:
                lines = []
                nav_title = formatted[0].get("navire") or nav_label
                for row in formatted[:30]:
                    qual = row.get("qualite") or "—"
                    ton = row.get("tonnage_transfere") or row.get("value")
                    arr = row.get("arrivage_id")
                    if arr is not None:
                        lines.append(f"- **{qual}** (arrivage {arr}) — {_clean_num(ton)} t")
                    else:
                        lines.append(f"- **{qual}** — {_clean_num(ton)} t")
                return attach_rewrite(
                    {
                        "question": question,
                        "result": formatted,
                        "source": "sql:sonasid",
                        "message": (
                            f"**Tonnage transféré par qualité — {nav_title} ({yr})**\n"
                            + "\n".join(lines)
                        ),
                    }
                )
    if re.search(r"\bnavires?\b", ql) and not re.search(r"\barrivages?\b", ql):
        try:
            from backend.llm.sonasid_schema import is_schema_metadata_question, schema_metadata_reply

            if is_schema_metadata_question(question):
                rep = schema_metadata_reply(question)
                return attach_rewrite(
                    {
                        "question": question,
                        "message": rep.get("message"),
                        "source": rep.get("source", "sonasid:schema"),
                    }
                )
        except Exception:
            pass
        if re.search(r"\btransf", ql) and re.search(r"\bqualit", ql, re.I):
            pass
        elif re.search(r"\bd[eéè]charg", ql, re.I) and re.search(
            r"\b(liste|détail|detail|quels|quelles)\b", ql
        ):
            pass
        elif re.search(r"\bd[eéè]charg", ql, re.I) and not re.search(
            r"\bnombre_navires_en_dechargement\b", (sql or ""), re.I
        ):
            pass
        elif any(x in ql for x in ["par mois", "mensuel", "chaque mois"]) and isinstance(
            result, list
        ) and result and isinstance(result[0], (list, tuple)) and len(result[0]) >= 2:
            formatted = _format_rows(ql, result)
            label = "Navires actifs" if re.search(r"\bactifs?\b", ql) else "Navires"
            out: Dict[str, Any] = {
                "question": question,
                "result": formatted,
                "source": "sql:sonasid",
                "message": _build_monthly_series_message(
                    question,
                    formatted if isinstance(formatted, list) else [],
                    metric_label=label,
                ),
            }
            if re.search(r"\bactifs?\b", ql):
                out["notice"] = (
                    "Comptage mensuel : navires actifs du référentiel ayant au moins un arrivage ce mois-là."
                )
            return attach_rewrite(out)
        else:
            label = "Navires actifs" if re.search(r"\bactifs?\b", ql) else "Navires"
            n = int(value) if value == int(value) else value
            return attach_rewrite(
                {
                    "question": question,
                    "nombre_navires": n,
                    "result": n,
                    "message": f"{label} : {n}",
                    "source": "sql:sonasid",
                }
            )
    if re.search(r"\barrivages?\b", ql) and re.search(r"\bqualit", ql, re.I):
        if isinstance(result, list) and result and isinstance(result[0], (list, tuple)) and len(result[0]) >= 2:
            return attach_rewrite(
                {
                    "question": question,
                    "result": _format_rows(ql, result),
                    "source": "sql:sonasid",
                    "notice": "Répartition des arrivages par qualité (via commandes liées).",
                }
            )
    if (
        re.search(r"\bfournisseurs?\b", ql)
        and isinstance(result, list)
        and len(result) > 1
        and result
        and isinstance(result[0], (list, tuple))
        and len(result[0]) >= 3
    ):
        formatted = _format_rows(ql, result)
        if isinstance(formatted, list) and formatted and isinstance(formatted[0], dict):
            if _user_requests_table_format(ql):
                period = ""
                m_y = re.search(r"\b(20\d{2})\b", ql)
                if m_y:
                    period = f" ({m_y.group(1)})"
                return attach_rewrite(
                    {
                        "question": question,
                        "result": formatted,
                        "source": "sql:sonasid",
                        "message": f"**Fournisseurs — arrivages{period}**",
                    }
                )
            lines = []
            for i, row in enumerate(formatted[:10], 1):
                nom = row.get("fournisseur") or "—"
                n = row.get("nombre_arrivages") or row.get("value")
                ton = row.get("tonnage_total")
                if ton is not None:
                    lines.append(f"{i}. **{nom}** — {_clean_num(n)} arrivages · {_clean_num(ton)} t")
                else:
                    lines.append(f"{i}. **{nom}** — {_clean_num(n)} arrivages")
            return attach_rewrite(
                {
                    "question": question,
                    "result": formatted,
                    "source": "sql:sonasid",
                    "message": "**Top fournisseurs par arrivages**\n" + "\n".join(lines),
                }
            )
    if (
        re.search(r"\bnavires?\b", ql)
        and re.search(r"\btransf", ql)
        and isinstance(result, list)
        and len(result) > 1
        and result
        and isinstance(result[0], (list, tuple))
        and len(result[0]) >= 3
    ):
        formatted = _format_rows(ql, result)
        if isinstance(formatted, list) and formatted and isinstance(formatted[0], dict):
            lines = []
            for i, row in enumerate(formatted[:10], 1):
                nom = row.get("navire") or "—"
                ton = row.get("tonnage_transfere") or row.get("value")
                lines.append(f"{i}. **{nom}** — {_clean_num(ton)} t transférées")
            return attach_rewrite(
                {
                    "question": question,
                    "result": formatted,
                    "source": "sql:sonasid",
                    "message": "**Top navires par tonnage transféré**\n" + "\n".join(lines),
                }
            )
    if re.search(r"\barrivages?\b", ql) and (
        re.search(r"\b(nombre|combien|count)\b", ql)
        or re.search(r"\bnombre_arrivages\b", (sql or ""), re.I)
    ):
        if re.search(r"\bqualit", ql, re.I):
            pass
        elif re.search(r"\bfournisseurs?\b", ql) and re.search(
            r"\b(quels?|top|plus|classement|ranking|principal)\b", ql
        ):
            pass
        elif any(x in ql for x in ["par mois", "mensuel", "chaque mois"]) and isinstance(
            result, list
        ) and result:
            formatted = _format_rows(ql, result)
            out: Dict[str, Any] = {
                "question": question,
                "result": formatted,
                "source": "sql:sonasid",
                "message": _build_monthly_series_message(
                    question,
                    formatted if isinstance(formatted, list) else [],
                    metric_label="Arrivages",
                ),
            }
            try:
                from backend.llm.sonasid_sql import _is_sonasid_trend_question, sonasid_trend_verdict

                if _is_sonasid_trend_question(q_in) and isinstance(formatted, list):
                    verdict = sonasid_trend_verdict(q_in, formatted)
                    if verdict:
                        out["message"] = verdict + "\n\n" + str(out.get("message") or "")
            except Exception:
                pass
            return attach_rewrite(out)
        elif "par mois" not in ql and "par semaine" not in ql and "par jour" not in ql and "tonnage" not in ql:
            n = int(value) if value == int(value) else value
            msg = f"Nombre d'arrivages : {n}"
            if (
                isinstance(result, list)
                and result
                and isinstance(result[0], (list, tuple))
                and len(result[0]) >= 2
                and re.search(r"\btonnage_total\b", (sql or ""), re.I)
            ):
                try:
                    ton = float(result[0][1] or 0)
                    from backend.llm.llm_sql import _extract_year_month_range

                    _, month, _, _ = _extract_year_month_range(question)
                    label = month or "Période demandée"
                    msg = f"**{label}** : {n} arrivages · {round(ton, 2)} t importées."
                except (TypeError, ValueError, IndexError):
                    pass
            return attach_rewrite(
                {
                    "question": question,
                    "nombre_arrivages": n,
                    "result": n,
                    "message": msg,
                    "source": "sql:sonasid",
                }
            )
    if (
        re.search(r"\btonnage\b", ql) or re.search(r"\b(marchandise|valeur)\b", ql, re.I)
    ) and "par mois" not in ql and "par semaine" not in ql and "par jour" not in ql:
        try:
            from backend.llm.sonasid_brief import _is_vague_port_overview, execute_sonasid_brief

            if _is_vague_port_overview(ql):
                return attach_rewrite(execute_sonasid_brief(q_in, "dashboard"))
        except Exception:
            pass
        is_import = bool(
            re.search(r"\bimport", ql, re.I)
            or re.search(r"\bmarchandise", ql, re.I)
            or re.search(r"\b(valeur|valeurs)\b.*\bimport", ql, re.I)
        )
        sql_has_import = bool(re.search(r"\btonnage_importe\b", (sql or ""), re.I))
        key = "tonnage_importe" if (is_import or sql_has_import) else "tonnage_total"
        v = _clean_num(value)
        if key == "tonnage_importe" and re.search(r"\b(marchandise|valeur)\b", ql, re.I):
            label = "Valeur importée (tonnage)"
        else:
            label = "Tonnage importé" if key == "tonnage_importe" else "Tonnage total"
        return attach_rewrite(
            {
                "question": question,
                key: v,
                "result": v,
                "message": f"{label} : {v}",
                "source": "sql:sonasid",
            }
        )

    out = {"question": question, "result": _format_rows(ql, result)}
    sql_norm = extract_sql(raw).strip().upper() if isinstance(raw, str) else ""

    # If the rule-engine fell back to "SELECT 1", the UI should not show a misleading "Résultat: 1".
    # Instead, ask the user to reformulate with an explicit KPI / period / filters.
    if value == 1 and sql_norm == "SELECT 1":
        _prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
        if _prof in {"sonasid", "shipping", "port"}:
            try:
                from backend.llm.sonasid_brief import _is_vague_port_overview, execute_sonasid_brief

                if _is_vague_port_overview(ql):
                    return attach_rewrite(execute_sonasid_brief(q_in, "dashboard"))
            except Exception:
                pass
            msg = (
                "Je peux t’aider sur le port et les arrivages — précise un peu ta demande "
                "(période, indicateur ou « récap / analyse »).\n"
                "Exemples :\n"
                "- un petit récap sur 2025\n"
                "- situation au port cette année\n"
                "- quels fournisseurs ont le plus d'arrivages en 2025\n"
                "- valeur des marchandises importées en 2025\n"
                "- analyse arrivages 2025 tous les axes"
            )
        else:
            msg = (
                "Je n’ai pas compris quel KPI calculer. "
                "Peux-tu reformuler en précisant le KPI et la période ?\n"
                "Exemples :\n"
                "- production 2025\n"
                "- consommation électrique 2025\n"
                "- TD du 2025-01-01 au 2025-01-31\n"
                "- nombre de coulées par jour en 2025-01"
            )
        out = {"question": question, "error": "NEED_REPHRASE", "message": msg}
        if llm_meta and os.getenv("LLM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}:
            out.update(llm_meta)
        return attach_rewrite(out)

    if llm_meta and os.getenv("LLM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}:
        out.update(llm_meta)
    elif llm_meta and value == 1 and sql_norm == "SELECT 1":
        out["hint"] = (
            "Le LLM n'a pas pu produire/exécuter de SQL valide. "
            "Vérifie Ollama (Llama) et le Python du venv : ./venv/bin/python3"
        )
        out.update(llm_meta)
    elif (
        not llm_meta
        and value == 1
        and sql_norm == "SELECT 1"
    ):
        # Aucune règle KPI : le LLM ne s'active que si le processus voit USE_LLM=true
        out["hint_llm"] = (
            f"Fallback SELECT 1 : LLM non appelé (is_llm_enabled={is_llm_enabled()}, "
            f"USE_LLM={os.getenv('USE_LLM', '')!r}). "
            "Même ligne : USE_LLM=true LLM_PROVIDER=llama ./venv/bin/python3 -c \"...\""
        )
    return attach_rewrite(out)
