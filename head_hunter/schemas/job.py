"""A job posting, normalized into structured requirements."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import HeadHunterModel, StoredRecord
from head_hunter.schemas.ids import new_id

PostingSource = Literal["paste", "upload", "email", "search"]
RequirementKind = Literal["required", "preferred"]
RequirementCategory = Literal["skill", "experience", "credential", "location", "other"]


class Requirement(HeadHunterModel):
    """One thing the posting asks for.

    Splitting a posting into these is what makes a fit report possible: each one
    is either met with evidence or unmet with a reason (AGENTS.md rule 3).
    """

    id: str = Field(
        default_factory=lambda: new_id("req"), description="Requirement id."
    )
    text: str = Field(description="The requirement, close to the posting's wording.")
    kind: RequirementKind = Field(description="Hard requirement or nice-to-have.")
    category: RequirementCategory = Field(description="What sort of requirement it is.")


class JobPosting(StoredRecord):
    """A normalized job posting, stored as its own file under ``data/jobs/``."""

    id: str = Field(default_factory=lambda: new_id("job"), description="Job id.")
    source: PostingSource = Field(description="How the posting reached us.")
    company: str | None = Field(default=None, description="Hiring company.")
    title: str | None = Field(default=None, description="Role title.")
    location: str | None = Field(default=None, description="Where the role is based.")
    remote: str | None = Field(
        default=None, description="Remote/hybrid/onsite, as the posting states it."
    )
    comp: str | None = Field(
        default=None, description="Compensation exactly as written, e.g. '$140k-$170k'."
    )
    requirements: list[Requirement] = Field(
        default_factory=list, description="The posting broken into checkable pieces."
    )
    raw_text: str = Field(description="The posting as received, unedited.")
    url: str | None = Field(default=None, description="Where the posting came from.")
