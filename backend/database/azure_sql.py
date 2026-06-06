"""Connexion Azure SQL (Sonasid) — test, introspection schéma."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    import pyodbc  # type: ignore
except Exception:
    pyodbc = None


def db_provider() -> str:
    return (os.getenv("DB_PROVIDER", "sqlite") or "sqlite").strip().lower()


def is_azure_provider(provider: Optional[str] = None) -> bool:
    p = (provider or db_provider()).strip().lower()
    return p in {"azure", "mssql", "sqlserver"}


def azure_config() -> Dict[str, str]:
    return {
        "server": (os.getenv("AZURE_SQL_SERVER", "") or "").strip(),
        "database": (os.getenv("AZURE_SQL_DB", "") or "").strip(),
        "user": (os.getenv("AZURE_SQL_USER", "") or "").strip(),
        "driver": (os.getenv("AZURE_SQL_ODBC_DRIVER", "") or "ODBC Driver 18 for SQL Server").strip(),
        "profile": (os.getenv("AZURE_SQL_PROFILE", "sonasid") or "sonasid").strip().lower(),
    }


def azure_connect():
    if pyodbc is None:
        raise RuntimeError("pyodbc non installé (pip install -r requirements.txt)")
    cfg = azure_config()
    server = cfg["server"]
    db = cfg["database"]
    user = cfg["user"]
    pwd = (os.getenv("AZURE_SQL_PASSWORD", "") or "").strip()
    if not server or not db or not user or not pwd:
        raise RuntimeError(
            "Variables Azure SQL manquantes (AZURE_SQL_SERVER, AZURE_SQL_DB, AZURE_SQL_USER, AZURE_SQL_PASSWORD)"
        )
    driver = cfg["driver"]
    conn_str = (
        f"Driver={{{driver}}};"
        f"Server=tcp:{server},1433;"
        f"Database={db};"
        f"Uid={user};"
        f"Pwd={pwd};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )
    return pyodbc.connect(conn_str)


def ping() -> Dict[str, Any]:
    """Test connexion : SELECT 1 + nom de base."""
    cfg = azure_config()
    if not is_azure_provider():
        return {"ok": False, "error": "DB_PROVIDER n'est pas azure/mssql/sqlserver", "provider": db_provider()}
    try:
        with azure_connect() as conn:
            cur = conn.cursor()
            cur.execute("SELECT DB_NAME(), @@VERSION")
            row = cur.fetchone()
            db_name = row[0] if row else None
            version = (row[1] or "")[:120] if row and len(row) > 1 else ""
        return {
            "ok": True,
            "server": cfg["server"],
            "database": db_name or cfg["database"],
            "user": cfg["user"],
            "profile": cfg["profile"],
            "version": version,
        }
    except Exception as e:
        return {
            "ok": False,
            "server": cfg["server"],
            "database": cfg["database"],
            "user": cfg["user"],
            "error": str(e) or repr(e),
        }


def list_tables(schema: str = "dbo", limit: int = 500) -> List[Dict[str, str]]:
    lim = max(1, min(int(limit), 2000))
    sql = (
        "SELECT TOP (?) TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE "
        "FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA = ? "
        "ORDER BY TABLE_NAME"
    )
    with azure_connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (lim, schema))
        rows = cur.fetchall()
    return [
        {"schema": r[0], "name": r[1], "type": r[2]}
        for r in rows
    ]


def list_columns(table: str, schema: str = "dbo") -> List[Dict[str, Any]]:
    t = (table or "").strip()
    if not t:
        raise ValueError("table requis")
    sql = (
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, "
        "CASE WHEN COLUMNPROPERTY(OBJECT_ID(?), COLUMN_NAME, 'IsIdentity') = 1 THEN 1 ELSE 0 END AS is_identity "
        "FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
        "ORDER BY ORDINAL_POSITION"
    )
    obj = f"{schema}.{t}"
    with azure_connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, (obj, schema, t))
        rows = cur.fetchall()
    return [
        {
            "name": r[0],
            "type": r[1],
            "nullable": r[2] == "YES",
            "identity": bool(r[3]),
        }
        for r in rows
    ]


def list_foreign_keys(table: str = "", schema: str = "dbo") -> List[Dict[str, str]]:
    """Clés étrangères dbo — filtre optionnel par table (parent ou référencée)."""
    s = (schema or "dbo").strip()
    t = (table or "").strip()
    sql = (
        "SELECT "
        "tp.name AS parent_table, cp.name AS parent_column, "
        "tr.name AS referenced_table, cr.name AS referenced_column, "
        "fk.name AS constraint_name "
        "FROM sys.foreign_keys fk "
        "INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id "
        "INNER JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id "
        "INNER JOIN sys.schemas ps ON tp.schema_id = ps.schema_id "
        "INNER JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id "
        "AND fkc.parent_column_id = cp.column_id "
        "INNER JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id "
        "INNER JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id "
        "AND fkc.referenced_column_id = cr.column_id "
        "WHERE ps.name = ? "
    )
    params: List[Any] = [s]
    if t:
        sql += "AND (tp.name = ? OR tr.name = ?) "
        params.extend([t, t])
    sql += "ORDER BY tp.name, cp.name"
    with azure_connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "from_table": r[0],
            "from_column": r[1],
            "to_table": r[2],
            "to_column": r[3],
            "constraint": r[4],
        }
        for r in rows
    ]


def sample_rows(table: str, schema: str = "dbo", top: int = 5) -> Tuple[List[str], List[List[Any]]]:
    """SELECT TOP n * — table name validée (identifiant simple)."""
    t = (table or "").strip()
    s = (schema or "dbo").strip()
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t):
        raise ValueError("Nom de table invalide")
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s):
        raise ValueError("Nom de schéma invalide")
    n = max(1, min(int(top), 50))
    sql = f"SELECT TOP ({n}) * FROM [{s}].[{t}]"
    with azure_connect() as conn:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
    return cols, rows

