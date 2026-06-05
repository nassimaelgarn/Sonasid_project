#!/usr/bin/env python3
"""
Tests pré-commit Sonasid — sans exécution SQL (pas besoin de firewall Azure).

Usage:
  cd sonasid_project
  source .venv/bin/activate
  export PYTHONPATH=.
  python scripts/test_sonasid_precommit.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("AZURE_SQL_PROFILE", "sonasid")
os.environ.setdefault("DB_PROVIDER", "azure")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.llm.llm_sql import extract_sql, generate_sql
from backend.llm.sonasid_brief import detect_sonasid_brief
from backend.llm.sonasid_sql import try_sonasid_kpi_sql
from backend.llm.sql_guard import validate_sonasid_select_sql


def check(label: str, ok: bool, detail: str = "") -> bool:
    status = "OK" if ok else "FAIL"
    line = f"[{status}] {label}"
    if detail:
        line += f" — {detail[:100]}"
    print(line)
    return ok


def main() -> int:
    ok_all = True

    print("=== 1. Détection brief multi-KPI ===")
    ok_all &= check(
        "résumé tous KPI 2025",
        detect_sonasid_brief("DONNE MOI UN RESUME DE TOUT LES KPI POUR 2025") == {"kind": "dashboard"},
    )
    ok_all &= check(
        "analyse multi-axes arrivages",
        detect_sonasid_brief(
            "je veux une analyse sur les arrivages des navires pour l'annee 2025 "
            "avec tout les axes d'analyse possible"
        )
        == {"kind": "arrivages_analysis"},
    )

    print("\n=== 2. SQL règles métier (Sonasid) ===")
    cases = [
        (
            "quels fournisseurs ont le plus d'arrivages en 2025 ?",
            lambda u: "GROUP BY" in u and "FOURNISSEUR" in u and "COUNT(DISTINCT" in u,
        ),
        (
            "nombre de navires actifs par mois en 2025",
            lambda u: "CONVERT(CHAR(7)" in u and "NAVIRE" in u,
        ),
        (
            "valeur des marchandises importées en 2025",
            lambda u: "TONNAGE" in u and "SELECT 1" not in u,
        ),
        (
            "arrivages par qualité en 2025",
            lambda u: "QUALITE" in u and "GROUP BY" in u,
        ),
    ]
    for q, pred in cases:
        raw = try_sonasid_kpi_sql(q) or generate_sql(q)
        sql = extract_sql(raw) if isinstance(raw, str) else str(raw)
        u = (sql or "").upper()
        ok_all &= check(q[:55], pred(u), sql[:90] + "...")

    print("\n=== 3. Garde-fou SQL Sonasid ===")
    good = (
        "SELECT TOP 10 f.Fournisseur_Nom, COUNT(*) n "
        "FROM dbo.ARRIVAGE a JOIN dbo.FOURNISSEUR f ON a.Arrivage_FournisseurId = f.Fournisseur_Id"
    )
    bad = "DROP TABLE dbo.ARRIVAGE"
    v_ok, _ = validate_sonasid_select_sql(good)
    v_bad, _ = validate_sonasid_select_sql(bad)
    ok_all &= check("SELECT autorisé", v_ok)
    ok_all &= check("DROP refusé", not v_bad)

    print("\n=== Résultat ===")
    if ok_all:
        print("Tous les tests pré-commit Sonasid sont OK.")
        print("\nPour tester avec de vraies données :")
        print("  • Prod VM : http://135.236.108.108:5175 (code déployé + pm2 restart)")
        print("  • Local   : ajouter IP 102.101.77.134 dans Azure SQL firewall")
        return 0
    print("Échecs détectés — corriger avant commit.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
