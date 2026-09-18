"""The Fit Report: how well the profile matches one posting.

AGENTS.md rule 3: every met requirement cites the evidence that meets it, and
every unmet requirement is tagged ``stretch`` (learnable, adjacent) or
``blocker`` (credential, clearance, hard years-of-experience). The ``score`` is
computed by a deterministic Python function in Phase 1, never chosen by a model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import HeadHunterModel, StoredRecord
from head_hunter.schemas.evidence import EvidenceId
from head_hunter.schemas.job import Requirement

GapKind = Literal["stretch", "blocker"]


class MetRequirement(HeadHunterModel):
    """A requirement the user meets, with the evidence that proves it."""

    requirement: Requirement = Field(description="The requirement being met.")
    evidence_ids: list[EvidenceId] = Field(
        min_length=1, description="Evidence backing this. Never empty."
    )
    note: str | None = Field(
        default=None, description="One line on how the evidence meets it."
    )


class UnmetRequirement(HeadHunterModel):
    """A requirement the user does not meet, and how hard that is to fix."""

    requirement: Requirement = Field(description="The requirement not met.")
    gap: GapKind = Field(description="stretch if learnable, blocker if not.")
    note: str = Field(description="One line on why it is a stretch or a blocker.")


class FitReport(StoredRecord):
    """A scored comparison of one profile against one posting."""

    job_id: str = Field(description="The posting this report is about.")
    score: int = Field(ge=0, le=100, description="Computed fit score, 0-100.")
    met: list[MetRequirement] = Field(
        default_factory=list, description="Requirements met, each with evidence."
    )
    unmet: list[UnmetRequirement] = Field(
        default_factory=list, description="Requirements not met, each tagged."
    )
    summary: str = Field(description="Plain-language read on the fit.")

    @property
    def blockers(self) -> list[UnmetRequirement]:
        """Return only the gaps that cannot be talked around."""
        return [u for u in self.unmet if u.gap == "blocker"]
