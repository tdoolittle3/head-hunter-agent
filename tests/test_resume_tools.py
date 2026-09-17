"""The Resume Tailor's tools, and the guarantee they carry.

The one that matters: a ``.docx`` cannot exist for a resume that did not pass
the traceability check. Everything else here is the refusals around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from head_hunter.storage import JsonRepository
from head_hunter.tools import (
    ToolError,
    add_accomplishment,
    add_role,
    add_skill,
    load_tailoring_context,
    render_resume,
    save_fit_report,
    save_job_posting,
    save_resume,
)

POSTING = """\
Senior Data Engineer at Globex, Remote (US).
About the role: you will own our ingestion and billing pipelines end to end,
working with the finance and platform teams to keep month-end reporting fast.
Requirements: 5+ years building data pipelines, an active Secret clearance,
and strong Airflow experience. Familiarity with BigQuery is preferred.
We offer $180k-$210k depending on experience and a fully remote setup.
"""

QUOTE = (
    "I rewrote the billing pipeline at Acme as incremental Airflow jobs and cut "
    "month-end close from nine days to two."
)
SKILL_QUOTE = "I have written Python daily for about eight years, mostly data work."


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every tool at a throwaway data directory."""
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HH_USER_ID", "local")


@pytest.fixture
def seeded() -> dict:
    """A profile with one traceable accomplishment, and a posting to target."""
    role_id = add_role(company="Acme Foods", title="Staff Engineer")["role_id"]
    accomplishment = add_accomplishment(
        role_id=role_id,
        situation="Month-end close took nine days.",
        action="Rewrote the billing pipeline as incremental Airflow jobs.",
        result="Close dropped from nine days to two.",
        source_text=QUOTE,
        metrics=["9 days to 2 days"],
        tools=["Python", "Airflow"],
    )
    skill = add_skill(name="Python", level="expert", source_text=SKILL_QUOTE, years=8)
    job = save_job_posting(
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
        ],
    )
    return {
        "job_id": job["job_id"],
        "role_id": role_id,
        "evidence_id": accomplishment["evidence_id"],
        "skill_evidence_id": skill["evidence_id"],
    }


def good_sections(evidence_id: str) -> list[dict]:
    return [
        {
            "title": "Staff Engineer, Acme Foods",
            "subtitle": "2019 – 2024",
            "bullets": [
                {
                    "text": "Rewrote the billing pipeline as incremental Airflow "
                    "jobs, cutting month-end close from 9 days to 2.",
                    "evidence_ids": [evidence_id],
                }
            ],
        }
    ]


# load_tailoring_context -------------------------------------------------


def test_the_context_carries_the_evidence_the_tailor_may_cite(seeded: dict) -> None:
    context = load_tailoring_context(seeded["job_id"])

    assert context["status"] == "ok"
    assert context["job"]["company"] == "Globex"
    assert seeded["evidence_id"] in {
        e["evidence_id"] for e in context["profile"]["evidence"]
    }
    assert context["profile"]["identity"] is not None


def test_the_context_says_when_no_fit_analysis_has_been_run(seeded: dict) -> None:
    assert load_tailoring_context(seeded["job_id"])["fit_report"]["status"] == "none"


def test_the_context_includes_the_fit_report_when_there_is_one(seeded: dict) -> None:
    repo = JsonRepository()
    job = repo.get_job("local", seeded["job_id"])
    save_fit_report(
        job_id=seeded["job_id"],
        met=[
            {
                "requirement_id": job.requirements[0].id,
                "evidence_ids": [seeded["evidence_id"]],
                "note": "Built pipelines for five years.",
            }
        ],
        unmet=[
            {
                "requirement_id": job.requirements[1].id,
                "gap": "blocker",
                "note": "No clearance on record and one cannot be self-obtained.",
            }
        ],
        summary="Strong on pipelines, stopped by the clearance.",
    )

    report = load_tailoring_context(seeded["job_id"])["fit_report"]

    assert report["status"] == "ok"
    assert report["unmet"][0]["gap"] == "blocker"


def test_an_unknown_job_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="No saved posting"):
        load_tailoring_context("job-nope-0000")


def test_a_resume_cannot_be_written_with_no_profile() -> None:
    job = save_job_posting(
        raw_text=POSTING,
        requirements=[{"text": "Python", "kind": "required", "category": "skill"}],
    )
    with pytest.raises(ToolError, match="no career profile"):
        load_tailoring_context(job["job_id"])


# save_resume ------------------------------------------------------------


def test_a_traceable_resume_validates_and_is_stored(seeded: dict) -> None:
    result = save_resume(seeded["job_id"], good_sections(seeded["evidence_id"]))

    assert result["status"] == "validated"
    assert result["passed"] is True
    assert result["checked_bullets"] == 1
    assert result["failures"] == []

    stored = JsonRepository().get_resume("local", seeded["job_id"])
    assert stored is not None
    assert stored.validation.passed


def test_an_invented_claim_comes_back_as_needs_work(seeded: dict) -> None:
    result = save_resume(
        seeded["job_id"],
        [
            {
                "title": "Staff Engineer, Acme Foods",
                "bullets": [
                    {
                        "text": "Holds an active Secret clearance and saved $2M.",
                        "evidence_ids": [seeded["evidence_id"]],
                    }
                ],
            }
        ],
    )

    assert result["status"] == "needs_work"
    assert result["passed"] is False
    assert len(result["failures"]) == 1
    assert "Secret" in result["failures"][0]["reason"]
    assert "save_resume again" in result["next_step"]


def test_the_failed_draft_is_still_readable_on_disk(seeded: dict) -> None:
    """Rule 5: the user can open the file and see what was rejected and why."""
    save_resume(
        seeded["job_id"],
        [
            {
                "title": "Summary",
                "bullets": [
                    {"text": "Ran Kubernetes.", "evidence_ids": [seeded["evidence_id"]]}
                ],
            }
        ],
    )
    stored = JsonRepository().get_resume("local", seeded["job_id"])

    assert stored.validation.passed is False
    assert "Kubernetes" in stored.validation.failures[0].reason


def test_a_bullet_with_no_citation_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="cites no evidence"):
        save_resume(
            seeded["job_id"],
            [
                {
                    "title": "Summary",
                    "bullets": [{"text": "Did things.", "evidence_ids": []}],
                }
            ],
        )


def test_a_section_with_no_bullets_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="no bullets"):
        save_resume(seeded["job_id"], [{"title": "Summary", "bullets": []}])


def test_a_resume_with_no_sections_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="no sections"):
        save_resume(seeded["job_id"], [])


def test_a_resume_for_an_unknown_job_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="No saved posting"):
        save_resume("job-nope-0000", good_sections(seeded["evidence_id"]))


# render_resume ----------------------------------------------------------


def test_rendering_writes_both_files(seeded: dict) -> None:
    save_resume(seeded["job_id"], good_sections(seeded["evidence_id"]))
    result = render_resume(seeded["job_id"])

    assert result["status"] == "rendered"
    markdown_path = Path(result["markdown_path"])
    docx_path = Path(result["docx_path"])

    assert markdown_path.is_file() and docx_path.is_file()
    assert markdown_path.read_text(encoding="utf-8") == result["markdown"]
    assert docx_path.read_bytes()[:2] == b"PK"  # a .docx is a zip
    assert "Staff Engineer, Acme Foods" in result["markdown"]


def test_a_failed_resume_cannot_be_rendered(seeded: dict) -> None:
    """The guarantee. No file exists for a claim the profile does not support."""
    save_resume(
        seeded["job_id"],
        [
            {
                "title": "Summary",
                "bullets": [
                    {
                        "text": "Holds an active Secret clearance.",
                        "evidence_ids": [seeded["evidence_id"]],
                    }
                ],
            }
        ],
    )

    with pytest.raises(ToolError, match="not passed the traceability check"):
        render_resume(seeded["job_id"])

    assert list((JsonRepository().root / "resumes").glob("*.docx")) == []


def test_rendering_before_writing_anything_is_refused(seeded: dict) -> None:
    with pytest.raises(ToolError, match="No resume has been written"):
        render_resume(seeded["job_id"])


def test_a_rerun_that_fails_blocks_rendering_again(seeded: dict) -> None:
    """A resume that passed and was then broken must not stay renderable."""
    save_resume(seeded["job_id"], good_sections(seeded["evidence_id"]))
    render_resume(seeded["job_id"])

    save_resume(
        seeded["job_id"],
        [
            {
                "title": "Summary",
                "bullets": [
                    {
                        "text": "Scaled the platform to 40 million users.",
                        "evidence_ids": [seeded["evidence_id"]],
                    }
                ],
            }
        ],
    )

    with pytest.raises(ToolError, match="not passed the traceability check"):
        render_resume(seeded["job_id"])
