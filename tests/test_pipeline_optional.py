"""
Tests d'intégration légers sur process_question (nécessite db/sonasid.db).
"""

import os

import pytest

from backend.database.run_query import db_path
from backend.pipeline.pipeline import process_question

pytestmark = pytest.mark.skipif(
    not os.path.isfile(db_path),
    reason=f"Base absente: {db_path}",
)


def test_process_question_conso_elec_par_mois_returns_result_list():
    out = process_question("consommation électrique par mois du 2025-01-01 au 2025-03-31")
    assert isinstance(out, dict)
    assert "result" in out
    assert isinstance(out["result"], list)


def test_process_question_taux_disponibilite_scalar_returns_td_percent():
    out = process_question("taux de disponibilité du 2025-01-01 au 2025-01-31")
    assert isinstance(out, dict)
    assert "TD_percent" in out
    assert isinstance(out["TD_percent"], (int, float))
