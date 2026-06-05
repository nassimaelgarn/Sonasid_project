"""
Analyse KPI sans LLM : synthèse statistique à partir du JSON envoyé par le bouton « Analyser ».
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start : i + 1]
                try:
                    return json.loads(chunk)
                except json.JSONDecodeError:
                    return None
    return None


def extract_kpi_payload_from_analyse_body(body: str) -> Optional[Dict[str, Any]]:
    """Le corps après « [Analyse KPI] » contient une ligne « Données JSON : » puis un objet JSON."""
    b = body or ""
    m = re.search(r"Données\s+JSON\s*:\s*", b, re.IGNORECASE)
    if not m:
        return _extract_json_object(b)
    return _extract_json_object(b[m.end() :])


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        n = int(round(v))
        return f"{n:,}".replace(",", " ")
    return f"{v:.2f}".replace(".", ",")


def _period_value_rows(data: Dict[str, Any]) -> List[Tuple[str, float]]:
    rows = data.get("result")
    if not isinstance(rows, list):
        return []
    out: List[Tuple[str, float]] = []
    for r in rows:
        if not isinstance(r, dict) or "_note" in r:
            continue
        p = r.get("period")
        if p is None:
            continue
        v = r.get("value")
        if v is None:
            v = r.get("poids")
        try:
            out.append((str(p), float(v)))
        except (TypeError, ValueError):
            continue
    return out


def extract_numeric_signals(data: Dict[str, Any]) -> List[float]:
    """
    Extract numeric values we consider "ground truth" for analysis grounding checks.
    Includes series values (period/value) and common scalar KPI keys.
    """
    if not isinstance(data, dict):
        return []
    out: List[float] = []
    pv = _period_value_rows(data)
    out.extend([v for _, v in pv])
    for k in (
        "TD_percent",
        "TR_percent",
        "Rendement_percent",
        "MTBF_secondes",
        "MTTR_secondes",
        "Consommation_Totale",
        "Consommation_MWh",
        "Consommation_EAF",
        "Consommation_LF",
        "Consommation_Oxygène",
        "Consommation_Carbon",
        "Consommation_GPL",
        "nombre_arrivages",
        "nombre_navires",
        "delta",
        "delta_percent",
    ):
        v = data.get(k)
        if isinstance(v, (int, float)):
            out.append(float(v))
    r = data.get("result")
    if isinstance(r, (int, float)):
        out.append(float(r))
    if isinstance(r, list):
        for row in r:
            if not isinstance(row, dict):
                continue
            for k, v in row.items():
                if k in {"_note", "qualite"}:
                    continue
                if isinstance(v, (int, float)):
                    out.append(float(v))
    # De-duplicate and keep finite only
    clean: List[float] = []
    for v in out:
        try:
            if v != v:  # NaN
                continue
            if abs(v) == float("inf"):
                continue
        except Exception:
            continue
        clean.append(v)
    return clean


def has_interpretable_data(data: Dict[str, Any]) -> bool:
    """
    True if we have enough structured data to justify an analysis.
    """
    if not isinstance(data, dict):
        return False
    if _period_value_rows(data):
        return True
    return bool(extract_numeric_signals(data))


def is_analysis_text_grounded(text: str, data: Dict[str, Any]) -> bool:
    """
    Minimal grounding check:
    - if we have numbers in data, the analysis must contain at least one digit.
    This avoids purely generic / hallucinated answers.
    """
    if not isinstance(data, dict):
        return False
    if not has_interpretable_data(data):
        return False
    t = (text or "").strip()
    if not t:
        return False
    return bool(re.search(r"\d", t))


def deterministic_kpi_analyse_from_dict(data: Dict[str, Any]) -> str:
    if not isinstance(data, dict):
        return ""
    try:
        import json

        return deterministic_kpi_analyse_text(json.dumps(data, ensure_ascii=False))
    except Exception:
        return ""


def _sonasid_dashboard_summary(data: Dict[str, Any]) -> Optional[str]:
    rows = data.get("result")
    if not isinstance(rows, list):
        return None
    summary = [
        r
        for r in rows
        if isinstance(r, dict)
        and "annee" in r
        and "arrivages" in r
        and "qualite" not in r
        and "mois" not in r
    ]
    if not summary:
        return None
    lines: List[str] = []
    qref = data.get("question")
    if isinstance(qref, str) and qref.strip():
        lines.append(f"**Contexte :** {qref.strip()}")
    for row in summary:
        year = row.get("annee")
        lines.append(f"**Année {year}**")
        labels = [
            ("navires_actifs", "Navires actifs"),
            ("arrivages", "Arrivages"),
            ("navires_distincts", "Navires distincts accostés"),
            ("tonnage_importe", "Tonnage importé"),
            ("tonnage_transfere", "Tonnage transféré"),
        ]
        for key, label in labels:
            v = row.get(key)
            if isinstance(v, (int, float)):
                suffix = " t" if "tonnage" in key else ""
                lines.append(f"- **{label} :** {_fmt_num(float(v))}{suffix}")
        qual_rows = [
            r
            for r in rows
            if isinstance(r, dict)
            and r.get("annee") == year
            and isinstance(r.get("qualite"), str)
        ]
        if qual_rows:
            top = sorted(
                qual_rows,
                key=lambda x: float(x.get("tonnage_commande") or x.get("arrivages") or 0),
                reverse=True,
            )[:3]
            parts = []
            for q in top:
                lib = q.get("qualite") or "—"
                n = q.get("arrivages")
                t = q.get("tonnage_commande")
                chunk = lib
                if isinstance(n, (int, float)):
                    chunk += f" ({_fmt_num(float(n))} arr."
                    if isinstance(t, (int, float)):
                        chunk += f", {_fmt_num(float(t))} t"
                    chunk += ")"
                parts.append(chunk)
            if parts:
                lines.append(f"- **Qualités dominantes :** {', '.join(parts)}.")
        mois_rows = [
            r
            for r in rows
            if isinstance(r, dict) and r.get("annee") == year and isinstance(r.get("mois"), str)
        ]
        if mois_rows:
            vals = [float(r.get("arrivages") or 0) for r in mois_rows]
            if vals:
                lines.append(
                    f"- **Activité mensuelle :** entre {_fmt_num(min(vals))} et {_fmt_num(max(vals))} "
                    f"arrivages/mois ({len(mois_rows)} mois couverts)."
                )
    lines.append(
        "- **Lecture :** les volumes et la répartition par qualité permettent d’identifier les "
        "périodes et produits les plus actifs sur le port."
    )
    return "**Analyse**\n" + "\n".join(lines)


def deterministic_kpi_analyse_text(body: str) -> str:
    """
    Retourne un texte non vide en français si le JSON est exploitable, sinon ''.
    """
    data = extract_kpi_payload_from_analyse_body(body)
    if not isinstance(data, dict):
        return ""
    if not has_interpretable_data(data):
        return ""

    brief = _sonasid_dashboard_summary(data)
    if brief:
        return brief

    lines: List[str] = []

    qref = data.get("question")
    if isinstance(qref, str) and qref.strip():
        lines.append(f"**Contexte :** {qref.strip()}")

    pv = _period_value_rows(data)
    if len(pv) >= 1:
        vals = [x[1] for x in pv]
        lines.append(f"- **Nombre de périodes :** {len(pv)}")
        lines.append(f"- **Valeur min / max :** {_fmt_num(min(vals))} / {_fmt_num(max(vals))}")
        lines.append(f"- **Somme sur la série affichée :** {_fmt_num(sum(vals))}")
        if len(pv) >= 2:
            p0, v0 = pv[0]
            p1, v1 = pv[-1]
            delta = v1 - v0
            lines.append(f"- **De {p0} à {p1} :** variation {_fmt_num(delta)} ({_fmt_num(v0)} → {_fmt_num(v1)})")
            if v0 not in (0, 0.0):
                pct = (v1 - v0) / v0 * 100.0
                lines.append(f"- **Variation relative (premier → dernier point) :** {pct:+.1f} %")
        total = data.get("_rows_total")
        if isinstance(total, int) and total > len(pv):
            lines.append(f"- **Série tronquée dans l’échange :** {len(pv)} points affichés sur {total} au total.")
        rows = data.get("result")
        if isinstance(rows, list) and rows:
            usable = [r for r in rows if isinstance(r, dict) and "_note" not in r and "eaf" in r and "lf" in r]
            if usable:
                try:
                    ea = sum(float(r.get("eaf") or 0) for r in usable)
                    la = sum(float(r.get("lf") or 0) for r in usable)
                    tot = ea + la
                    if tot > 0:
                        lines.append(
                            f"- **Répartition EAF / LF (somme des mois affichés) :** "
                            f"EAF ≈ {ea / tot * 100:.1f} %, LF ≈ {la / tot * 100:.1f} %."
                        )
                except (TypeError, ValueError):
                    pass
        text = "\n".join(lines)
        return f"**Synthèse (automatique)**\n{text}"

    # Scalaires courants
    scalar_labels = [
        ("TD_percent", "Taux de disponibilité (TD)"),
        ("TR_percent", "Temps requis (TR)"),
        ("Rendement_percent", "Rendement"),
        ("MTBF_secondes", "MTBF (secondes)"),
        ("MTTR_secondes", "MTTR (secondes)"),
        ("Consommation_Totale", "Consommation totale"),
        ("Consommation_MWh", "Consommation (MWh)"),
        ("tonnage_importe", "Tonnage importé"),
        ("tonnage_total", "Tonnage total"),
        ("nombre_arrivages", "Nombre d'arrivages"),
        ("nombre_navires", "Navires"),
    ]
    found = False
    frag: List[str] = []
    for key, label in scalar_labels:
        v = data.get(key)
        if isinstance(v, (int, float)):
            frag.append(f"- **{label} :** {_fmt_num(float(v))}{'%' if 'percent' in key else ''}")
            found = True
    r = data.get("result")
    if isinstance(r, (int, float)) and not found:
        frag.append(f"- **Résultat :** {_fmt_num(float(r))}")
        found = True
    if found:
        head = "**Synthèse (automatique)**\n"
        tail = "\n".join(frag)
        tail += (
            "\n- **Note :** ce bloc ne contient que des totaux agrégés (pas de détail par période). "
            "Pour une lecture mois par mois, demande explicitement « par mois » ou regarde la courbe si elle est affichée."
        )
        return head + tail

    if isinstance(data.get("result"), list) and data["result"]:
        n = len(data["result"])
        lines.append(f"- **Enregistrements :** {n} ligne(s) (structure non standard pour un résumé auto).")
        return "**Synthèse (automatique)**\n" + "\n".join(lines)

    return ""


def compact_kpi_raw_for_analysis(raw: Any) -> str:
    """
    Compact JSON payload for KPI interpretation (aligned with ChatWorkspace.jsx compactKpiRawForAnalysis).
    """
    if not isinstance(raw, dict):
        return "{}"
    out: Dict[str, Any] = {}
    for k in ("question", "source", "metric", "type"):
        if k in raw:
            out[k] = raw[k]
    pa = raw.get("period_a")
    if isinstance(pa, dict):
        out["period_a"] = {"range": pa.get("range"), "value": pa.get("value")}
    pb = raw.get("period_b")
    if isinstance(pb, dict):
        out["period_b"] = {"range": pb.get("range"), "value": pb.get("value")}
    if isinstance(raw.get("delta"), (int, float)):
        out["delta"] = raw.get("delta")
    if isinstance(raw.get("delta_percent"), (int, float)):
        out["delta_percent"] = raw.get("delta_percent")
    rows = raw.get("result")
    if isinstance(rows, list):
        max_rows = 28
        if len(rows) <= max_rows:
            out["result"] = rows
        else:
            out["result"] = [
                *rows[:14],
                {"_note": f"… {len(rows) - 28} lignes omises …"},
                *rows[-14:],
            ]
            out["_rows_total"] = len(rows)
    elif raw.get("result") is not None:
        out["result"] = raw.get("result")
    for k in (
        "TD_percent",
        "TR_percent",
        "Rendement_percent",
        "MTBF_secondes",
        "MTTR_secondes",
        "Consommation_Totale",
        "Consommation_MWh",
        "Consommation_EAF",
        "Consommation_LF",
        "Consommation_Oxygène",
        "Consommation_Carbon",
        "Consommation_GPL",
    ):
        if isinstance(raw.get(k), (int, float)):
            out[k] = raw[k]
    try:
        s = json.dumps(out, ensure_ascii=False)
    except Exception:
        return "{}"
    max_len = 10000
    if len(s) > max_len:
        s = f"{s[: max_len - 24]}…[tronqué]"
    return s


def build_kpi_analyse_body(*, canonical_question: str, raw: Dict[str, Any]) -> str:
    """Same shape as frontend buildAnalyzeKpiQuery (without sending a new KPI request)."""
    from backend.llm.llm_sql import KPI_ANALYSE_MARKER

    payload = compact_kpi_raw_for_analysis(raw)
    if not payload or payload == "{}":
        return ""
    ref = (canonical_question or "").strip()
    lines = [
        KPI_ANALYSE_MARKER,
        f"Référence (ne pas relancer de requête SQL) : {ref}" if ref else "",
        "Données JSON :",
        payload,
        "",
        "Tâche : analyse courte en français (tendances, évolution temporelle si série, valeurs marquantes, limites éventuelles des données).",
    ]
    return "\n".join([x for x in lines if x])
