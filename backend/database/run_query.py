import os
import re
import sqlite3
from typing import Any, Dict, Optional

try:
    import pyodbc  # type: ignore
except Exception:
    pyodbc = None

# Load env vars from project .env for CLI/scripts (FastAPI loads it elsewhere).
try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

# Chemin absolu du projet
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if load_dotenv is not None:
    load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

# Chemin DB correct
db_path = os.path.join(BASE_DIR, "db", "sonasid.db")

def _db_provider() -> str:
    return (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()


def _azure_table_map() -> Dict[str, str]:
    """
    Map SQLite table names used by the rule engine to Azure SQL objects.
    Override via env if your schema uses different names.
    Profil « sonasid » : pas de tables aciérie (schéma port / navires).
    """
    profile = (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower()
    if profile in {"sonasid", "shipping", "port"}:
        m: Dict[str, str] = {}
        if os.getenv("AZURE_SQL_TABLE_NAVIRE", "").strip():
            m["NAVIRE"] = os.getenv("AZURE_SQL_TABLE_NAVIRE", "dbo.NAVIRE").strip()
        if os.getenv("AZURE_SQL_TABLE_ARRIVAGE", "").strip():
            m["ARRIVAGE"] = os.getenv("AZURE_SQL_TABLE_ARRIVAGE", "dbo.ARRIVAGE").strip()
        return m
    return {
        "02_EAF": os.getenv("AZURE_SQL_TABLE_EAF", "dbo.EAF").strip() or "dbo.EAF",
        "03_LF": os.getenv("AZURE_SQL_TABLE_LF", "dbo.LF").strip() or "dbo.LF",
        "01_PAF": os.getenv("AZURE_SQL_TABLE_PAF", "dbo.PAF").strip() or "dbo.PAF",
        # Azure tables contain '-' and accented chars: bracket-quote by default.
        "04_CCM_Coulée": os.getenv("AZURE_SQL_TABLE_CCM_COULEE", "dbo.[CCM-Coulée]").strip() or "dbo.[CCM-Coulée]",
        "05_CCM_Brame": os.getenv("AZURE_SQL_TABLE_CCM_BRAME", "dbo.[CCM-Brame]").strip() or "dbo.[CCM-Brame]",
        "CCM_Analyse": os.getenv("AZURE_SQL_TABLE_CCM_ANALYSE", "dbo.[CCM-Analyse]").strip() or "dbo.[CCM-Analyse]",
        "Défauts_Brame": os.getenv("AZURE_SQL_TABLE_DEFAUTS_BRAME", "dbo.Défauts_Brame").strip() or "dbo.Défauts_Brame",
        "EAF_Analyses": os.getenv("AZURE_SQL_TABLE_EAF_ANALYSES", "dbo.[EAF-Analyses]").strip() or "dbo.[EAF-Analyses]",
        "LF_Analyse": os.getenv("AZURE_SQL_TABLE_LF_ANALYSE", "dbo.[LF-Analyse]").strip() or "dbo.[LF-Analyse]",
        # Use brackets by default (accented identifier).
        "EAF_Arrêts": os.getenv("AZURE_SQL_TABLE_EAF_ARRETS", "dbo.[EAF_Arrêts]").strip() or "dbo.[EAF_Arrêts]",
    }


def _replace_sqlite_tables(sql: str) -> str:
    out = sql
    for src, dst in _azure_table_map().items():
        # Handle "02_EAF" (quoted) and unquoted occurrences.
        out = re.sub(rf'(?i)"{re.escape(src)}"', dst, out)
        # Avoid turning dbo.EAF into dbo.dbo.EAF
        # Also avoid replacing inside bracketed identifiers like [EAF_Arrêts]
        out = re.sub(rf"(?i)(?<![.\[])\b{re.escape(src)}\b", dst, out)
    return out


def _translate_year_like(col: str, year: str) -> str:
    y = int(year)
    return f"{col} >= '{y:04d}-01-01' AND {col} < '{(y+1):04d}-01-01'"


def _translate_month_like(col: str, ym: str) -> str:
    y, m = ym.split("-", 1)
    y_i = int(y)
    m_i = int(m)
    if m_i == 12:
        return f"{col} >= '{y_i:04d}-12-01' AND {col} < '{(y_i+1):04d}-01-01'"
    return f"{col} >= '{y_i:04d}-{m_i:02d}-01' AND {col} < '{y_i:04d}-{(m_i+1):02d}-01'"


def _sqlite_to_tsql(sql: str) -> str:
    """
    Best-effort translation for the rule-engine SQL (SQLite-flavored) into T-SQL.
    Covers the common patterns used by this project (period grouping and LIKE year/month filters).
    """
    s = (sql or "").strip()
    if not s:
        return s

    # Tables
    s = _replace_sqlite_tables(s)

    # Period grouping: strftime('%Y-%m', DATE(substr(COL,1,10))) -> CONVERT(char(7), COL, 126)
    s = re.sub(
        r"(?is)strftime\(\s*'%Y-%m'\s*,\s*DATE\(\s*substr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*10\s*\)\s*\)\s*\)",
        r"CONVERT(char(7), \1, 126)",
        s,
    )

    # Period grouping (week): strftime('%Y-W%W', DATE(substr(COL,1,10))) -> yyyy-Www (ISO week)
    # Example output: 2025-W05
    s = re.sub(
        r"(?is)strftime\(\s*'%Y-W%W'\s*,\s*DATE\(\s*substr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*10\s*\)\s*\)\s*\)",
        (
            r"CONCAT("
            r"DATEPART(year, TRY_CONVERT(date, LEFT(\1, 10))),"
            r"'-W',"
            r"RIGHT('0' + CAST(DATEPART(isowk, TRY_CONVERT(date, LEFT(\1, 10))) AS varchar(2)), 2)"
            r")"
        ),
        s,
    )

    # SQLite date helpers -> T-SQL equivalents
    # DATE(substr(COL,1,10)) -> TRY_CONVERT(date, LEFT(COL,10))
    s = re.sub(
        r"(?is)\bDATE\(\s*substr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*10\s*\)\s*\)",
        r"TRY_CONVERT(date, LEFT(\1, 10))",
        s,
    )

    # If the source column is already a datetime/date in SQL Server, LEFT(col,10) is unsafe
    # (implicit string format may not be ISO). Casting is robust for both datetime and ISO text.
    s = re.sub(
        r"(?is)\bTRY_CONVERT\(\s*date\s*,\s*LEFT\(\s*([A-Za-z0-9_\.\[\]]+)\s*,\s*10\s*\)\s*\)",
        r"CAST(\1 AS date)",
        s,
    )
    # substr(COL,1,10) -> LEFT(COL,10)
    s = re.sub(
        r"(?is)\bsubstr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*10\s*\)",
        r"LEFT(\1, 10)",
        s,
    )
    # substr(COL,1,4) -> LEFT(COL,4)
    s = re.sub(
        r"(?is)\bsubstr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*4\s*\)",
        r"LEFT(\1, 4)",
        s,
    )
    # Generic: substr(COL,1,N) -> LEFT(COL,N)
    s = re.sub(
        r"(?is)\bsubstr\(\s*([A-Za-z0-9_\.]+)\s*,\s*1\s*,\s*(\d+)\s*\)",
        r"LEFT(\1, \2)",
        s,
    )

    # SQLite string concat operator
    s = re.sub(r"(?is)\s*\|\|\s*", " + ", s)

    # SQLite date() function on dynamic expressions:
    # date(expr,'+1 month') -> DATEADD(month,1,TRY_CONVERT(date,expr))
    s = re.sub(
        r"(?is)\bdate\(\s*([^,]+?)\s*,\s*'\+1\s+month'\s*\)",
        r"DATEADD(month, 1, TRY_CONVERT(date, \1))",
        s,
    )
    # date(expr) -> TRY_CONVERT(date, expr)
    s = re.sub(
        r"(?is)\bdate\(\s*([^\)]+?)\s*\)",
        r"TRY_CONVERT(date, \1)",
        s,
    )

    # GROUP BY on aliases: SQL Server does not allow grouping by SELECT aliases.
    # Rewrite common alias tokens inside GROUP BY lists.
    alias_expr: Dict[str, str] = {}

    # period alias: produced by our strftime->... rewrites (month/week/day buckets)
    m_period = re.search(r"(?is)(CONVERT\(char\(7\),\s*[A-Z0-9_\.]+\s*,\s*126\))\s+AS\s+period\b", s)
    if m_period:
        alias_expr["period"] = m_period.group(1)
    else:
        m_period_week = re.search(r"(?is)(CONCAT\(.+?\))\s+AS\s+period\b", s)
        if m_period_week:
            alias_expr["period"] = m_period_week.group(1)
        else:
        # day buckets often use DATE(substr(...)) -> TRY_CONVERT(date, LEFT(...,10))
            m_period_day = re.search(r"(?is)(TRY_CONVERT\(date,\s*LEFT\(\s*[A-Z0-9_\.]+\s*,\s*10\s*\)\))\s+AS\s+period\b", s)
            if m_period_day:
                alias_expr["period"] = m_period_day.group(1)
            else:
                # sometimes generated directly as yyyy-mm-dd text
                m_period_day2 = re.search(r"(?is)(CONVERT\(char\(10\),\s*[A-Z0-9_\.]+\s*,\s*23\))\s+AS\s+period\b", s)
                if m_period_day2:
                    alias_expr["period"] = m_period_day2.group(1)
                else:
                    # Common simple patterns: CAST(datecol AS date) AS period, CONVERT(date, col) AS period
                    m_period_day3 = re.search(
                        r"(?is)(CAST\(\s*[A-Z0-9_\.\[\]]+\s+AS\s+date\s*\))\s+AS\s+period\b",
                        s,
                    )
                    if m_period_day3:
                        alias_expr["period"] = m_period_day3.group(1)
                    else:
                        m_period_day4 = re.search(
                            r"(?is)(CONVERT\(\s*date\s*,\s*[A-Z0-9_\.\[\]]+\s*(?:,\s*\d+\s*)?\))\s+AS\s+period\b",
                            s,
                        )
                        if m_period_day4:
                            alias_expr["period"] = m_period_day4.group(1)

    # largeur / epaisseur aliases (common patterns)
    for alias in ("largeur", "epaisseur", "épaisseur"):
        m_alias = re.search(rf"(?is)([A-Z0-9_\.\[\]]+)\s+AS\s+{re.escape(alias)}\b", s)
        if m_alias:
            alias_expr[alias] = m_alias.group(1)

    # grade alias (e.g. SELECT TRIM(STEELGRADECODE_ACT) AS grade, ...)
    m_grade = re.search(r"(?is)(?:\bSELECT\b|,)\s*([^,]+?)\s+AS\s+grade\b", s)
    if m_grade:
        alias_expr["grade"] = (m_grade.group(1) or "").strip()

    # categorie alias (e.g. CAT_Nom AS categorie)
    m_cat = re.search(r"(?is)(?:\bSELECT\b|,)\s*([^,]+?)\s+AS\s+categorie\b", s)
    if m_cat:
        alias_expr["categorie"] = (m_cat.group(1) or "").strip()

    if alias_expr and re.search(r"(?is)\bGROUP\s+BY\b", s):
        def _rewrite_group_by_clause(m: re.Match) -> str:
            clause = m.group(0)
            out = clause
            # Replace longer tokens first to avoid partial overlaps.
            for alias, expr in sorted(alias_expr.items(), key=lambda kv: -len(kv[0])):
                out = re.sub(rf"(?is)\b{re.escape(alias)}\b", expr, out)
            return out

        s = re.sub(r"(?is)\bGROUP\s+BY\s+[^\n]+", _rewrite_group_by_clause, s)

    # Heuristic fix for CTE series queries (e.g. conso_elec WITH all_conso):
    # Outer query groups by the CTE column "period"; rewriting it to an inner-table expression
    # (HEATDEPARTURE_ACT, etc.) breaks because that column is out of scope.
    if re.search(r"(?is)\bFROM\s+all_conso\b", s):
        # If GROUP BY got rewritten to columns that don't exist in the outer scope, restore grouping by CTE aliases.
        if re.search(r"(?is)\bGROUP\s+BY\b.*HEATDEPARTURE_ACT", s):
            s = re.sub(r"(?is)\bGROUP\s+BY\s+[^\n]+", "GROUP BY period", s, count=1)
        if re.search(r"(?is)\bGROUP\s+BY\b.*STEELGRADECODE_ACT", s):
            s = re.sub(r"(?is)\bGROUP\s+BY\s+[^\n]+", "GROUP BY grade", s, count=1)

    # LIKE '2025%' or LIKE '2025-01%'
    def repl_like(m: re.Match) -> str:
        col = m.group(1)
        pat = m.group(2)
        if re.match(r"^20\d{2}$", pat):
            return _translate_year_like(col, pat)
        if re.match(r"^20\d{2}-\d{2}$", pat):
            return _translate_month_like(col, pat)
        return m.group(0)

    s = re.sub(r"(?is)\b([A-Z0-9_\.]+)\s+LIKE\s+'(20\d{2}(?:-\d{2})?)%'", repl_like, s)

    # TD/TR helper functions used by SQLite rules (julianday / DATE('YYYY-MM-DD', '+1 day'))
    # IMPORTANT: replace DATE('..','+1 day') BEFORE DATE('..')
    # DATE('YYYY-MM-DD','+1 month','-1 day') -> EOMONTH(CAST('YYYY-MM-DD' as date))
    s = re.sub(
        r"(?is)\bDATE\(\s*'(\d{4}-\d{2}-\d{2})'\s*,\s*'\+1\s+month'\s*,\s*'-1\s+day'\s*\)",
        r"EOMONTH(CAST('\1' AS date))",
        s,
    )
    s = re.sub(
        r"(?is)\bDATE\(\s*'(\d{4}-\d{2}-\d{2})'\s*,\s*'\+1\s+day'\s*\)",
        r"DATEADD(day, 1, CAST('\1' AS date))",
        s,
    )
    s = re.sub(r"(?is)\bDATE\(\s*'(\d{4}-\d{2}-\d{2})'\s*\)", r"CAST('\1' AS date)", s)

    # Core pattern used by _open_time_seconds_expr:
    # (julianday(END, '+1 day') - julianday(START)) * 86400  -> DATEDIFF(second, START, DATEADD(day,1,END))
    # Handle nested expressions like END=EOMONTH(CAST('2025-01-01' AS date))
    s = re.sub(
        r"(?is)\(\s*julianday\(\s*(.+?)\s*,\s*'\+1\s+day'\s*\)\s*-\s*julianday\(\s*(.+?)\s*\)\s*\)\s*\*\s*86400",
        r"DATEDIFF(second, \2, DATEADD(day, 1, \1))",
        s,
    )
    # (julianday(A) - julianday(B)) * 86400 -> DATEDIFF(second, B, A)
    s = re.sub(
        r"(?is)\(\s*julianday\(\s*(.+?)\s*\)\s*-\s*julianday\(\s*(.+?)\s*\)\s*\)\s*\*\s*86400",
        r"DATEDIFF(second, \2, \1)",
        s,
    )

    # Remaining julianday(...) isn't supported in T-SQL; strip wrapper to avoid hard failures when possible.
    s = re.sub(r"(?is)\bjulianday\(\s*(.+?)\s*\)", r"\1", s)

    # LIMIT n (SQLite) -> TOP (n) (SQL Server)
    m_lim = re.search(r"(?is)\bLIMIT\s+(\d+)\s*$", s)
    if m_lim:
        n_lim = m_lim.group(1)
        s = re.sub(r"(?is)\bLIMIT\s+\d+\s*$", "", s).rstrip()
        # Insert TOP right after SELECT / SELECT DISTINCT
        if re.match(r"(?is)^\s*SELECT\s+DISTINCT\s+", s):
            s = re.sub(r"(?is)^\s*SELECT\s+DISTINCT\s+", f"SELECT DISTINCT TOP ({n_lim}) ", s, count=1)
        elif re.match(r"(?is)^\s*SELECT\s+", s):
            s = re.sub(r"(?is)^\s*SELECT\s+", f"SELECT TOP ({n_lim}) ", s, count=1)

    # Remove SQLite-only guards that don't apply in T-SQL (after other rewrites)
    s = re.sub(r"(?is)\bLEFT\(\s*([A-Z0-9_\.]+)\s*,\s*4\s*\)\s+GLOB\s+'20\[0-9\]\[0-9\]'\s+AND\s+", "", s)
    s = re.sub(r"(?is)\bTRY_CONVERT\(date,\s*LEFT\([A-Z0-9_\.]+,\s*10\)\)\s+IS\s+NOT\s+NULL\s+AND\s+", "", s)

    # Quote style: "alias" -> [alias] is not necessary; keep as-is.
    # SQL Server requires aliases for derived tables: FROM (SELECT ...) AS t
    s = _ensure_derived_table_aliases(s)
    return s


def _ensure_derived_table_aliases(tsql: str) -> str:
    """
    Add missing aliases for derived tables in T-SQL.
    SQLite allows `FROM (SELECT ...)` without alias; SQL Server does not.
    Best-effort: detects `FROM (` followed by SELECT and inserts `AS qN` at the matching closing `)`.
    """
    s = tsql or ""
    if "FROM" not in s.upper():
        return s
    out = []
    i = 0
    n = len(s)
    stack = []  # (paren_depth_at_from, alias_id)
    paren_depth = 0
    alias_counter = 0

    def _peek_nonspace(j: int) -> str:
        while j < n and s[j].isspace():
            j += 1
        return s[j] if j < n else ""

    while i < n:
        # Track parentheses
        c = s[i]
        # Detect "FROM (" then optional whitespace then "SELECT"
        if s[i : i + 4].upper() == "FROM" and _peek_nonspace(i + 4) == "(":
            j = i + 4
            while j < n and s[j].isspace():
                j += 1
            if j < n and s[j] == "(":
                k = j + 1
                while k < n and s[k].isspace():
                    k += 1
                if s[k : k + 6].upper() == "SELECT":
                    # We'll need an alias at the closing paren matching this '('
                    alias_counter += 1
                    stack.append((paren_depth, alias_counter))

        if c == "(":
            paren_depth += 1
            out.append(c)
            i += 1
            continue
        if c == ")":
            out.append(c)
            # If this closes a derived table paren, insert alias if missing
            if stack and paren_depth - 1 == stack[-1][0]:
                _, aid = stack.pop()
                # If next token already has an alias, don't add.
                nxt = s[i + 1 : i + 40].upper()
                if not re.match(r"^\s+(AS\s+)?[A-Z_][A-Z0-9_]*", nxt or ""):
                    out.append(f" AS q{aid}")
            paren_depth -= 1
            i += 1
            continue

        out.append(c)
        i += 1

    return "".join(out)


def _azure_conn():
    from backend.database.azure_sql import azure_connect

    return azure_connect()


def run_query(sql):
    provider = _db_provider()
    if provider in {"azure", "mssql", "sqlserver"}:
        try:
            tsql = _sqlite_to_tsql(sql)
            with _azure_conn() as conn:
                cur = conn.cursor()
                cur.execute(tsql)
                rows = cur.fetchall()
                return [list(r) for r in rows]
        except Exception as e:
            msg = str(e) or repr(e)
            debug = os.getenv("SQL_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
            if debug:
                return f"{msg}\n\n--- SQL ---\n{tsql}"
            return msg

    # Default: SQLite local
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        result = cursor.fetchall()
    except Exception as e:
        result = str(e)
    conn.close()
    return result