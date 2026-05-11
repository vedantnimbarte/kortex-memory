"""``kortex-mcp`` entrypoint.

Subcommands:

    kortex-mcp stdio        # serve over stdin/stdout (default)
    kortex-mcp --help       # show usage

SSE transport lands in M7 as ``kortex-mcp serve --port 8765``.
"""

from __future__ import annotations

import asyncio
import sys

from kortex_core.telemetry.logging import configure_logging


def _usage() -> str:
    return (
        "usage: kortex-mcp <subcommand> [options]\n"
        "\n"
        "Subcommands:\n"
        "  stdio                       Run the MCP server over stdin/stdout.\n"
        "  serve [--host H] [--port P] Run the MCP server over HTTP/SSE.\n"
        "\n"
        "Required environment:\n"
        "  KORTEX_API_KEY      Plaintext kx_* token (stdio only — SSE uses per-request).\n"
        "  KORTEX_DATABASE_URL Async SQLAlchemy DSN to the kortex Postgres.\n"
    )


def _parse_serve_args(argv: list[str]) -> tuple[str, int]:
    host = "0.0.0.0"  # noqa: S104
    port = 8765
    it = iter(argv)
    for token in it:
        if token == "--host":
            host = next(it)
        elif token == "--port":
            port = int(next(it))
        elif token in {"-h", "--help"}:
            raise SystemExit(_usage())
    return host, port


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        sys.stderr.write(_usage())
        return 0 if args else 2

    cmd, *rest = args
    configure_logging()

    if cmd == "stdio":
        from kortex_mcp.transports.stdio import run_stdio

        asyncio.run(run_stdio())
        return 0

    if cmd == "serve":
        from kortex_mcp.transports.sse import run_sse

        host, port = _parse_serve_args(rest)
        run_sse(host=host, port=port)
        return 0

    sys.stderr.write(f"unknown subcommand: {cmd}\n\n{_usage()}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
