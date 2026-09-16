"""A tailored resume and its traceability validation.

Defined in Phase 0, written in Phase 2. AGENTS.md rule 2: every ``ResumeBullet``
references at least one ``evidence_id``, and ``validate_resume()`` is a plain
Python function that fails a bullet whose claims are not in the cited evidence.
The schema enforces the easy half of that (a bullet cannot have zero citations);
the validator enforces the rest.
"""

from __future__ import annotations

from pydantic import Field

from head_hunter.schemas.base import HeadHunterModel, StoredRecord


class ResumeBullet(HeadHunterModel):
    """One line of a resume, tied to the evidence that supports it."""

    text: str = Field(description="The bullet as it will appear on the page.")
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Evidence supporting every claim in the text. Never empty.",
    )


class ResumeSection(HeadHunterModel):
    """A titled block of bullets, e.g. one role or a skills summary."""

    title: str = Field(description="Section heading, e.g. 'Staff Engineer, Acme'.")
    subtitle: str | None = Field(
        default=None, description="Dates, location, or other secondary line."
    )
    bullets: list[ResumeBullet] = Field(
        default_factory=list, description="The lines in this section."
    )


class ValidationFailure(HeadHunterModel):
    """One bullet that could not be traced, and why."""

    section_title: str = Field(description="Section the bullet is in.")
    bullet_text: str = Field(description="The offending bullet.")
    reason: str = Field(
        description="What could not be supported, e.g. an unsupported number."
    )


class ValidationResult(HeadHunterModel):
    """The outcome of running the traceability validator over a resume."""

    passed: bool = Field(description="True only when there are no failures.")
    failures: list[ValidationFailure] = Field(
        default_factory=list, description="Every bullet that failed, with a reason."
    )
    checked_bullets: int = Field(
        default=0, description="How many bullets were checked."
    )


class Resume(StoredRecord):
    """An ATS-friendly resume written for one specific posting."""

    job_id: str = Field(description="The posting this resume targets.")
    sections: list[ResumeSection] = Field(
        default_factory=list, description="The body of the resume."
    )
    validation: ValidationResult | None = Field(
        default=None, description="Validator outcome. None means not yet checked."
    )
