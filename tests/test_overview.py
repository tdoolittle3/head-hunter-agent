"""compute_overview is arithmetic over stored records; pin that arithmetic."""

from __future__ import annotations

from head_hunter.overview import compute_overview
from head_hunter.schemas import (
    FitReport,
    JobPosting,
    OpenQuestion,
    Profile,
    Role,
    Skill,
)

USER = "alice-uid"


def job(
    job_id: str, company: str | None = None, title: str | None = None
) -> JobPosting:
    return JobPosting(
        id=job_id,
        user_id=USER,
        source="paste",
        company=company,
        title=title,
        raw_text="the posting",
    )


def report(job_id: str, score: int) -> FitReport:
    return FitReport(user_id=USER, job_id=job_id, score=score, summary="a read")


def test_a_brand_new_user_gets_an_empty_overview() -> None:
    overview = compute_overview(None, [], [], 0, [])

    assert overview.profile.exists is False
    assert overview.profile.roles == 0
    assert overview.matching.jobs == 0
    assert overview.matching.average_score is None
    assert overview.matching.best is None
    assert overview.funnel.total == 0


def test_profile_counts_come_from_the_profile() -> None:
    profile = Profile(
        user_id=USER,
        roles=[
            Role(company="Acme", title="Engineer"),
            Role(company="Beta", title="Lead"),
        ],
        skills=[Skill(name="Python", level="strong", evidence_ids=["ev1"])],
        open_questions=[OpenQuestion(question="Which database was that migration on?")],
    )

    overview = compute_overview(profile, [], [], 0, [])

    assert overview.profile.exists is True
    assert overview.profile.roles == 2
    assert overview.profile.accomplishments == 0
    assert overview.profile.skills == 1
    assert overview.profile.open_questions == 1


def test_matching_averages_and_names_the_best_posting() -> None:
    jobs = [job("job-a", "Acme", "Engineer"), job("job-b", "Beta", "Lead")]
    reports = [report("job-a", 60), report("job-b", 81)]

    overview = compute_overview(None, jobs, reports, 1, [])

    assert overview.matching.jobs == 2
    assert overview.matching.fit_reports == 2
    # 70.5 rounds to the even neighbour, like every Python round does.
    assert overview.matching.average_score == 70
    assert overview.matching.resumes == 1
    best = overview.matching.best
    assert best is not None
    assert (best.job_id, best.score) == ("job-b", 81)
    assert (best.company, best.title) == ("Beta", "Lead")


def test_a_best_fit_whose_posting_is_gone_still_shows_its_score() -> None:
    overview = compute_overview(None, [], [report("job-x", 55)], 0, [])

    best = overview.matching.best
    assert best is not None
    assert best.score == 55
    assert best.company is None
    assert best.title is None
