"""Guard the eval fixtures.

The blocker-detection eval is only meaningful while the fixture profile really
has no clearance in it. If someone later edits the fixture and adds one, the
eval would quietly start passing for the wrong reason. These checks run without
a model, so they fail fast in CI rather than months later.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from head_hunter.schemas import JobPosting, MetRequirement, Profile, UnmetRequirement
from head_hunter.scoring import BLOCKER_SCORE_CAP, score_fit

EVALS = Path(__file__).resolve().parent.parent / "head_hunter" / "evals"
FIXTURES = EVALS / "fixture_data"
EVAL_SET = EVALS / "blocker_detection.evalset.json"
RESUME_EVAL_SET = EVALS / "no_invented_experience.evalset.json"


def load_profile() -> Profile:
    return Profile.model_validate_json(
        (FIXTURES / "profile.json").read_text(encoding="utf-8")
    )


def load_job() -> JobPosting:
    return JobPosting.model_validate_json(
        (FIXTURES / "jobs" / "job-eval-0001.json").read_text(encoding="utf-8")
    )


def test_fixtures_are_valid_records() -> None:
    assert load_profile().user_id == "local"
    assert load_job().id == "job-eval-0001"


def test_the_profile_says_nothing_about_a_clearance() -> None:
    """The whole point of the case. If this fails, the eval proves nothing."""
    blob = (FIXTURES / "profile.json").read_text(encoding="utf-8").lower()

    for word in ("clearance", "secret", "ts/sci", "polygraph"):
        assert word not in blob, f"fixture profile mentions {word!r}"


def test_the_profile_is_otherwise_strong() -> None:
    """A weak profile would fail the eval for the wrong reason.

    The fixture has to be a strong match on everything except the credential.
    """
    profile = load_profile()

    # Not merely non-empty: a thin profile makes the coordinator stop and ask
    # "shall I run it anyway?" instead of running, which makes the eval flaky.
    assert not profile.is_thin(), (
        "the fixture profile must be rich enough that the coordinator runs the "
        "analysis without stopping to suggest another interview first"
    )
    assert {s.name for s in profile.skills} >= {"Python", "Airflow", "BigQuery"}
    assert all(a.evidence_id for a in profile.accomplishments)


def test_the_posting_has_exactly_one_required_credential() -> None:
    job = load_job()
    credentials = [
        r
        for r in job.requirements
        if r.category == "credential" and r.kind == "required"
    ]

    assert len(credentials) == 1
    assert "clearance" in credentials[0].text.lower()


def test_calling_the_clearance_a_blocker_produces_the_expected_score() -> None:
    """The arithmetic behind the reference answer in the eval set."""
    job = load_job()
    clearance = next(r for r in job.requirements if r.category == "credential")
    others = [r for r in job.requirements if r.id != clearance.id]

    score = score_fit(
        met=[
            MetRequirement(requirement=r, evidence_ids=["ev-eval-0001"]) for r in others
        ],
        unmet=[
            UnmetRequirement(
                requirement=clearance,
                gap="blocker",
                note="Not held; cannot self-obtain.",
            )
        ],
    )

    assert score == BLOCKER_SCORE_CAP == 35


def test_calling_it_a_stretch_would_score_much_higher() -> None:
    """Shows the eval is actually discriminating between the two answers."""
    job = load_job()
    clearance = next(r for r in job.requirements if r.category == "credential")
    others = [r for r in job.requirements if r.id != clearance.id]

    as_stretch = score_fit(
        met=[
            MetRequirement(requirement=r, evidence_ids=["ev-eval-0001"]) for r in others
        ],
        unmet=[
            UnmetRequirement(requirement=clearance, gap="stretch", note="Could pursue.")
        ],
    )

    assert as_stretch > BLOCKER_SCORE_CAP + 30


def test_the_eval_set_parses_and_targets_the_fixture_job() -> None:
    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    case = data["eval_cases"][0]
    prompt = case["conversation"][0]["user_content"]["parts"][0]["text"]
    reference = case["conversation"][0]["final_response"]["parts"][0]["text"].lower()

    assert "job-eval-0001" in prompt
    assert "blocker" in reference
    assert "clearance" in reference


def test_the_resume_eval_set_parses_and_demands_the_omission() -> None:
    """Phase 2's hallucination case, and AGENTS.md's required eval.

    The profile lacks the credential; the right resume leaves it off and says
    so. A reference answer that merely mentioned the clearance would let a
    resume claiming one score well on a similarity metric.
    """
    data = json.loads(RESUME_EVAL_SET.read_text(encoding="utf-8"))
    case = data["eval_cases"][0]
    prompt = case["conversation"][0]["user_content"]["parts"][0]["text"]
    reference = case["conversation"][0]["final_response"]["parts"][0]["text"].lower()

    assert "job-eval-0001" in prompt
    assert "left off" in reference or "does not mention" in reference
    assert "clearance" in reference


def test_the_reference_resume_answer_only_claims_what_the_fixture_supports() -> None:
    """Guards the reference answer itself against drifting into invention.

    Every number it quotes has to be in the fixture profile, or the eval would
    be rewarding the wrong answer.
    """
    profile_blob = (FIXTURES / "profile.json").read_text(encoding="utf-8").lower()
    data = json.loads(RESUME_EVAL_SET.read_text(encoding="utf-8"))
    reference = data["eval_cases"][0]["conversation"][0]["final_response"]["parts"][0][
        "text"
    ].lower()

    for claim in ("nine days to two", "five a week", "acme foods", "airflow"):
        assert claim in reference, f"reference stopped citing {claim!r}"
        assert claim in profile_blob, f"reference claims {claim!r}, profile does not"

    for invented in ("aws", "kubernetes", "snowflake", "kafka"):
        assert invented not in reference


def test_no_eval_output_is_committed_with_the_fixtures() -> None:
    """A committed report or resume would let an eval pass without doing work.

    The Fit Analyst has a `get_fit_report` tool, so a checked-in report for the
    fixture job could be read back instead of the profile being compared to the
    posting -- which is exactly how an earlier version of this eval passed
    while doing no work. The same trap exists for the Resume Tailor: a
    committed resume record already carries a passing `validation`, so
    `render_resume` would produce files without a single bullet being checked.
    Running the evals writes both locally, which is fine and gitignored;
    `make eval` clears them first. Committing them is not.
    """
    tracked = subprocess.run(
        [
            "git",
            "ls-files",
            "head_hunter/evals/fixture_data/fit_reports",
            "head_hunter/evals/fixture_data/resumes",
        ],
        capture_output=True,
        text=True,
        cwd=EVALS.parent.parent,
        check=False,
    )
    if tracked.returncode != 0:
        pytest.skip("not a git checkout")

    assert not tracked.stdout.strip(), (
        "eval output is committed under fixture_data/; remove it with "
        "`git rm --cached` -- a fit report or resume there is output, not a "
        "fixture"
    )
