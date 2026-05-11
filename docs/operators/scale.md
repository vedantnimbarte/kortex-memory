# Scaling

## API

Two scaling signals are wired through the HPA:

- CPU utilization (default 70%)
- Custom Prometheus metric `kortex_api_requests_per_second` (default target 150 RPS/pod)

For traffic over 1k RPS, raise `api.replicas` and `api.hpa.maxReplicas`; sit the
deployment behind a CDN that respects `Cache-Control: private, no-cache`.

## Worker

The worker scales on Redis queue depth (`redis_queue_depth{queue="embed"}` by
default). Bump `worker.hpa.queueDepthTarget` higher to absorb spiky ingestion
without thrashing pods.

## DB

`pgvector` HNSW indexes have non-trivial build cost. When loading >1M memories
in bulk, drop the index, ingest, then `CREATE INDEX` once. The migration
already configures HNSW with `m=16, ef_construction=64`; tune `ef_search` at
query time via `SET hnsw.ef_search = 100`.

## MCP

Stateless. Scale on CPU. For very high concurrent agent count, consider
running multiple MCP deployments behind a hash-based load balancer (per
`Authorization` header) so a single agent's traffic stays on one pod for the
duration of its SSE connection.
