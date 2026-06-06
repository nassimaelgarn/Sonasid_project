import os


def test_agent_router_compare_months_from_french_month_names():
    # Ensure agent path is used in app; here we call run_agent directly.
    from backend.agent.graph import run_agent

    res = run_agent(
        question="compare la consommation électrique entre janvier et février 2025",
        session_id="t_months",
        model_name="flash",
    )
    assert isinstance(res, dict)
    assert res.get("source") == "agent:compare_periods"
    assert res.get("period_a", {}).get("range", "").startswith("2025-01-01")
    assert res.get("period_b", {}).get("range", "").startswith("2025-02-01")


def test_agent_router_compare_months_requires_year_when_missing():
    from backend.agent.graph import node_route

    st = {
        "user_question": "compare la consommation électrique entre janvier et février",
        "rag_context": "",
        "model_name": "flash",
        "last_kpi_question": "",
    }
    orig = os.environ.get("DEFAULT_COMPARE_YEAR")
    if "DEFAULT_COMPARE_YEAR" in os.environ:
        del os.environ["DEFAULT_COMPARE_YEAR"]
    try:
        out = node_route(st)
        assert out.get("intent") == "clarify"
        assert "quelle année" in (out.get("clarify_message") or "").lower()
    finally:
        if orig is not None:
            os.environ["DEFAULT_COMPARE_YEAR"] = orig

