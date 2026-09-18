"""Readable record ids.

AGENTS.md rule 5 says a non-programmer has to be able to read the JSON files, so
ids look like ``acc-20260916-7f3a9c2e`` rather than a raw UUID: you can tell what
kind of thing it is and roughly when it was captured just by looking at it.

The random suffix is wide enough that collisions are not a practical concern. It
used to be two bytes, which sounds like plenty until you do the birthday maths:
a hundred ids sharing a prefix and a date collided about 7% of the time. A
duplicate evidence id makes a citation ambiguous and a duplicate job id lets one
posting overwrite another, so this is a correctness problem, not a tidiness one.
"""

from __future__ import annotations

import secrets
from collections.abc import Container
from datetime import UTC, datetime

_RANDOM_BYTES = 4
"""Eight hex characters: still scannable, ~1 in a million for 100 same-day ids."""

_MAX_ATTEMPTS = 8


def new_id(prefix: str, taken: Container[str] | None = None) -> str:
    """Build a readable, collision-resistant id.

    Args:
        prefix: Short tag for the record type, e.g. ``acc``, ``ev``, ``job``.
        taken: Ids already in use, if the caller knows them. When given, the id
            returned is guaranteed not to be one of them.

    Returns:
        An id of the form ``<prefix>-<YYYYMMDD>-<8 hex chars>``.

    Raises:
        RuntimeError: If a free id could not be found, which should be
            impossible and means something is wrong with ``taken``.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    for _ in range(_MAX_ATTEMPTS):
        candidate = f"{prefix}-{stamp}-{secrets.token_hex(_RANDOM_BYTES)}"
        if taken is None or candidate not in taken:
            return candidate
    raise RuntimeError(
        f"Could not generate an unused {prefix!r} id in {_MAX_ATTEMPTS} attempts."
    )
