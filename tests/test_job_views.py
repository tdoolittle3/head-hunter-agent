"""The Jobs page joins are plain Python; pin what they produce."""

from __future__ import annotations

from head_hunter.job_views import build_job_detail, summarize_jobs
from head_hunter.schemas import (
    Evidence,
    FitReport,
    JobPosting,
    MetRequirement,
    Profile,
    Requirement,
    UnmetRequirement,
)

USER = "alice-uid"


def job(job_id: str, **fields: str | None) -> JobPosting:
    return JobPosting(
        id=job_id, user_id=USER, source="paste", raw_text="the posting", **fields
    )


def requirement(text: str, kind: str = "required") -> Requirement:
    return Requirement(text=text, kind=kind, category="skill")


def test_summaries_carry_the_score_and_resume_flag() -> None:
    jobs = [job("job-a", company="Acme", title="Engineer"), job("job-b")]
    reports = {
        "job-a": FitReport(user_id=USER, job_id="job-a", score=82, summary="Strong")
    }

    rows = summarize_jobs(jobs, reports, jobs_with_resumes={"job-b"})

    assert [(r.job_id, r.score, r.has_resume) for r in rows] == [
        ("job-a", 82, False),
        ("job-b", None, True),
    ]
    assert rows[0].company == "Acme"


def test_detail_quotes_the_users_own_words_for_met_requirements() -> None:
    profile = Profile(
        user_id=USER,
        evidence=[Evidence(id="ev1", source_text="I cut deploy time by 80%.")],
    )
    report = FitReport(
        user_id=USER,
        job_id="job-a",
        score=82,
        summary="Strong on delivery.",
        met=[
            MetRequirement(
                requirement=requirement("CI/CD experience"),
                evidence_ids=["ev1"],
                note="Did exactly this at Acme.",
            )
        ],
        unmet=[
            UnmetRequirement(
                requirement=requirement("Active clearance"),
                gap="blocker",
                note="Needs a credential that cannot be learned on the job.",
            )
        ],
    )

    detail = build_job_detail(job("job-a"), report, profile, has_resume=True)

    assert detail.score == 82
    assert detail.met[0].requirement == "CI/CD experience"
    assert detail.met[0].evidence[0].text == "I cut deploy time by 80%."
    assert detail.unmet[0].gap == "blocker"
    assert detail.has_resume is True


def test_a_dangling_evidence_id_is_shown_not_hidden() -> None:
    report = FitReport(
        user_id=USER,
        job_id="job-a",
        score=50,
        summary="",
        met=[
            MetRequirement(requirement=requirement("Python"), evidence_ids=["ev-gone"])
        ],
    )

    detail = build_job_detail(job("job-a"), report, profile=None, has_resume=False)

    assert detail.met[0].evidence[0].text == "(this evidence is not on file)"


def test_an_unanalysed_job_has_no_score_and_no_lists() -> None:
    detail = build_job_detail(job("job-a"), None, None, has_resume=False)

    assert detail.score is None
    assert detail.summary is None
    assert detail.met == [] and detail.unmet == []


def test_status_comes_from_the_journal_and_defaults_to_not_applied() -> None:
    from head_hunter.job_views import job_statuses
    from head_hunter.schemas import JournalEntry

    def event(job_id: str, kind: str) -> JournalEntry:
        return JournalEntry(user_id=USER, job_id=job_id, kind=kind, summary=kind)

    entries = [
        event("job-a", "applied"),
        event("job-a", "interview"),
        event("job-b", "applied"),
        event("job-b", "rejection"),
        event("job-c", "offer"),
    ]
    statuses = job_statuses(entries)
    rows = summarize_jobs(
        [job("job-a"), job("job-b"), job("job-c"), job("job-d")],
        {},
        set(),
        statuses,
    )

    assert [(r.status.label, r.status.tone) for r in rows] == [
        ("Interview", "active"),
        ("Rejected", "closed"),
        ("Offer", "offer"),
        ("Not applied", "none"),
    ]
