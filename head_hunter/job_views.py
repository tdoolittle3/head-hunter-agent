"""What the Jobs page shows: saved postings, each with its fit laid out.

Plain Python on purpose (AGENTS.md rule 4): this joins records other code
already wrote -- postings, fit reports, the profile's evidence -- into exactly
the shape the page draws. The one judgment-free rule it enforces is rule 3's
display side: a met requirement is always shown with the user's own words that
met it.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from head_hunter.schemas import (
    FitReport,
    HeadHunterModel,
    JobPosting,
    Profile,
)


class JobSummary(HeadHunterModel):
    """One row of the jobs list."""

    job_id: str = Field(description="The posting's id.")
    company: str | None = Field(description="Hiring company, if known.")
    title: str | None = Field(description="Role title, if known.")
    location: str | None = Field(description="Where the role is based.")
    remote: str | None = Field(description="Remote/hybrid/onsite, as posted.")
    comp: str | None = Field(description="Compensation as written, if any.")
    saved_at: datetime = Field(description="When the posting was saved.")
    score: int | None = Field(description="Fit score, or None before analysis.")
    has_resume: bool = Field(description="Whether a tailored resume exists.")


class EvidenceQuote(HeadHunterModel):
    """One piece of the user's own words backing a met requirement."""

    id: str = Field(description="The evidence id cited by the fit report.")
    text: str = Field(description="What the user actually said.")


class MetItem(HeadHunterModel):
    """A requirement the user meets, with the words that prove it."""

    requirement: str = Field(description="The requirement, as the posting put it.")
    kind: str = Field(description="required or preferred.")
    note: str | None = Field(description="How the evidence meets it, one line.")
    evidence: list[EvidenceQuote] = Field(description="The cited words.")


class UnmetItem(HeadHunterModel):
    """A requirement the user does not meet."""

    requirement: str = Field(description="The requirement, as the posting put it.")
    kind: str = Field(description="required or preferred.")
    gap: str = Field(description="stretch if learnable, blocker if not.")
    note: str = Field(description="Why it is a stretch or a blocker.")


class JobDetail(HeadHunterModel):
    """Everything the page shows for one posting."""

    job_id: str
    company: str | None
    title: str | None
    location: str | None
    remote: str | None
    comp: str | None
    url: str | None
    saved_at: datetime
    score: int | None = Field(description="Fit score, or None before analysis.")
    summary: str | None = Field(description="The fit report's plain-language read.")
    met: list[MetItem]
    unmet: list[UnmetItem]
    has_resume: bool


def summarize_jobs(
    jobs: list[JobPosting],
    reports: dict[str, FitReport | None],
    jobs_with_resumes: set[str],
) -> list[JobSummary]:
    """One list row per posting, in the order the postings arrived."""
    rows = []
    for job in jobs:
        report = reports.get(job.id)
        rows.append(
            JobSummary(
                job_id=job.id,
                company=job.company,
                title=job.title,
                location=job.location,
                remote=job.remote,
                comp=job.comp,
                saved_at=job.created_at,
                score=report.score if report else None,
                has_resume=job.id in jobs_with_resumes,
            )
        )
    return rows


def _quote(profile: Profile | None, evidence_id: str) -> EvidenceQuote:
    evidence = profile.evidence_by_id(evidence_id) if profile else None
    # A dangling id is a bug worth seeing, not hiding (AGENTS.md rule 6).
    text = evidence.source_text if evidence else "(this evidence is not on file)"
    return EvidenceQuote(id=evidence_id, text=text)


def build_job_detail(
    job: JobPosting,
    report: FitReport | None,
    profile: Profile | None,
    has_resume: bool,
) -> JobDetail:
    """Join one posting with its fit report and the evidence the report cites."""
    met = [
        MetItem(
            requirement=item.requirement.text,
            kind=item.requirement.kind,
            note=item.note,
            evidence=[_quote(profile, ev_id) for ev_id in item.evidence_ids],
        )
        for item in (report.met if report else [])
    ]
    unmet = [
        UnmetItem(
            requirement=item.requirement.text,
            kind=item.requirement.kind,
            gap=item.gap,
            note=item.note,
        )
        for item in (report.unmet if report else [])
    ]
    return JobDetail(
        job_id=job.id,
        company=job.company,
        title=job.title,
        location=job.location,
        remote=job.remote,
        comp=job.comp,
        url=job.url,
        saved_at=job.created_at,
        score=report.score if report else None,
        summary=report.summary if report else None,
        met=met,
        unmet=unmet,
        has_resume=has_resume,
    )
