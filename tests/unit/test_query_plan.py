"""QueryPlan parsing / validation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kortex_core.retrieval.query_plan import (
    KeywordSearch,
    LinkExpand,
    QueryPlan,
    SemanticSearch,
    StopAndAnswer,
    parse_plan,
    query_plan_schema,
)


def test_parse_empty_payload_returns_empty_plan() -> None:
    plan = parse_plan(None)
    assert isinstance(plan, QueryPlan)
    assert plan.steps == []


def test_parse_full_plan() -> None:
    plan = parse_plan(
        {
            "rationale": "search then expand links",
            "steps": [
                {"type": "semantic_search", "query": "caching", "top_k": 30},
                {"type": "keyword_search", "query": "Redis", "top_k": 20},
                {"type": "link_expand", "link_types": ["related"], "max_depth": 2},
                {"type": "stop_and_answer", "reason": "enough"},
            ],
        }
    )
    assert plan.rationale == "search then expand links"
    assert len(plan.steps) == 4
    assert isinstance(plan.steps[0], SemanticSearch)
    assert isinstance(plan.steps[1], KeywordSearch)
    assert isinstance(plan.steps[2], LinkExpand)
    assert isinstance(plan.steps[3], StopAndAnswer)
    assert plan.steps[2].max_depth == 2


def test_link_expand_rejects_invalid_depth() -> None:
    with pytest.raises(ValidationError):
        parse_plan({"steps": [{"type": "link_expand", "max_depth": 7}]})


def test_query_plan_schema_is_object_schema() -> None:
    schema = query_plan_schema()
    assert schema["type"] == "object"
    assert "steps" in schema["properties"]
