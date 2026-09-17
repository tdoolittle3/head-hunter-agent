"""The traceability validator, which is the whole point of Phase 2.

Rule 2 in AGENTS.md is a product promise: the resume can only say things the
profile says. A prompt cannot guarantee that. These tests are what does.

The profile built here has two roles on purpose, so the cross-contamination
case -- a bullet citing one role's evidence while naming the other role's
employer -- is actually reachable.
"""

from __future__ import annotations

import pytest

from head_hunter.resume_validation import validate_resume
from head_hunter.schemas import (
    Accomplishment,
    Evidence,
    Identity,
    Profile,
    Resume,
    ResumeBullet,
    ResumeSection,
    Role,
    Skill,
)

ACME_TEXT = (
    "I rewrote the billing pipeline at Acme as incremental Airflow jobs and "
    "cut month-end close from nine days to two."
)
NORTHWIND_TEXT = (
    "At Northwind I ran the support rotation and got first response time down "
    "from about 40 minutes to under 10."
)
SKILL_TEXT = "I've been writing Python daily for about eight years, mostly data work."


@pytest.fixture
def profile() -> Profile:
    return Profile(
        user_id="local",
        identity=Identity(full_name="Jordan Reyes", location="Denver, CO"),
        roles=[
            Role(
                id="role-acme",
                company="Acme Foods",
                title="Staff Engineer",
                start_date="2019-01",
                end_date="2024-11",
            ),
            Role(
                id="role-northwind",
                company="Northwind",
                title="Support Lead",
                start_date="2016-02",
                end_date="2018-12",
            ),
        ],
        accomplishments=[
            Accomplishment(
                id="acc-acme",
                role_id="role-acme",
                situation="Month-end close took nine days.",
                action="Rewrote the billing pipeline as incremental Airflow jobs.",
                result="Close dropped from nine days to two.",
                metrics=["9 days to 2 days"],
                tools=["Python", "Airflow"],
                evidence_id="ev-acme",
                source_text=ACME_TEXT,
            ),
            Accomplishment(
                id="acc-northwind",
                role_id="role-northwind",
                situation="First response time was about 40 minutes.",
                action="Reorganised the support rotation.",
                result="First response fell to under 10 minutes.",
                metrics=["40 minutes to under 10"],
                tools=[],
                evidence_id="ev-northwind",
                source_text=NORTHWIND_TEXT,
            ),
        ],
        skills=[
            Skill(name="Python", level="expert", years=8, evidence_ids=["ev-skill"])
        ],
        evidence=[
            Evidence(id="ev-acme", source_text=ACME_TEXT),
            Evidence(id="ev-northwind", source_text=NORTHWIND_TEXT),
            Evidence(id="ev-skill", source_text=SKILL_TEXT),
        ],
    )


def one_bullet(text: str, evidence_ids: list[str]) -> Resume:
    return Resume(
        user_id="local",
        job_id="job-1",
        sections=[
            ResumeSection(
                title="Staff Engineer, Acme Foods",
                bullets=[ResumeBullet(text=text, evidence_ids=evidence_ids)],
            )
        ],
    )


def reason(profile: Profile, text: str, evidence_ids: list[str]) -> str:
    result = validate_resume(one_bullet(text, evidence_ids), profile)
    assert not result.passed, f"expected {text!r} to fail"
    assert len(result.failures) == 1
    return result.failures[0].reason


# What must pass ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Rewrote the billing pipeline as incremental Airflow jobs.",
        # The user said "nine days to two"; digits are the same claim.
        "Cut month-end close from 9 days to 2.",
        # And the reverse: evidence in digits, bullet spelled out.
        "Cut month-end close from nine to two days.",
        # An unusual verb at the start of a bullet is grammar, not a name.
        "Spearheaded the rewrite of billing into incremental Airflow jobs.",
        # The employer of the role this evidence belongs to.
        "Rebuilt billing at Acme Foods as incremental Airflow jobs.",
    ],
)
def test_supported_bullets_pass(profile: Profile, text: str) -> None:
    result = validate_resume(one_bullet(text, ["ev-acme"]), profile)
    assert result.passed, [f.reason for f in result.failures]
    assert result.checked_bullets == 1
    assert result.failures == []


def test_a_bullet_may_draw_on_every_citation_it_makes(profile: Profile) -> None:
    resume = one_bullet(
        "Python and Airflow, used to cut month-end close from nine days to two.",
        ["ev-acme", "ev-skill"],
    )
    assert validate_resume(resume, profile).passed


# What must fail ---------------------------------------------------------


def test_an_invented_number_fails(profile: Profile) -> None:
    text = "Cut month-end close by 80%."
    assert "80%" in reason(profile, text, ["ev-acme"])


def test_a_magnitude_cannot_borrow_a_bare_number(profile: Profile) -> None:
    """A sum in millions must not pass because the evidence mentioned "two"."""
    text = "Cut month-end close from nine days to two, saving $2M a year."
    assert "$2M" in reason(profile, text, ["ev-acme"])


def test_an_invented_tool_fails(profile: Profile) -> None:
    text = "Migrated the billing pipeline to Snowflake."
    assert "Snowflake" in reason(profile, text, ["ev-acme"])


def test_an_acronym_the_evidence_never_mentions_fails(profile: Profile) -> None:
    text = "Rebuilt the billing pipeline on AWS."
    assert "AWS" in reason(profile, text, ["ev-acme"])


def test_a_product_name_containing_a_digit_is_not_read_as_a_number(
    profile: Profile,
) -> None:
    """S3 must be checked as a name. Reading it as "3" would let it through."""
    text = "Moved the billing pipeline to S3."
    assert "S3" in reason(profile, text, ["ev-acme"])


def test_another_employers_name_fails(profile: Profile) -> None:
    """The case the whole corpus design exists for."""
    text = "Rewrote the billing pipeline at Northwind."
    assert "Northwind" in reason(profile, text, ["ev-acme"])


def test_a_name_at_the_start_of_a_bullet_is_still_checked(profile: Profile) -> None:
    text = "Northwind billing rebuilt as incremental Airflow jobs."
    assert "Northwind" in reason(profile, text, ["ev-acme"])


def test_a_requirement_the_profile_never_mentions_fails(profile: Profile) -> None:
    """The eval case in Python form: no clearance in, no clearance out."""
    text = "Holds an active Secret security clearance."
    assert "Secret" in reason(profile, text, ["ev-acme"])


def test_an_unknown_evidence_id_fails(profile: Profile) -> None:
    text = "Rewrote the billing pipeline."
    assert "ev-nope" in reason(profile, text, ["ev-nope"])


def test_an_empty_bullet_fails(profile: Profile) -> None:
    assert "empty" in reason(profile, "   ", ["ev-acme"]).lower()


def test_a_bullet_cannot_be_built_without_a_citation() -> None:
    """The schema enforces the half of rule 2 the validator never sees."""
    with pytest.raises(ValueError):
        ResumeBullet(text="Did a thing.", evidence_ids=[])


# The result as a whole --------------------------------------------------


def test_failures_name_the_section_and_the_bullet(profile: Profile) -> None:
    resume = Resume(
        user_id="local",
        job_id="job-1",
        sections=[
            ResumeSection(
                title="Summary",
                bullets=[
                    ResumeBullet(
                        text="Rewrote billing as incremental Airflow jobs.",
                        evidence_ids=["ev-acme"],
                    ),
                    ResumeBullet(
                        text="Saved the company $4M.", evidence_ids=["ev-acme"]
                    ),
                ],
            )
        ],
    )
    result = validate_resume(resume, profile)

    assert result.checked_bullets == 2
    assert len(result.failures) == 1
    assert result.failures[0].section_title == "Summary"
    assert result.failures[0].bullet_text == "Saved the company $4M."


def test_an_empty_resume_passes_vacuously(profile: Profile) -> None:
    result = validate_resume(Resume(user_id="local", job_id="job-1"), profile)
    assert result.passed
    assert result.checked_bullets == 0


def test_validation_is_stable(profile: Profile) -> None:
    """Rule 4: the same input gives the same answer, because it is not a model."""
    resume = one_bullet("Cut close from 9 days to 2 using Kafka.", ["ev-acme"])
    first = validate_resume(resume, profile)
    second = validate_resume(resume, profile)
    assert first == second
