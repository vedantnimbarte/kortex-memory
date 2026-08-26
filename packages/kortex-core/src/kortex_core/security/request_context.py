"""Who is calling, from where, for the audit log.

The source IP and user agent live at the HTTP boundary, and the things worth
auditing live five layers below it. Threading two parameters through every
service to carry them would mean every future audit site has to remember to
pass them, and the ones that forget produce entries that look complete and are
not.

So they ride a contextvar, set once by the request middleware and read by
:meth:`AuditRepository.append` as a default. A caller with better information
still passes it explicitly; everything else gets it for free.

Outside a request — a worker task, a CLI command — these are simply unset, and
the audit entry records no origin rather than a misleading one.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

client_ip_var: ContextVar[str | None] = ContextVar("kortex_client_ip", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("kortex_user_agent", default=None)

MAX_USER_AGENT = 512
"""Matches the column. A truncated agent is still identifying; an oversized one
is a failed insert in the middle of an audit write."""


def set_origin(ip: str | None, user_agent: str | None) -> tuple[Token, Token]:
    return (
        client_ip_var.set(ip or None),
        user_agent_var.set((user_agent or "")[:MAX_USER_AGENT] or None),
    )


def reset_origin(tokens: tuple[Token, Token]) -> None:
    client_ip_var.reset(tokens[0])
    user_agent_var.reset(tokens[1])


def current_origin() -> tuple[str | None, str | None]:
    return client_ip_var.get(), user_agent_var.get()
