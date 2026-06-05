from __future__ import annotations

import calendar
import json
import os
from contextlib import ExitStack
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, StateGraph

from backend.agent.llm import invoke_chat_text
from backend.agent.state import AgentState
from backend.agent.tools import tool_compare_periods, tool_kpi_answer, tool_rag_context
from backend.llm.kpi_analyse_fallback import deterministic_kpi_analyse_text, extract_kpi_payload_from_analyse_body, is_analysis_text_grounded
from backend.llm.llm_sql import (
    KPI_ANALYSE_MARKER,
    is_kpi_analyse_message,
    is_period_only_followup_text,
    kpi_period_span_from_question,
    normalize_kpi_question,
    question_has_explicit_period,
)


BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_stack = ExitStack()


def _is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def _sonasid_kpi_keywords() -> list[str]:
    return [
        "navire",
        "navires",
        "arrivage",
        "arrivages",
        "tonnage",
        "fournisseur",
        "qualité",
        "qualite",
        "transféré",
        "transfere",
        "transfert",
        "commande",
        "demurrage",
        "démurrage",
        "accostage",
        "booking",
        "port",
    ]


def _agent_domain_line() -> str:
    if _is_sonasid_profile():
        return "assistant décisionnel port & arrivages (Sonasid)"
    return "dashboard KPI d'aciérie"


def _build_checkpointer():
    """
    Persistent checkpointer (SQLite) like Calia, with fallback to in-memory.
    """
    if os.getenv("AGENT_PERSIST", "true").strip().lower() in {"0", "false", "no", "off"}:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()

    try:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = os.getenv(
            "AGENT_CHECKPOINT_DB",
            os.path.join(BASE_DIR, "db", "langgraph_checkpoints.sqlite"),
        ).strip()
        # SqliteSaver.from_conn_string returns a context manager.
        # We keep it open for the lifetime of the process (like Calia).
        return _stack.enter_context(SqliteSaver.from_conn_string(db_path))
    except Exception:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()


_checkpointer = _build_checkpointer()


def _safe_json_load(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except Exception:
        return None


def node_retrieve(state: AgentState) -> AgentState:
    q = (state.get("user_question") or "").strip()
    sid = (state.get("session_id") or "default").strip()
    ctx = ""
    try:
        ctx = tool_rag_context(question=q, session_id=sid)
    except Exception:
        ctx = ""
    return {"rag_context": ctx}


def node_route(state: AgentState) -> AgentState:
    """
    Uses LLM to decide between:
    - intent=chat (simple conversational answer)
    - intent=kpi (execute KPI/SQL pipeline)
    """
    q = (state.get("user_question") or "").strip()
    if is_kpi_analyse_message(q):
        return {"intent": "chat"}
    ql = q.lower().strip()
    rag = (state.get("rag_context") or "").strip()
    model_name = (state.get("model_name") or "").strip()
    last_kpi_q = (state.get("last_kpi_question") or "").strip()

    # SQL request must win over KPI follow-up rewrites.
    # Otherwise "quelle est la requête SQL du TD en janvier 2025" can be rewritten into
    # "taux de disponibilité en 2025-01" and we lose the user's intent to SEE the SQL.
    def _is_sql_request_text(text: str) -> bool:
        t = (text or "").lower()
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

    if _is_sql_request_text(q):
        return {"intent": "kpi", "kpi_question": q}

    # Sonasid : brief multi-KPI / analyse multi-axes avant le moteur SQL unitaire.
    if _is_sonasid_profile():
        try:
            from backend.llm.sonasid_brief import detect_sonasid_brief

            if detect_sonasid_brief(q):
                return {"intent": "kpi", "kpi_question": q}
        except Exception:
            pass

    # Sonasid : questions reconnues par le moteur métier → exécution KPI directe (pas de clarification LLM).
    if _is_sonasid_profile():
        try:
            from backend.llm.sonasid_sql import try_sonasid_kpi_sql

            if try_sonasid_kpi_sql(q):
                return {"intent": "kpi", "kpi_question": q}
        except Exception:
            pass

    # Suite « période seule » après un KPI sans fenêtre (ex. need_period sur « consommation gpl » puis « 2025 »).
    if last_kpi_q and is_period_only_followup_text(q) and not question_has_explicit_period(last_kpi_q):
        return {"intent": "kpi", "kpi_question": f"{last_kpi_q} {q}".strip()}

    # If the user sends only a period (e.g. "2025", "2025-01", "du ... au ...") without any KPI topic
    # and we don't have a previous KPI to reuse, ask ONE clarification question.
    if (not last_kpi_q) and is_period_only_followup_text(q):
        if _is_sonasid_profile():
            clarify_examples = (
                "- nombre d'arrivages en "
                + q.strip()
                + "\n"
                "- arrivages par mois en "
                + q.strip()
                + "\n"
                "- tonnage total des arrivages "
                + q.strip()
            )
        else:
            clarify_examples = (
                "- production 2025\n"
                "- consommation électrique 2025\n"
                "- TD 2025\n"
                "- MTTR par mois en 2025"
            )
        return {
            "intent": "clarify",
            "clarify_message": (
                "Tu veux la période **"
                + q.strip()
                + "**, OK — mais pour quel KPI ?\n"
                "Exemples :\n"
                + clarify_examples
            ),
        }

    # If the user answers with only a consumption type after a clarification,
    # auto-expand to a full KPI question ("consommation ...") instead of running a useless query.
    only_type_map = {
        "oxygene": "consommation oxygène",
        "oxygène": "consommation oxygène",
        "gpl": "consommation gpl",
        "gaz": "consommation gpl",
        "carbone": "consommation carbone",
        "carbon": "consommation carbone",
        "electrique": "consommation électrique",
        "électrique": "consommation électrique",
        "electricite": "consommation électrique",
        "électricité": "consommation électrique",
        "elec": "consommation électrique",
        "élec": "consommation électrique",
    }
    if ql in only_type_map:
        return {"intent": "kpi", "kpi_question": only_type_map[ql]}

    def _normalize_month_token(text: str) -> str:
        """
        Accept month formats like "01-2025" and normalize to "2025-01".
        """
        def repl(m: re.Match) -> str:
            mm, yyyy = m.group(1), m.group(2)
            return f"{yyyy}-{mm}"

        return re.sub(r"\b(0[1-9]|1[0-2])-(20\d{2})\b", repl, text)

    def _infer_metric_from_text(text: str) -> str:
        lt = (text or "").lower()
        if "production" in lt or re.search(r"\bprod\b", lt):
            return "production"
        if "consommation" in lt or "conso" in lt:
            if any(x in lt for x in ["électricité", "electricite", "électrique", "electrique", "elec", "élec"]):
                return "consommation électrique"
            if any(x in lt for x in ["oxygène", "oxygene", "oxyg"]):
                return "consommation oxygène"
            if "gpl" in lt or "gaz" in lt:
                return "consommation gpl"
            if "carbone" in lt or "carbon" in lt:
                return "consommation carbone"
            return "consommation"
        if "disponibilite" in lt or "disponibilité" in lt or re.search(r"\btd\b", lt):
            return "taux de disponibilité"
        if "temps requis" in lt or re.search(r"\btr\b", lt):
            return "temps requis"
        if "mtbf" in lt:
            return "mtbf"
        if "mttr" in lt:
            return "mttr"
        if "rendement" in lt:
            return "rendement"
        return ""

    def _infer_metric_from_last(last_text: str) -> str:
        """
        Derive the KPI topic from the previous KPI question.
        Prefer the richer inference that keeps consumption sub-type
        (électrique / oxygène / GPL / carbone) when possible.
        """
        metric = _infer_metric_from_text(last_text or "")
        if metric:
            return metric
        lt = (last_text or "").lower()
        if "coulée" in lt or "coulee" in lt:
            return "nombre de coulées"
        if "brame" in lt:
            return "nombre de brames"
        return ""

    # Follow-up rewrite: "et par jour en 2025-01" should reuse the last KPI topic (production/conso/etc).
    # Otherwise rule-engine will see no metric and fallback to SELECT 1.
    followup = ql.startswith("et ") or ql.startswith("et,") or ql.startswith("et par")
    bucket = None
    if "par jour" in ql or "par journée" in ql:
        bucket = "jour"
    elif "par semaine" in ql:
        bucket = "semaine"
    elif "par mois" in ql:
        bucket = "mois"
    elif "par an" in ql or "par année" in ql:
        bucket = "année"
    has_bucket = bool(bucket)
    has_metric = any(
        k in ql
        for k in [
            "production",
            "prod",
            "consommation",
            "conso",
            "disponibilite",
            "disponibilité",
            "dispo",
            "taux de disponibilite",
            "taux de disponibilité",
            "td",
            "tr",
            "mtbf",
            "mttr",
            "rendement",
            "coul",
            "coulee",
            "coulée",
            "brame",
        ]
    )
    # If the user only asked for a time bucket without a KPI topic AND we have no previous KPI,
    # do not run a random KPI. Ask a single clarification question.
    if has_bucket and (not has_metric) and (not last_kpi_q):
        return {
            "intent": "clarify",
            "clarify_message": (
                f"Par **{bucket or 'jour'}** de quel KPI ?\n"
                "Exemples :\n"
                f"- consommation électrique par {bucket or 'jour'} en 2025\n"
                f"- production par {bucket or 'jour'} en 2025-01\n"
                f"- nombre de brames par {bucket or 'jour'} en 2025"
            ),
        }
    if last_kpi_q and has_bucket and (followup or not has_metric):
        metric = _infer_metric_from_last(last_kpi_q)
        if metric:
            qn = _normalize_month_token(q)
            # Remove leading "et" to avoid awkward phrasing.
            qn = re.sub(r"(?i)^\s*et\s+", "", qn).strip()
            # If user only asked for a bucket ("par jour") without a period, reuse last KPI period.
            if not question_has_explicit_period(qn):
                lp = (state.get("last_kpi_period") or "").strip()
                if lp and ".." in lp:
                    a, b = (lp.split("..", 1) + [""])[:2]
                    a = (a or "").strip()
                    b = (b or "").strip()
                    if a and b:
                        qn = f"{qn} du {a} au {b}"
            return {"intent": "kpi", "kpi_question": f"{metric} {qn}".strip()}

    # Follow-up rewrite: month-only questions should reuse last KPI context.
    # Examples:
    # - "en mars ?" -> last KPI metric + inferred year
    # - "mars 2025" -> last KPI metric + 2025-03
    # - "TD en mars" -> TD + inferred year
    if last_kpi_q:
        t = (q or "").lower()
        month_re = r"\b(janvier|janv\.?|jan|février|fevrier|févr\.?|fevr\.?|feb|mars|mar|avril|avr\.?|mai|juin|juillet|juil\.?|août|aout|septembre|sept\.?|octobre|oct\.?|novembre|nov\.?|décembre|decembre|déc\.?|dec\.?)\b"
        has_month_token = bool(re.search(month_re, t)) or bool(re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q or ""))
        if has_month_token:
            # Guardrail: don't rewrite a full KPI question that already has qualifiers
            # (e.g. "consommation par ferraille en 2025-01"). This rewrite is only for
            # month-only follow-ups like "en mars ?" / "mars 2025".
            qualifiers = [
                "ferraille",
                "ferrailles",
                "catégorie",
                "categorie",
                "grade",
                "top",
                "largeur",
                "epaisseur",
                "épaisseur",
                "brame",
                "brames",
                "coulée",
                "coulee",
                "coulées",
                "coulees",
            ]
            if any(k in t for k in qualifiers):
                # Keep the original question (it's not a month-only follow-up).
                metric = ""
            else:
                # Choose metric: explicit in current text, else from last KPI.
                metric_now = _infer_metric_from_text(q) if has_metric else ""
                metric = metric_now or _infer_metric_from_last(last_kpi_q)

            if metric:
                # Extract year from current question, else from last KPI period, else from last KPI question.
                year_m = re.search(r"\b(20\d{2})\b", q or "")
                year = int(year_m.group(1)) if year_m else None
                if not year:
                    lp = (state.get("last_kpi_period") or "").strip()
                    m = re.match(r"^\s*(20\d{2})-\d{2}-\d{2}\.\.", lp)
                    if m:
                        year = int(m.group(1))
                if not year:
                    m = re.search(r"\b(20\d{2})\b", last_kpi_q)
                    if m:
                        year = int(m.group(1))
                if not year:
                    year = datetime.date.today().year

                # If already explicit YYYY-MM, just attach metric.
                ym = re.search(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q or "")
                if ym:
                    y, mm = int(ym.group(1)), int(ym.group(2))
                    return {"intent": "kpi", "kpi_question": f"{metric} en {y:04d}-{mm:02d}".strip()}

                month_map = {
                    "janvier": 1,
                    "janv": 1,
                    "janv.": 1,
                    "jan": 1,
                    "février": 2,
                    "fevrier": 2,
                    "févr": 2,
                    "fevr": 2,
                    "févr.": 2,
                    "fevr.": 2,
                    "feb": 2,
                    "mars": 3,
                    "mar": 3,
                    "avril": 4,
                    "avr": 4,
                    "avr.": 4,
                    "mai": 5,
                    "juin": 6,
                    "juillet": 7,
                    "juil": 7,
                    "juil.": 7,
                    "août": 8,
                    "aout": 8,
                    "septembre": 9,
                    "sept": 9,
                    "sept.": 9,
                    "octobre": 10,
                    "oct": 10,
                    "oct.": 10,
                    "novembre": 11,
                    "nov": 11,
                    "nov.": 11,
                    "décembre": 12,
                    "decembre": 12,
                    "déc": 12,
                    "dec": 12,
                    "déc.": 12,
                    "dec.": 12,
                }
                m = re.search(month_re, t)
                if m:
                    tok = (m.group(1) or "").strip().lower()
                    tok = tok.replace("?", "").replace(",", "").strip()
                    mm = month_map.get(tok)
                    if mm:
                        return {"intent": "kpi", "kpi_question": f"{metric} en {year:04d}-{mm:02d}".strip()}

    def looks_like_kpi(text: str) -> bool:
        t = (text or "").lower()
        # If the user is clearly doing small-talk, don't force KPI routing
        # just because a year/date is present (e.g. "coucou en 2026").
        small_talk_tokens = [
            "bonjour",
            "salut",
            "hello",
            "bonsoir",
            "coucou",
            "yo",
            "ça va",
            "ca va",
            "cava",
            "cv",
            "cc",
            "merci",
            "thanks",
            "ok",
        ]
        keywords = [
            "kpi",
            *(_sonasid_kpi_keywords() if _is_sonasid_profile() else []),
            "production",
            "prod",
            "consommation",
            "conso",
            "disponibilite",
            "disponibilité",
            "taux de disponibilite",
            "taux de disponibilité",
            "dispo",
            "td",
            "tr",
            "mtbf",
            "mttr",
            "rendement",
            "coul",
            "coulee",
            "coulée",
            "brame",
            "brames",
            "ferraille",
            "ferrailles",
            "oxyg",
            "gpl",
            "carbone",
            "electric",
            "élec",
            "elec",
            "gaz",
        ]
        if any(tok in t for tok in small_talk_tokens) and not any(k in t for k in keywords):
            return False
        if any(k in t for k in keywords):
            return True
        if re.search(r"\btop\s*\d+\b", t):
            return True
        if "par mois" in t or "par semaine" in t or "par jour" in t or "par an" in t or "par année" in t:
            return True
        if re.search(r"\b20\d{2}\b", t) or re.search(r"\d{4}-\d{2}", t) or re.search(r"\d{4}-\d{2}-\d{2}", t):
            # dates souvent liées aux KPI
            return True
        return False

    # NOTE: We intentionally do NOT short-circuit greetings here.
    # The LLM should answer naturally (ChatGPT-like) for general conversation.

    # Default behavior: be ChatGPT-like. Only go KPI when it's clearly KPI.
    if not looks_like_kpi(q):
        return {"intent": "chat"}

    def _month_token_to_num(tok: str) -> Optional[int]:
        t = (tok or "").strip().lower()
        m = {
            "janvier": 1,
            "janv": 1,
            "janv.": 1,
            "jan": 1,
            "février": 2,
            "fevrier": 2,
            "févr": 2,
            "fevr": 2,
            "févr.": 2,
            "fevr.": 2,
            "feb": 2,
            "mars": 3,
            "mar": 3,
            "avril": 4,
            "avr": 4,
            "avr.": 4,
            "mai": 5,
            "juin": 6,
            "juillet": 7,
            "juil": 7,
            "juil.": 7,
            "août": 8,
            "aout": 8,
            "septembre": 9,
            "sept": 9,
            "sept.": 9,
            "octobre": 10,
            "oct": 10,
            "oct.": 10,
            "novembre": 11,
            "nov": 11,
            "nov.": 11,
            "décembre": 12,
            "decembre": 12,
            "déc": 12,
            "dec": 12,
            "déc.": 12,
            "dec.": 12,
        }
        return m.get(t)

    def _month_range(year: int, month: int) -> Dict[str, str]:
        last = calendar.monthrange(year, month)[1]
        return {"start": f"{year:04d}-{month:02d}-01", "end": f"{year:04d}-{month:02d}-{last:02d}"}

    # Compare intent: "compare ... 2024 vs 2025" or "comparaison ...".
    years = re.findall(r"\b(20\d{2})\b", q)
    if re.search(r"\b(compare|comparaison|vs|versus)\b", ql) and len(years) >= 2:
        y1, y2 = years[0], years[1]
        return {
            "intent": "compare",
            "kpi_question": q,
            "compare_a": {"start": f"{y1}-01-01", "end": f"{y1}-12-31"},
            "compare_b": {"start": f"{y2}-01-01", "end": f"{y2}-12-31"},
        }

    # Compare months intent: "compare ... janvier et février (2025)" or "2025-01 vs 2025-02".
    if re.search(r"\b(compare|comparaison|vs|versus|entre)\b", ql):
        ym = re.findall(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", q)
        if len(ym) >= 2:
            (y1, m1), (y2, m2) = ym[0], ym[1]
            if y1 == y2:
                year = int(y1)
                metric = _infer_metric_from_text(q) or q
                return {
                    "intent": "compare",
                    "kpi_question": metric,
                    "compare_a": _month_range(year, int(m1)),
                    "compare_b": _month_range(year, int(m2)),
                }

        def _extract_month_year_pairs(text: str) -> list[tuple[int, int]]:
            """
            Extract explicit pairs like "janvier 2025" or "2025 janvier".
            Returns list of (year, month_num) in appearance order.
            """
            t = (text or "").lower()
            # Reuse the same month token regex used below.
            month_re = r"(janvier|janv\.?|jan|février|fevrier|févr\.?|fevr\.?|feb|mars|mar|avril|avr\.?|mai|juin|juillet|juil\.?|août|aout|septembre|sept\.?|octobre|oct\.?|novembre|nov\.?|décembre|decembre|déc\.?|dec\.?)"
            out: list[tuple[int, int]] = []
            for m in re.finditer(rf"\b{month_re}\s*(20\d{{2}})\b", t):
                mm = _month_token_to_num(m.group(1))
                yy = int(m.group(2))
                if mm:
                    out.append((yy, mm))
            for m in re.finditer(rf"\b(20\d{{2}})\s*{month_re}\b", t):
                yy = int(m.group(1))
                mm = _month_token_to_num(m.group(2))
                if mm:
                    out.append((yy, mm))
            return out

        pairs = _extract_month_year_pairs(q)
        if len(pairs) >= 2:
            (y1, m1), (y2, m2) = pairs[0], pairs[1]
            metric = _infer_metric_from_text(q) or q
            return {
                "intent": "compare",
                "kpi_question": metric,
                "compare_a": _month_range(y1, m1),
                "compare_b": _month_range(y2, m2),
            }

        months = re.findall(
            r"\b(janvier|janv\.?|jan|février|fevrier|févr\.?|fevr\.?|feb|mars|mar|avril|avr\.?|mai|juin|juillet|juil\.?|août|aout|septembre|sept\.?|octobre|oct\.?|novembre|nov\.?|décembre|decembre|déc\.?|dec\.?)\b",
            ql,
        )
        if len(months) >= 2:
            m1 = _month_token_to_num(months[0])
            m2 = _month_token_to_num(months[1])
            # If user wrote one year for the whole comparison, use it.
            y = years[0] if years else ""
            # If user wrote "janvier 2025" but not the other month, propagate that year.
            if not y and len(pairs) == 1:
                y = str(pairs[0][0])
            if not y:
                # Default year when user omits it (configurable).
                y = (os.getenv("DEFAULT_COMPARE_YEAR", "") or "").strip()
                if not re.match(r"^20\d{2}$", y):
                    y = str(datetime.now().year)
            if m1 and m2:
                year = int(y)
                metric = _infer_metric_from_text(q) or q
                return {
                    "intent": "compare",
                    "kpi_question": metric,
                    "compare_a": _month_range(year, m1),
                    "compare_b": _month_range(year, m2),
                }

    # Clarify intent for ambiguous KPI requests (ask 1 question max).
    conso_words = {"conso", "consommation", "consommer", "consommateurs"}
    # Types that disambiguate "consommation ..." questions. Include ferraille to avoid
    # wrongly clarifying scrap-consumption questions.
    conso_types = {
        "élec",
        "elec",
        "électrique",
        "electric",
        "electricite",
        "électricité",
        "oxyg",
        "oxygene",
        "oxygène",
        "gpl",
        "carbone",
        "carbon",
        "gaz",
        "ferraille",
        "ferrailles",
    }
    if any(w in ql for w in conso_words) and not any(w in ql for w in conso_types):
        return {
            "intent": "clarify",
            "clarify_message": "Tu parles de quelle consommation : électrique, oxygène, GPL ou carbone ? (tu peux aussi préciser une période, sinon je prends la sélection du dashboard)",
        }

    # Ne pas laisser le LLM « reformuler » une question déjà explicite : erreurs observées
    # (ex. « la production en 2025-01 » → kpi_question « rendement … », mauvais SQL / mauvais KPI).
    if any(
        tok in ql
        for tok in (
            "production",
            "rendement",
            "consommation",
            "conso",
            "disponibilite",
            "disponibilité",
            "taux de disponibilite",
            "taux de disponibilité",
            "mtbf",
            "mttr",
            "coulée",
            "coulee",
            "brame",
            "brames",
            "ferraille",
            "ferrailles",
            "oxyg",
            "gpl",
            "carbone",
            "élec",
            "elec",
            "gaz",
        )
    ) or re.search(r"\b(prod|td|tr)\b", ql):
        return {"intent": "kpi", "kpi_question": q}

    sys = (
        f"Tu es un routeur d'intention pour une API KPI ({_agent_domain_line()}).\n"
        "Tu dois répondre UNIQUEMENT en JSON valide, sans markdown.\n"
        "Format:\n"
        '{"intent":"chat"|"kpi","kpi_question":string|null,"message":string|null}\n'
        "Règles:\n"
        "- L'utilisateur est clairement dans un contexte KPI. Tu dois mettre intent='kpi'.\n"
        "- IMPORTANT: 'cava' veut dire 'ça va' (salutation), pas le vin.\n"
        "- kpi_question: reformule en une question KPI explicite si intent='kpi', sinon null.\n"
        "- Tu DOIS renvoyer intent='kpi'.\n"
    )

    content = f"Question utilisateur:\n{q}\n\nContexte RAG (si utile):\n{rag if rag else '(vide)'}\n"
    prompt = sys + "\n\n" + content
    try:
        text = invoke_chat_text(prompt=prompt, model_name=model_name)
    except Exception:
        # If local Ollama is down, fallback to a cloud free model when possible.
        try:
            text = invoke_chat_text(prompt=prompt, model_name="flash")
        except Exception:
            text = ""
    data = _safe_json_load(text or "")
    if not isinstance(data, dict):
        return {"intent": "kpi", "kpi_question": q}

    intent = (data.get("intent") or "").strip().lower()
    # Force KPI (the heuristic already decided it's KPI)
    intent = "kpi"
    kpi_q = (data.get("kpi_question") or "").strip() or q
    return {"intent": "kpi", "kpi_question": kpi_q}


def node_clarify(state: AgentState) -> AgentState:
    q = (state.get("user_question") or "").strip()
    msg = (state.get("clarify_message") or "").strip() or "Peux-tu préciser ?"
    return {"response": {"question": q, "message": msg, "source": "agent:clarify"}}


def node_compare(state: AgentState) -> AgentState:
    q = (state.get("kpi_question") or state.get("user_question") or "").strip()
    a = state.get("compare_a") or {}
    b = state.get("compare_b") or {}
    pa = f"{a.get('start')}..{a.get('end')}"
    pb = f"{b.get('start')}..{b.get('end')}"
    res = tool_compare_periods(question=q, period_a=pa, period_b=pb)
    return {"response": res}


def node_chat(state: AgentState) -> AgentState:
    """
    Conversational answer, still grounded by RAG context when useful.
    """
    q = (state.get("user_question") or "").strip()
    ql = q.lower().strip()
    rag = (state.get("rag_context") or "").strip()
    model_name = (state.get("model_name") or "").strip()
    actor_name = (state.get("actor_name") or "").strip()
    last_kpi_q = (state.get("last_kpi_question") or "").strip()
    last_kpi_period = (state.get("last_kpi_period") or "").strip()
    pre_answer = (state.get("answer") or "").strip() if isinstance(state, dict) else ""

    def _maybe_prefix_actor(text: str) -> str:
        n = (actor_name or "").strip()
        if not n:
            return text
        # Avoid double-prefix if the assistant already used the name.
        if text.lstrip().lower().startswith(n.lower()):
            return text
        return f"{n}, {text}"

    try:
        from backend.llm.conversational import conversational_reply, is_pure_greeting

        if is_pure_greeting(q):
            r = conversational_reply(
                q,
                actor_name=actor_name,
                session_id=(state.get("session_id") or None),
                model_name=model_name,
            )
            return {"response": r}
    except Exception:
        pass

    # If routing already provided a deterministic conversational answer, return it directly.
    if pre_answer:
        return {
            "response": {
                "question": q,
                "message": _maybe_prefix_actor(pre_answer),
                "source": str(state.get("source") or "agent:chat:preanswer"),
            }
        }

    if is_kpi_analyse_message(q):
        q_body = q[len(KPI_ANALYSE_MARKER) :].lstrip()
        payload = extract_kpi_payload_from_analyse_body(q_body) or {}
        if not isinstance(payload, dict) or not payload:
            return {
                "response": {
                    "question": q,
                    "message": (
                        "Je ne peux pas faire une analyse sans données chiffrées.\n"
                        "Exécute d’abord un KPI (avec période), puis clique sur **Analyser** sous le résultat."
                    ),
                    "source": "agent:analyse:need_data",
                }
            }
        sys = (
            f"Tu es un analyste KPI pour {_agent_domain_line()}.\n"
            "Des résultats chiffrés du dashboard viennent d’être calculés ; tu dois les interpréter.\n"
            "Réponds en français, de façon concise (listes à puces courtes si utile).\n"
            "N’invente aucune valeur absente des données fournies. Ne propose pas de nouvelle requête SQL.\n"
        )
        content = f"Consigne et données:\n{q_body}\n\nContexte complémentaire:\n{rag if rag else '(vide)'}\n"
        prompt = sys + "\n\n" + content
        text = ""
        last_err: Optional[str] = None
        for mn in (model_name, "flash"):
            if not mn:
                continue
            try:
                text = invoke_chat_text(prompt=prompt, model_name=mn)
            except Exception as e:
                last_err = str(e) or repr(e)
                text = ""
            if text:
                break
        if not text:
            fb = deterministic_kpi_analyse_text(q_body)
            if fb:
                text = (
                    fb
                    + "\n\n_(Synthèse calculée automatiquement — le modèle d’interprétation n’a pas répondu ; "
                    "vérifie `OPENROUTER_API_KEY`, ou essaie le modèle **Flash** dans la barre latérale.)_"
                )
            elif last_err:
                text = (
                    "Je n’ai pas pu appeler le modèle d’analyse.\n"
                    f"Détail technique : {last_err}\n"
                    "Vérifie la clé OpenRouter, les crédits, ou passe sur **Flash** / **Llama (local)**."
                )
            else:
                text = (
                    "Je n’ai pas pu générer l’analyse (réponse vide du modèle).\n"
                    "Essaie **Flash**, ou vérifie `OPENROUTER_API_KEY` et les quotas OpenRouter."
                )
        # Reject generic answers that don't cite any number.
        if not is_analysis_text_grounded(text, payload):
            fb = deterministic_kpi_analyse_text(q_body)
            if fb:
                text = fb
            else:
                text = (
                    "Je ne peux pas produire une analyse fiable sans chiffres exploitables dans les données.\n"
                    "Exécute d’abord un KPI (avec période), puis clique sur **Analyser** sous le résultat."
                )
                return {
                    "response": {
                        "question": q,
                        "message": text,
                        "source": "agent:analyse:need_data",
                    }
                }
        return {"response": {"question": q, "message": text, "source": "agent:analyse"}}

    # Normalize common slang so the LLM doesn't interpret "cava" as the beverage.
    # Keep it as the user's intent (wellbeing check), but don't force the assistant to loop on it.
    if ql in {"cava", "ca va", "ça va", "cv", "cava ?"}:
        q = "Ça va ?"

    # Deterministic answers for common UX questions (avoid LLM dependency).
    def _fmt_fr_date(d: datetime) -> str:
        mois = [
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
        ]
        m = mois[d.month - 1] if 1 <= d.month <= 12 else str(d.month)
        return f"{d.day} {m} {d.year}"

    # Calendar date questions (today / tomorrow / yesterday / day-after-tomorrow).
    # Never route these to KPI "période" logic.
    ql2 = re.sub(r"[?!.:,;]+", " ", ql).strip()
    asks_calendar_date = bool(re.search(r"\b(date|jour)\b", ql2)) or bool(re.search(r"\b(et\s+)?(demain|hier)\b", ql2))
    if asks_calendar_date and re.search(r"\b(aujourd|today|maintenant|on est quel|quelle est la date)\b", ql2):
        now = datetime.now()
        text = f"Aujourd’hui, nous sommes le {_fmt_fr_date(now)}."
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent:date"}}
    if asks_calendar_date and re.search(r"\b(apr[eè]s[-\\s]?demain)\b", ql2):
        d = datetime.now() + timedelta(days=2)
        text = f"Après-demain, ce sera le {_fmt_fr_date(d)}."
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent:date"}}
    if asks_calendar_date and re.search(r"\b(demain)\b", ql2):
        d = datetime.now() + timedelta(days=1)
        text = f"Demain, ce sera le {_fmt_fr_date(d)}."
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent:date"}}
    if asks_calendar_date and re.search(r"\b(hier)\b", ql2):
        d = datetime.now() - timedelta(days=1)
        text = f"Hier, c’était le {_fmt_fr_date(d)}."
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent:date"}}

    if any(x in ql for x in ["unité", "unite", "unit"]):
        text = (
            "Dans cette version livrable, on n’affiche pas l’unité pour éviter les confusions (selon les sources, l’unité peut varier).\n"
            "Si tu veux, je peux l’ajouter proprement plus tard par KPI (ex: MWh, Nm³, kg) une fois qu’on valide les unités côté dataset."
        )
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent"}}

    # Follow-up about the period/date: answer deterministically using last KPI context.
    if re.search(r"\b(quelle|de quelle|sur quelle)\s+(date|p[ée]riode)\b", ql) or ql in {
        "date ?",
        "la date ?",
        "période ?",
        "periode ?",
    }:
        if last_kpi_q:
            if last_kpi_period:
                a, b = (last_kpi_period.split("..", 1) + [""])[:2]
                text = f"Pour le dernier KPI ({last_kpi_q}), la période utilisée est **{a} → {b}**."
            else:
                text = (
                    f"Pour le dernier KPI ({last_kpi_q}), **aucune période n’a été précisée**.\n"
                    "Choisis une période à gauche (7j/30j/YTD/personnalisé), ou écris-la dans ta question (ex: “du 2025-01-01 au 2025-01-31”)."
                )
        else:
            text = (
                "Tu parles de quelle période ? Choisis-la à gauche, ou écris-la dans ta question "
                "(ex: “du 2025-01-01 au 2025-01-31”)."
            )
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent"}}

    # ChatGPT-like: allow conversation summaries / recaps without triggering KPI execution.
    if any(
        k in ql
        for k in {
            "résume",
            "résumer",
            "resume",
            "resumer",
            "récap",
            "recap",
            "récapitule",
            "recapitule",
            "synthèse",
            "synthese",
        }
    ):
        sys = (
            f"Tu es un assistant type ChatGPT pour un {_agent_domain_line()}.\n"
            "L'utilisateur demande un résumé / récapitulatif.\n"
            "Réponds en français, de façon courte et claire.\n"
            "Si le contexte ne suffit pas, pose UNE seule question pour préciser ce qu'il veut résumer.\n"
        )
        ctx_bits = []
        if last_kpi_q:
            ctx_bits.append(f"Dernier KPI: {last_kpi_q}")
        if last_kpi_period:
            ctx_bits.append(f"Dernière période: {last_kpi_period}")
        ctx_line = "\n".join(ctx_bits) if ctx_bits else "(aucun KPI précédent)"
        content = (
            f"Demande:\n{q}\n\n"
            f"Contexte conversation (RAG):\n{rag if rag else '(vide)'}\n\n"
            f"Contexte KPI:\n{ctx_line}\n"
        )
        prompt = sys + "\n\n" + content
        text = ""
        for mn in (model_name, "flash"):
            if not mn:
                continue
            try:
                text = (invoke_chat_text(prompt=prompt, model_name=mn) or "").strip()
            except Exception:
                text = ""
            if text:
                break
        if not text:
            text = (
                "Tu veux un résumé de quoi exactement :\n"
                "- la conversation,\n"
                "- le dernier KPI,\n"
                "- ou une période précise (ex: janvier 2025) ?"
            )
        return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent:summary"}}

    # Simple general-knowledge answers when the cloud model is down (avoid KPI marketing loop).
    if re.search(r"\bcapitale\b", ql) and re.search(r"\bmaroc\b", ql):
        return {
            "response": {
                "question": q,
                "message": _maybe_prefix_actor("La capitale du Maroc est **Rabat**."),
                "source": "agent:trivia",
            }
        }

    sys = (
        f"Tu es un assistant pour un {_agent_domain_line()}.\n"
        "Réponds en français, **2 phrases maximum** (3 si indispensable). Pas de listes.\n"
        "Ne termine pas chaque message par une question.\n"
        "Si l'utilisateur dit 'cava', il veut dire 'ça va ?'.\n"
    )
    content = f"Question:\n{q}\n\nContexte (si utile):\n{rag if rag else '(vide)'}\n"
    prompt = sys + "\n" + content
    text = ""
    llm_err = ""
    try:
        text = (invoke_chat_text(prompt=prompt, model_name=model_name) or "").strip()
    except Exception as e:
        llm_err = str(e) or repr(e)
        text = ""
    if not text:
        if any(x in ql for x in ["bonjour", "salut", "hello", "coucou", "bonsoir"]):
            text = "Bonjour ! Comment puis-je t’aider ?"
        elif llm_err:
            text = (
                "Je n’ai pas pu joindre le modèle conversationnel (OpenRouter).\n"
                f"Détail : {llm_err[:280]}\n"
                "Essaie le modèle **Llama (local)** si Ollama tourne, ou mets à jour `OPENROUTER_CHAT_FALLBACK` dans `.env`."
            )
        else:
            if _is_sonasid_profile():
                text = (
                    "Bonjour, bienvenue dans l'assistant IA Sonasid. "
                    "Je serai ravi de t'aider — que veux-tu savoir ?"
                )
            else:
                text = "Bonjour ! Je peux t’aider à analyser tes KPI (production, consommations, TD/TR, MTBF/MTTR, rendement…). Dis-moi ce que tu veux regarder."
    asked_wellbeing = any(x in ql for x in ["ca va", "ça va", "cava", "cv", "va ?"])
    if (not asked_wellbeing) and ("ça va ?" in text.lower() or "ca va ?" in text.lower()):
        # Avoid getting stuck in "ça va ?" loops.
        text = re.sub(r"(?i)\b(ca va|ça va)\s*\?\s*", "", text).strip()
    # If the user asked "ça va ?", answer it explicitly (more natural UX).
    try:
        if asked_wellbeing:
            t_low = (text or "").strip().lower()
            # If the model starts with a generic "Bonjour" while the user asked "ça va ?",
            # keep the focus on answering the wellbeing check.
            text = re.sub(r"(?i)^\s*(bonjour|salut|hello|coucou)\s*[!,:-]*\s*", "", (text or "")).strip()
            t_low = text.lower()
            if "ça va" not in t_low and "ca va" not in t_low:
                text = ("Ça va très bien, merci. " + (text or "").lstrip()).strip()
    except Exception:
        pass
    # Do not append canned KPI guidance automatically.
    # The assistant should stay natural; if the user needs guidance, the LLM can provide it.
    # If the user greeted and the model didn't greet back, add a short professional greeting.
    try:
        t_low = (text or "").strip().lower()
        q_low = (q or "").strip().lower()
        greeted = any(x in q_low for x in ["bonjour", "salut", "hello", "coucou"])
        has_greeting = any(t_low.startswith(x) for x in ["bonjour", "salut", "hello", "coucou"])
        if greeted and (not has_greeting):
            name = (actor or "").strip()
            prefix = f"Bonjour {name}," if name else "Bonjour,"
            text = f"{prefix} {text}".strip()
    except Exception:
        pass
    return {"response": {"question": q, "message": _maybe_prefix_actor(text), "source": "agent"}}


def node_kpi(state: AgentState) -> AgentState:
    q = (state.get("kpi_question") or state.get("user_question") or "").strip()
    res = tool_kpi_answer(question=q)
    # Store last KPI context so follow-up questions (e.g. "de quelle date ?") can be answered.
    period = kpi_period_span_from_question(q)
    # Mark that an agent handled it (optional)
    if isinstance(res, dict) and "source" in res and isinstance(res["source"], str):
        res["source"] = res["source"] + " + agent"
    elif isinstance(res, dict) and "source" not in res:
        res["source"] = "agent"
    return {"response": res, "last_kpi_question": q, "last_kpi_period": period}


def _should_kpi(state: AgentState) -> str:
    i = (state.get("intent") or "").strip().lower()
    if i in {"kpi", "chat", "clarify", "compare"}:
        return i
    return "chat"


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("retrieve", node_retrieve)
    g.add_node("route", node_route)
    g.add_node("chat", node_chat)
    g.add_node("kpi", node_kpi)
    g.add_node("clarify", node_clarify)
    g.add_node("compare", node_compare)

    g.set_entry_point("retrieve")
    g.add_edge("retrieve", "route")
    g.add_conditional_edges(
        "route",
        _should_kpi,
        {"kpi": "kpi", "chat": "chat", "clarify": "clarify", "compare": "compare"},
    )
    g.add_edge("kpi", END)
    g.add_edge("chat", END)
    g.add_edge("clarify", END)
    g.add_edge("compare", END)
    return g.compile(checkpointer=_checkpointer)


_graph = build_graph()


def run_agent(*, question: str, session_id: Optional[str], model_name: str = "", actor_name: str = "") -> Dict[str, Any]:
    sid = (session_id or "default").strip() or "default"
    raw_q = (question or "").strip()
    qn = raw_q if is_kpi_analyse_message(raw_q) else normalize_kpi_question(raw_q)
    state_in: AgentState = {
        "session_id": sid,
        "user_question": qn,
        "model_name": model_name or "",
        "actor_name": (actor_name or "").strip(),
        "messages": [HumanMessage(content=qn)],
    }
    out = _graph.invoke(state_in, config={"configurable": {"thread_id": sid}})
    resp = out.get("response") if isinstance(out, dict) else None
    if isinstance(resp, dict):
        return resp
    return {"question": qn, "error": "Agent: réponse invalide"}

