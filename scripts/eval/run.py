"""Benchmark runner CLI.

    python -m scripts.eval.run --suite synthetic --mode hybrid
    python -m scripts.eval.run --suite longmemeval --data data/longmemeval_s.json \
        --mode hybrid --mode agentic --limit 50 --judge

Runs every requested mode over the same corpus so the modes are compared on
identical inputs, writes a JSON result file for machine comparison, and prints
the markdown table that goes into docs/benchmarks.md.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from pathlib import Path

from scripts.eval.datasets import SUITES, DatasetError, EvalInstance, fingerprint, load
from scripts.eval.harness import Backend, EvalRun, HarnessError
from scripts.eval.metrics import QueryOutcome, RunReport, render_markdown, summarise


def _judge(outcomes: list[QueryOutcome], instances: list[EvalInstance]) -> None:
    """Grade synthesised answers with the configured LLM, in place.

    Uses the same LLM stack the server does, so the judge is configured exactly
    like everything else. Questions without an answer stay unjudged — `None`
    means "not measured", never "wrong".
    """
    from kortex_core.llm.protocol import LlmError, LlmMessage
    from kortex_core.llm.registry import get_llm
    from kortex_core.settings import get_settings

    gold = {q.question_id: q for inst in instances for q in inst.questions}
    settings = get_settings()
    try:
        llm = get_llm(settings.llm_provider)
    except (KeyError, LlmError) as e:
        print(f"  judge unavailable ({e}); accuracy will be reported as not measured")
        return

    system = (
        "You grade whether a candidate answer matches a reference answer. "
        'Reply with JSON {"correct": true|false}. Judge on substance, not '
        "wording: a paraphrase carrying the same facts is correct, an answer "
        "that omits or contradicts the reference is not. An answer that says it "
        "does not know is incorrect."
    )
    schema = {
        "type": "object",
        "required": ["correct"],
        "properties": {"correct": {"type": "boolean"}},
        "additionalProperties": False,
    }

    async def grade(outcome: QueryOutcome) -> bool | None:
        question = gold.get(outcome.question_id)
        if question is None or not outcome.answer:
            return None
        try:
            resp = await llm.complete(
                messages=[
                    LlmMessage(role="system", content=system),
                    LlmMessage(
                        role="user",
                        content=(
                            f"Question: {question.question}\n"
                            f"Reference answer: {question.answer}\n"
                            f"Candidate answer: {outcome.answer}"
                        ),
                    ),
                ],
                model=settings.llm_model_summarizer,
                max_tokens=64,
                temperature=0.0,
                json_schema=schema,
            )
        except LlmError:
            return None
        return bool((resp.structured or {}).get("correct", False))

    async def grade_all() -> list[bool | None]:
        return [await grade(o) for o in outcomes]

    verdicts = asyncio.run(grade_all())
    for index, verdict in enumerate(verdicts):
        outcome = outcomes[index]
        outcomes[index] = QueryOutcome(
            question_id=outcome.question_id,
            category=outcome.category,
            latency_s=outcome.latency_s,
            retrieved_doc_ids=outcome.retrieved_doc_ids,
            gold_doc_ids=outcome.gold_doc_ids,
            answer=outcome.answer,
            judged_correct=verdict,
            used_tokens=outcome.used_tokens,
            error=outcome.error,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.eval.run", description=__doc__)
    parser.add_argument("--suite", choices=SUITES, default="synthetic")
    parser.add_argument(
        "--data", type=Path, help="Downloaded dataset file (not needed for synthetic)"
    )
    parser.add_argument(
        "--mode",
        action="append",
        choices=["hybrid", "agentic"],
        help="Repeatable. Defaults to both, so neither can be quietly omitted.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Cap instances (0 = all)")
    parser.add_argument("--count", type=int, default=50, help="Synthetic suite size")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument(
        "--judge", action="store_true", help="Grade answers with the configured LLM"
    )
    parser.add_argument("--embed-timeout", type=float, default=600.0)
    parser.add_argument("--keep", action="store_true", help="Leave evaluation memories behind")
    parser.add_argument("--out", type=Path, default=Path("eval-results.json"))
    parser.add_argument(
        "--api-url", default=os.environ.get("KORTEX_API_URL", "http://localhost:8000")
    )
    parser.add_argument("--api-key", default=os.environ.get("KORTEX_API_KEY", ""))
    args = parser.parse_args(argv)

    modes = args.mode or ["hybrid", "agentic"]
    if not args.api_key:
        print("error: set KORTEX_API_KEY (or pass --api-key)", file=sys.stderr)
        return 2

    try:
        instances = load(args.suite, args.data, count=args.count)
    except DatasetError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if args.limit:
        instances = instances[: args.limit]
    if not instances:
        print("error: the suite loaded zero instances", file=sys.stderr)
        return 2

    corpus = fingerprint(instances)
    questions = sum(len(i.questions) for i in instances)
    print(
        f"suite={args.suite} instances={len(instances)} questions={questions} "
        f"corpus={corpus} modes={','.join(modes)}"
    )

    backend = Backend(base_url=args.api_url, api_key=args.api_key)
    reports: list[RunReport] = []
    per_mode_outcomes: dict[str, list[dict]] = {}

    for mode in modes:
        print(f"\n[{mode}] running…")
        outcomes: list[QueryOutcome] = []
        warnings: list[str] = []
        try:
            with EvalRun(
                backend,
                mode=mode,
                top_k=args.top_k,
                synthesize=args.judge,
                keep_scope=args.keep,
            ) as run:
                run.preflight()
                for index, instance in enumerate(instances, start=1):
                    got, warning = run.run_instance(instance, embed_timeout_s=args.embed_timeout)
                    outcomes.extend(got)
                    if warning:
                        warnings.append(warning)
                    print(
                        f"  [{mode}] {index}/{len(instances)} "
                        f"{instance.instance_id[:32]} docs={len(instance.documents)}",
                        end="\r",
                    )
        except HarnessError as e:
            print(f"\nerror: {e}", file=sys.stderr)
            return 1
        print()

        if args.judge:
            print(f"  [{mode}] judging {len(outcomes)} answers…")
            _judge(outcomes, instances)

        report = summarise(
            suite=args.suite,
            mode=mode,
            instances=len(instances),
            corpus_fingerprint=corpus,
            outcomes=outcomes,
            judge="llm" if args.judge else "none",
        )
        if warnings:
            report.notes.append(
                f"{len(warnings)} instance(s) were queried before embedding finished; "
                "those answers reflect keyword fallback, not vector search. "
                f"First: {warnings[0]}"
            )
        reports.append(report)
        per_mode_outcomes[mode] = [
            {
                "question_id": o.question_id,
                "category": o.category,
                "latency_s": o.latency_s,
                "retrieved_doc_ids": list(o.retrieved_doc_ids),
                "gold_doc_ids": list(o.gold_doc_ids),
                "first_gold_rank": o.first_gold_rank,
                "judged_correct": o.judged_correct,
                "used_tokens": o.used_tokens,
                "error": o.error,
            }
            for o in outcomes
        ]

    command = (
        f"python -m scripts.eval.run --suite {args.suite}"
        + (f" --data {args.data}" if args.data else "")
        + "".join(f" --mode {m}" for m in modes)
        + (f" --limit {args.limit}" if args.limit else "")
        + (" --judge" if args.judge else "")
    )
    payload = {
        "generated_at": dt.datetime.now(tz=dt.UTC).isoformat(),
        "api_url": args.api_url,
        "command": command,
        "reports": [r.as_dict() for r in reports],
        "outcomes": per_mode_outcomes,
    }
    args.out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")

    table = render_markdown(reports, command=command)
    print("\n" + table)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
