import calendar
import os
import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

# Temps d'ouverture mensuel (30 jours en secondes)
# Valeur par défaut si aucune période n'est fournie
TEMPS_OUVERTURE_DEFAULT = 86400 * 30

# Préfixe UI / API : interprétation des chiffres déjà affichés (pas une nouvelle requête KPI).
KPI_ANALYSE_MARKER = "[Analyse KPI]"


def is_kpi_analyse_message(text: str) -> bool:
    return (text or "").lstrip().startswith(KPI_ANALYSE_MARKER)


def normalize_kpi_question(question: str) -> str:
    """
    Rend les questions plus tolérantes aux fautes / formulations alternatives avant le moteur de règles.
    (Pas d’appel LLM ici : rapide, déterministe, idempotent à peu près.)
    """
    if not question or not isinstance(question, str):
        return question or ""
    q = unicodedata.normalize("NFKC", question).strip()
    q = re.sub(r"\s+", " ", q)

    typo_pairs = [
        (r"\bconsomations?\b", "consommation"),
        (r"\bconssommations?\b", "consommation"),
        (r"\bconsomation\b", "consommation"),
        (r"\bconsomqtions?\b", "consommation"),
        (r"\bconsommqtions?\b", "consommation"),
        (r"\bproducktions?\b", "production"),
        (r"\bproduktions?\b", "production"),
        (r"\bprodcutions?\b", "production"),
        (r"\brendemets?\b", "rendement"),
        (r"\brendemnt\b", "rendement"),
        (r"\bferailles?\b", "ferraille"),
        (r"\bferailes?\b", "ferraille"),
        (r"\bcoulles\b", "coulées"),
        (r"\bcoulees\b", "coulées"),
        (r"\bcoullées\b", "coulées"),
        (r"\bcoullees\b", "coulées"),
        (r"\bbrammes?\b", "brames"),
        (r"\bbramez\b", "brames"),
        (r"\belek(trique|tricité|tricite)?\b", r"électrique"),
        (r"\belectricite\b", "électricité"),
        (r"\belectricité\b", "électricité"),
        (r"\belectrique\b", "électrique"),
        (r"\boxygene\b", "oxygène"),
        (r"\bdisponiblite\b", "disponibilité"),
        (r"\bdisponibilté\b", "disponibilité"),
        (r"\bdisponiblité\b", "disponibilité"),
        # SQL wording typos: normalize to "requete" (matched by SQL intent detector)
        (r"\bimporte\b", "importé"),
        (r"\bimportes\b", "importés"),
        (r"\brequtes?\b", "requete"),
        (r"\breqetes?\b", "requete"),
        (r"\brequetes?\b", "requete"),
        (r"\bréquettes?\b", "requete"),
        (r"\bpar\s+joun[ée]e\b", "par jour"),
        (r"\bpar\s+journee\b", "par jour"),
        (r"\bkip\b", "kpi"),
        (r"\bkips\b", "kpi"),
        (r"\bpar\s+sem\b", "par semaine"),
        (r"\bpar\s+semiane\b", "par semaine"),
        (r"\bpar\s+moit\b", "par mois"),
        (r"\bpar\s+an\b", "par année"),
    ]
    for pat, rep in typo_pairs:
        q = re.sub(pat, rep, q, flags=re.IGNORECASE)

    try:
        import os

        prof = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
        if prof in {"sonasid", "shipping", "port"}:
            from backend.llm.sonasid_typo import apply_sonasid_typos

            q = apply_sonasid_typos(q)
    except Exception:
        pass

    ql = q.lower()

    # prod (mot entier) → production si pas déjà présent
    if re.search(r"(?<![a-z])prods?(?![a-z])", ql) and "production" not in ql and "consomm" not in ql:
        q = f"{q} production"
        ql = q.lower()

    # dispo / disponibilité → mot-clé attendu par le moteur
    if (
        (re.search(r"(?<![a-z])dispos?(?![a-z])", ql) or "disponibilit" in ql)
        and "disponibilite" not in ql
        and "disponibilité" not in ql
        and not re.search(r"(^|\s)td(\s|$|[?.!,])", ql)
    ):
        q = f"{q} disponibilité"
        ql = q.lower()

    # TR (taux / temps requis) : éviter les faux positifs type "entre"
    if "temps requis" not in ql and re.search(r"(^|\s)tr(\s|$|[?.!,])", ql):
        q = f"{q} temps requis"
        ql = q.lower()

    # Combien / quelle … coulée(s) → nombre de coulées
    if re.search(r"\b(combien|quel|quelle|quels|quelles)\b", ql) and re.search(r"coul", ql):
        if "nombre" not in ql:
            q = f"{q} nombre de coulées"
            ql = q.lower()

    # Unités d’énergie → consommation électrique
    if re.search(r"\b(mwh|kwh)\b", ql) and "consomm" not in ql:
        q = f"consommation électrique {q}"
        ql = q.lower()

    # IMPORTANT: do not assume a default consumption type.
    # If user says "consommation" or "consommation totale" without specifying the fluid
    # (électricité / oxygène / GPL / carbone / ferrailles), we keep the question as-is.

    # Énergie (é)lectrique …
    if re.search(r"\b(énergie|energie)\s+(é|e)?lect", ql) and "consomm" not in ql:
        q = re.sub(
            r"\b(énergie|energie)\s+(é|e)?lect\w*",
            "consommation électrique",
            q,
            count=1,
            flags=re.IGNORECASE,
        )
        ql = q.lower()

    # Taux de dispo (sans « disponibilité » complet)
    if "taux" in ql and re.search(r"(?<![a-z])dispo", ql) and "disponibilite" not in ql and "disponibilité" not in ql:
        q = f"{q} disponibilité"
        ql = q.lower()

    # Raccourci GPL : « gpl 2025 », « gpl en 2025 », « ppl 2025 » (faute clavier) — aligné sur l’agent (only_type_map « gpl »).
    if "consomm" not in ql and "conso" not in ql:
        q = re.sub(r"^\s*ppl\b", "gpl", q, flags=re.IGNORECASE)
        ql = q.lower()
        _other_kpi = any(
            x in ql
            for x in (
                "production",
                "rendement",
                "disponibil",
                "mtbf",
                "mttr",
                "coulée",
                "coulee",
                "brame",
                "ferraille",
                "ferrailles",
            )
        ) or re.search(r"(^|\s)td(\s|$|[?.!,])", ql)
        if not _other_kpi:
            if re.match(r"^\s*gpl\b", ql):
                q = re.sub(r"^\s*gpl\b", "consommation gpl", q, count=1, flags=re.IGNORECASE)
                ql = q.lower()
            elif re.match(r"^\s*gaz\b", ql) and question_has_explicit_period(q):
                q = re.sub(r"^\s*gaz\b", "consommation gpl", q, count=1, flags=re.IGNORECASE)
                ql = q.lower()

    return q.strip()


def normalize_user_question(question: str) -> str:
    """Point d'entrée unique : fautes, accents, synonymes avant tout routage."""
    return normalize_kpi_question(question)


def _extract_year_month_range(question: str) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Extrait (year, month, start_date, end_date) depuis une question.
    - year: '2024'
    - month: '2024-01'
    - start/end: 'YYYY-MM-DD' si pattern 'du ... au ...' (ou 'de ... à ...')
    """
    q = question.lower()

    m = re.search(r"(?:du|de)\s+(\d{4}-\d{2}-\d{2})\s+(?:au|a|à)\s+(\d{4}-\d{2}-\d{2})", q)
    if m:
        return None, None, m.group(1), m.group(2)

    # Month in ISO form: YYYY-MM
    m = re.search(r"\b(\d{4}-\d{2})\b", q)
    month = m.group(1) if m else None

    # Month in French words or "mois 1"
    if not month:
        # Remove accents for easier matching but keep original q for year search.
        q_noacc = "".join(
            c for c in unicodedata.normalize("NFKD", q) if not unicodedata.combining(c)
        )
        month_map = {
            "janvier": 1,
            "fevrier": 2,
            "mars": 3,
            "avril": 4,
            "mai": 5,
            "juin": 6,
            "juillet": 7,
            "aout": 8,
            "septembre": 9,
            "octobre": 10,
            "novembre": 11,
            "decembre": 12,
        }

        # Examples: "janvier 2025", "en janvier 2025", "janvier en 2025"
        m_fr = re.search(
            r"\b(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)\b(?:\s+(20\d{2}))?",
            q_noacc,
        )
        y_any = None
        m_year = re.search(r"\b(20\d{2})\b", q_noacc)
        if m_year:
            y_any = m_year.group(1)
        if m_fr:
            mm = month_map.get(m_fr.group(1))
            yy = m_fr.group(2) or y_any
            if mm and yy:
                month = f"{int(yy):04d}-{mm:02d}"

        # Examples: "mois 1 2025", "mois 01 2025"
        if not month:
            m_num = re.search(r"\bmois\s*(\d{1,2})\s*(20\d{2})\b", q_noacc)
            if m_num:
                mm = int(m_num.group(1))
                yy = int(m_num.group(2))
                if 1 <= mm <= 12:
                    month = f"{yy:04d}-{mm:02d}"

    m = re.search(r"\b(20\d{2})\b", q)
    year = m.group(1) if m else None
    # Évite year + month redondants (ex. "2025-01" ne doit pas garder year=2025 en parallèle).
    if month and year and month.startswith(f"{year}-"):
        year = None

    return year, month, None, None


def question_has_explicit_period(question: str) -> bool:
    """
    True si la question borne une fenêtre temporelle (année, mois, plage, date ISO, ou preset texte).
    Utilisé pour éviter d'agréger tout l'historique quand l'utilisateur n'a pas précisé de période.
    """
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()
    year, month, start, end = _extract_year_month_range(q)
    if start and end:
        return True
    if month:
        return True
    if year:
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", q):
        return True
    if re.search(
        r"\b(7j|30j|ytd|mtd|aujourd'?hui|hier|cette semaine|ce mois|mois courant|ann[ée]e courante|"
        r"derniers?\s+jours?|last\s+7|last\s+30|year\s+to\s+date)\b",
        ql,
    ):
        return True
    if re.search(r"\bdepuis\s+(le\s+)?\d{4}-\d{2}-\d{2}\b", ql):
        return True
    if re.search(r"\bentre\s+le\s+\d{4}-\d{2}-\d{2}\b", ql):
        return True
    if _question_mentions_relative_period(ql):
        return True
    return False


def _question_mentions_relative_period(ql: str) -> bool:
    s = re.sub(r"\s+", " ", (ql or "").lower()).strip()
    for ch in ("\u2019", "\u2018", "`", "\u00b4"):
        s = s.replace(ch, "'")
    s = re.sub(r"\blan dernier\b", "l'an dernier", s)
    s = re.sub(r"\bl an dernier\b", "l'an dernier", s)
    return bool(
        re.search(
            r"\b(l'an dernier|l'année dernière|l année dernière|annee derniere|année dernière|année passée|"
            r"annee passee|dernière année|derniere annee|last year|cette année|annee en cours|année en cours|"
            r"cette annee|this year|récemment|recemment|derniers mois|derniers temps|recent)\b",
            s,
        )
    )


def kpi_period_span_from_question(question: str) -> str:
    """
    Fenêtre calendaire déduite de la question (plage du…au…, année 20xx, mois AAAA-MM, date ISO).
    Format pour l’agent : « YYYY-MM-DD..YYYY-MM-DD ». Vide si aucune borne date/mois/année exploitable.
    Les presets type « 7j » / « ce mois » ne sont pas résolus ici (période injectée côté UI).
    """
    q = (question or "").strip()
    if not q:
        return ""
    year, month, start, end = _extract_year_month_range(q)
    if start and end:
        return f"{start}..{end}"
    if month:
        y_str, m_str = month.split("-", 1)
        yi, mi = int(y_str), int(m_str)
        last = calendar.monthrange(yi, mi)[1]
        return f"{month}-01..{month}-{last:02d}"
    if year:
        return f"{year}-01-01..{year}-12-31"
    d = _extract_date(q)
    if d:
        return f"{d}..{d}"
    return ""


# Préfixe du message assistant persisté quand le pipeline renvoie pipeline:need_period.
NEED_PERIOD_ASSISTANT_PREFIX = "Pour ce KPI, il me manque une période"

# Indices qu'un message utilisateur est bien une demande KPI (évite « pourquoi » + « 2025 »).
_KPI_TOPIC_HINTS = (
    "navire",
    "navires",
    "arrivage",
    "arrivages",
    "tonnage",
    "demurrage",
    "démurrage",
    "accostage",
    "booking",
    "port",
    "gpl",
    "gaz",
    "production",
    "prod",
    "consommation",
    "conso",
    "oxyg",
    "carbone",
    "carbon",
    "élec",
    "elec",
    "electric",
    "td",
    "tr",
    "mtbf",
    "mttr",
    "rendement",
    "coulée",
    "coulee",
    "brame",
    "ferrailles",
    "ferraille",
    "disponibilité",
    "disponibilite",
    "dispo",
)


def list_kpi_catalog() -> List[Dict[str, str]]:
    """
    Canonical KPI prompts used to generate a "catalog" of SQL queries.
    Each item contains:
    - name: human-friendly KPI label
    - question: canonical prompt to feed `generate_sql`
    """
    profile = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if profile in {"sonasid", "shipping", "port"}:
        from backend.llm.sonasid_sql import list_sonasid_kpi_catalog

        return list_sonasid_kpi_catalog()
    return [
        # Production / brames
        {"name": "Production (total)", "question": "production en 2025"},
        {"name": "Production (par mois)", "question": "production par mois en 2025"},
        {"name": "Production (par jour)", "question": "production par jour en 2025-01"},
        {"name": "Poids brames (total)", "question": "poids des brames en 2025"},
        {"name": "Poids brames (par mois)", "question": "poids des brames par mois en 2025"},
        {"name": "Poids brames (épaisseur/jour)", "question": "poids des brames par epaisseur par jour en 2025-01"},
        {"name": "Poids brames (largeur/jour)", "question": "poids des brames par largeur par jour en 2025-01"},
        {"name": "Top 5 grades (poids brames)", "question": "poids des brames par grade top 5 en 2025"},
        {"name": "Top 5 largeurs (poids brames)", "question": "poids des brames par largeur top 5 en 2025"},
        {"name": "Top 5 épaisseurs (poids brames)", "question": "poids des brames par epaisseur top 5 en 2025"},
        {"name": "Nombre de brames", "question": "nombre de brames en 2025"},
        {"name": "Nombre de coulées", "question": "nombre de coulées en 2025"},
        # Consommations
        {"name": "Consommation électrique (total)", "question": "consommation électrique en 2025"},
        {"name": "Consommation électrique (par mois)", "question": "consommation électrique par mois en 2025"},
        {"name": "Consommation électrique (par jour)", "question": "consommation électrique par jour en 2025-02"},
        {"name": "Consommation oxygène (total)", "question": "consommation oxygène en 2025"},
        {"name": "Consommation oxygène (par mois)", "question": "consommation oxygène par mois en 2025"},
        {"name": "Consommation carbone (total)", "question": "consommation carbone en 2025"},
        {"name": "Consommation carbone (par mois)", "question": "consommation carbone par mois en 2025"},
        {"name": "Consommation GPL (total)", "question": "consommation gpl en 2025"},
        {"name": "Consommation GPL (par mois)", "question": "consommation gpl par mois en 2025"},
        # Ferrailles
        {"name": "Consommation ferrailles (total)", "question": "consommation ferrailles en 2025"},
        {"name": "Consommation ferrailles (catégorie/mois)", "question": "consommation par ferraille par mois en 2025"},
        {"name": "Top 5 catégories ferrailles", "question": "consommation par ferraille top 5 en 2025"},
        # Arrêts (EAF) / fiabilité
        {"name": "TD (taux de disponibilité) en %", "question": "td en 2025"},
        {"name": "TD par mois", "question": "td par mois en 2025"},
        {"name": "TR (temps requis) en %", "question": "tr en 2025"},
        {"name": "TR par mois", "question": "tr par mois en 2025"},
        {"name": "MTBF (secondes)", "question": "mtbf en 2025"},
        {"name": "MTBF par mois (secondes)", "question": "mtbf par mois en 2025"},
        {"name": "MTBF par semaine (secondes)", "question": "mtbf par semaine en 2025"},
        {"name": "MTBF par jour (secondes)", "question": "mtbf par jour en 2025-01"},
        {"name": "MTTR (secondes)", "question": "mttr en 2025"},
        {"name": "MTTR par mois (secondes)", "question": "mttr par mois en 2025"},
        {"name": "MTTR par semaine (secondes)", "question": "mttr par semaine en 2025"},
        {"name": "MTTR par jour (secondes)", "question": "mttr par jour en 2025-01"},
    ]


def assistant_memory_indicates_pipeline_need_period(content: str) -> bool:
    """Détecte le texte « il manque une période » même si encodage / espaces diffèrent légèrement."""
    raw = (content or "").strip()
    if not raw:
        return False
    # Réponses tabulaires JSON : ne pas confondre avec une colonne « période ».
    if raw.startswith("{") and '"__kind"' in raw and "kpi_table" in raw:
        return NEED_PERIOD_ASSISTANT_PREFIX.lower() in unicodedata.normalize("NFKC", raw).lower()
    norm = unicodedata.normalize("NFKC", raw).lower()
    if NEED_PERIOD_ASSISTANT_PREFIX.lower() in norm:
        return True
    return bool(re.search(r"manque\s+une\s+p[ée]riode", norm))


def _prior_user_looks_like_kpi_topic(text: str) -> bool:
    t = unicodedata.normalize("NFKC", (text or "").strip()).lower()
    if not t or len(t) > 160:
        return False
    noise = ("merci", "ok", "oui", "non", "pourquoi", "comment", "quand", "qui", "salut", "bonjour")
    if t in noise or any(t.startswith(w + " ") for w in noise):
        return False
    return any(h in t for h in _KPI_TOPIC_HINTS) or bool(re.search(r"\b(prod|conso|kpi)\b", t))


def is_period_only_followup_text(text: str) -> bool:
    """True si le message ne porte qu'une fenêtre temporelle (réponse courte après demande de période)."""
    s = (text or "").strip().lower()
    if not s:
        return False
    if re.match(r"^\d{4}$", s):
        return True
    if re.match(r"^\d{4}-\d{2}$", s):
        return True
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return True
    if re.match(
        r"^(?:du|de)\s+\d{4}-\d{2}-\d{2}\s+(?:au|a|à)\s+\d{4}-\d{2}-\d{2}$",
        s,
    ):
        return True
    if re.match(r"^(?:en|pour|sur)\s+\d{4}(?:-\d{2}(?:-\d{2})?)?$", s):
        return True
    if re.match(r"^(7j|30j|ytd|mtd)$", s):
        return True
    if re.match(
        r"^(ce mois|mois courant|cette semaine|aujourd'hui|aujourd’hui|hier|année courante|annee courante)$",
        s,
    ):
        return True
    return False


def is_same_kpi_followup_text(text: str) -> bool:
    """Relance du type « même chose pour 2026 », « pareil en 2026 », « idem »."""
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not s:
        return False
    if is_period_only_followup_text(s):
        return False
    if re.search(r"\b(meme|même|pareil|idem|identique|aussi)\b", s):
        if re.search(r"\b20\d{2}\b", s) or re.search(r"\b(pour|en|sur)\s+\d{4}", s):
            return True
        if re.search(r"\b(chose|question|analyse|demande|kpi|resume|résumé|recap)\b", s):
            return True
    if re.match(r"^(?:et|ou)\s+(?:pour|en|sur)\s+\d{4}", s):
        return True
    return False


def _last_kpi_user_question(prior_messages: Optional[List[Dict[str, Any]]]) -> str:
    from backend.security.access_control import looks_like_kpi_question

    msgs = prior_messages or []
    for i in range(len(msgs) - 1, -1, -1):
        if str(msgs[i].get("role", "")).strip() != "user":
            continue
        prev_u = str(msgs[i].get("content") or "").strip()
        if not prev_u:
            continue
        if looks_like_kpi_question(prev_u):
            return prev_u
        if len(prev_u) > 12 and not is_pure_greeting_short(prev_u):
            return prev_u
    return ""


def is_pure_greeting_short(text: str) -> bool:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    return bool(re.match(r"^(bonjour|salut|hello|coucou|bonsoir|merci|ok)\b", t))


def merge_kpi_followup_from_history(
    question: str,
    prior_messages: Optional[List[Dict[str, Any]]],
) -> str:
    """
    « Même chose pour 2026 » → reprend la dernière question KPI et change la période.
    """
    q = (question or "").strip()
    if not q or not is_same_kpi_followup_text(q):
        return q
    prev_u = _last_kpi_user_question(prior_messages)
    if not prev_u:
        return q
    ql = q.lower()
    m_year = re.search(r"\b(20\d{2})\b", ql)
    if m_year:
        new_y = m_year.group(1)
        if re.search(r"\b20\d{2}\b", prev_u):
            return re.sub(r"\b20\d{2}\b", new_y, prev_u)
        return f"{prev_u} {new_y}".strip()
    m_month = re.search(r"\b(20\d{2}-\d{2})\b", ql)
    if m_month:
        new_m = m_month.group(1)
        if re.search(r"\b20\d{2}-\d{2}\b", prev_u):
            return re.sub(r"\b20\d{2}-\d{2}\b", new_m, prev_u, count=1)
        return f"{prev_u} {new_m}".strip()
    return f"{prev_u} {q}".strip()


def merge_need_period_followup_from_history(
    question: str,
    prior_messages: Optional[List[Dict[str, Any]]],
) -> str:
    """
    Si le dernier message assistant était « il manque une période » et l'utilisateur envoie
    uniquement une période, fusionner avec la question utilisateur précédente.
    prior_messages : ordre chronologique (comme get_conversation_history), sans le tour courant.
    """
    q = (question or "").strip()
    if not q or not is_period_only_followup_text(q):
        return q
    msgs = prior_messages or []
    if not msgs:
        return q

    # 1) Dernier assistant qui ressemble à pipeline:need_period → question user juste avant.
    for i in range(len(msgs) - 1, -1, -1):
        if str(msgs[i].get("role", "")).strip() != "assistant":
            continue
        if not assistant_memory_indicates_pipeline_need_period(str(msgs[i].get("content") or "")):
            continue
        for j in range(i - 1, -1, -1):
            if str(msgs[j].get("role", "")).strip() == "user":
                prev_u = str(msgs[j].get("content") or "").strip()
                if prev_u:
                    return f"{prev_u} {q}".strip()
        break

    # 2) Dernier message = user KPI sans période, sans réponse assistant en base (persist en retard, etc.).
    last = msgs[-1]
    if str(last.get("role", "")).strip() == "user":
        prev_u = str(last.get("content") or "").strip()
        if (
            prev_u
            and not question_has_explicit_period(prev_u)
            and _prior_user_looks_like_kpi_topic(prev_u)
        ):
            return f"{prev_u} {q}".strip()

    return q




def generate_sql(question):
    q = normalize_kpi_question(question)
    
    # Try deterministic Sonasid rules first
    try:
        from backend.llm.sonasid_sql import try_sonasid_kpi_sql

        son = try_sonasid_kpi_sql(q)
        if son is not None:
            return son
    except Exception:
        pass

    # Try LLM-based SQL generation fallback
    try:
        from backend.llm.sonasid_open import is_sonasid_open_mode, is_sonasid_llm_available
        if is_sonasid_open_mode() and is_sonasid_llm_available():
            try:
                from backend.llm.llm_router import generate_sql_with_llm
                from backend.llm.sql_guard import validate_sonasid_select_sql

                llm_sql, _prov, _reason = generate_sql_with_llm(q)
                if llm_sql:
                    sql_only = llm_sql.strip()
                    if sql_only and sql_only.upper() != "SELECT 1":
                        ok, _ = validate_sonasid_select_sql(sql_only)
                        if ok:
                            return sql_only
            except Exception:
                pass
    except Exception:
        pass

    return "SELECT 1"


def extract_sql(text):
    return text.strip()
