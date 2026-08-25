"""Run a benchmark suite against a live Kortex over HTTP.

Deliberately over the API rather than in-process: LongMemEval-V2 scores
accuracy *against latency*, and in-process timings would measure a system
nobody runs. This also means the harness can point at anything — the
one-container image, a compose stack, or a deployed cluster — and the numbers
describe that deployment.

Each instance gets its own project scope so haystacks cannot contaminate each
other, and the scope is deleted afterwards unless --keep is passed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import httpx

from scripts.eval.datasets import Document, EvalInstance, Question
from scripts.eval.metrics import QueryOutcome

# Haystack documents are stored as `event` so the write-path conflict judge
# (which only inspects fact/preference/decision) stays out of the measurement.
# Leaving it in would bill an LLM call per ingested document and time a code
# path the benchmark is not trying to score.
INGEST_KIND = "event"


class HarnessError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Backend:
    base_url: str
    api_key: str
    timeout_s: float = 120.0

    def client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Key": self.api_key, "Accept": "application/json"},
            timeout=self.timeout_s,
        )


class EvalRun:
    """One suite, one mode, against one backend."""

    def __init__(
        self,
        backend: Backend,
        *,
        mode: str = "hybrid",
        top_k: int = 10,
        synthesize: bool = False,
        keep_scope: bool = False,
    ):
        if mode not in ("hybrid", "agentic"):
            raise HarnessError(f"unknown mode {mode!r}; expected hybrid or agentic")
        self._backend = backend
        self._mode = mode
        self._top_k = top_k
        self._synthesize = synthesize
        self._keep = keep_scope
        self._client = backend.client()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EvalRun:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- HTTP plumbing ---

    def _request(self, method: str, path: str, **kw: object) -> dict | list:
        resp = self._client.request(method, path, **kw)  # type: ignore[arg-type]
        if resp.status_code >= 400:
            raise HarnessError(f"{method} {path} -> {resp.status_code}: {resp.text[:400]}")
        return resp.json() if resp.content else {}

    def preflight(self) -> dict:
        """Fail early and clearly rather than midway through a long ingest."""
        try:
            who = self._request("GET", "/v1/auth/whoami")
        except httpx.HTTPError as e:
            raise HarnessError(f"cannot reach {self._backend.base_url}: {e}") from e
        assert isinstance(who, dict)
        return who

    # --- scope lifecycle ---

    def create_scope(self, label: str) -> tuple[str, int]:
        workspaces = self._request("GET", "/v1/workspaces")
        if not isinstance(workspaces, list) or not workspaces:
            raise HarnessError("no workspace available to hold the evaluation project")
        ws = workspaces[0]
        slug = f"eval-{label}-{uuid.uuid4().hex[:6]}".lower()[:64]
        project = self._request(
            "POST",
            f"/v1/workspaces/{ws['public_id']}/projects",
            json={"slug": slug, "name": f"eval {label}"},
        )
        assert isinstance(project, dict)
        return str(project["public_id"]), int(project["id"])

    # --- ingest ---

    def ingest(self, scope_id: int, documents: tuple[Document, ...]) -> dict[str, str]:
        """Store the haystack. Returns {memory public_id: doc_id}.

        The mapping is kept client-side because search responses do not carry
        the memory's metadata, and it is what turns returned memories back into
        the document ids the ground truth is expressed in.
        """
        mapping: dict[str, str] = {}
        for doc in documents:
            created = self._request(
                "POST",
                "/v1/memories",
                json={
                    "scope_type": "project",
                    "scope_id": scope_id,
                    "title": doc.title[:500],
                    "body": doc.body,
                    "kind": INGEST_KIND,
                    "metadata": {"eval_doc_id": doc.doc_id, "eval_ts": doc.timestamp},
                },
            )
            assert isinstance(created, dict)
            mapping[str(created["public_id"])] = doc.doc_id
        return mapping

    def wait_for_embeddings(self, *, timeout_s: float, poll_s: float = 3.0) -> tuple[bool, str]:
        """Block until nothing is queued. Returns (ready, detail).

        Measuring retrieval before the corpus is embedded would score the BM25
        fallback and report it as vector search — the single easiest way to
        publish a wrong number here.
        """
        deadline = time.monotonic() + timeout_s
        detail = "no ingest-status endpoint"
        while time.monotonic() < deadline:
            try:
                status = self._request("GET", "/v1/admin/ingest-status")
            except HarnessError as e:
                return False, f"ingest-status unavailable: {e}"
            assert isinstance(status, dict)
            pending, failed = int(status.get("pending", 0)), int(status.get("failed", 0))
            detail = f"pending={pending} failed={failed}"
            if failed:
                return (
                    False,
                    f"{failed} memories failed to embed — see `kortex admin ingest-status`",
                )
            if pending == 0:
                return True, detail
            time.sleep(poll_s)
        return False, f"timed out after {timeout_s:.0f}s with {detail}"

    # --- query ---

    def ask(self, question: Question, scope_id: int, mapping: dict[str, str]) -> QueryOutcome:
        payload: dict[str, object] = {
            "query": question.question,
            "scopes": [{"scope_type": "project", "scope_id": scope_id}],
        }
        if self._mode == "hybrid":
            path, payload["limit"] = "/v1/search", self._top_k
        else:
            path = "/v1/search/recall"
            payload["synthesize"] = self._synthesize

        started = time.perf_counter()
        try:
            result = self._request("POST", path, json=payload)
        except (HarnessError, httpx.HTTPError) as e:
            return QueryOutcome(
                question_id=question.question_id,
                category=question.category,
                latency_s=time.perf_counter() - started,
                retrieved_doc_ids=(),
                gold_doc_ids=question.gold_doc_ids,
                error=str(e)[:300],
            )
        latency = time.perf_counter() - started
        assert isinstance(result, dict)

        if self._mode == "hybrid":
            items = result.get("hits") or []
            answer = None
        else:
            items = result.get("candidates") or []
            answer = result.get("answer")

        retrieved = tuple(
            mapping[pid]
            for item in items[: self._top_k]
            if (pid := str(item.get("public_id"))) in mapping
        )
        # `usage` lands with issue #12; until then this is honestly zero rather
        # than an estimate dressed up as a measurement.
        usage = result.get("usage") or {}
        return QueryOutcome(
            question_id=question.question_id,
            category=question.category,
            latency_s=latency,
            retrieved_doc_ids=retrieved,
            gold_doc_ids=question.gold_doc_ids,
            answer=str(answer) if answer else None,
            used_tokens=int(usage.get("tokens_in", 0)) + int(usage.get("tokens_out", 0)),
        )

    # --- cleanup ---

    def delete_memories(self, public_ids: list[str]) -> None:
        if self._keep or not public_ids:
            return
        for chunk in (public_ids[i : i + 100] for i in range(0, len(public_ids), 100)):
            try:
                self._request(
                    "POST",
                    "/v1/memories/bulk",
                    json={"action": "delete", "public_ids": chunk},
                )
            except HarnessError:
                # Cleanup is best-effort; a failure here must not lose the run's
                # results, which are the expensive part.
                return

    def run_instance(
        self,
        instance: EvalInstance,
        *,
        embed_timeout_s: float,
    ) -> tuple[list[QueryOutcome], str | None]:
        """Ingest, wait, ask every question, clean up. Returns (outcomes, warning)."""
        _, scope_id = self.create_scope(instance.instance_id[:24])
        mapping = self.ingest(scope_id, instance.documents)
        ready, detail = self.wait_for_embeddings(timeout_s=embed_timeout_s)
        warning = None if ready else f"{instance.instance_id}: {detail}"

        outcomes = [self.ask(q, scope_id, mapping) for q in instance.questions]
        self.delete_memories(list(mapping))
        return outcomes, warning
