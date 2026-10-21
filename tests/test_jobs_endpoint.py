"""The jobs endpoints serve one user's postings, reports and resume files."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_auth_server import (
    PROJECT,
    WEB_CONFIG,
    FakeRunner,
    bearer,
    claims,
    fake_verifier,
)

from head_hunter import server
from head_hunter.schemas import (
    Evidence,
    FitReport,
    JobPosting,
    JournalEntry,
    MetRequirement,
    Profile,
    Requirement,
    Resume,
    ResumeBullet,
    ResumeSection,
)
from head_hunter.storage import JsonRepository

USER = "alice-uid"


@pytest.fixture
def store(tmp_path: Path) -> JsonRepository:
    return JsonRepository(tmp_path)


@pytest.fixture
def api(store: JsonRepository, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier({"alice-token": claims()}),
        runner=FakeRunner(),
        web_config=WEB_CONFIG,
        repo_factory=lambda: store,
    )
    return TestClient(app)


def saved_job(store: JsonRepository, job_id: str = "job-a") -> JobPosting:
    return store.save_job(
        JobPosting(
            id=job_id,
            user_id=USER,
            source="paste",
            company="Acme",
            title="Engineer",
            raw_text="the posting",
        )
    )


def test_the_jobs_endpoints_require_sign_in(api: TestClient) -> None:
    assert api.get("/api/jobs").status_code == 401
    assert api.get("/api/jobs/job-a").status_code == 401
    assert api.get("/api/jobs/job-a/resume.docx").status_code == 401
    assert api.delete("/api/jobs/job-a").status_code == 401


def test_the_list_carries_scores(api: TestClient, store: JsonRepository) -> None:
    saved_job(store)
    store.save_fit_report(
        FitReport(user_id=USER, job_id="job-a", score=82, summary="Strong")
    )

    rows = api.get("/api/jobs", headers=bearer("alice-token")).json()

    assert [(r["job_id"], r["score"], r["has_resume"]) for r in rows] == [
        ("job-a", 82, False)
    ]


def test_the_detail_quotes_evidence(api: TestClient, store: JsonRepository) -> None:
    saved_job(store)
    store.save_profile(
        Profile(
            user_id=USER,
            evidence=[Evidence(id="ev1", source_text="I cut deploy time by 80%.")],
        )
    )
    store.save_fit_report(
        FitReport(
            user_id=USER,
            job_id="job-a",
            score=82,
            summary="Strong",
            met=[
                MetRequirement(
                    requirement=Requirement(
                        text="CI/CD", kind="required", category="skill"
                    ),
                    evidence_ids=["ev1"],
                )
            ],
        )
    )

    body = api.get("/api/jobs/job-a", headers=bearer("alice-token")).json()

    assert body["met"][0]["evidence"][0]["text"] == "I cut deploy time by 80%."
    assert api.get("/api/jobs/nope", headers=bearer("alice-token")).status_code == 404


def test_a_resume_can_be_downloaded_in_both_formats(
    api: TestClient, store: JsonRepository
) -> None:
    saved_job(store)
    store.save_profile(
        Profile(user_id=USER, evidence=[Evidence(id="ev1", source_text="I did it.")])
    )
    store.save_resume(
        Resume(
            user_id=USER,
            job_id="job-a",
            sections=[
                ResumeSection(
                    title="Acme",
                    bullets=[ResumeBullet(text="Did it.", evidence_ids=["ev1"])],
                )
            ],
        )
    )

    docx = api.get("/api/jobs/job-a/resume.docx", headers=bearer("alice-token"))
    assert docx.status_code == 200
    assert docx.headers["content-type"].startswith(server.DOCX_MEDIA_TYPE)
    assert 'filename="resume-acme-engineer.docx"' in docx.headers["content-disposition"]
    assert docx.content[:2] == b"PK"  # a zip container, like every real .docx

    markdown = api.get("/api/jobs/job-a/resume.md", headers=bearer("alice-token"))
    assert markdown.status_code == 200
    assert "Did it." in markdown.text


def test_removing_a_job_takes_its_report_and_resume(
    api: TestClient, store: JsonRepository
) -> None:
    saved_job(store)
    store.save_fit_report(
        FitReport(user_id=USER, job_id="job-a", score=82, summary="Strong")
    )
    store.save_resume(Resume(user_id=USER, job_id="job-a"))
    store.save_journal_entry(
        JournalEntry(user_id=USER, job_id="job-a", kind="applied", summary="Applied.")
    )

    response = api.delete("/api/jobs/job-a", headers=bearer("alice-token"))

    assert response.status_code == 200
    assert response.json() == {"status": "deleted"}
    assert store.get_job(USER, "job-a") is None
    assert store.get_fit_report(USER, "job-a") is None
    assert store.get_resume(USER, "job-a") is None
    # The record that you applied is not undone by removing the posting.
    assert [e.job_id for e in store.list_journal_entries(USER)] == ["job-a"]
    assert api.get("/api/jobs/job-a", headers=bearer("alice-token")).status_code == 404


def test_removing_a_job_that_is_not_there_is_a_404(api: TestClient) -> None:
    response = api.delete("/api/jobs/nope", headers=bearer("alice-token"))

    assert response.status_code == 404


def test_a_job_without_a_resume_says_so(api: TestClient, store: JsonRepository) -> None:
    saved_job(store)
    store.save_profile(Profile(user_id=USER))

    response = api.get("/api/jobs/job-a/resume.docx", headers=bearer("alice-token"))

    assert response.status_code == 404
    assert "No resume" in response.json()["detail"]
