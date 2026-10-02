"""Shared plumbing for the agent tools.

AGENTS.md rule 6 says tools raise and agents tell the user what failed. Those
are two separate obligations, and ADK only gives you the first for free: a tool
that raises with no ``on_tool_error_callback`` registered takes the whole
invocation down with a stack trace, which tells the user nothing.

Verified against ADK 2.9.1 by running both cases. With
:func:`report_tool_error` attached, the model receives the message and relays
it ("I was not able to ... the error message was ..."), which is what rule 6
actually asks for.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from head_hunter import config
from head_hunter.storage import JsonRepository, Repository


class ToolError(RuntimeError):
    """A tool could not do what was asked.

    The message is written for the model to read and relay, so it says what
    went wrong *and* what would fix it.
    """


def report_tool_error(
    tool: Any, args: dict[str, Any], tool_context: Any, error: Exception
) -> dict[str, str]:
    """Turn a raised tool error into something the model can explain.

    Attach as ``on_tool_error_callback`` on every agent. Without it the
    exception escapes the invocation and the user just sees the run die.
    """
    return {
        "error": str(error),
        "tool": getattr(tool, "name", "unknown"),
        "guidance": (
            "Tell the user plainly what failed and what you need from them. "
            "Do not retry with invented values."
        ),
    }


def repository() -> Repository:
    """Return the repository the tools should read and write through.

    ``HH_STORAGE`` picks the backend. It defaults to the JSON store, so a
    checkout with no Google Cloud project still runs; deployments set
    ``firestore``, because a Cloud Run filesystem does not survive a restart.
    """
    if config.storage_backend() == "firestore":
        from head_hunter.storage import FirestoreRepository

        return FirestoreRepository()
    return JsonRepository()


def current_user_id(tool_context: ToolContext | None = None) -> str:
    """Return the user id every stored record is keyed by.

    ``HH_SINGLE_USER``, when set, pins everyone to one profile: that is the
    local and private-test setup. Otherwise the id comes from the ADK session,
    which is where a verified identity will arrive once auth is in front of the
    service.

    The id is never a tool argument. If it were, the model could be talked into
    asking for someone else's profile.
    """
    pinned = config.single_user()
    if pinned:
        return pinned
    user_id = getattr(tool_context, "user_id", None)
    if not user_id:
        raise ToolError(
            "Cannot tell whose profile this is: the session carries no user id "
            "and HH_SINGLE_USER is not set."
        )
    return user_id
