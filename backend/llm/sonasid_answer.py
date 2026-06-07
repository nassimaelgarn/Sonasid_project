"""
Réponses utilisateur Sonasid : langage naturel, SQL interne uniquement.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional


def _is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def user_requested_sql(question: str) -> bool:
    ql = (question or "").lower()
    return bool(
        re.search(r"\b(requête|requete|query)\s*(sql)?\b", ql)
        or re.search(r"\bsql\b", ql)
        or re.search(r"\b(montre|affiche|donne|donne-moi)\b.{0,30}\b(sql|requête|requete)\b", ql)
        or re.search(r"\bquelle est la requête\b", ql)
    )


def friendly_db_error(err: str) -> str:
    """Message utilisateur sans dump ODBC ni SQL."""
    text = str(err or "").strip()
    if not text:
        return "Impossible d'accéder aux données pour le moment."
    if "--- SQL ---" in text:
        text = text.split("--- SQL ---", 1)[0].strip()
    low = text.lower()
    if "40615" in text or "not allowed" in low or "firewall" in low:
        m_ip = re.search(r"IP address '([\d.]+)'", text)
        ip = m_ip.group(1) if m_ip else "votre réseau"
        return (
            f"**Connexion à la base impossible** (pare-feu Azure SQL).\n\n"
            f"L'accès depuis **{ip}** n'est pas autorisé.\n\n"
            "→ Testez sur **sonasid-alexsys.westeurope.cloudapp.azure.com:5175** (VM prod),\n"
            "→ ou demandez à un admin d'ajouter cette IP dans le pare-feu du serveur `sql-son-prd`."
        )
    if len(text) > 280:
        return "Impossible d'exécuter la requête sur Azure SQL. Vérifiez la connexion prod ou le pare-feu."
    return text


def _fmt_num(v: Any) -> str:
    try:
        if isinstance(v, bool):
            return str(v)
        if isinstance(v, int):
            return f"{v:,}".replace(",", " ")
        if isinstance(v, float):
            x = v
        elif hasattr(v, "__float__"):
            x = float(v)
        else:
            return str(v)
        if abs(x - round(x)) < 1e-6:
            return f"{int(round(x)):,}".replace(",", " ")
        return f"{x:,.2f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def build_natural_message(question: str, result: Any, *, ql: str = "") -> str:
    """Synthèse lisible à partir des lignes déjà formatées (sans SQL)."""
    ql = ql or (question or "").lower()

    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            if "fournisseur" in first or "fournisseur_id" in first:
                lines = ["**Top fournisseurs (arrivages)**", ""]
                for i, row in enumerate(result[:15], 1):
                    nom = row.get("fournisseur") or "—"
                    n = row.get("nombre_arrivages")
                    t = row.get("tonnage_total")
                    chunk = f"{i}. **{nom}**"
                    parts = []
                    if isinstance(n, (int, float)):
                        parts.append(f"{_fmt_num(n)} arrivages")
                    if isinstance(t, (int, float)):
                        parts.append(f"{_fmt_num(t)} t")
                    if parts:
                        chunk += " — " + ", ".join(parts)
                    lines.append(chunk)
                if re.search(r"\b20\d{2}\b", ql):
                    y = re.search(r"\b(20\d{2})\b", ql).group(1)
                    lines.insert(1, f"Période : **{y}**.")
                return "\n".join(lines)

            if "period" in first or "periode" in first or "mois" in first:
                key = "period" if "period" in first else ("mois" if "mois" in first else "periode")
                vals = []
                lines = ["**Évolution dans le temps**", ""]
                for row in result[:24]:
                    p = row.get(key) or row.get("period")
                    v = row.get("value")
                    if v is None:
                        for k in ("nombre_arrivages", "tonnage_importe", "tonnage_total", "tonnage_decharge"):
                            if isinstance(row.get(k), (int, float)):
                                v = row[k]
                                break
                    if p is not None and isinstance(v, (int, float)):
                        vals.append(float(v))
                        lines.append(f"- **{p}** : {_fmt_num(v)}")
                if vals:
                    lines.append("")
                    lines.append(
                        f"Sur la période affichée : minimum **{_fmt_num(min(vals))}**, "
                        f"maximum **{_fmt_num(max(vals))}**, total **{_fmt_num(sum(vals))}**."
                    )
                return "\n".join(lines)

            if "qualite" in first:
                lines = ["**Répartition par qualité**", ""]
                for row in result[:15]:
                    lib = row.get("qualite") or "—"
                    v = row.get("value") or row.get("tonnage") or row.get("tonnage_importe")
                    n = row.get("nombre_arrivages")
                    if isinstance(v, (int, float)):
                        extra = f", {_fmt_num(n)} arrivages" if isinstance(n, (int, float)) else ""
                        lines.append(f"- **{lib}** : {_fmt_num(v)}{extra}")
                    elif isinstance(n, (int, float)):
                        lines.append(f"- **{lib}** : {_fmt_num(n)} arrivages")
                return "\n".join(lines)

            if len(result) <= 8:
                lines = ["**Résultat**", ""]
                for row in result:
                    parts = []
                    for k, v in row.items():
                        if k in {"value", "_note"} or v is None:
                            continue
                        label = str(k).replace("_", " ").capitalize()
                        if isinstance(v, (int, float)):
                            parts.append(f"{label} : {_fmt_num(v)}")
                        else:
                            parts.append(f"{label} : {v}")
                    if parts:
                        lines.append("- " + " · ".join(parts))
                return "\n".join(lines)

            if re.search(r"\bd[eéè]charg", ql) and isinstance(first, dict) and first.get("navire"):
                lines = ["**Navires en déchargement**", ""]
                for row in result[:15]:
                    nom = row.get("navire") or "—"
                    ton = row.get("tonnage_arrivage")
                    rest = row.get("quantite_restante")
                    chunk = f"- **{nom}**"
                    if row.get("arrivage_id") is not None:
                        chunk += f" (arrivage {row.get('arrivage_id')})"
                    extras = []
                    if isinstance(ton, (int, float)):
                        extras.append(f"{_fmt_num(ton)} t à bord")
                    if isinstance(rest, (int, float)):
                        extras.append(f"{_fmt_num(rest)} t restantes")
                    if extras:
                        chunk += " — " + ", ".join(extras)
                    lines.append(chunk)
                if len(result) > 15:
                    lines.append(f"\n… et {len(result) - 15} autres lignes.")
                return "\n".join(lines)

    if isinstance(result, (int, float)):
        label = "Résultat"
        if re.search(r"\barrivages?\b", ql):
            label = "Nombre d'arrivages"
        elif re.search(r"\btonnage\b", ql):
            label = "Tonnage"
        elif re.search(r"\bnavires?\b", ql):
            if re.search(r"\btransf", ql) and re.search(r"\bqualit", ql):
                return ""
            label = "Navires"
        return f"**{label}** : {_fmt_num(float(result))}"

    return ""


def _compact_result_for_narration(result: Any, *, max_rows: int = 20) -> Any:
    if isinstance(result, list):
        rows = [r for r in result if isinstance(r, dict)][:max_rows]
        if rows:
            return rows
        return result[:max_rows]
    if isinstance(result, (int, float)):
        return result
    return result


def narrate_sql_result(
    question: str,
    result: Any,
    *,
    model_name: str = "",
) -> str:
    """
    Réponse naturelle à partir des données SQL (Flash / OpenRouter).
    Ne s'active que si SONASID_LLM_NARRATE=true et LLM disponible.
    """
    try:
        from backend.llm.sonasid_open import is_sonasid_llm_narrate

        if not is_sonasid_llm_narrate():
            return ""
    except Exception:
        return ""

    compact = _compact_result_for_narration(result)
    if compact is None or compact == [] or compact == "":
        return ""

    fallback = build_natural_message(question, result, ql=(question or "").lower())
    payload = json.dumps(compact, ensure_ascii=False, default=str)
    if len(payload) > 5000:
        payload = payload[:5000] + "…"

    from backend.llm.sonasid_prompts import sonasid_analyst_domain

    sys = (
        sonasid_analyst_domain()
        + "Réponds en français avec intelligence et clarté (3 à 6 phrases ou puces courtes).\n"
        + "Interprète la question : tendance, comparaison, point clé, alerte, lecture métier (sans jargon SQL).\n"
        + "Ne montre jamais de SQL, de formule technique, ni de mention « synthèse automatique ».\n"
    )
    prompt = (
        f"{sys}\n\nQuestion utilisateur :\n{question.strip()}\n\n"
        f"Données (résultat requête) :\n{payload}\n"
    )

    text = ""
    try:
        from backend.agent.llm import invoke_chat_text

        models: List[str] = []
        for mn in (
            (model_name or "").strip(),
            (os.getenv("SONASID_NARRATE_MODEL", "") or "").strip(),
            (os.getenv("OPENROUTER_CHAT_FALLBACK", "") or "").strip(),
            "flash",
        ):
            if mn and mn not in models:
                models.append(mn)
        for mn in models:
            try:
                text = (
                    invoke_chat_text(
                        prompt=prompt,
                        model_name=mn,
                        temperature=float(os.getenv("SONASID_NARRATE_TEMPERATURE", "0.4")),
                    )
                    or ""
                ).strip()
            except Exception:
                text = ""
            if text:
                break
    except Exception:
        text = ""

    if not text:
        return fallback or ""
    if fallback and not re.search(r"\d", text):
        return f"{text}\n\n{fallback}"
    return text


def user_requested_formula(question: str) -> bool:
    ql = (question or "").lower()
    return bool(
        re.search(r"\b(formule|formules|logic|logique)\b", ql)
        or re.search(r"\b(comment|commment)\s+(calcul|est calcul)", ql)
        or re.search(r"\b(montre|affiche|donne).{0,24}\b(formule|logic|logique)\b", ql)
        or re.search(r"\bformule\s+(utilis|officiel|metier|métier)\b", ql)
    )


def _strip_formula_block(text: str) -> str:
    return re.sub(
        r"(?:\n|^)\*\*Formule / logique :\*\*[^\n]*",
        "",
        str(text or ""),
        flags=re.IGNORECASE,
    ).strip()


def llm_enrich_brief_message(
    out: Dict[str, Any],
    *,
    question: str,
    model_name: str = "",
) -> Dict[str, Any]:
    """Reformule un brief multi-KPI via le modèle sélectionné (sans inventer de chiffres)."""
    if not str(out.get("source") or "").startswith("sonasid:brief"):
        return out
    try:
        from backend.llm.sonasid_open import is_sonasid_llm_narrate

        if not is_sonasid_llm_narrate():
            return out
    except Exception:
        return out

    base = str(out.get("message") or "").strip()
    if not base:
        return out

    dash = out.get("dashboard") if isinstance(out.get("dashboard"), dict) else {}
    facts = base
    if dash:
        import json

        extra: List[str] = []
        kpis = dash.get("kpis")
        if isinstance(kpis, list) and kpis:
            extra.append("Cartes KPI (JSON) :\n" + json.dumps(kpis, ensure_ascii=False, default=str))
        charts = dash.get("charts")
        if isinstance(charts, list):
            for ch in charts[:5]:
                if not isinstance(ch, dict):
                    continue
                title = ch.get("title")
                series = ch.get("result")
                if title and isinstance(series, list) and series:
                    extra.append(
                        f"{title} :\n"
                        + json.dumps(series[:14], ensure_ascii=False, default=str)
                    )
        if extra:
            facts = base + "\n\n" + "\n\n".join(extra)

    from backend.llm.sonasid_prompts import sonasid_analyst_domain

    analysis_mode = bool(out.get("dashboard_analysis_requested"))
    sys = sonasid_analyst_domain()
    if analysis_mode:
        sys += (
            "Tu rédiges une **analyse du dashboard** port & arrivages à partir des chiffres ci-dessous.\n"
            "Structure : 4 à 8 phrases ou puces — activité portuaire, volumes (import / transfert / déchargement), "
            "saisonnalité mensuelle si des séries sont fournies, points d'attention logistiques.\n"
        )
    else:
        sys += (
            "À partir des chiffres FACTUELS ci-dessous, rédige une courte **lecture métier** en français "
            "(3 à 6 phrases ou puces) : tendances, comparaisons, points d'attention.\n"
        )
    sys += "Ne recopie pas tout le tableau. N'invente aucun chiffre absent des données.\n"
    prompt = f"{sys}\n\nQuestion utilisateur :\n{question.strip()}\n\nDonnées factuelles :\n{facts}\n"

    text = ""
    try:
        from backend.agent.llm import invoke_chat_text

        models: List[str] = []
        for mn in (
            (model_name or "").strip(),
            (os.getenv("SONASID_NARRATE_MODEL", "") or "").strip(),
            (os.getenv("SONASID_DEFAULT_CHAT_MODEL", "") or "").strip(),
            "kimi",
            "flash",
        ):
            if mn and mn not in models:
                models.append(mn)
        for mn in models:
            try:
                text = (
                    invoke_chat_text(
                        prompt=prompt,
                        model_name=mn,
                        temperature=float(os.getenv("SONASID_NARRATE_TEMPERATURE", "0.45")),
                    )
                    or ""
                ).strip()
            except Exception:
                text = ""
            if text:
                break
    except Exception:
        text = ""

    if not text:
        return out
    enriched = dict(out)
    enriched["message"] = f"{base}\n\n---\n\n**Lecture métier**\n\n{text}"
    enriched["brief_llm_enriched"] = True
    return enriched


def finalize_user_response(
    out: Dict[str, Any],
    question: str,
    *,
    model_name: str = "",
) -> Dict[str, Any]:
    """
    - Masque le SQL sauf demande explicite.
    - Ajoute un message en langage naturel si absent.
    """
    if not _is_sonasid_profile() or not isinstance(out, dict):
        return out
    if out.get("error") and out.get("message"):
        out = dict(out)
        out.pop("formula", None)
        out.pop("tsql", None)
        out.pop("sql", None)
        return out

    if str(out.get("source") or "").startswith("sonasid:brief"):
        skip_enrich = (
            out.get("brief_kind") == "dashboard" and not out.get("dashboard_analysis_requested")
        )
        if not skip_enrich:
            out = llm_enrich_brief_message(out, question=question, model_name=model_name)
        if out.get("dashboard_analysis_requested") and "**Lecture métier**" not in str(
            out.get("message") or ""
        ):
            try:
                from backend.llm.sonasid_brief import _deterministic_dashboard_analysis

                det = _deterministic_dashboard_analysis(out)
                if det:
                    base = str(out.get("message") or "").strip()
                    out = dict(out)
                    out["message"] = f"{base}\n\n---\n\n{det}".strip()
                    out["dashboard_analysis_deterministic"] = True
            except Exception:
                pass
        out = dict(out)
        out.pop("formula", None)
        return out

    show_sql = user_requested_sql(question)
    show_formula = user_requested_formula(question)
    debug = os.getenv("LLM_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

    internal_sql = out.get("tsql") or out.get("sql")
    if internal_sql and not show_sql:
        if debug:
            out = dict(out)
            out["_debug_sql"] = internal_sql
        else:
            out = dict(out)
            out.pop("tsql", None)
            out.pop("sql", None)
            out.pop("sqls", None)
            out.pop("tsqls", None)

    if not show_formula:
        out = dict(out)
        out.pop("formula", None)
        if out.get("message"):
            out["message"] = _strip_formula_block(str(out["message"]))

    if out.get("message"):
        return out

    result = out.get("result")
    if result is None and isinstance(out.get("nombre_arrivages"), (int, float)):
        result = out.get("nombre_arrivages")
    elif result is None:
        for k in ("tonnage_importe", "tonnage_total", "nombre_navires"):
            if isinstance(out.get(k), (int, float)):
                result = out[k]
                break

    q_for_msg = str(out.get("question") or question)
    src = str(out.get("source") or "")
    if src.startswith("llm:") or (
        src.startswith("sql:") and not out.get("message")
    ):
        narrated = narrate_sql_result(q_for_msg, result, model_name=model_name)
        if narrated:
            out = dict(out)
            out["message"] = narrated
            return out

    msg = build_natural_message(q_for_msg, result, ql=(question or "").lower())
    if msg:
        out = dict(out)
        out["message"] = msg
    return out
