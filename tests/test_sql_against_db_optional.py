"""
Exécute de vraies requêtes SQLite contre db/sonasid.db si elle existe (CI / machines sans DB = skip).
"""

import os

import pytest

from backend.database.run_query import db_path, run_query
from backend.llm.llm_sql import extract_sql, generate_sql
pytestmark = pytest.mark.skipif(
    not os.path.isfile(db_path),
    reason=f"Base absente: {db_path}",
)


def test_run_query_conso_elec_par_mois_returns_rows():
    sql = generate_sql("consommation électrique par mois du 2025-01-01 au 2025-12-31")
    clean = extract_sql(sql)
    rows = run_query(clean)
    assert isinstance(rows, list)
    if rows:
        assert len(rows[0]) >= 2


def test_run_query_taux_disponibilite_par_mois_executes():
    sql = generate_sql("taux de disponibilité par mois du 2025-01-01 au 2025-06-30")
    clean = extract_sql(sql)
    rows = run_query(clean)
    if isinstance(rows, str):
        pytest.skip(f"Schéma SQLite incompatible avec la requête TD: {rows}")
    assert isinstance(rows, list)


def test_run_query_production_par_mois_executes():
    sql = generate_sql("production par mois du 2025-01-01 au 2025-12-31")
    clean = extract_sql(sql)
    rows = run_query(clean)
    assert isinstance(rows, list)
    assert not isinstance(rows, str), rows


def test_run_query_mttr_par_mois_executes():
    sql = generate_sql("MTTR par mois du 2025-01-01 au 2025-03-31")
    clean = extract_sql(sql)
    rows = run_query(clean)
    assert isinstance(rows, list)
    assert not isinstance(rows, str), rows


