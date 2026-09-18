"""The tools are where the agent design rules are actually enforced.

A prompt can be ignored by a model having a bad day; a tool that refuses to
construct cannot. These tests check the refusals, not the happy path alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from head_hunter.storage import JsonRepository
from head_hunter.tools import (
    ToolError,
    add_accomplishment,
    add_open_question,
    add_role,
    add_skill,
    list_jobs,
    load_job_and_profile,
    load_profile,
    prepare_job_text,
    save_fit_report,
    save_job_posting,
    save_profile,
)

POSTING = """\
Senior Data Engineer at Globex, Remote (US).
About the role: you will own our ingestion and billing pipelines end to end,
working with the finance and platform teams to keep month-end reporting fast.
Requirements: 5+ years building data pipelines, an active Secret clearance,
and strong Airflow experience. Familiarity with BigQuery is preferred.
We offer $180k-$210k depending on experience and a fully remote setup.
"""

QUOTE = "I rewrote the billing pipeline and cut month-end close from nine days to two."


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every tool at a throwaway data directory."""
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HH_USER_ID", "local")


def seeded_role() -> str:
    return add_role(company="Acme Foods", title="Staff Engineer")["role_id"]


def seeded_job() -> dict:
    return save_job_posting(
        raw_text=POSTING,
        company="Globex",
        title="Senior Data Engineer",
        requirements=[
            {
                "text": "5+ years building data pipelines",
                "kind": "required",
                "category": "experience",
            },
            {
                "text": "Active Secret clearance",
                "kind": "required",
                "category": "credential",
            },
            {"text": "BigQuery", "kind": "preferred", "category": "skill"},
        ],
    )


# --- Rule 1: nothing becomes a fact without the user's words ---------------


def test_accomplishment_requires_the_users_own_words() -> None:
    role_id = seeded_role()

    with pytest.raises(ToolError, match="own words"):
        add_accomplishment(
            role_id=role_id,
            situation="s",
            action="a",
            result="r",
            source_text="",
        )


def test_a_throwaway_quote_is_not_evidence() -> None:
    role_id = seeded_role()

    with pytest.raises(ToolError, match="own words"):
        add_accomplishment(
            role_id=role_id, situation="s", action="a", result="r", source_text="yes"
        )


def test_accomplishment_creates_evidence_carrying_the_quote() -> None:
    role_id = seeded_role()
    result = add_accomplishment(
        role_id=role_id,
        situation="Close took nine days.",
        action="Rewrote the pipeline.",
        result="Close dropped to two days.",
        source_text=QUOTE,
        metrics=["9 days to 2 days"],
    )

    assert result["evidence_id"].startswith("ev-")
    assert load_profile()["accomplishment_count"] == 1

    stored = JsonRepository().get_profile("local")
    assert stored is not None
    assert stored.evidence_by_id(result["evidence_id"]).source_text == QUOTE


def test_skill_requires_evidence_and_a_valid_level() -> None:
    with pytest.raises(ToolError, match="own words"):
        add_skill(name="Airflow", level="strong", source_text="")

    with pytest.raises(ToolError, match="level must be one of"):
        add_skill(name="Airflow", level="pretty good", source_text=QUOTE)


def test_accomplishment_rejects_an_unknown_role() -> None:
    with pytest.raises(ToolError, match="No role with id"):
        add_accomplishment(
            role_id="role-nope",
            situation="s",
            action="a",
            result="r",
            source_text=QUOTE,
        )


def test_a_hunch_can_only_be_recorded_as_an_open_question() -> None:
    """The one tool that accepts a guess keeps it out of the fact lists."""
    add_open_question(
        question="Did you lead that rewrite or contribute to it?",
        hypothesis="Sounds like they led it, but they never said so.",
        reason="Scope changes how the bullet can be written.",
    )

    profile = load_profile()
    assert profile["accomplishment_count"] == 0
    assert profile["skills"] == []
    assert profile["open_questions"][0]["hypothesis"].startswith("Sounds like")


# --- Profile basics and persistence ---------------------------------------


def test_load_profile_reports_empty_before_anything_is_saved() -> None:
    assert load_profile()["status"] == "empty"


def test_profile_persists_across_tool_calls() -> None:
    save_profile(full_name="Jordan Reyes", goals=["Staff data platform role."])
    role_id = add_role(company="Acme Foods", title="Staff Engineer")["role_id"]
    add_accomplishment(
        role_id=role_id,
        situation="Close took nine days.",
        action="Rewrote the pipeline.",
        result="Two days.",
        source_text=QUOTE,
    )

    profile = load_profile()
    assert profile["identity"]["full_name"] == "Jordan Reyes"
    assert profile["roles"][0]["accomplishments_recorded"] == 1


def test_save_profile_only_touches_fields_you_pass() -> None:
    save_profile(full_name="Jordan Reyes", goals=["First goal."])
    save_profile(email="jordan@example.com")

    profile = load_profile()
    assert profile["identity"]["full_name"] == "Jordan Reyes"
    assert profile["identity"]["email"] == "jordan@example.com"
    assert profile["goals"] == ["First goal."]


def test_remote_preference_is_validated() -> None:
    with pytest.raises(ToolError, match="remote_preference"):
        save_profile(remote_preference="whenever")


def test_adding_a_known_skill_again_updates_it() -> None:
    add_skill(name="Airflow", level="working", source_text=QUOTE)
    add_skill(name="airflow", level="strong", source_text=QUOTE, years=4)

    skills = load_profile()["skills"]
    assert len(skills) == 1
    assert skills[0]["level"] == "strong"


# --- Intake ---------------------------------------------------------------


def test_short_text_is_not_accepted_as_a_posting() -> None:
    with pytest.raises(ToolError, match="too short"):
        prepare_job_text("Senior Data Engineer at Globex")


def test_prepare_job_text_strips_furniture() -> None:
    result = prepare_job_text("Apply Now\n" + POSTING + "\nShare this job\nFacebook")

    assert "Apply Now" not in result["cleaned_text"]
    assert "5+ years building data pipelines" in result["cleaned_text"]


def test_a_posting_with_no_requirements_is_refused() -> None:
    with pytest.raises(ToolError, match="no requirements cannot be scored"):
        save_job_posting(raw_text=POSTING, requirements=[])


def test_requirement_kind_and_category_are_validated() -> None:
    with pytest.raises(ToolError, match="has kind"):
        save_job_posting(
            raw_text=POSTING,
            requirements=[{"text": "x", "kind": "nice", "category": "skill"}],
        )

    with pytest.raises(ToolError, match="has category"):
        save_job_posting(
            raw_text=POSTING,
            requirements=[{"text": "x", "kind": "required", "category": "vibes"}],
        )


def test_saved_posting_keeps_the_raw_text_and_is_listed() -> None:
    job_id = seeded_job()["job_id"]
    listed = list_jobs()

    assert listed["count"] == 1
    assert listed["jobs"][0]["job_id"] == job_id

    stored = JsonRepository().get_job("local", job_id)
    assert stored.raw_text == POSTING, "the untouched original must be kept"


# --- Fit analysis ---------------------------------------------------------


def seeded_profile_and_job() -> tuple[str, dict]:
    role_id = add_role(company="Acme Foods", title="Staff Engineer")["role_id"]
    add_accomplishment(
        role_id=role_id,
        situation="Close took nine days.",
        action="Rewrote the billing pipeline.",
        result="Close dropped to two days.",
        source_text=QUOTE,
    )
    job_id = seeded_job()["job_id"]
    return job_id, load_job_and_profile(job_id)


def test_fit_analysis_needs_a_profile_to_compare_against() -> None:
    job_id = seeded_job()["job_id"]

    with pytest.raises(ToolError, match="no career profile yet"):
        load_job_and_profile(job_id)


def test_unknown_job_id_is_refused() -> None:
    with pytest.raises(ToolError, match="No saved posting"):
        load_job_and_profile("job-nope")


def test_a_met_requirement_must_cite_evidence() -> None:
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]

    with pytest.raises(ToolError, match="cites no evidence"):
        save_fit_report(
            job_id=job_id,
            met=[{"requirement_id": reqs[0]["requirement_id"], "evidence_ids": []}],
            unmet=[
                {"requirement_id": r["requirement_id"], "gap": "stretch", "note": "n"}
                for r in reqs[1:]
            ],
            summary="s",
        )


def test_every_requirement_must_be_judged() -> None:
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]
    evidence_id = loaded["profile"]["evidence"][0]["evidence_id"]

    with pytest.raises(ToolError, match="Every requirement must be judged"):
        save_fit_report(
            job_id=job_id,
            met=[
                {
                    "requirement_id": reqs[0]["requirement_id"],
                    "evidence_ids": [evidence_id],
                }
            ],
            unmet=[],
            summary="s",
        )


def test_a_requirement_cannot_be_both_met_and_unmet() -> None:
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]
    evidence_id = loaded["profile"]["evidence"][0]["evidence_id"]

    with pytest.raises(ToolError, match="appears more than once"):
        save_fit_report(
            job_id=job_id,
            met=[
                {
                    "requirement_id": r["requirement_id"],
                    "evidence_ids": [evidence_id],
                }
                for r in reqs
            ],
            unmet=[
                {
                    "requirement_id": reqs[0]["requirement_id"],
                    "gap": "stretch",
                    "note": "n",
                }
            ],
            summary="s",
        )


def test_an_unmet_requirement_needs_a_reason() -> None:
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]

    with pytest.raises(ToolError, match="needs a one-line note"):
        save_fit_report(
            job_id=job_id,
            met=[],
            unmet=[
                {"requirement_id": r["requirement_id"], "gap": "stretch", "note": ""}
                for r in reqs
            ],
            summary="s",
        )


def test_the_model_cannot_choose_the_score() -> None:
    """A credential blocker must sink the score no matter what was written."""
    job_id, loaded = seeded_profile_and_job()
    reqs = {r["text"]: r["requirement_id"] for r in loaded["job"]["requirements"]}
    evidence_id = loaded["profile"]["evidence"][0]["evidence_id"]

    result = save_fit_report(
        job_id=job_id,
        met=[
            {
                "requirement_id": reqs["5+ years building data pipelines"],
                "evidence_ids": [evidence_id],
            },
            {"requirement_id": reqs["BigQuery"], "evidence_ids": [evidence_id]},
        ],
        unmet=[
            {
                "requirement_id": reqs["Active Secret clearance"],
                "gap": "blocker",
                "note": "No clearance on record and it cannot be self-obtained.",
            }
        ],
        summary="Strong on pipelines; the clearance is a hard stop.",
    )

    assert result["score"] <= 35
    assert result["blockers"] == ["Active Secret clearance"]


def test_a_met_requirement_cannot_cite_evidence_that_does_not_exist() -> None:
    """The finding that started this: a fabricated id used to score 100/100."""
    job_id, loaded = seeded_profile_and_job()
    reqs = {r["text"]: r["requirement_id"] for r in loaded["job"]["requirements"]}
    real = loaded["profile"]["evidence"][0]["evidence_id"]

    with pytest.raises(ToolError, match="not in the profile"):
        save_fit_report(
            job_id=job_id,
            met=[
                {
                    "requirement_id": reqs["5+ years building data pipelines"],
                    "evidence_ids": [real],
                },
                {"requirement_id": reqs["BigQuery"], "evidence_ids": [real]},
                {
                    "requirement_id": reqs["Active Secret clearance"],
                    "evidence_ids": ["ev-does-not-exist"],
                },
            ],
            unmet=[],
            summary="Perfect fit.",
        )


def test_a_blank_citation_is_not_a_citation() -> None:
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]

    with pytest.raises(ToolError, match="cites no evidence"):
        save_fit_report(
            job_id=job_id,
            met=[{"requirement_id": reqs[0]["requirement_id"], "evidence_ids": ["  "]}],
            unmet=[],
            summary="s",
        )


def test_citations_must_be_a_list_not_a_bare_string() -> None:
    """A string would otherwise be iterated one character at a time."""
    job_id, loaded = seeded_profile_and_job()
    reqs = loaded["job"]["requirements"]
    real = loaded["profile"]["evidence"][0]["evidence_id"]

    with pytest.raises(ToolError, match="single string"):
        save_fit_report(
            job_id=job_id,
            met=[{"requirement_id": reqs[0]["requirement_id"], "evidence_ids": real}],
            unmet=[],
            summary="s",
        )


def test_a_fit_report_needs_a_profile_before_anything_can_be_met() -> None:
    job_id = seeded_job()["job_id"]

    with pytest.raises(ToolError, match="no career profile"):
        save_fit_report(job_id=job_id, met=[], unmet=[], summary="s")
