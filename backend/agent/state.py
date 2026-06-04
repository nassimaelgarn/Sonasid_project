from __future__ import annotations

from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # LangGraph message history (Human/AI messages)
    messages: Annotated[list[Any], add_messages]

    # Request metadata
    session_id: str
    user_question: str
    model_name: str
    actor_name: str

    # RAG context for decision / response
    rag_context: str

    # Router decision: "kpi" | "chat" | "clarify" | "compare"
    intent: str

    # Optional deterministic chat answer decided by router (e.g., greetings)
    answer: str
    source: str

    # For KPI tool execution
    kpi_question: str
    last_kpi_question: str
    last_kpi_period: str  # e.g. "YYYY-MM-DD..YYYY-MM-DD" or "" if not specified

    # For clarify / compare flows
    clarify_message: str
    compare_a: dict
    compare_b: dict

    # Final payload (dict returned by API)
    response: dict

