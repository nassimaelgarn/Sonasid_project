#!/usr/bin/env python3
"""Teste la connexion Azure SQL Sonasid (lit sonasid_project/.env)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"), override=True)
except ImportError:
    pass

from backend.database.azure_sql import azure_config, db_provider, list_tables, ping


def main() -> int:
    print("DB_PROVIDER =", db_provider())
    cfg = azure_config()
    print(f"Server: {cfg['server']}")
    print(f"Database: {cfg['database']}")
    print(f"User: {cfg['user']}")
    print(f"Profile: {cfg['profile']}")
    print("--- ping ---")
    res = ping()
    if not res.get("ok"):
        print("ÉCHEC:", res.get("error"))
        print("\nVérifie AZURE_SQL_PASSWORD dans .env (mot de passe sqladmin).")
        return 1
    print("OK — base:", res.get("database"))
    print("Version:", (res.get("version") or "")[:80], "...")
    print("--- tables dbo (extrait) ---")
    tables = list_tables(schema="dbo", limit=40)
    for t in tables[:25]:
        print(f"  {t['schema']}.{t['name']} ({t['type']})")
    if len(tables) > 25:
        print(f"  ... +{len(tables) - 25} autres")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
