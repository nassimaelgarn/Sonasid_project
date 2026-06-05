import os
import re

from backend.llm.sonasid_schema import allowed_table_names


ALLOWED_TABLES_ACIERIE = {
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
    "exec",
    "execute",
    "xp_",
    "sp_",
)


def _is_sonasid_profile() -> bool:
    p = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    return p in {"sonasid", "shipping", "port"}


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql or "").strip()


def _extract_tables(sql: str):
    pattern = r"(?:from|join)\s+(?:dbo\.)?\"?([A-Za-z0-9_À-ÿ]+)\"?"
    return re.findall(pattern, sql, flags=re.IGNORECASE)


def validate_select_sql(sql: str):
    if _is_sonasid_profile():
        return validate_sonasid_select_sql(sql)

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
        if re.search(rf"\b{re.escape(keyword)}\b", lower_sql):
            return False, f"Mot-clé interdit détecté: {keyword.upper()}"

    tables = _extract_tables(normalized)
    unknown = [t for t in tables if t not in ALLOWED_TABLES_ACIERIE]
    if unknown:
        return False, f"Table(s) non autorisée(s): {', '.join(sorted(set(unknown)))}"

    return True, "OK"


def validate_sonasid_select_sql(sql: str):
    normalized = _normalize_sql(sql)
    lower_sql = normalized.lower()

    if not normalized:
        return False, "SQL vide"

    if ";" in normalized[:-1]:
        return False, "Plusieurs statements SQL détectés"

    if not (lower_sql.startswith("select") or lower_sql.startswith("with")):
        return False, "Seules les requêtes SELECT/CTE sont autorisées"

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{re.escape(keyword)}\b", lower_sql):
            return False, f"Mot-clé interdit détecté: {keyword.upper()}"

    if re.search(r"\b(sys\.|information_schema|master\.|msdb\.)\b", lower_sql):
        return False, "Accès aux métadonnées système interdit"

    allowed = allowed_table_names()
    tables = _extract_tables(normalized)
    if not tables:
        return False, "Aucune table FROM/JOIN détectée"

    unknown = [t.upper() for t in tables if t.upper() not in allowed]
    if unknown:
        return False, f"Table(s) non autorisée(s): {', '.join(sorted(set(unknown)))}"

    return True, "OK"
