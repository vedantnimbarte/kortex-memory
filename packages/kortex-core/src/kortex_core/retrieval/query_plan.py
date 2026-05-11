"""Structured retrieval plans emitted by the planner LLM.

A plan is a short, validated sequence of steps the agent loop executes against
the hybrid substrate. Steps are deliberately narrow: ``SemanticSearch``,
``KeywordSearch``, ``LinkExpand``, ``TimeFilter``, ``StopAndAnswer``. The
planner cannot escape tenancy — every step is dispatched by Python.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, RootModel


class SemanticSearch(BaseModel):
    type: Literal["semantic_search"] = "semantic_search"
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=100)


class KeywordSearch(BaseModel):
    type: Literal["keyword_search"] = "keyword_search"
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=100)


class LinkExpand(BaseModel):
    """Walk ``memory_links`` from already-collected candidates."""

    type: Literal["link_expand"] = "link_expand"
    link_types: list[
        Literal["related", "derived_from", "supersedes", "contradicts", "part_of"]
    ] = Field(default_factory=lambda: ["related", "derived_from"])
    max_depth: int = Field(default=1, ge=1, le=2)


class TimeFilter(BaseModel):
    type: Literal["time_filter"] = "time_filter"
    after: dt.datetime | None = None
    before: dt.datetime | None = None


class StopAndAnswer(BaseModel):
    type: Literal["stop_and_answer"] = "stop_and_answer"
    reason: str = ""


PlanStep = Annotated[
    SemanticSearch | KeywordSearch | LinkExpand | TimeFilter | StopAndAnswer,
    Field(discriminator="type"),
]


class QueryPlan(BaseModel):
    """The planner's structured output."""

    rationale: str = Field(default="", max_length=500)
    steps: list[PlanStep] = Field(default_factory=list, max_length=8)


# JSON schema used by the LLM adapter for tool-call structured output.
def query_plan_schema() -> dict[str, Any]:
    return QueryPlan.model_json_schema()


# Convenience: parse a structured dict from an LLM into a QueryPlan.
def parse_plan(payload: dict[str, Any] | None) -> QueryPlan:
    if not payload:
        return QueryPlan()
    return QueryPlan.model_validate(payload)


# Trivial root model so we can validate a bare step too (used in tests).
class _StepRoot(RootModel[PlanStep]):
    pass
