"""
Tests du moteur rule-based: on vérifie que generate_sql produit le bon *type* de requête
(série temporelle vs totaux scalaires) sans dépendre d'une base SQLite locale.
"""

from backend.llm.llm_sql import (
    KPI_ANALYSE_MARKER,
    extract_sql,
    generate_sql,
    is_kpi_analyse_message,
    kpi_period_span_from_question,
)


def _compact_upper(s: str) -> str:
    return s.upper().replace(" ", "")


def test_kpi_analyse_message_detection():
    assert is_kpi_analyse_message(f"{KPI_ANALYSE_MARKER}\nfoo")
    assert is_kpi_analyse_message(f"  {KPI_ANALYSE_MARKER} x")
    assert not is_kpi_analyse_message("production 2025")


def test_deterministic_kpi_analyse_period_series():
    from backend.llm.kpi_analyse_fallback import deterministic_kpi_analyse_text

    body = """Référence : production 2025 par mois
Données JSON :
{"question":"production 2025 par mois","result":[{"period":"2025-01","value":100},{"period":"2025-02","value":120}],"_rows_total":2}
"""
    out = deterministic_kpi_analyse_text(body)
    assert "Synthèse" in out
    assert "2025-01" in out or "min" in out.lower()


def test_production_par_epaisseur_top_mentions_thickness_group_by():
    sql = generate_sql("production 2025 par épaisseur top 5")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "NOMINAL_THICKNESS" in u
    assert "GROUPBYEPAISSEUR" in u
    assert "LIMIT5" in u


def test_production_par_largeur_top_mentions_width_group_by():
    sql = generate_sql("production 2025 par largeur top 5")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "NOMINAL_WIDTH_HEAD" in u
    assert "GROUPBYLARGEUR" in u
    assert "LIMIT5" in u


def test_td_month_name_with_year_is_converted_to_yyyy_mm_filter():
    sql = generate_sql("taux de disponibilité en février 2025")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    # After normalization, month should be treated like '2025-02' (not just year 2025)
    assert "2025-02" in sql or "2025-02" in u


def test_azure_provider_td_series_is_tsql():
    import os
    os.environ["DB_PROVIDER"] = "azure"
    sql = generate_sql("taux de disponibilité par mois en 2025")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "CONVERT(CHAR(7),DELAYSTART,126)" in u
    assert "STRFTIME" not in u
    assert "SUBSTR" not in u
    assert "JULIANDAY" not in u


def test_azure_provider_tr_series_is_tsql():
    import os
    os.environ["DB_PROVIDER"] = "azure"
    sql = generate_sql("TR par mois en 2025")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "CONVERT(CHAR(7),DELAYSTART,126)" in u
    assert "STRFTIME" not in u
    assert "SUBSTR" not in u


def test_conso_elec_par_mois_returns_cte_with_group_by_period():
    sql = generate_sql("consommation électrique par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "UNIONALL" in u
    assert '"02_EAF"' in sql or "02_EAF" in sql


def test_conso_elec_sans_par_mois_returns_dict_eaf_lf():
    raw = generate_sql("consommation électrique")
    assert isinstance(raw, dict)
    assert raw.get("type") == "conso_elec"
    assert "eaf" in raw and "lf" in raw
    assert "SUM(TOTAL_ELEC_EGY)" in raw["eaf"]


def test_conso_elec_par_grade_top_returns_group_by_grade():
    sql = generate_sql("consommation électrique par grade top 5")
    assert isinstance(sql, str)
    assert "GROUPBYGRADE" in _compact_upper(sql)


def test_production_par_mois_mentions_group_by_period():
    sql = generate_sql("production par mois")
    assert isinstance(sql, str)
    assert "GROUPBYPERIOD" in _compact_upper(sql)


def test_unknown_question_falls_back_to_select_one():
    raw = generate_sql("question totalement hors sujet xyz123")
    assert isinstance(raw, str)
    assert extract_sql(raw).strip().upper() == "SELECT 1"


def test_conso_elec_with_date_range_adds_between():
    sql = generate_sql("consommation électrique par mois du 2025-01-01 au 2025-03-31")
    assert isinstance(sql, str)
    u = sql.upper()
    assert "BETWEEN" in u
    assert "2025-01-01" in sql
    assert "2025-03-31" in sql


def test_taux_disponibilite_scalar_targets_td():
    sql = generate_sql("taux de disponibilité")
    assert isinstance(sql, str)
    assert "ASTD" in _compact_upper(sql) or "AS TD" in sql.upper()
    assert "EAF_ARRÊTS" in sql.upper() or "EAF_Arrêts".upper() in sql.upper()


def test_taux_disponibilite_par_mois_series():
    sql = generate_sql("taux de disponibilité par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "ASTD" in u or "TD" in u


def test_temps_requis_scalar_contains_tr():
    sql = generate_sql("temps requis")
    assert isinstance(sql, str)
    assert "ASTR" in _compact_upper(sql) or "AS TR" in sql.upper()


def test_temps_requis_par_mois_series():
    sql = generate_sql("temps requis par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "ASTR" in u


def test_mtbf_scalar_contains_mtbf():
    sql = generate_sql("MTBF")
    assert isinstance(sql, str)
    assert "MTBF" in sql.upper()


def test_mtbf_par_mois_group_by_period():
    sql = generate_sql("MTBF par mois")
    assert isinstance(sql, str)
    assert "GROUPBYPERIOD" in _compact_upper(sql)
    assert "MTBF" in sql.upper()


def test_mttr_scalar_contains_mttr():
    sql = generate_sql("MTTR")
    assert isinstance(sql, str)
    assert "MTTR" in sql.upper()


def test_mttr_par_mois_series():
    sql = generate_sql("MTTR par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "MTTR" in sql.upper()


def test_conso_oxygene_par_mois_series():
    sql = generate_sql("consommation oxygène par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "BURNER_TOTALOXY" in u


def test_conso_oxygene_scalar_returns_dict():
    raw = generate_sql("consommation oxygène")
    assert isinstance(raw, dict)
    assert raw.get("type") == "conso_oxygene"
    assert "eaf" in raw
    assert "SUM(BURNER_TOTALOXY)" in raw["eaf"].upper()


def test_conso_gpl_scalar_dict():
    raw = generate_sql("consommation gpl")
    assert isinstance(raw, dict)
    assert raw.get("type") == "conso_gpl"
    assert "SUM(BURNER_TOTALGAS)" in raw["eaf"].upper()


def test_gpl_shorthand_with_year():
    for q in ("gpl 2025", "gpl en 2025", "GPL 2025", "ppl 2025"):
        raw = generate_sql(q)
        assert isinstance(raw, dict), q
        assert raw.get("type") == "conso_gpl", q


def test_kpi_period_span_from_question_year_and_range():
    assert kpi_period_span_from_question("production 2025") == "2025-01-01..2025-12-31"
    assert kpi_period_span_from_question("PRODUCTION 2025") == "2025-01-01..2025-12-31"
    assert kpi_period_span_from_question("du 2025-01-01 au 2025-03-31") == "2025-01-01..2025-03-31"
    assert kpi_period_span_from_question("production en 2025-04") == "2025-04-01..2025-04-30"
    assert kpi_period_span_from_question("production") == ""


def test_nombre_coulees_par_mois():
    sql = generate_sql("nombre de coulées par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "NBCOULEES" in u or "nb_coulees".upper() in u


def test_nombre_coulees_par_grade_top():
    sql = generate_sql("nombre de coulées par grade top 5")
    assert isinstance(sql, str)
    assert "GROUPBY" in _compact_upper(sql)
    assert "GRADE" in sql.upper()


def test_nombre_brames_par_mois():
    sql = generate_sql("nombre de brames par mois")
    assert isinstance(sql, str)
    u = _compact_upper(sql)
    assert "GROUPBYPERIOD" in u
    assert "05_CCM_BRAME" in u or '"05_CCM_Brame"'.upper() in u.upper()


def test_rendement_query_contains_rendement():
    sql = generate_sql("rendement")
    assert isinstance(sql, str)
    assert "RENDEMENT" in sql.upper()


def test_extract_sql_strips_whitespace():
    assert extract_sql("  SELECT 1  \n") == "SELECT 1"
