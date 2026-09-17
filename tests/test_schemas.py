"""Every schema must survive a trip through JSON unchanged.

If a model cannot round-trip, the JSON store silently loses data, which is the
one thing the file-backed design cannot tolerate.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from head_hunter.schemas import (
    Accomplishment,
    Constraints,
    Education,
    Evidence,
    FitReport,
    Identity,
    JobPosting,
    JournalEntry,
    MetRequirement,
    OpenQuestion,
    Profile,
    Requirement,
    Resume,
    ResumeBullet,
    ResumeSection,
    Role,
    Skill,
    UnmetRequirement,
    ValidationFailure,
    ValidationResult,
)

EVIDENCE = Evidence(
    id="ev-20260916-aaaa",
    source_text=(
        "I rewrote the billing pipeline and cut month-end close from nine days to two."
    ),
    source="interview",
)

ROLE = Role(
    id="role-20260916-bbbb",
    company="Acme Foods",
    title="Staff Engineer",
    start_date="2021-03",
    end_date="2024-11",
    location="Denver, CO",
    employment_type="full-time",
    summary="Owned the billing and reporting stack.",
)

ACCOMPLISHMENT = Accomplishment(
    id="acc-20260916-cccc",
    role_id=ROLE.id,
    situation="Month-end close took nine days and blocked the finance team.",
    action="Rewrote the billing pipeline as incremental jobs.",
    result="Close dropped to two days.",
    metrics=["9 days to 2 days"],
    tools=["Python", "Airflow", "BigQuery"],
    evidence_id=EVIDENCE.id,
    source_text=EVIDENCE.source_text,
)

SKILL = Skill(
    name="Airflow",
    level="strong",
    years=4.0,
    evidence_ids=[EVIDENCE.id],
    last_used="2024",
)

OPEN_QUESTION = OpenQuestion(
    id="q-20260916-dddd",
    question="Did you lead the billing rewrite, or contribute to it?",
    hypothesis="Sounds like they led it, but they never said so.",
    about_role_id=ROLE.id,
    reason="Scope is unclear and it changes how the bullet can be written.",
)

REQUIREMENT = Requirement(
    id="req-20260916-eeee",
    text="5+ years building data pipelines",
    kind="required",
    category="experience",
)

CREDENTIAL_REQUIREMENT = Requirement(
    id="req-20260916-ffff",
    text="Active Secret clearance",
    kind="required",
    category="credential",
)

PROFILE = Profile(
    user_id="local",
    identity=Identity(full_name="Jordan Reyes", email="jordan@example.com"),
    goals=["Move into a staff-plus data platform role."],
    constraints=Constraints(
        locations=["Denver, CO"], remote="remote", comp_floor=185000
    ),
    roles=[ROLE],
    accomplishments=[ACCOMPLISHMENT],
    skills=[SKILL],
    education=[
        Education(id="edu-20260916-1111", institution="CU Boulder", credential="BS")
    ],
    evidence=[EVIDENCE],
    open_questions=[OPEN_QUESTION],
)

JOB = JobPosting(
    user_id="local",
    id="job-20260916-2222",
    source="paste",
    company="Globex",
    title="Senior Data Engineer",
    location="Remote (US)",
    remote="remote",
    comp="$180k-$210k",
    requirements=[REQUIREMENT, CREDENTIAL_REQUIREMENT],
    raw_text="Globex is hiring a Senior Data Engineer...",
)

FIT_REPORT = FitReport(
    user_id="local",
    job_id=JOB.id,
    score=72,
    met=[MetRequirement(requirement=REQUIREMENT, evidence_ids=[EVIDENCE.id])],
    unmet=[
        UnmetRequirement(
            requirement=CREDENTIAL_REQUIREMENT,
            gap="blocker",
            note="No clearance on record and one cannot be self-obtained.",
        )
    ],
    summary="Strong on the pipeline work; the clearance is a hard stop.",
)

RESUME = Resume(
    user_id="local",
    job_id=JOB.id,
    sections=[
        ResumeSection(
            title="Staff Engineer, Acme Foods",
            subtitle="2021-2024",
            bullets=[
                ResumeBullet(
                    text="Cut month-end close from nine days to two.",
                    evidence_ids=[EVIDENCE.id],
                )
            ],
        )
    ],
    validation=ValidationResult(
        passed=False,
        failures=[
            ValidationFailure(
                section_title="Staff Engineer, Acme Foods",
                bullet_text="Led a team of twelve.",
                reason="Team size does not appear in the cited evidence.",
            )
        ],
        checked_bullets=1,
    ),
)

JOURNAL = JournalEntry(
    user_id="local",
    id="jnl-20260916-3333",
    job_id=JOB.id,
    kind="interview",
    summary="Second round with the platform team.",
    reflection="Felt good until they asked about streaming.",
    went_well=["Pipeline war story landed."],
    to_improve=["Have a streaming answer ready."],
)

ALL_MODELS = [
    EVIDENCE,
    ROLE,
    ACCOMPLISHMENT,
    SKILL,
    OPEN_QUESTION,
    REQUIREMENT,
    PROFILE,
    JOB,
    FIT_REPORT,
    RESUME,
    JOURNAL,
]


@pytest.mark.parametrize("model", ALL_MODELS, ids=lambda m: type(m).__name__)
def test_model_round_trips_through_json(model: BaseModel) -> None:
    restored = type(model).model_validate_json(model.model_dump_json())
    assert restored == model


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Skill.model_validate({"name": "Airflow", "level": "strong", "yeers": 4})


def test_skill_level_is_a_fixed_ladder() -> None:
    with pytest.raises(ValidationError):
        Skill.model_validate({"name": "Airflow", "level": "pretty good"})


def test_met_requirement_must_cite_evidence() -> None:
    with pytest.raises(ValidationError):
        MetRequirement(requirement=REQUIREMENT, evidence_ids=[])


def test_resume_bullet_must_cite_evidence() -> None:
    with pytest.raises(ValidationError):
        ResumeBullet(text="Did a thing.", evidence_ids=[])


def test_fit_score_is_bounded() -> None:
    with pytest.raises(ValidationError):
        FitReport(user_id="local", job_id=JOB.id, score=101, summary="")


def test_blockers_property_filters_stretch_gaps() -> None:
    assert len(FIT_REPORT.blockers) == 1
    assert FIT_REPORT.blockers[0].requirement.category == "credential"


def test_evidence_lookup_finds_and_misses() -> None:
    assert PROFILE.evidence_by_id(EVIDENCE.id) == EVIDENCE
    assert PROFILE.evidence_by_id("ev-does-not-exist") is None


def test_thin_profile_detection() -> None:
    assert Profile(user_id="local").is_thin()
    assert PROFILE.is_thin()  # one accomplishment is still thin

    rich = PROFILE.model_copy(deep=True)
    rich.accomplishments = [ACCOMPLISHMENT] * 3
    assert not rich.is_thin()
