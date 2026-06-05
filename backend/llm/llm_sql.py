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
        (r"\bpar\s+sem\b", "par semaine"),
        (r"\bpar\s+semiane\b", "par semaine"),
        (r"\bpar\s+moit\b", "par mois"),
        (r"\bpar\s+an\b", "par année"),
    ]
    for pat, rep in typo_pairs:
        q = re.sub(pat, rep, q, flags=re.IGNORECASE)

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


def _extract_grade(question_lower):
    words = question_lower.split()
    for i in range(len(words)):
        if words[i] == "grade" and i + 1 < len(words):
            candidate = re.sub(r"[^a-zA-Z0-9_]", "", words[i + 1]).upper()
            stop = {"TOP", "EN", "PAR", "DU", "DE", "AU", "A", "À", "MOIS", "AN", "ANNEE", "ANNÉE"}
            if not candidate or candidate in stop:
                return None
            return candidate
    return None


def _extract_date(question):
    match = re.search(r"\d{4}-\d{2}-\d{2}", question)
    return match.group(0) if match else None


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
    if _extract_date(q):
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
    return False


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


def _extract_top_n(question_lower: str) -> Optional[int]:
    # "top 5", "top5"
    m = re.search(r"\btop\s*(\d+)\b", question_lower)
    if m:
        return int(m.group(1))
    # "les 5 grades", "5 grades"
    m = re.search(r"\b(\d+)\s+grades?\b", question_lower)
    if m:
        return int(m.group(1))
    return None


def _time_conditions(field: str, date: Optional[str], year: Optional[str], month: Optional[str], start: Optional[str], end: Optional[str]):
    """
    Conditions robustes sur champs TEXT datetime.
    Priorité: range > date > month > year.
    """
    conds = []
    if start and end:
        conds.append(f"DATE(substr({field},1,10)) BETWEEN DATE('{start}') AND DATE('{end}')")
        return conds
    if date:
        conds.append(f"{field} LIKE '%{date}%'")
        return conds
    if month:
        conds.append(f"{field} LIKE '{month}%'")
        return conds
    if year:
        conds.append(f"{field} LIKE '{year}%'")
        return conds
    return conds


def _extract_period(question_lower):
    """Retourne (clé, _) pour: 'jour', 'semaine', 'mois', 'annee' ou None."""
    if "par jour" in question_lower or "par journee" in question_lower:
        return ("jour", None)
    if "par semaine" in question_lower:
        return ("semaine", None)
    if "par mois" in question_lower:
        return ("mois", None)
    if "par annee" in question_lower or "par an" in question_lower:
        return ("annee", None)
    return (None, None)


def _period_expr(period_key: Optional[str], field: str) -> Optional[str]:
    if not period_key:
        return None
    # On force une date SQLite valide; si invalide => NULL (évite le '1900')
    f = f"DATE(substr({field},1,10))"
    if period_key == "jour":
        return f
    if period_key == "semaine":
        return f"strftime('%Y-W%W', {f})"
    if period_key == "mois":
        return f"strftime('%Y-%m', {f})"
    if period_key == "annee":
        return f"strftime('%Y', {f})"
    return None


def _valid_date_condition(field: str) -> str:
    # Exclut dates/valeurs invalides (strftime/DATE -> NULL)
    return f"DATE(substr({field},1,10)) IS NOT NULL"


def _valid_recent_year_condition(field: str) -> str:
    # Exclut les dates '1900' et autres années anormales (attendu: 20xx)
    return f"substr({field},1,4) GLOB '20[0-9][0-9]'"


def _add_filters_eaf(query, grade, date):
    conds = []
    if grade:
        conds.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
    if date:
        conds.append(f"HEATDEPARTURE_ACT LIKE '%{date}%'")
    if conds:
        query += " WHERE " + " AND ".join(conds)
    return query


def _add_filters_lf(query, grade, date):
    conds = []
    if grade:
        conds.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
    if date:
        conds.append(f"HEATDEPARTURE_ACT LIKE '%{date}%'")
    if conds:
        query += " WHERE " + " AND ".join(conds)
    return query


def _where_eaf(grade: Optional[str], date: Optional[str], year: Optional[str], month: Optional[str], start: Optional[str], end: Optional[str]):
    conds = []
    if grade:
        conds.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
    conds += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start, end)
    return conds


def _where_lf(grade: Optional[str], date: Optional[str], year: Optional[str], month: Optional[str], start: Optional[str], end: Optional[str]):
    conds = []
    if grade:
        conds.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
    conds += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start, end)
    return conds


def _add_filters_arrêts(query, date):
    # Backward-compatible (jour exact)
    if date:
        query += f" WHERE (DELAYSTART LIKE '%{date}%' OR DELAYEND LIKE '%{date}%')"
    return query


def _add_filters_arrêts_range(query, date: Optional[str], year: Optional[str], month: Optional[str], start: Optional[str], end: Optional[str]):
    conds = []
    # On filtre sur DELAYSTART (plus stable pour dater l'arrêt)
    conds += _time_conditions("DELAYSTART", date, year, month, start, end)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    return query


def _resolve_period_start_end(date: Optional[str], year: Optional[str], month: Optional[str], start: Optional[str], end: Optional[str]):
    """
    Retourne (start_date_sql, end_date_sql) en SQL SQLite (DATE('YYYY-MM-DD')...).
    Priorité: range > date > month > year > None.
    """
    if start and end:
        return f"DATE('{start}')", f"DATE('{end}')"
    if date:
        return f"DATE('{date}')", f"DATE('{date}')"
    if month:
        # month: YYYY-MM
        start_sql = f"DATE('{month}-01')"
        end_sql = f"DATE('{month}-01','+1 month','-1 day')"
        return start_sql, end_sql
    if year:
        start_sql = f"DATE('{year}-01-01')"
        end_sql = f"DATE('{year}-12-31')"
        return start_sql, end_sql
    return None, None


def _open_time_seconds_expr(start_sql: Optional[str], end_sql: Optional[str]) -> str:
    """
    Temps d'ouverture en secondes:
    - si start/end sont fournis: (end+1 - start) * 86400
    - sinon: constante par défaut (30 jours)
    """
    if start_sql and end_sql:
        return f"((julianday({end_sql}, '+1 day') - julianday({start_sql})) * 86400)"
    return str(TEMPS_OUVERTURE_DEFAULT)


def _base_arrêts():
    return """
        SELECT
            SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes,
            SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
            COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
        FROM "EAF_Arrêts"
    """


def generate_sql(question):
    try:
        from backend.llm.sonasid_sql import try_sonasid_kpi_sql

        son = try_sonasid_kpi_sql(question)
        if son:
            return son
    except Exception:
        pass

    q = normalize_kpi_question(question)
    question_lower = q.lower()

    db_provider = (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()
    profile = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if db_provider in {"azure", "mssql", "sqlserver"} and profile in {"sonasid", "shipping", "port"}:
        open_llm = os.getenv("SONASID_OPEN_LLM", "true").strip().lower() in {"1", "true", "yes", "on"}
        if open_llm:
            try:
                from backend.llm.llm_router import is_llm_enabled, generate_sql_with_llm

                if is_llm_enabled():
                    llm_sql, _prov, _reason = generate_sql_with_llm(question)
                    if llm_sql and extract_sql(llm_sql).strip().upper() != "SELECT 1":
                        return llm_sql
            except Exception:
                pass
        return "SELECT 1"
    grade = _extract_grade(question_lower)
    date = _extract_date(q)
    year, month, start_date, end_date = _extract_year_month_range(q)
    top_n = _extract_top_n(question_lower)
    period_key, _period_unused = _extract_period(question_lower)

    def _tsql_where_range(field: str) -> str:
        """
        T-SQL WHERE clause for a datetime-ish field using the extracted period.
        Uses half-open ranges when possible.
        """
        if start_date and end_date:
            return f"WHERE {field} >= '{start_date}' AND {field} < DATEADD(day, 1, '{end_date}')"
        if date:
            # Day exact: [date, date+1)
            return f"WHERE {field} >= '{date}' AND {field} < DATEADD(day, 1, '{date}')"
        if month:
            return f"WHERE {field} >= '{month}-01' AND {field} < DATEADD(month, 1, '{month}-01')"
        if year:
            try:
                y = int(year)
            except Exception:
                y = 0
            if y:
                return f"WHERE {field} >= '{y:04d}-01-01' AND {field} < '{(y+1):04d}-01-01'"
        return ""

    def _tsql_scalar_range_bounds():
        """
        Compute (start_iso, end_exclusive_sql) for scalar KPIs in T-SQL.
        Returns (start_iso, end_excl_expr) where end_excl_expr is a T-SQL expression.
        """
        if start_date and end_date:
            return start_date, f"DATEADD(day, 1, CAST('{end_date}' AS datetime2))"
        if date:
            return date, f"DATEADD(day, 1, CAST('{date}' AS datetime2))"
        if month:
            # month: YYYY-MM
            m0 = f"{month}-01"
            return m0, f"DATEADD(month, 1, CAST('{m0}' AS datetime2))"
        if year:
            try:
                y = int(year)
            except Exception:
                y = 0
            if y:
                y0 = f"{y:04d}-01-01"
                return y0, f"CAST('{(y+1):04d}-01-01' AS datetime2)"
        return None, None

    def _tsql_open_seconds_scalar_expr() -> str:
        """
        Scalar opening time seconds for the extracted period, in T-SQL.
        Uses half-open [start, end) range.
        """
        start_iso, end_excl = _tsql_scalar_range_bounds()
        if start_iso and end_excl:
            return f"DATEDIFF(second, CAST('{start_iso}' AS datetime2), {end_excl}) * 1.0"
        return str(TEMPS_OUVERTURE_DEFAULT)

    def _tsql_arrêts_scalar(metric: str) -> str:
        """
        T-SQL scalar KPI on EAF_Arrêts for the extracted period.
        metric in {'TD','TR','MTBF','MTTR'}.
        Returns one row, one column (TD/TR in 0..1, MTBF/MTTR in seconds).
        """
        start_iso, end_excl = _tsql_scalar_range_bounds()
        where_sql = ""
        if start_iso and end_excl:
            where_sql = f"WHERE DELAYSTART >= '{start_iso}' AND DELAYSTART < {end_excl}"
        open_s = _tsql_open_seconds_scalar_expr()

        base = f"""
        WITH agg AS (
          SELECT
            SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes,
            SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
            COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
          FROM "EAF_Arrêts"
          {where_sql}
        )
        """

        if metric == "TD":
            return (
                base
                + f"""
                SELECT
                  CASE
                    WHEN ({open_s} - arrets_programmes) <= 0 THEN 0
                    WHEN (({open_s} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_s} - arrets_programmes)) > 1 THEN 1
                    WHEN (({open_s} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_s} - arrets_programmes)) < 0 THEN 0
                    ELSE ({open_s} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_s} - arrets_programmes)
                  END AS TD
                FROM agg
                """
            )
        if metric == "TR":
            return (
                base
                + f"""
                SELECT
                  CASE
                    WHEN {open_s} = 0 THEN 0
                    ELSE ({open_s} - arrets_programmes) * 1.0 / {open_s}
                  END AS TR
                FROM agg
                """
            )
        if metric == "MTBF":
            return (
                base
                + f"""
                SELECT
                  CASE
                    WHEN ({open_s} - arrets_programmes) <= 0 THEN 0
                    ELSE ({open_s} - arrets_programmes - arrets_non_programmes) * 1.0 / (nb_arrets_non_programmes + 1)
                  END AS MTBF_secondes
                FROM agg
                """
            )
        if metric == "MTTR":
            return (
                base
                + """
                SELECT
                  CASE
                    WHEN nb_arrets_non_programmes <= 0 THEN 0
                    ELSE arrets_non_programmes * 1.0 / nb_arrets_non_programmes
                  END AS MTTR_secondes
                FROM agg
                """
            )

        return base + "SELECT 0 AS value FROM agg"

    def _tsql_open_seconds_expr(period_key: str) -> str:
        """
        Opening time in seconds for each bucket in T-SQL, based on 'period' (yyyy-mm / yyyy / yyyy-mm-dd / yyyy-Www).
        We compute using DATEDIFF between bucket start and next bucket start.
        """
        if period_key == "jour":
            return "86400.0"
        if period_key == "semaine":
            return "(7.0 * 86400.0)"
        if period_key == "mois":
            return "DATEDIFF(second, CAST(period + '-01' AS date), DATEADD(month, 1, CAST(period + '-01' AS date)))"
        if period_key == "annee":
            return "DATEDIFF(second, CAST(period + '-01-01' AS date), DATEADD(year, 1, CAST(period + '-01-01' AS date)))"
        return str(TEMPS_OUVERTURE_DEFAULT)

    def _tsql_arrêts_series(*, metric: str, period_key: str) -> str:
        """
        Generate T-SQL series for KPIs computed from EAF_Arrêts:
        metric in {'TD','TR','MTBF','MTTR'}.
        Output columns: period, value.
        """
        where_sql = _tsql_where_range("DELAYSTART")
        if period_key == "jour":
            period_expr = "CONVERT(char(10), DELAYSTART, 23)"  # yyyy-mm-dd
        elif period_key == "semaine":
            # ISO-ish: yyyy-Www (week number). Good enough for grouping.
            period_expr = "CONCAT(DATEPART(year, DELAYSTART), '-W', RIGHT('0' + CAST(DATEPART(iso_week, DELAYSTART) AS varchar(2)), 2))"
        elif period_key == "mois":
            period_expr = "CONVERT(char(7), DELAYSTART, 126)"  # yyyy-mm
        elif period_key == "annee":
            period_expr = "CONVERT(char(4), DELAYSTART, 126)"  # yyyy
        else:
            period_expr = "CONVERT(char(7), DELAYSTART, 126)"

        open_s_expr = _tsql_open_seconds_expr(period_key)

        # Aggregate base stoppages
        base_select = f"""
            WITH agg AS (
              SELECT
                {period_expr} AS period,
                SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes,
                SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
                COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
              FROM "EAF_Arrêts"
              {where_sql}
              GROUP BY {period_expr}
            )
        """

        if metric == "TD":
            # TD in percent
            return (
                base_select
                + f"""
                SELECT
                  period,
                  CASE
                    WHEN ({open_s_expr} - arrets_programmes) <= 0 THEN 0
                    WHEN (({open_s_expr} - arrets_programmes - arrets_non_programmes) * 100.0 / ({open_s_expr} - arrets_programmes)) > 100 THEN 100
                    WHEN (({open_s_expr} - arrets_programmes - arrets_non_programmes) * 100.0 / ({open_s_expr} - arrets_programmes)) < 0 THEN 0
                    ELSE ({open_s_expr} - arrets_programmes - arrets_non_programmes) * 100.0 / ({open_s_expr} - arrets_programmes)
                  END AS value
                FROM agg
                WHERE period IS NOT NULL
                ORDER BY period
                """
            )

        if metric == "TR":
            # TR in percent
            return (
                base_select
                + f"""
                SELECT
                  period,
                  CASE
                    WHEN {open_s_expr} = 0 THEN 0
                    ELSE ({open_s_expr} - arrets_programmes) * 100.0 / {open_s_expr}
                  END AS value
                FROM agg
                WHERE period IS NOT NULL
                ORDER BY period
                """
            )

        if metric == "MTBF":
            # MTBF seconds: (temps_requis - arrets_non_programmes) / (nb_non_prog + 1)
            return (
                base_select
                + f"""
                SELECT
                  period,
                  CASE
                    WHEN ({open_s_expr} - arrets_programmes) <= 0 THEN 0
                    ELSE (({open_s_expr} - arrets_programmes - arrets_non_programmes) * 1.0 / (nb_arrets_non_programmes + 1))
                  END AS value
                FROM agg
                WHERE period IS NOT NULL
                ORDER BY period
                """
            )

        if metric == "MTTR":
            # MTTR seconds: arrets_non_programmes / nb_non_prog
            return (
                base_select
                + """
                SELECT
                  period,
                  CASE
                    WHEN nb_arrets_non_programmes <= 0 THEN 0
                    ELSE (arrets_non_programmes * 1.0 / nb_arrets_non_programmes)
                  END AS value
                FROM agg
                WHERE period IS NOT NULL
                ORDER BY period
                """
            )

        return base_select + "SELECT NULL AS period, 0 AS value WHERE 1=0"

    # =====================================================
    # CONSOMMATIONS (EAF + LF ou EAF seul)
    # =====================================================

    # Conso par ferraille / catégorie (avec filtres + séries + topN)
    # Accept "conso ferrailles" and "consommation ferrailles".
    if ("conso" in question_lower or "consomm" in question_lower) and ("ferraille" in question_lower or "ferrailles" in question_lower):
        where = []
        if grade:
            where.append(f"TRIM(CSO_GRADE) LIKE '%{grade}%'")
        where += _time_conditions("CSO_DATE", date, year, month, start_date, end_date)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        limit = f" LIMIT {top_n}" if top_n else ""

        # Série temporelle par catégorie
        if period_key:
            period_col = _period_expr(period_key, "CSO_DATE")
            # Nettoyage dates invalides
            where_ts = [_valid_date_condition("CSO_DATE"), _valid_recent_year_condition("CSO_DATE")] + where
            w_ts = " WHERE " + " AND ".join(where_ts)
            return f"""
            SELECT {period_col} AS period, CAT_Nom AS categorie, SUM(CSD_POIDS) AS poids
            FROM "01_PAF"
            {w_ts}
            GROUP BY period, categorie
            ORDER BY period, poids DESC
            """

        return f"""
        SELECT CAT_Nom AS categorie, SUM(CSD_POIDS) AS poids
        FROM "01_PAF"
        {w}
        GROUP BY categorie
        ORDER BY poids DESC
        {limit}
        """

    # Poids ferrailles (filtrable par grade + temps)
    if "poids" in question_lower and ("ferraille" in question_lower or "ferrailles" in question_lower):
        where = []
        if grade:
            where.append(f"TRIM(CSO_GRADE) LIKE '%{grade}%'")
        where += _time_conditions("CSO_DATE", date, year, month, start_date, end_date)
        where_sql = (" WHERE " + " AND ".join(where)) if where else ""
        return f'SELECT SUM(CSD_POIDS) FROM "01_PAF"{where_sql}'

    # Poids brames par largeur/épaisseur (avec filtres + séries + topN)
    if ("poids" in question_lower or "poids des brames" in question_lower) and ("brame" in question_lower or "brames" in question_lower) and (
        "largeur" in question_lower or "épaisseur" in question_lower or "epaisseur" in question_lower
    ):
        where_time = [_valid_date_condition("CUT_TIME"), _valid_recent_year_condition("CUT_TIME")] + _time_conditions(
            "CUT_TIME", date, year, month, start_date, end_date
        )
        wb = (" WHERE " + " AND ".join(where_time)) if where_time else ""
        limit = f" LIMIT {top_n}" if top_n else ""

        # Filtre grade via la coulée si grade fourni
        join = ""
        grade_filter = ""
        if grade:
            join = 'JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID'
            grade_filter = f" AND TRIM(c.GRADE_CODE) LIKE '%{grade}%'"

        by_largeur_only = "largeur" in question_lower and ("épaisseur" not in question_lower and "epaisseur" not in question_lower)
        by_epaisseur_only = ("épaisseur" in question_lower or "epaisseur" in question_lower) and ("largeur" not in question_lower)

        if period_key:
            period_col = _period_expr(period_key, "b.CUT_TIME")
            if by_largeur_only:
                return f"""
                SELECT {period_col} AS period,
                       b.NOMINAL_WIDTH_HEAD AS largeur,
                       SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
                FROM "05_CCM_Brame" b
                {join}
                {wb}
                {grade_filter}
                GROUP BY period, largeur
                ORDER BY period, poids_brames DESC
                """
            if by_epaisseur_only:
                return f"""
                SELECT {period_col} AS period,
                       b.NOMINAL_THICKNESS AS epaisseur,
                       SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
                FROM "05_CCM_Brame" b
                {join}
                {wb}
                {grade_filter}
                GROUP BY period, epaisseur
                ORDER BY period, poids_brames DESC
                """
            return f"""
            SELECT {period_col} AS period,
                   b.NOMINAL_WIDTH_HEAD AS largeur,
                   b.NOMINAL_THICKNESS AS epaisseur,
                   SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
            FROM "05_CCM_Brame" b
            {join}
            {wb}
            {grade_filter}
            GROUP BY period, largeur, epaisseur
            ORDER BY period, poids_brames DESC
            """

        if by_largeur_only:
            return f"""
            SELECT b.NOMINAL_WIDTH_HEAD AS largeur,
                   SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
            FROM "05_CCM_Brame" b
            {join}
            {wb}
            {grade_filter}
            GROUP BY largeur
            ORDER BY poids_brames DESC
            {limit}
            """

        if by_epaisseur_only:
            return f"""
            SELECT b.NOMINAL_THICKNESS AS epaisseur,
                   SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
            FROM "05_CCM_Brame" b
            {join}
            {wb}
            {grade_filter}
            GROUP BY epaisseur
            ORDER BY poids_brames DESC
            {limit}
            """

        return f"""
        SELECT b.NOMINAL_WIDTH_HEAD AS largeur,
               b.NOMINAL_THICKNESS AS epaisseur,
               SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
        FROM "05_CCM_Brame" b
        {join}
        {wb}
        {grade_filter}
        GROUP BY largeur, epaisseur
        ORDER BY poids_brames DESC
        {limit}
        """

    # Production par largeur/épaisseur (on utilise les brames CCM : poids des pièces par dimension)
    # Remarque : le jeu de données ne garantit pas un champ "production" dimensionné ailleurs que via les brames.
    if "production" in question_lower and (
        "largeur" in question_lower or "épaisseur" in question_lower or "epaisseur" in question_lower
    ):
        where_time = [_valid_date_condition("CUT_TIME"), _valid_recent_year_condition("CUT_TIME")] + _time_conditions(
            "CUT_TIME", date, year, month, start_date, end_date
        )
        wb = (" WHERE " + " AND ".join(where_time)) if where_time else ""
        limit = f" LIMIT {top_n}" if top_n else ""

        join = ""
        grade_filter = ""
        if grade:
            join = 'JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID'
            grade_filter = f" AND TRIM(c.GRADE_CODE) LIKE '%{grade}%'"

        by_largeur_only = "largeur" in question_lower and ("épaisseur" not in question_lower and "epaisseur" not in question_lower)
        by_epaisseur_only = ("épaisseur" in question_lower or "epaisseur" in question_lower) and ("largeur" not in question_lower)

        if by_largeur_only:
            return f"""
            SELECT b.NOMINAL_WIDTH_HEAD AS largeur,
                   SUM(b.PIECE_WEIGHT_MEAS) AS production
            FROM "05_CCM_Brame" b
            {join}
            {wb}
            {grade_filter}
            GROUP BY largeur
            ORDER BY production DESC
            {limit}
            """

        if by_epaisseur_only:
            return f"""
            SELECT b.NOMINAL_THICKNESS AS epaisseur,
                   SUM(b.PIECE_WEIGHT_MEAS) AS production
            FROM "05_CCM_Brame" b
            {join}
            {wb}
            {grade_filter}
            GROUP BY epaisseur
            ORDER BY production DESC
            {limit}
            """

        return f"""
        SELECT b.NOMINAL_WIDTH_HEAD AS largeur,
               b.NOMINAL_THICKNESS AS epaisseur,
               SUM(b.PIECE_WEIGHT_MEAS) AS production
        FROM "05_CCM_Brame" b
        {join}
        {wb}
        {grade_filter}
        GROUP BY largeur, epaisseur
        ORDER BY production DESC
        {limit}
        """

    # Agent can paraphrase "consommation" as "les plus consommateurs" etc.
    conso_base = ("consomm" in question_lower) or ("conso" in question_lower)
    conso_elec = conso_base and ("elec" in question_lower or "électrique" in question_lower or "electricite" in question_lower or "électricité" in question_lower)
    conso_oxygene = conso_base and ("oxygène" in question_lower or "oxygen" in question_lower or "oxygene" in question_lower)
    conso_carbon = conso_base and ("carbon" in question_lower or "carbone" in question_lower)
    conso_gpl = conso_base and ("gpl" in question_lower or "gaz" in question_lower)

    if conso_elec:
        # time-series
        if period_key:
            period_eaf = _period_expr(period_key, "HEATDEPARTURE_ACT")
            period_lf = _period_expr(period_key, "HEATDEPARTURE_ACT")
            where_eaf = _where_eaf(grade, date, year, month, start_date, end_date)
            where_lf = _where_lf(grade, date, year, month, start_date, end_date)
            where_eaf.insert(0, _valid_recent_year_condition("HEATDEPARTURE_ACT"))
            where_eaf.insert(0, _valid_date_condition("HEATDEPARTURE_ACT"))
            where_lf.insert(0, _valid_recent_year_condition("HEATDEPARTURE_ACT"))
            where_lf.insert(0, _valid_date_condition("HEATDEPARTURE_ACT"))
            we = (" WHERE " + " AND ".join(where_eaf)) if where_eaf else ""
            wl = (" WHERE " + " AND ".join(where_lf)) if where_lf else ""
            return f"""
            WITH all_conso AS (
              SELECT {period_eaf} AS period, TOTAL_ELEC_EGY AS val
              FROM "02_EAF"
              {we}
              UNION ALL
              SELECT {period_lf} AS period, ELEC_CONS_TOTAL AS val
              FROM "03_LF"
              {wl}
            )
            SELECT period, SUM(val) AS conso_elec
            FROM all_conso
            GROUP BY period
            ORDER BY period
            """

        # par grade
        if "par grade" in question_lower or (("grade" in question_lower or "grades" in question_lower) and (top_n or "top" in question_lower)):
            where_eaf = _where_eaf(grade, date, year, month, start_date, end_date)
            where_lf = _where_lf(grade, date, year, month, start_date, end_date)
            we = (" WHERE " + " AND ".join(where_eaf)) if where_eaf else ""
            wl = (" WHERE " + " AND ".join(where_lf)) if where_lf else ""
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            WITH all_conso AS (
              SELECT TRIM(STEELGRADECODE_ACT) AS grade, TOTAL_ELEC_EGY AS val
              FROM "02_EAF"
              {we}
              UNION ALL
              SELECT TRIM(STEELGRADECODE_ACT) AS grade, ELEC_CONS_TOTAL AS val
              FROM "03_LF"
              {wl}
            )
            SELECT grade, SUM(val) AS conso_elec
            FROM all_conso
            GROUP BY grade
            ORDER BY conso_elec DESC
            {limit}
            """

        # scalaire (compat pipeline dict)
        eaf_q = "SELECT SUM(TOTAL_ELEC_EGY) FROM \"02_EAF\""
        lf_q = "SELECT SUM(ELEC_CONS_TOTAL) FROM \"03_LF\""
        where_eaf = _where_eaf(grade, date, year, month, start_date, end_date)
        where_lf = _where_lf(grade, date, year, month, start_date, end_date)
        if where_eaf:
            eaf_q += " WHERE " + " AND ".join(where_eaf)
        if where_lf:
            lf_q += " WHERE " + " AND ".join(where_lf)
        return {"type": "conso_elec", "eaf": eaf_q, "lf": lf_q}

    if conso_oxygene:
        where = _where_eaf(grade, date, year, month, start_date, end_date)
        w = (" WHERE " + " AND ".join(where)) if where else ""

        if period_key:
            period_col = _period_expr(period_key, "HEATDEPARTURE_ACT")
            where = [_valid_recent_year_condition("HEATDEPARTURE_ACT"), _valid_date_condition("HEATDEPARTURE_ACT")] + where
            w = " WHERE " + " AND ".join(where)
            return f"""
            SELECT {period_col} AS period, SUM(BURNER_TOTALOXY) AS conso_oxygene
            FROM "02_EAF"
            {w}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower or (("grade" in question_lower or "grades" in question_lower) and (top_n or "top" in question_lower)):
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(STEELGRADECODE_ACT) AS grade, SUM(BURNER_TOTALOXY) AS conso_oxygene
            FROM "02_EAF"
            {w}
            GROUP BY grade
            ORDER BY conso_oxygene DESC
            {limit}
            """

        eaf_q = f"SELECT SUM(BURNER_TOTALOXY) FROM \"02_EAF\"{w}"
        return {"type": "conso_oxygene", "eaf": eaf_q, "lf": "SELECT 0"}

    if conso_carbon:
        where = _where_eaf(grade, date, year, month, start_date, end_date)
        w = (" WHERE " + " AND ".join(where)) if where else ""

        if period_key:
            period_col = _period_expr(period_key, "HEATDEPARTURE_ACT")
            where = [_valid_recent_year_condition("HEATDEPARTURE_ACT"), _valid_date_condition("HEATDEPARTURE_ACT")] + where
            w = " WHERE " + " AND ".join(where)
            return f"""
            SELECT {period_col} AS period, SUM(INJ_CARBON) AS conso_carbone
            FROM "02_EAF"
            {w}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower or (("grade" in question_lower or "grades" in question_lower) and (top_n or "top" in question_lower)):
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(STEELGRADECODE_ACT) AS grade, SUM(INJ_CARBON) AS conso_carbone
            FROM "02_EAF"
            {w}
            GROUP BY grade
            ORDER BY conso_carbone DESC
            {limit}
            """

        eaf_q = f"SELECT SUM(INJ_CARBON) FROM \"02_EAF\"{w}"
        return {"type": "conso_carbon", "eaf": eaf_q, "lf": "SELECT 0"}

    if conso_gpl:
        where = _where_eaf(grade, date, year, month, start_date, end_date)
        w = (" WHERE " + " AND ".join(where)) if where else ""

        if period_key:
            period_col = _period_expr(period_key, "HEATDEPARTURE_ACT")
            where = [_valid_recent_year_condition("HEATDEPARTURE_ACT"), _valid_date_condition("HEATDEPARTURE_ACT")] + where
            w = " WHERE " + " AND ".join(where)
            return f"""
            SELECT {period_col} AS period, SUM(BURNER_TOTALGAS) AS conso_gpl
            FROM "02_EAF"
            {w}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower or (("grade" in question_lower or "grades" in question_lower) and (top_n or "top" in question_lower)):
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(STEELGRADECODE_ACT) AS grade, SUM(BURNER_TOTALGAS) AS conso_gpl
            FROM "02_EAF"
            {w}
            GROUP BY grade
            ORDER BY conso_gpl DESC
            {limit}
            """

        eaf_q = f"SELECT SUM(BURNER_TOTALGAS) FROM \"02_EAF\"{w}"
        return {"type": "conso_gpl", "eaf": eaf_q, "lf": "SELECT 0"}

    # Consommation électrique (uniquement si l'utilisateur l'a demandé explicitement).
    if "consommation" in question_lower and re.search(r"\b(élec|elec|électrique|electricite|électricité|energie elect)\b", question_lower):
        eaf_q = "SELECT SUM(TOTAL_ELEC_EGY) FROM \"02_EAF\""
        lf_q = "SELECT SUM(ELEC_CONS_TOTAL) FROM \"03_LF\""
        where_eaf = _where_eaf(grade, date, year, month, start_date, end_date)
        where_lf = _where_lf(grade, date, year, month, start_date, end_date)
        if where_eaf:
            eaf_q += " WHERE " + " AND ".join(where_eaf)
        if where_lf:
            lf_q += " WHERE " + " AND ".join(where_lf)
        return {"type": "conso_elec", "eaf": eaf_q, "lf": lf_q}

    # Consommation sans type (électricité / oxygène / GPL / carbone / ferrailles) → clarification.
    if "consommation" in question_lower or re.search(r"\bconso\b", question_lower):
        return {"type": "need_conso_type"}

    # =====================================================
    # TD : Taux de Disponibilité
    # TD [%] = (Temps Requis - Somme des arrêts non programmés) / Temps Requis
    # =====================================================
    if (
        "disponibilite" in question_lower
        or "disponibilité" in question_lower
        or bool(re.search(r"(^|\s)td(\s|$|[?.!,])", question_lower))
    ):
        # Série temporelle
        period_key, _ = _extract_period(question_lower)
        # Azure SQL: generate T-SQL directly for series (avoid SQLite-specific DATE/strftime/julianday/substr).
        if db_provider in {"azure", "mssql", "sqlserver"} and period_key:
            return _tsql_arrêts_series(metric="TD", period_key=period_key)
        if db_provider in {"azure", "mssql", "sqlserver"} and not period_key:
            return _tsql_arrêts_scalar(metric="TD")
        if period_key:
            period_col = _period_expr(period_key, "DELAYSTART")
            # Nettoyage dates invalides + filtre période demandé
            where = [_valid_date_condition("DELAYSTART"), _valid_recent_year_condition("DELAYSTART")]
            where += _time_conditions("DELAYSTART", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""

            # Temps d'ouverture par bucket
            if period_key == "jour":
                open_expr = "86400.0"
            elif period_key == "semaine":
                open_expr = f"(7.0 * 86400.0)"
            elif period_key == "mois":
                open_expr = (
                    f"((julianday(date({period_col} || '-01','+1 month')) - julianday(date({period_col} || '-01'))) * 86400.0)"
                )
            elif period_key == "annee":
                open_expr = (
                    f"((julianday(date({period_col} || '-01-01','+1 year')) - julianday(date({period_col} || '-01-01'))) * 86400.0)"
                )
            else:
                open_expr = str(TEMPS_OUVERTURE_DEFAULT)

            return f"""
            WITH agg AS (
              SELECT
                {period_col} AS period,
                SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes,
                SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
                COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
              FROM "EAF_Arrêts"
              {where_sql}
              GROUP BY period
            )
            SELECT
              period,
              CASE
                WHEN ({open_expr} - arrets_programmes) <= 0 THEN 0
                WHEN (({open_expr} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_expr} - arrets_programmes)) > 1 THEN 1
                WHEN (({open_expr} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_expr} - arrets_programmes)) < 0 THEN 0
                ELSE ({open_expr} - arrets_programmes - arrets_non_programmes) * 1.0 / ({open_expr} - arrets_programmes)
              END AS TD
            FROM agg
            WHERE period IS NOT NULL
            ORDER BY period
            """

        arr_query = _base_arrêts()
        arr_query = _add_filters_arrêts_range(arr_query, date, year, month, start_date, end_date)
        start_sql, end_sql = _resolve_period_start_end(date, year, month, start_date, end_date)
        temps_ouverture_expr = _open_time_seconds_expr(start_sql, end_sql)
        return f"""
        SELECT 
            CASE 
                WHEN temps_requis = 0 THEN 0
                WHEN ((temps_requis - arrets_non_programmes) * 1.0 / temps_requis) > 1 THEN 1
                WHEN ((temps_requis - arrets_non_programmes) * 1.0 / temps_requis) < 0 THEN 0
                ELSE (temps_requis - arrets_non_programmes) * 1.0 / temps_requis
            END AS TD
        FROM (
            SELECT
                ({temps_ouverture_expr} - arrets_programmes) AS temps_requis,
                arrets_non_programmes
            FROM ({arr_query})
        )
        """

    # =====================================================
    # TR : Temps Requis
    # TR [%] = (Temps d'ouverture - Arrêts programmés) / Temps d'ouverture
    # =====================================================
    if (
        "temps requis" in question_lower
        or bool(re.search(r"(^|\s)tr(\s|$|[?.!,])", question_lower))
    ):
        # Série temporelle
        period_key, _ = _extract_period(question_lower)
        if db_provider in {"azure", "mssql", "sqlserver"} and period_key:
            return _tsql_arrêts_series(metric="TR", period_key=period_key)
        if db_provider in {"azure", "mssql", "sqlserver"} and not period_key:
            return _tsql_arrêts_scalar(metric="TR")
        if period_key:
            period_col = _period_expr(period_key, "DELAYSTART")
            where = [_valid_date_condition("DELAYSTART"), _valid_recent_year_condition("DELAYSTART")]
            where += _time_conditions("DELAYSTART", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""

            if period_key == "jour":
                open_expr = "86400.0"
            elif period_key == "semaine":
                open_expr = f"(7.0 * 86400.0)"
            elif period_key == "mois":
                open_expr = (
                    f"((julianday(date({period_col} || '-01','+1 month')) - julianday(date({period_col} || '-01'))) * 86400.0)"
                )
            elif period_key == "annee":
                open_expr = (
                    f"((julianday(date({period_col} || '-01-01','+1 year')) - julianday(date({period_col} || '-01-01'))) * 86400.0)"
                )
            else:
                open_expr = str(TEMPS_OUVERTURE_DEFAULT)

            return f"""
            WITH agg AS (
              SELECT
                {period_col} AS period,
                SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes
              FROM "EAF_Arrêts"
              {where_sql}
              GROUP BY period
            )
            SELECT
              period,
              CASE WHEN {open_expr} = 0 THEN 0
                   ELSE ({open_expr} - arrets_programmes) * 100.0 / {open_expr}
              END AS TR
            FROM agg
            WHERE period IS NOT NULL
            ORDER BY period
            """

        arr_query = _base_arrêts()
        arr_query = _add_filters_arrêts_range(arr_query, date, year, month, start_date, end_date)
        start_sql, end_sql = _resolve_period_start_end(date, year, month, start_date, end_date)
        temps_ouverture_expr = _open_time_seconds_expr(start_sql, end_sql)
        return f"""
        SELECT 
            CASE WHEN {temps_ouverture_expr} = 0 THEN 0
                 ELSE ({temps_ouverture_expr} - arrets_programmes) * 100.0 / {temps_ouverture_expr}
            END AS TR
        FROM ({arr_query})
        """

    # =====================================================
    # MTBF : (Temps Requis - Somme arrêts non prog) / (Nombre arrêts + 1)
    # =====================================================
    if "mtbf" in question_lower:
        period_key, _ = _extract_period(question_lower)
        if db_provider in {"azure", "mssql", "sqlserver"} and period_key:
            return _tsql_arrêts_series(metric="MTBF", period_key=period_key)
        if db_provider in {"azure", "mssql", "sqlserver"} and not period_key:
            return _tsql_arrêts_scalar(metric="MTBF")
        if period_key:
            period_col = _period_expr(period_key, "DELAYSTART")
            where = [_valid_date_condition("DELAYSTART"), _valid_recent_year_condition("DELAYSTART")]
            where += _time_conditions("DELAYSTART", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""

            if period_key == "jour":
                open_expr = "86400.0"
            elif period_key == "semaine":
                open_expr = f"(7.0 * 86400.0)"
            elif period_key == "mois":
                open_expr = (
                    f"((julianday(date({period_col} || '-01','+1 month')) - julianday(date({period_col} || '-01'))) * 86400.0)"
                )
            elif period_key == "annee":
                open_expr = (
                    f"((julianday(date({period_col} || '-01-01','+1 year')) - julianday(date({period_col} || '-01-01'))) * 86400.0)"
                )
            else:
                open_expr = str(TEMPS_OUVERTURE_DEFAULT)

            return f"""
            WITH agg AS (
              SELECT
                {period_col} AS period,
                SUM(CASE WHEN LOWER(SECTIONNAME) LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_programmes,
                SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
                COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
              FROM "EAF_Arrêts"
              {where_sql}
              GROUP BY period
            )
            SELECT
              period,
              CASE WHEN (nb_arrets_non_programmes + 1) = 0 THEN 0
                   ELSE ({open_expr} - arrets_programmes - arrets_non_programmes) * 1.0
                        / (nb_arrets_non_programmes + 1)
              END AS MTBF
            FROM agg
            WHERE period IS NOT NULL
            ORDER BY period
            """

        arr_query = _base_arrêts()
        arr_query = _add_filters_arrêts_range(arr_query, date, year, month, start_date, end_date)
        start_sql, end_sql = _resolve_period_start_end(date, year, month, start_date, end_date)
        temps_ouverture_expr = _open_time_seconds_expr(start_sql, end_sql)
        return f"""
        SELECT 
            CASE WHEN (nb_arrets_non_programmes + 1) = 0 THEN 0
                 ELSE ({temps_ouverture_expr} - arrets_programmes - arrets_non_programmes) * 1.0 
                      / (nb_arrets_non_programmes + 1)
            END AS MTBF
        FROM ({arr_query})
        """

    # =====================================================
    # MTTR : Somme arrêts non prog / Nombre arrêts non prog
    # =====================================================
    if "mttr" in question_lower:
        period_key, _ = _extract_period(question_lower)
        if db_provider in {"azure", "mssql", "sqlserver"} and period_key:
            return _tsql_arrêts_series(metric="MTTR", period_key=period_key)
        if db_provider in {"azure", "mssql", "sqlserver"} and not period_key:
            return _tsql_arrêts_scalar(metric="MTTR")
        if period_key:
            period_col = _period_expr(period_key, "DELAYSTART")
            where = [_valid_date_condition("DELAYSTART"), _valid_recent_year_condition("DELAYSTART")]
            where += _time_conditions("DELAYSTART", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""

            return f"""
            WITH agg AS (
              SELECT
                {period_col} AS period,
                SUM(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN DURATION ELSE 0 END) AS arrets_non_programmes,
                COUNT(CASE WHEN LOWER(SECTIONNAME) NOT LIKE '%program%' THEN 1 END) AS nb_arrets_non_programmes
              FROM "EAF_Arrêts"
              {where_sql}
              GROUP BY period
            )
            SELECT
              period,
              CASE WHEN nb_arrets_non_programmes = 0 THEN 0
                   ELSE arrets_non_programmes * 1.0 / nb_arrets_non_programmes
              END AS MTTR
            FROM agg
            WHERE period IS NOT NULL
            ORDER BY period
            """

        arr_query = _base_arrêts()
        arr_query = _add_filters_arrêts_range(arr_query, date, year, month, start_date, end_date)
        return f"""
        SELECT 
            CASE WHEN nb_arrets_non_programmes = 0 THEN 0
                 ELSE arrets_non_programmes * 1.0 / nb_arrets_non_programmes
            END AS MTTR
        FROM ({arr_query})
        """

    # =====================================================
    # RENDEMENT : % Poids Brames / Poids Ferrailles
    # =====================================================
    if "rendement" in question_lower or "r [%]" in question_lower:
        # Conversion vers une base commune (kg) pour le ratio.
        # Données DATA-ACIERIE : CSD_POIDS (PAF) en tonnes, PIECE_WEIGHT_MEAS (brames) en kg.
        # Sans ça, le dénominateur est ~1000× trop petit et le % explose (ex. > 80 000 %).
        scrap_unit = os.getenv("SCRAP_UNIT", "t").strip().lower()  # kg | t
        slab_unit = os.getenv("SLAB_UNIT", "kg").strip().lower()  # kg | t
        scrap_factor = 1000.0 if scrap_unit in {"t", "tonne", "tonnes"} else 1.0
        slab_factor = 1000.0 if slab_unit in {"t", "tonne", "tonnes"} else 1.0

        # Rendement filtrable (temps + grade)
        where_paf = []
        if grade:
            where_paf.append(f"TRIM(CSO_GRADE) LIKE '%{grade}%'")
        where_paf += _time_conditions("CSO_DATE", date, year, month, start_date, end_date)
        wp = (" WHERE " + " AND ".join(where_paf)) if where_paf else ""

        where_brame = _time_conditions("b.CUT_TIME", date, year, month, start_date, end_date)
        wb = (" WHERE " + " AND ".join(where_brame)) if where_brame else ""

        # Si grade demandé, on filtre les brames via la coulée (GRADE_CODE)
        grade_join_filter = f"AND TRIM(c.GRADE_CODE) LIKE '%{grade}%'" if grade else ""

        # Série temporelle (par jour / semaine / mois / année)
        if period_key:
            period_b = _period_expr(period_key, "b.CUT_TIME")
            period_p = _period_expr(period_key, "CSO_DATE")
            return f"""
            WITH
            br AS (
              SELECT
                {period_b} AS period,
                COALESCE(SUM(b.PIECE_WEIGHT_MEAS), 0) * {slab_factor} AS poids_brames
              FROM "05_CCM_Brame" b
              JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID
              {wb}
              {grade_join_filter}
              GROUP BY {period_b}
            ),
            sc AS (
              SELECT
                {period_p} AS period,
                COALESCE(SUM(CSD_POIDS), 0) * {scrap_factor} AS poids_ferrailles
              FROM "01_PAF"
              {wp}
              GROUP BY {period_p}
            ),
            p AS (
              SELECT period FROM br
              UNION
              SELECT period FROM sc
            )
            SELECT
              p.period,
              CASE WHEN COALESCE(sc.poids_ferrailles, 0) = 0 THEN 0
                   ELSE 100.0 * COALESCE(br.poids_brames, 0) / COALESCE(sc.poids_ferrailles, 0)
              END AS Rendement
            FROM p
            LEFT JOIN br ON br.period = p.period
            LEFT JOIN sc ON sc.period = p.period
            WHERE p.period IS NOT NULL
            ORDER BY p.period
            """

        # Scalaire (sans granularité)
        return f"""
        SELECT 
            CASE WHEN poids_ferrailles = 0 THEN 0
                 ELSE 100.0 * poids_brames / poids_ferrailles
            END AS Rendement
        FROM (
            SELECT 
                (
                  SELECT COALESCE(SUM(b.PIECE_WEIGHT_MEAS), 0)
                  FROM "05_CCM_Brame" b
                  JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID
                  {wb}
                  {grade_join_filter}
                ) * {slab_factor} AS poids_brames,
                (
                  SELECT COALESCE(SUM(CSD_POIDS), 0)
                  FROM "01_PAF"
                  {wp}
                ) * {scrap_factor} AS poids_ferrailles
        )
        """

    # =====================================================
    # NOMBRE COULÉES / BRAMES / POIDS BRAMES
    # =====================================================
    if "coulée" in question_lower or "coulee" in question_lower:
        # Série temporelle (par jour / semaine / mois / année)
        if period_key:
            where = []
            where.append(_valid_date_condition("HEATDEPARTURE_ACT"))
            where.append(_valid_recent_year_condition("HEATDEPARTURE_ACT"))
            if grade:
                where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
            where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            period_col = _period_expr(period_key, "HEATDEPARTURE_ACT")
            return f"""
            SELECT {period_col} AS period, COUNT(DISTINCT HEATID) AS nb_coulees
            FROM "02_EAF"
            {where_sql}
            GROUP BY period
            ORDER BY period
            """

        # accept paraphrases: "par grade", "par chaque grade", "par type/grade", "par grade top 5"
        if ("par grade" in question_lower) or ("par chaque grade" in question_lower) or ("grade" in question_lower and (top_n or "top" in question_lower)):
            where = []
            if grade:
                where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
            where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(STEELGRADECODE_ACT) AS grade, COUNT(DISTINCT HEATID) AS nb_coulees
            FROM "02_EAF"
            {where_sql}
            GROUP BY TRIM(STEELGRADECODE_ACT)
            ORDER BY nb_coulees DESC
            {limit}
            """

        qsql = 'SELECT COUNT(DISTINCT HEATID) FROM "02_EAF"'
        where = []
        if grade:
            where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
        where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
        if where:
            qsql += " WHERE " + " AND ".join(where)
        return qsql

    if "nombre" in question_lower and "brame" in question_lower:
        # Série temporelle (par jour / semaine / mois / année)
        if period_key:
            where = [_valid_date_condition("CUT_TIME"), _valid_recent_year_condition("CUT_TIME")] + _time_conditions("CUT_TIME", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            period_col = _period_expr(period_key, "CUT_TIME")
            return f"""
            SELECT {period_col} AS period, COUNT(*) AS nb_brames
            FROM "05_CCM_Brame"
            {where_sql}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower:
            where = _time_conditions("b.CUT_TIME", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(c.GRADE_CODE) AS grade, COUNT(*) AS nb_brames
            FROM "05_CCM_Brame" b
            JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID
            {where_sql}
            GROUP BY TRIM(c.GRADE_CODE)
            ORDER BY nb_brames DESC
            {limit}
            """

        qsql = 'SELECT COUNT(*) FROM "05_CCM_Brame"'
        where = _time_conditions("CUT_TIME", date, year, month, start_date, end_date)
        if where:
            qsql += " WHERE " + " AND ".join(where)
        return qsql

    if "poids brame" in question_lower or "poids des brames" in question_lower:
        # Série temporelle (par jour / semaine / mois / année)
        if period_key:
            where = [_valid_date_condition("CUT_TIME"), _valid_recent_year_condition("CUT_TIME")] + _time_conditions("CUT_TIME", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            period_col = _period_expr(period_key, "CUT_TIME")
            return f"""
            SELECT {period_col} AS period, SUM(PIECE_WEIGHT_MEAS) AS poids_brames
            FROM "05_CCM_Brame"
            {where_sql}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower:
            where = _time_conditions("b.CUT_TIME", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(c.GRADE_CODE) AS grade, SUM(b.PIECE_WEIGHT_MEAS) AS poids_brames
            FROM "05_CCM_Brame" b
            JOIN "04_CCM_Coulée" c ON c.HEAT_STEEL_ID = b.HEAT_STEEL_ID
            {where_sql}
            GROUP BY TRIM(c.GRADE_CODE)
            ORDER BY poids_brames DESC
            {limit}
            """

        qsql = 'SELECT SUM(PIECE_WEIGHT_MEAS) FROM "05_CCM_Brame"'
        where = _time_conditions("CUT_TIME", date, year, month, start_date, end_date)
        if where:
            qsql += " WHERE " + " AND ".join(where)
        return qsql

    # =====================================================
    # PRODUCTION (TAPPING_WEIGHT = poids de coulée)
    # =====================================================
    if "production" in question_lower:
        # Handle implicit follow-ups like "par jour en 2025-01" even without the literal "par jour".
        # If the user gives a month (YYYY-MM) and asks "par jour", we should return a daily series.
        if (("par jour" in question_lower) or ("par journée" in question_lower)) and not period_key:
            period_key = "jour"

        # Série temporelle (par jour / semaine / mois / année)
        if period_key:
            where = []
            where.append(_valid_date_condition("HEATDEPARTURE_ACT"))
            where.append(_valid_recent_year_condition("HEATDEPARTURE_ACT"))
            if grade:
                where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
            where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            period_col = _period_expr(period_key, "HEATDEPARTURE_ACT")
            return f"""
            SELECT {period_col} AS period, SUM(TAPPING_WEIGHT) AS production
            FROM "02_EAF"
            {where_sql}
            GROUP BY period
            ORDER BY period
            """

        if "par grade" in question_lower:
            where = []
            if grade:
                where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
            where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
            where_sql = (" WHERE " + " AND ".join(where)) if where else ""
            limit = f" LIMIT {top_n}" if top_n else ""
            return f"""
            SELECT TRIM(STEELGRADECODE_ACT) AS grade, SUM(TAPPING_WEIGHT) AS production
            FROM "02_EAF"
            {where_sql}
            GROUP BY TRIM(STEELGRADECODE_ACT)
            ORDER BY production DESC
            {limit}
            """

        qsql = 'SELECT SUM(TAPPING_WEIGHT) FROM "02_EAF"'
        where = []
        if grade:
            where.append(f"TRIM(STEELGRADECODE_ACT) LIKE '%{grade}%'")
        where += _time_conditions("HEATDEPARTURE_ACT", date, year, month, start_date, end_date)
        if where:
            qsql += " WHERE " + " AND ".join(where)
        return qsql

    return "SELECT 1"


def extract_sql(text):
    return text.strip()
