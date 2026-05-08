"""``kortex-worker`` entrypoint.

Subcommands:

    kortex-worker worker      # start a celery worker
    kortex-worker beat        # start the celery beat scheduler
    kortex-worker run-once <task>  # run a task once (debug)
"""

from __future__ import annotations

import sys

from kortex_worker.celery_app import celery_app, init


def main() -> int:
    init()
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0

    cmd, *rest = args
    if cmd == "worker":
        # Default to default+embed+slow queues so a single worker covers M2.
        argv = [
            "worker",
            "-Q",
            "default,embed,slow",
            "-l",
            "info",
            "--concurrency",
            "2",
            *rest,
        ]
        celery_app.worker_main(argv=argv)
        return 0
    if cmd == "beat":
        celery_app.start(argv=["beat", "-l", "info", *rest])
        return 0
    if cmd == "run-once":
        if not rest:
            print("usage: kortex-worker run-once <task-name>", file=sys.stderr)
            return 2
        from celery import current_app

        task = current_app.tasks.get(rest[0])
        if task is None:
            print(f"unknown task: {rest[0]}", file=sys.stderr)
            return 2
        result = task.apply()
        print(result.get())
        return 0
    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
