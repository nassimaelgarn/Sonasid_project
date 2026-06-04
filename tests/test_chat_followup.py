import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.llm.llm_sql import (
    is_period_only_followup_text,
    merge_need_period_followup_from_history,
    question_has_explicit_period,
)


def test_consommation_gpl_has_no_explicit_period_for_agent_merge():
    assert not question_has_explicit_period("consommation gpl")


def test_is_period_only_followup_text():
    assert is_period_only_followup_text("2025")
    assert is_period_only_followup_text("2025-01")
    assert not is_period_only_followup_text("gpl 2025")
    assert not is_period_only_followup_text("")


def test_merge_need_period_followup_from_history():
    need_msg = "Pour ce KPI, il me manque une période.\nPrécise par exemple."
    prior = [
        {"role": "user", "content": "gpl"},
        {"role": "assistant", "content": need_msg},
    ]
    assert merge_need_period_followup_from_history("2025", prior) == "gpl 2025"

    assert merge_need_period_followup_from_history("gpl 2025", prior) == "gpl 2025"
    assert merge_need_period_followup_from_history("ok merci", prior) == "ok merci"

    prior2 = [{"role": "user", "content": "hello"}]
    assert merge_need_period_followup_from_history("2025", prior2) == "2025"


def test_merge_when_assistant_need_period_not_at_start():
    prior = [
        {"role": "user", "content": "gpl"},
        {"role": "assistant", "content": "Note\nPour ce KPI, il me manque une période.\nSuite"},
    ]
    assert merge_need_period_followup_from_history("2025", prior) == "gpl 2025"


def test_merge_when_only_prior_user_no_assistant_row():
    prior = [{"role": "user", "content": "gpl"}]
    assert merge_need_period_followup_from_history("2025", prior) == "gpl 2025"

