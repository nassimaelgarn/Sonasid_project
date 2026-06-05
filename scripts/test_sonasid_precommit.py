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
        (
            "quels navires ont le plus de tonnage transféré en 2025 ?",
            lambda u: "NAVIRE" in u
            and "TRANSFERT" in u
            and "GROUP BY" in u
            and "TONNAGE_TRANSFERE" in u.replace(" ", "")
            and "SUM(ARRIVAGE_TONNAGETOTAL)" not in u,
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

    print("\n=== 4. Questions ouvertes / vagues → brief ===")
    vague_cases = [
        ("situation au port cette année", "dashboard"),
        ("un petit récap sur 2025 stp", "dashboard"),
        ("dis-moi ce qui s'est passé côté arrivages l'an dernier", "arrivages_analysis"),
        ("comment ça se présente niveau marchandises importées récemment", "dashboard"),
        ("c'est quoi la situation au port cette année", "dashboard"),
    ]
    for q, expected_kind in vague_cases:
        hint = detect_sonasid_brief(q)
        ok = hint is not None and hint.get("kind") == expected_kind
        ok_all &= check(q[:50], ok, str(hint))

    print("\n=== 5. Périodes relatives (l'an dernier → 2025) ===")
    from datetime import datetime
    from backend.llm.sonasid_brief import _resolve_brief_years

    expected_last = datetime.now().year - 1
    period_cases = [
        "dis-moi ce qui s'est passé côté arrivages l'an dernier",
        "arrivages lan dernier",
        "situation port l an dernier",
        f"situation port cette année",
    ]
    for q in period_cases:
        yrs = _resolve_brief_years(q)
        if "dernier" in q or "lan dernier" in q or "l an dernier" in q:
            ok = yrs == [expected_last]
        else:
            ok = yrs == [datetime.now().year]
        ok_all &= check(q[:45], ok, str(yrs))

    print("\n=== 6. Questions ouvertes → SQL / expansion ===")
    from backend.llm.sonasid_sql import expand_sonasid_open_question
    from backend.llm.conversational import should_use_kpi_pipeline

    open_cases = [
        ("les arrivages ont augmenté ou pas ?", "par mois", True),
        ("nombre d'arrivages par mois l'année dernière", "2025", True),
        ("qu'est-ce qui est arrivé en janvier 2025 ?", "2025-01", True),
    ]
    for q, needle, kpi in open_cases:
        expanded, _ = expand_sonasid_open_question(q)
        raw = generate_sql(expanded) or try_sonasid_kpi_sql(expanded)
        sql = extract_sql(raw) if isinstance(raw, str) else str(raw or "")
        ok = should_use_kpi_pipeline(q) == kpi and needle in (expanded + " " + sql)
        ok_all &= check(q[:42], ok, expanded[:60])

    print("\n=== 7. Mode Sonasid ouvert (LLM-first) ===")
    from backend.llm.sonasid_open import (
        is_sonasid_llm_first,
        is_sonasid_open_mode,
        looks_like_sonasid_data_question,
    )

    ok_all &= check("mode ouvert actif", is_sonasid_open_mode())
    ok_all &= check(
        "question créative → domaine port",
        looks_like_sonasid_data_question("est-ce que le port était chargé l'été dernier ?"),
    )
    ok_all &= check(
        "LLM-first désactivé par défaut (rules first)",
        not is_sonasid_llm_first()
        or (os.getenv("SONASID_LLM_FIRST") or "").strip().lower() in {"1", "true", "yes", "on"},
        f"first={is_sonasid_llm_first()}",
    )

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
