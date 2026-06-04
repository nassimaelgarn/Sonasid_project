#!/usr/bin/env python3
"""
Smoke test Sonasid sur Azure SQL (connexion + KPI port/arrivages).
Lit sonasid_project/.env — ne logue pas le mot de passe.
"""

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

from backend.database.azure_sql import azure_config, db_provider, ping
from backend.database.run_query import run_query
from backend.pipeline.pipeline import process_question


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    _section("Configuration")
    print("DB_PROVIDER =", db_provider())
    cfg = azure_config()
    print(f"Server     : {cfg['server']}")
    print(f"Database   : {cfg['database']}")
    print(f"Profile    : {cfg['profile']}")

    _section("Connexion")
    res = ping()
    if not res.get("ok"):
        print("ÉCHEC:", res.get("error"))
        return 1
    print("OK —", res.get("database"))
    print("Version :", (res.get("version") or "")[:100])

    _section("Répartition arrivages par année (DateCreation)")
    rows = run_query(
        """
        SELECT YEAR(Arrivage_DateCreation) AS annee, COUNT(*) AS n
        FROM dbo.ARRIVAGE
        WHERE Arrivage_DateCreation IS NOT NULL
        GROUP BY YEAR(Arrivage_DateCreation)
        ORDER BY annee
        """
    )
    for r in rows or []:
        print(f"  {r[0]}: {r[1]} arrivages")

    _section("Navires actifs")
    nav = run_query(
        "SELECT COUNT(*) FROM dbo.NAVIRE WHERE Navire_Active = 1"
    )
    print("  ", nav[0][0] if nav else "?")

    _section("KPI chatbot (pipeline)")
    tests = [
        "nombre des arrivages",
        "nombre d'arrivages en 2025",
        "nombre d'arrivages en 2026",
        "nombre d'arrivages fournisseur id 1",
        "tonnage importé fournisseur id 1",
        "tonnage par qualité fournisseur id 1",
        "tonnage transféré par qualité",
        "nombre de navires actifs",
        "arrivages par mois en 2025",
    ]
    failed = 0
    for q in tests:
        out = process_question(q)
        src = out.get("source") or out.get("error") or "?"
        msg = (out.get("message") or str(out.get("result")) or out.get("error") or "")[:70]
        ok = not out.get("error") and src != "pipeline:need_period"
        status = "OK" if ok else "KO"
        if not ok:
            failed += 1
        print(f"  [{status}] {q}")
        print(f"        → {msg} ({src})")

    _section("Résumé")
    if failed:
        print(f"{failed} test(s) en échec.")
        return 1
    print("Tous les tests Azure SQL / KPI sont OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
 