# ADR 0001: Use Postgres + pgvector with HNSW for vector storage

- **Status:** Accepted
- **Date:** 2026-05-08

## Context

We need vector similarity search with multi-tenant isolation, transactional
writes alongside relational data (memories ↔ links ↔ scopes ↔ access policies),
and the ability to run the whole thing on a single managed Postgres in dev and
prod. Dedicated vector DBs (Pinecone, Weaviate, Qdrant) all force a sync seam
between SQL and vectors, plus a second backup/RBAC story.

## Decision

Use **Postgres 16 + pgvector ≥ 0.7**, with **HNSW** indexes (`m=16,
ef_construction=64`, cosine distance). All vector ops live in the same DB as
memories/links/attachments, behind the same tenant chokepoint.

## Consequences

- One backup story (`pg_dump` + WAL archive), one ACL story, one transaction model.
- HNSW build cost is non-trivial for >1M rows — the M9 runbook covers bulk-load patterns (drop index, ingest, rebuild).
- We're tied to Postgres' planner; for hybrid queries (vector + BM25) we hand-write SQL because that's where the planner's tuning starts to matter.
- Migrating to a dedicated vector DB later is feasible (the `Embedder` and `MemoryRepository.hybrid_search` seams are clean), but for v0.1 the simplicity wins.
