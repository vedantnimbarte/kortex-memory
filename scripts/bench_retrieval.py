"""Loadtest the /v1/search/recall endpoint.

Usage:

    KORTEX_API_URL=https://kortex.internal \
    KORTEX_API_KEY=kx_... \
    python scripts/bench_retrieval.py --rps 50 --duration 5m \
        --query-file fixtures/queries.txt

Reports per-second throughput and p50/p95/p99 from observed wall-clock samples.
This is deliberately small — for serious campaigns, point a real load tool
(``k6``, ``hey``) at the API. The script exists so M9's loadtest gate
(``recall p99 < 1.2s @ 50 RPS``) can run from a tiny dev box.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time
from collections.abc import Iterable
from pathlib import Path

import httpx

_DEFAULT_QUERIES = [
    "caching strategy",
    "deployment pipeline",
    "auth middleware decision",
    "feature flag rollout",
    "database migration plan",
]


def _parse_duration(s: str) -> int:
    if s.endswith("m"):
        return int(s[:-1]) * 60
    if s.endswith("h"):
        return int(s[:-1]) * 3600
    if s.endswith("s"):
        return int(s[:-1])
    return int(s)


def _load_queries(path: Path | None) -> list[str]:
    if not path:
        return _DEFAULT_QUERIES
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


async def _hammer(
    client: httpx.AsyncClient,
    queries: list[str],
    rps: int,
    duration_s: int,
) -> list[float]:
    samples: list[float] = []
    deadline = time.monotonic() + duration_s
    interval = 1.0 / max(1, rps)
    while time.monotonic() < deadline:
        start = time.monotonic()
        q = random.choice(queries)
        try:
            resp = await client.post(
                "/v1/search/recall",
                json={"query": q},
                timeout=30.0,
            )
            resp.raise_for_status()
        except Exception:
            pass
        elapsed = time.monotonic() - start
        samples.append(elapsed)
        # Pace by inserting a sleep proportional to how fast the request returned.
        gap = interval - elapsed
        if gap > 0:
            await asyncio.sleep(gap)
    return samples


def _summary(samples: Iterable[float]) -> dict[str, float]:
    s = sorted(samples)
    if not s:
        return {"n": 0}
    n = len(s)
    return {
        "n": n,
        "p50": s[int(n * 0.5)],
        "p95": s[min(n - 1, int(n * 0.95))],
        "p99": s[min(n - 1, int(n * 0.99))],
        "mean": statistics.fmean(s),
        "max": s[-1],
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rps", type=int, default=50)
    ap.add_argument("--duration", default="60s")
    ap.add_argument("--query-file", type=Path)
    args = ap.parse_args()

    api_url = os.environ.get("KORTEX_API_URL", "http://localhost:8000")
    api_key = os.environ.get("KORTEX_API_KEY")
    if not api_key:
        print("KORTEX_API_KEY required")
        return 2

    queries = _load_queries(args.query_file)
    headers = {"X-API-Key": api_key}
    async with httpx.AsyncClient(base_url=api_url, headers=headers) as client:
        samples = await _hammer(client, queries, args.rps, _parse_duration(args.duration))

    s = _summary(samples)
    print(
        f"samples={s.get('n', 0)} p50={s.get('p50', 0):.3f}s p95={s.get('p95', 0):.3f}s "
        f"p99={s.get('p99', 0):.3f}s max={s.get('max', 0):.3f}s"
    )
    # Non-zero exit if the SLO budget is busted.
    if s.get("p99", 0) > 1.2:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
