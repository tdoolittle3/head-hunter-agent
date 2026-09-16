"""The Career Profile and everything nested inside it.

The profile is the source of truth about the user. Agents either add to it or
read from it; none of them keeps private notes (README, "Rules that don't
bend"). It is stored as a single readable JSON file so a non-programmer can open
it and check what the system believes about them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import HeadHunterModel, StoredRecord
from head_hunter.schemas.evidence import Evidence
from head_hunter.schemas.ids import new_id

SkillLevel = Literal["aware", "working", "strong", "expert"]
"""Fixed ladder rather than free text, so fit scoring can compare skills."""

OpenQuestionStatus = Literal["open", "answered", "dropped"]


class Identity(HeadHunterModel):
    """Who the user is, for the header of a resume."""

    full_name: str | None = Field(default=None, description="Name as it should appear.")
    email: str | None = Field(default=None, description="Contact email.")
    phone: str | None = Field(default=None, description="Contact phone.")
    location: str | None = Field(default=None, description="Where they live now.")
    links: list[str] = Field(
        default_factory=list, description="LinkedIn, portfolio, GitHub, and the like."
    )
    headline: str | None = Field(
        default=None, description="One line the user uses to describe themselves."
    )


class Constraints(HeadHunterModel):
    """What the user will and will not accept in a role."""

    locations: list[str] = Field(
        default_factory=list, description="Places they would work."
    )
    remote: Literal["remote", "hybrid", "onsite", "flexible"] | None = Field(
        default=None, description="Working arrangement they need."
    )
    comp_floor: float | None = Field(
        default=None, description="Lowest base compensation they would accept."
    )
    comp_currency: str = Field(default="USD", description="Currency of comp_floor.")
    earliest_start: str | None = Field(
        default=None, description="When they could start, in the user's own words."
    )
    notes: str | None = Field(
        default=None, description="Anything else that rules a role in or out."
    )


class Role(HeadHunterModel):
    """One job the user has held. Accomplishments hang off these."""

    id: str = Field(default_factory=lambda: new_id("role"), description="Role id.")
    company: str = Field(description="Employer or client.")
    title: str = Field(description="Job title as it was actually used.")
    start_date: str | None = Field(default=None, description="Start, e.g. 2021-03.")
    end_date: str | None = Field(
        default=None, description="End, e.g. 2024-11. None means current."
    )
    is_current: bool = Field(default=False, description="Still in this role.")
    location: str | None = Field(default=None, description="Where the role was based.")
    employment_type: str | None = Field(
        default=None, description="Full-time, contract, founder, and so on."
    )
    summary: str | None = Field(
        default=None, description="What the role was, in one or two sentences."
    )


class Accomplishment(HeadHunterModel):
    """Something the user did, in situation / action / result form.

    Carries ``evidence_id`` and a copy of the user's ``source_text``. The
    Interviewer records these only from what the user actually said; anything it
    merely infers becomes an :class:`OpenQuestion` instead (AGENTS.md rule 1).
    """

    id: str = Field(
        default_factory=lambda: new_id("acc"), description="Accomplishment id."
    )
    role_id: str = Field(description="The Role this belongs to.")
    situation: str = Field(description="The problem or context.")
    action: str = Field(description="What the user personally did.")
    result: str = Field(description="What changed because of it.")
    metrics: list[str] = Field(
        default_factory=list,
        description="Numbers the user gave, e.g. 'cut build time 40%'.",
    )
    tools: list[str] = Field(
        default_factory=list, description="Technologies or systems used."
    )
    evidence_id: str = Field(description="The Evidence record this came from.")
    source_text: str = Field(
        description="The user's own words. A convenience copy of the Evidence text."
    )


class Skill(HeadHunterModel):
    """A capability the user has, backed by at least one piece of evidence."""

    name: str = Field(description="The skill, e.g. 'Kubernetes' or 'contract law'.")
    level: SkillLevel = Field(description="How strong they are with it.")
    years: float | None = Field(default=None, description="Years of real use.")
    evidence_ids: list[str] = Field(
        default_factory=list, description="Evidence records that back this up."
    )
    last_used: str | None = Field(
        default=None, description="Roughly when last used, e.g. 2025 or 'current'."
    )


class Education(HeadHunterModel):
    """A degree, certification, or formal program."""

    id: str = Field(default_factory=lambda: new_id("edu"), description="Education id.")
    institution: str = Field(description="School or issuing body.")
    credential: str | None = Field(
        default=None, description="Degree or certification earned."
    )
    field: str | None = Field(default=None, description="Field of study.")
    start_date: str | None = Field(default=None, description="Start, e.g. 2014.")
    end_date: str | None = Field(default=None, description="End or expected end.")
    completed: bool = Field(
        default=True, description="Finished, as opposed to in progress."
    )


class OpenQuestion(HeadHunterModel):
    """Something the agent still needs to ask.

    This is where inferences live. If the Interviewer suspects something but the
    user has not said it, the guess goes in ``hypothesis`` and the question goes
    in ``question`` — it never becomes an Accomplishment or Skill until the user
    confirms it (AGENTS.md rule 1).
    """

    id: str = Field(default_factory=lambda: new_id("q"), description="Question id.")
    question: str = Field(description="What to ask the user next time.")
    hypothesis: str | None = Field(
        default=None,
        description="What the agent suspects but has NOT been told. Never a fact.",
    )
    about_role_id: str | None = Field(
        default=None, description="Role this concerns, if any."
    )
    about_skill: str | None = Field(
        default=None, description="Skill this concerns, if any."
    )
    reason: str | None = Field(
        default=None,
        description="Why this gap matters, e.g. 'no metrics on this role'.",
    )
    status: OpenQuestionStatus = Field(
        default="open", description="Whether still open."
    )


class Profile(StoredRecord):
    """The user's whole career, as the system understands it."""

    identity: Identity = Field(default_factory=Identity, description="Contact details.")
    goals: list[str] = Field(
        default_factory=list, description="What the user wants next, in their words."
    )
    constraints: Constraints = Field(
        default_factory=Constraints, description="What they will and will not accept."
    )
    roles: list[Role] = Field(default_factory=list, description="Jobs held.")
    accomplishments: list[Accomplishment] = Field(
        default_factory=list, description="Confirmed things they did."
    )
    skills: list[Skill] = Field(default_factory=list, description="Confirmed skills.")
    education: list[Education] = Field(
        default_factory=list, description="Degrees and certifications."
    )
    evidence: list[Evidence] = Field(
        default_factory=list, description="Every captured statement, verbatim."
    )
    open_questions: list[OpenQuestion] = Field(
        default_factory=list, description="Gaps and unconfirmed hunches to follow up."
    )

    def evidence_by_id(self, evidence_id: str) -> Evidence | None:
        """Look up one evidence record, or None if it is not there."""
        return next((e for e in self.evidence if e.id == evidence_id), None)

    def is_thin(self) -> bool:
        """Report whether the profile is too sparse to analyse a job against.

        Deterministic on purpose: the coordinator uses this to decide whether to
        steer the user to the Interviewer first, rather than asking a model.
        """
        return not self.roles or len(self.accomplishments) < 3
