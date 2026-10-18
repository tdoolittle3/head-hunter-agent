"""The bird's-eye view of one person's job search, for the Profile page.

Plain Python on purpose (AGENTS.md rule 4): everything here is counting over
records other code already wrote. The page draws exactly what this returns and
calculates nothing itself.
"""

from __future__ import annotations

from pydantic import Field

from head_hunter.funnel import Funnel, compute_funnel
from head_hunter.schemas import (
    FitReport,
    HeadHunterModel,
    JobPosting,
    JournalEntry,
    Profile,
)


class ProfileStats(HeadHunterModel):
    """How much of a career profile the Interviewer has captured."""

    exists: bool = Field(description="Whether an interview has started at all.")
    roles: int = Field(description="Jobs held.")
    accomplishments: int = Field(description="Evidence-backed accomplishments.")
    skills: int = Field(description="Confirmed skills.")
    open_questions: int = Field(
        description="Gaps the Interviewer still wants to ask about."
    )


class BestFit(HeadHunterModel):
    """The strongest match scored so far."""

    job_id: str = Field(description="The posting it scored against.")
    company: str | None = Field(description="Hiring company, if the posting named it.")
    title: str | None = Field(description="Role title, if the posting named it.")
    score: int = Field(description="Its fit score, 0-100.")


class MatchingStats(HeadHunterModel):
    """How the saved postings compare against the profile."""

    jobs: int = Field(description="Postings saved.")
    fit_reports: int = Field(description="Postings scored against the profile.")
    average_score: int | None = Field(
        description="Mean fit score, or None before the first report."
    )
    best: BestFit | None = Field(
        description="The highest-scoring posting, or None before the first report."
    )
    resumes: int = Field(description="Tailored resumes written.")


class Overview(HeadHunterModel):
    """Everything the Profile page shows, and nothing it has to calculate."""

    profile: ProfileStats
    matching: MatchingStats
    funnel: Funnel


def compute_overview(
    profile: Profile | None,
    jobs: list[JobPosting],
    reports: list[FitReport],
    resumes: int,
    entries: list[JournalEntry],
) -> Overview:
    """Summarize one user's records.

    Args:
        profile: The career profile, or None before the first interview.
        jobs: Every posting saved for the user.
        reports: Every fit report written for those postings.
        resumes: How many tailored resumes exist.
        entries: The whole journal, for the application funnel.
    """
    postings = {job.id: job for job in jobs}
    top = max(reports, key=lambda report: report.score, default=None)
    best = None
    if top is not None:
        posting = postings.get(top.job_id)
        best = BestFit(
            job_id=top.job_id,
            company=posting.company if posting else None,
            title=posting.title if posting else None,
            score=top.score,
        )
    return Overview(
        profile=ProfileStats(
            exists=profile is not None,
            roles=len(profile.roles) if profile else 0,
            accomplishments=len(profile.accomplishments) if profile else 0,
            skills=len(profile.skills) if profile else 0,
            open_questions=len(profile.open_questions) if profile else 0,
        ),
        matching=MatchingStats(
            jobs=len(jobs),
            fit_reports=len(reports),
            average_score=(
                round(sum(r.score for r in reports) / len(reports)) if reports else None
            ),
            best=best,
            resumes=resumes,
        ),
        funnel=compute_funnel(entries),
    )
