import re


ALLOWED_TABLES = {
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
}

FORBIDDEN_KEYWORDS = (
    "insert",
    "update",
    "delete",
    "drop",
    "alter",
    "truncate",
    "attach",
    "detach",
    "pragma",
    "vacuum",
    "create",
    "replace",
)


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql or "").strip()


def _extract_tables(sql: str):
    # Capture tables used after FROM/JOIN, quoted or unquoted.
    pattern = r'(?:from|join)\s+"?([A-Za-z0-9_À-ÿ]+)"?'
    return re.findall(pattern, sql, flags=re.IGNORECASE)


def validate_select_sql(sql: str):
    """
    Returns (is_valid: bool, reason: str).
    """
    normalized = _normalize_sql(sql)
    lower_sql = normalized.lower()

    if not normalized:
        return False, "SQL vide"

    if ";" in normalized[:-1]:
        return False, "Plusieurs statements SQL détectés"

    if not (lower_sql.startswith("select") or lower_sql.startswith("with")):
        return False, "Seules les requêtes SELECT/CTE sont autorisées"

    if "sqlite_master" in lower_sql:
        return False, "Accès aux métadonnées SQLite interdit"

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lower_sql):
            return False, f"Mot-clé interdit détecté: {keyword.upper()}"

    tables = _extract_tables(normalized)
    unknown = [t for t in tables if t not in ALLOWED_TABLES]
    if unknown:
        return False, f"Table(s) non autorisée(s): {', '.join(sorted(set(unknown)))}"

    return True, "OK"
