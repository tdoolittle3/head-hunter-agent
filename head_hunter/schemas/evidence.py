"""Evidence: the user's own words, captured verbatim.

This is the load-bearing model for AGENTS.md rule 1 (evidence-backed profile)
and rule 2 (traceable resumes). Every accomplishment and every skill points at
an ``Evidence`` record, and every resume bullet must eventually trace back here.
Nothing else in the system is allowed to own "what the user actually said".
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from head_hunter.schemas.base import HeadHunterModel, utc_now
from head_hunter.schemas.ids import new_id

EvidenceSource = Literal["interview", "resume_upload", "email", "user_edit"]

EvidenceId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
"""A citation. Blank and whitespace-only ids are rejected at the schema edge, so
a list of citations cannot be padded out with strings that point at nothing.
Whether the id names a real Evidence record is checked where the profile is in
hand -- see ``validate_resume`` and ``save_fit_report``.
"""


class Evidence(HeadHunterModel):
    """A single captured statement from the user, stored in their own words.

    ``source_text`` is lightly cleaned (filler words, false starts) but never
    reworded, summarised, or embellished. If it is not in here, no downstream
    agent may claim it.
    """

    id: str = Field(default_factory=lambda: new_id("ev"), description="Evidence id.")
    source_text: str = Field(
        description="The user's own words, lightly cleaned. Never paraphrased."
    )
    source: EvidenceSource = Field(
        default="interview", description="How this statement was captured."
    )
    captured_at: datetime = Field(
        default_factory=utc_now, description="When the user said it."
    )
    note: str | None = Field(
        default=None,
        description=(
            "Optional context about the capture, e.g. which question prompted it."
        ),
    )
