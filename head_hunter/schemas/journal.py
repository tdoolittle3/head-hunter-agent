"""The Journal: applications, interviews, and what the user made of them.

Defined in Phase 0, used in Phase 4 by the Coach. Nothing reads or writes these
yet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import StoredRecord, utc_now
from head_hunter.schemas.ids import new_id

JournalEventKind = Literal[
    "applied", "screen", "interview", "offer", "rejection", "withdrawn", "note"
]


class JournalEntry(StoredRecord):
    """One event in a job search, plus the user's reflection on it."""

    id: str = Field(default_factory=lambda: new_id("jnl"), description="Entry id.")
    job_id: str | None = Field(
        default=None, description="Posting this concerns, if any."
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
