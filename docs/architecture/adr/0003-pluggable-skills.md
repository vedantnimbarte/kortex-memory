# ADR 0003: Server-side pluggable skills

- **Status:** Accepted
- **Date:** 2026-05-11

## Context

Each tenant has different ideas about what constitutes an "important" memory,
how fast memories should decay, when to consolidate, and how to summarise. We
need plug-points without letting customer code run in our process.

## Decision

Define a small set of **`Protocol`-typed skills** in `kortex_core/skills/`:
`DecayPolicy`, `ImportanceScorer`, `Summarizer`, `Consolidator`, `AccessPolicy`,
`Reranker`. Each ships with a sensible default. Tenants override via subclass +
registry registration; no eval, no in-process plugin loading.

## Consequences

- The orchestrator (`AgenticRetriever`, decay worker, consolidator worker) is small and predictable; per-tenant choices live in dataclass-shaped skill outputs.
- Default implementations are good enough for v0.1 — `ExponentialDecayPolicy`, `HybridScorer`, `LLMSummarizer`, `LLMConsolidator`, `RoleSensitivityPolicy`, `BgeReranker` (with `HeuristicReranker` fallback).
- Future swapping (e.g. `LLMJudge` importance scorer) is a one-class change.
