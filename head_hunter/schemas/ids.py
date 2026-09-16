"""Readable record ids.

AGENTS.md rule 5 says a non-programmer has to be able to read the JSON files, so
ids look like ``acc-20260916-7f3a`` rather than a raw UUID: you can tell what
kind of thing it is and roughly when it was captured just by looking at it.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime


def new_id(prefix: str) -> str:
    """Build a readable, collision-resistant id.

    Args:
        prefix: Short tag for the record type, e.g. ``acc``, ``ev``, ``job``.

    Returns:
        An id of the form ``<prefix>-<YYYYMMDD>-<4 hex chars>``.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return f"{prefix}-{stamp}-{secrets.token_hex(2)}"
