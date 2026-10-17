"""The Journal: applications, interviews, and what the user made of them.

Phase 4. The Coach writes these, one per event, and the application funnel is
computed from them in plain Python (:mod:`head_hunter.funnel`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import StoredRecord, utc_now
from head_hunter.schemas.ids import new_id

JournalEventKind = Literal[
    "applied",
    "screen",
    "interview",
    "next_round",
    "final_round",
    "offer",
    "rejection",
    "withdrawn",
    "note",
]


class JournalEntry(StoredRecord):
    """One event in a job search, plus the user's reflection on it.

    An application is the set of entries that share a ``job_id``. For a job the
    user applied to without ever pasting the posting, ``company`` and ``title``
    stand in for it.
    """

    id: str = Field(default_factory=lambda: new_id("jnl"), description="Entry id.")
    job_id: str | None = Field(
        default=None, description="Posting this concerns, if any."
    )
    company: str | None = Field(
        default=None, description="Hiring company, when there is no saved posting."
    )
    title: str | None = Field(
        default=None, description="Role title, when there is no saved posting."
    )
    kind: JournalEventKind = Field(description="What happened.")
    occurred_at: datetime = Field(
        default_factory=utc_now, description="When it happened."
    )
    summary: str = Field(description="What happened, in one or two lines.")
    reflection: str | None = Field(
        default=None, description="The user's own words on how it went."
    )
    went_well: list[str] = Field(default_factory=list, description="What worked.")
    to_improve: list[str] = Field(default_factory=list, description="What did not.")
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="Evidence captured here, e.g. a story told in a debrief.",
    )
