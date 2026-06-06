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

    print("\n=== 4. KPI précis ≠ brief générique ===")
    specific_cases = [
        "tonnage transféré par qualité navire id 79 en 2025",
        "tonnage transféré par qualité en 2025",
        "quels navires ont le plus de tonnage transféré en 2025 ?",
        "tonnage transféré par qualité navire en 2025",
    ]
    for q in specific_cases:
        ok = detect_sonasid_brief(q) is None
        if q.endswith("navire en 2025"):
            raw = try_sonasid_kpi_sql(q)
            ok = ok and isinstance(raw, dict) and raw.get("type") == "need_navire"
        ok_all &= check(f"pas brief: {q[:42]}", ok)

    raw_liste = try_sonasid_kpi_sql("liste des navires en déchargement") or ""
    u_liste = str(raw_liste).upper()
    ok_all &= check(
        "liste navires déchargement → SQL détail",
        "NAVIRE_NOM" in u_liste and "SELECT COUNT" not in u_liste,
        str(raw_liste)[:90],
    )

    print("\n=== 5b. Schéma / tables (sans LLM) ===")
    from backend.llm.conversational import should_use_kpi_pipeline
    from backend.llm.sonasid_schema import is_schema_metadata_question, schema_metadata_reply

    schema_q = "Merci de me communiquer les noms des tables et leurs relations dans la base de données"
    rep = schema_metadata_reply(schema_q)
    ok_all &= check(
        "question schéma détectée",
        is_schema_metadata_question(schema_q),
    )
    ok_all &= check(
        "réponse schéma ARRIVAGE",
        "ARRIVAGE" in str(rep.get("message", "")) and rep.get("source") == "sonasid:schema",
    )
    count_q = "cite le nombre des tables dans la base de données"
    ok_all &= check(
        "nombre tables → inventaire",
        is_schema_metadata_question(count_q) and "tables" in schema_metadata_reply(count_q).get("message", "").lower(),
    )
    nav_rep = schema_metadata_reply("structure de la table NAVIRE")
    ok_all &= check(
        "fiche NAVIRE dans dictionnaire",
        "Navire_Nom" in str(nav_rep.get("message", "")) and "Navire_IMO" in str(nav_rep.get("message", "")),
    )
    qual_rep = schema_metadata_reply("champs table QUALITE")
    ok_all &= check(
        "fiche QUALITE dans dictionnaire",
        "Qualite_Libelle" in str(qual_rep.get("message", "")),
    )
    flotte_rep = schema_metadata_reply("structure table FLOTTE")
    ok_all &= check(
        "fiche FLOTTE + lien TRANSFERT",
        "Flotte_Immatriculation" in str(flotte_rep.get("message", ""))
        and "TRANSFERT" in str(flotte_rep.get("message", "")),
    )
    ok_all &= check(
        "diagramme inclut FLOTTE",
        "FLOTTE" in schema_metadata_reply(schema_q).get("message", ""),
    )
    resume_tables_q = "resumé sur tout les tables de la base"
    ok_all &= check(
        "résumé tables → inventaire schéma",
        is_schema_metadata_question(resume_tables_q)
        and schema_metadata_reply(resume_tables_q).get("source") == "sonasid:schema",
    )
    ok_all &= check(
        "structure NAVIRE par mois → schéma (pas KPI)",
        is_schema_metadata_question("structure de la table NAVIRE par mois")
        and not should_use_kpi_pipeline("structure de la table NAVIRE par mois"),
    )
    ok_all &= check(
        "champs QUALITE → fiche dictionnaire",
        "Qualite_Libelle" in schema_metadata_reply("champs table QUALITE").get("message", ""),
    )
    from backend.llm.sonasid_schema import extract_table_name_from_question

    ok_all &= check(
        "extract table NAVIRE",
        extract_table_name_from_question("structure de la table NAVIRE") == "NAVIRE",
    )
    ok_all &= check(
        "endpoint relations importable",
        callable(__import__("backend.database.azure_sql", fromlist=["list_foreign_keys"]).list_foreign_keys),
    )

    print("\n=== 5. Questions ouvertes / vagues → brief ===")
    vague_cases = [
        ("situation au port cette année", "dashboard"),
        ("un petit récap sur 2025 stp", "dashboard"),
        ("dis-moi ce qui s'est passé côté arrivages l'an dernier", "arrivages_analysis"),
        ("comment ça se présente niveau marchandises importées récemment", "dashboard"),
        ("c'est quoi la situation au port cette année", "dashboard"),
        ("parle moi de tous les arrivages de 2026", "arrivages_analysis"),
    ]
    for q, expected_kind in vague_cases:
        hint = detect_sonasid_brief(q)
        ok = hint is not None and hint.get("kind") == expected_kind
        ok_all &= check(q[:50], ok, str(hint))

    print("\n=== 6. Périodes relatives (l'an dernier → 2025) ===")
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

    print("\n=== 7. Questions ouvertes → SQL / expansion ===")
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

    print("\n=== 8. Mode Sonasid ouvert (LLM-first) ===")
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

    print("\n=== 9. Résilience (essayer avant erreur) ===")
    from backend.llm.sonasid_resilience import (
        build_guidance_reply,
        should_force_kpi_pipeline,
        try_deterministic_sonasid_reply,
    )

    ok_all &= check(
        "force KPI si règle existe",
        should_force_kpi_pipeline("liste des navires en déchargement"),
    )
    ok_all &= check(
        "schéma sans LLM",
        try_deterministic_sonasid_reply("cite le nombre des tables") is not None,
    )
    guide = build_guidance_reply("question bizarre xyz")
    ok_all &= check(
        "guide sans chiffre inventé",
        "Aucun chiffre" in guide.get("message", "") or "Questions que je sais" in guide.get("message", ""),
    )

    print("\n=== 8. STT (Whisper fallback) ===")
    from backend.llm.stt import transcribe_audio_bytes

    text, err = transcribe_audio_bytes(b"", fmt="webm")
    ok_all &= check("audio vide rejeté", text is None and err is not None)

    print("\n=== 9. Libellé période mensuelle ===")
    from backend.pipeline.pipeline import _build_monthly_series_message

    one = _build_monthly_series_message(
        "arrivages en 2026-01 par mois",
        [{"period": "2026-01", "value": 3}],
        metric_label="Arrivages",
    )
    ok_all &= check("1 mois sans flèche redondante", "janvier 2026" in one and "→" not in one)

    print("\n=== 10. Registre modèles (Azure) ===")
    import os

    from backend.llm.model_registry import list_chat_models, resolve_chat_model

    os.environ["AZURE_OPENAI_API_KEY"] = "test-key"
    os.environ["AZURE_OPENAI_ENDPOINT"] = "https://x.services.ai.azure.com/openai/v1"
    os.environ["AZURE_INFERENCE_ENDPOINT"] = "https://x.services.ai.azure.com/models"
    os.environ["OPENROUTER_API_KEY"] = "or-key"
    ids = [m.id for m in list_chat_models()]
    ok_all &= check(
        "3 Azure + OpenRouter + Ollama",
        ids == ["grok", "kimi", "deepseek", "trinity", "flash", "ollama"],
        ids,
    )
    ok_all &= check("slug kimi", resolve_chat_model("kimi") == "azure/Kimi-K2.6")
    ok_all &= check("slug grok", resolve_chat_model("grok") == "azure-inference/grok-4.3")
    ok_all &= check("slug deepseek", resolve_chat_model("deepseek") == "azure/DeepSeek-V4-Pro")

    print("\n=== 11. Présentation entreprise Sonasid ===")
    from backend.llm.sonasid_schema import company_overview_reply, is_sonasid_company_question

    q_co = "je veux avoir une idée sur l entreprise Sonasid"
    ok_all &= check("détecte question entreprise", is_sonasid_company_question(q_co))
    rep_co = company_overview_reply(q_co)
    ok_all &= check(
        "réponse entreprise avec métier",
        rep_co.get("source") == "sonasid:company"
        and "logistique portuaire" in rep_co.get("message", "").lower(),
    )

    print("\n=== 12. Tolérance fautes + smart routing ===")
    from backend.llm.llm_sql import normalize_user_question
    from backend.llm.sonasid_typo import apply_sonasid_typos

    messy = "combien d arivages en 2025 tonage importé"
    fixed = normalize_user_question(messy)
    ok_all &= check(
        "normalise typos Sonasid",
        "arrivages" in fixed.lower() and "tonnage" in fixed.lower(),
        fixed,
    )
    ok_all &= check("apply_sonasid_typos", "tonnage" in apply_sonasid_typos("tonage").lower())

    print("\n=== 13. Relance « en tableau » (anti-504) ===")
    from backend.llm.llm_sql import (
        is_contextual_data_followup_text,
        is_table_format_followup_text,
        merge_table_format_followup_from_history,
        should_skip_kpi_rewrite,
    )

    table_q = "je les veux dans un tableau avec leurs arrivages"
    ok_all &= check(
        "detecte follow-up tableau",
        is_table_format_followup_text(table_q),
        table_q,
    )
    names_table_q = "mets leurs noms dans un tableau avec chacun leurs arrivages"
    ok_all &= check(
        "detecte relance anaphorique fournisseurs",
        is_contextual_data_followup_text(names_table_q),
        names_table_q,
    )
    prior = [
        {"role": "user", "content": "Cite moi tous les fournisseurs en 2025"},
        {"role": "assistant", "content": "Top fournisseurs… European Metal Recycling…"},
    ]
    merged = merge_table_format_followup_from_history(table_q, prior)
    ok_all &= check(
        "fusionne avec question fournisseurs",
        "fournisseur" in merged.lower() and "2025" in merged,
        merged,
    )
    merged2 = merge_table_format_followup_from_history(names_table_q, prior)
    ok_all &= check(
        "fusionne noms/tableau → fournisseurs 2025",
        "fournisseur" in merged2.lower() and "2025" in merged2,
        merged2,
    )
    ok_all &= check(
        "bloque rewrite LLM sur relance contextuelle",
        should_skip_kpi_rewrite(names_table_q),
        names_table_q,
    )
    ok_all &= check(
        "SQL déterministe fournisseurs + tableau",
        isinstance(try_sonasid_kpi_sql(merged2), str)
        and "FOURNISSEUR" in (try_sonasid_kpi_sql(merged2) or "").upper(),
        merged2[:80],
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
