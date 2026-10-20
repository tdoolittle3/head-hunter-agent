"""The Intake agent's tools: turning a pasted posting into a stored JobPosting.

The split of labour here follows AGENTS.md rule 4. Stripping site furniture is
deterministic, so :mod:`head_hunter.jd_text` does it in plain Python before the
model ever sees the text. Deciding which sentences are requirements, and whether
each is required or preferred, is judgment, so the model does that and hands the
result back through :func:`save_job_posting`.
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from head_hunter.jd_text import clean_job_text, looks_like_job_posting
from head_hunter.schemas import JobPosting, Requirement, new_id
from head_hunter.tools._base import (
    ToolError,
    current_session_id,
    current_user_id,
    repository,
)

REQUIREMENT_KINDS = ("required", "preferred")
REQUIREMENT_CATEGORIES = ("skill", "experience", "credential", "location", "other")


def prepare_job_text(raw_text: str) -> dict:
    """Clean a pasted job description before you read it.

    Call this first. It strips navigation, apply buttons, cookie notices, and
    social share rows in plain Python, so you can focus on the actual posting.

    Args:
        raw_text: The posting exactly as the user pasted it.

    Returns:
        The cleaned text to work from, plus how much was stripped.
    """
    if not looks_like_job_posting(raw_text):
        raise ToolError(
            "That does not look like a full job posting -- it is too short. "
            "Ask the user to paste the whole description, including the "
            "requirements or qualifications section."
        )

    cleaned = clean_job_text(raw_text)
    return {
        "status": "ok",
        "cleaned_text": cleaned,
        "original_characters": len(raw_text),
        "cleaned_characters": len(cleaned),
    }


def save_job_posting(
    raw_text: str,
    requirements: list[dict],
    company: str | None = None,
    title: str | None = None,
    location: str | None = None,
    remote: str | None = None,
    comp: str | None = None,
    url: str | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Save a job posting you have broken into structured requirements.

    Every requirement must be a dict with these keys:
      - ``text``: the requirement, close to the posting's own wording
      - ``kind``: 'required' or 'preferred'
      - ``category``: 'skill', 'experience', 'credential', 'location', or 'other'

    Split compound requirements apart. "5 years of Python and a security
    clearance" is two requirements, one experience and one credential, because
    the user might meet one and not the other.

    Args:
        raw_text: The posting as the user pasted it, unedited.
        requirements: The structured requirement list described above.
        company: Hiring company.
        title: Role title.
        location: Where the role is based.
        remote: Remote, hybrid, or onsite, as the posting states it.
        comp: Compensation exactly as written, e.g. '$140k-$170k'.
        url: Where the posting came from.
        tool_context: Supplied by the system to say whose records these are.
            Never fill this in.

    Returns:
        The new ``job_id``, needed to run a fit analysis.
    """
    if not requirements:
        raise ToolError(
            "A posting with no requirements cannot be scored. Re-read the "
            "description for a qualifications, requirements, or 'what you "
            "bring' section. If there genuinely is none, tell the user."
        )

    parsed: list[Requirement] = []
    for index, item in enumerate(requirements, start=1):
        if not isinstance(item, dict):
            raise ToolError(
                f"Requirement {index} must be a dict with text, kind, and "
                f"category; got {type(item).__name__}."
            )

        text = str(item.get("text", "")).strip()
        kind = str(item.get("kind", "")).strip().lower()
        category = str(item.get("category", "")).strip().lower()

        if not text:
            raise ToolError(f"Requirement {index} has no text.")
        if kind not in REQUIREMENT_KINDS:
            raise ToolError(
                f"Requirement {index} ({text!r}) has kind {kind!r}; "
                f"must be one of {', '.join(REQUIREMENT_KINDS)}."
            )
        if category not in REQUIREMENT_CATEGORIES:
            raise ToolError(
                f"Requirement {index} ({text!r}) has category {category!r}; "
                f"must be one of {', '.join(REQUIREMENT_CATEGORIES)}."
            )

        parsed.append(Requirement(text=text, kind=kind, category=category))

    repo = repository()
    taken = {existing.id for existing in repo.list_jobs(current_user_id(tool_context))}
    job = JobPosting(
        id=new_id("job", taken),
        user_id=current_user_id(tool_context),
        source="paste",
        company=company,
        title=title,
        location=location,
        remote=remote,
        comp=comp,
        requirements=parsed,
        raw_text=raw_text,
        url=url,
        session_id=current_session_id(tool_context),
    )
    repo.save_job(job, create_only=True)

    return {
        "status": "saved",
        "job_id": job.id,
        "company": company,
        "title": title,
        "required_count": sum(1 for r in parsed if r.kind == "required"),
        "preferred_count": sum(1 for r in parsed if r.kind == "preferred"),
    }


def get_job_status(job_id: str, tool_context: ToolContext | None = None) -> dict:
    """Report where one saved job stands, so a session can pick up from it.

    Use this when the user arrives wanting to work on a specific posting — the
    Jobs page opens the chat with a message naming its ``job_id``. It gathers
    what exists for that job in one call: the posting itself, the fit report if
    one has been run, the tailored resume if one has been written, and any
    application events logged for it. From that you can say where things stand
    and offer the next step instead of asking the user to repeat themselves.

    Args:
        job_id: The saved posting, from list_jobs or the user's message.
        tool_context: Supplied by the system to say whose records these are.
            Never fill this in.

    Returns:
        The posting's header, requirement counts, the fit report's score and
        gaps if analysed, the resume's validation state if written, and the
        journal events for the job, newest first.
    """
    repo = repository()
    user_id = current_user_id(tool_context)

    job = repo.get_job(user_id, job_id)
    if job is None:
        raise ToolError(
            f"No saved posting with id {job_id!r}. Call list_jobs to see what "
            "is saved, or ask the user to paste the job description."
        )

    report = repo.get_fit_report(user_id, job_id)
    resume = repo.get_resume(user_id, job_id)
    events = sorted(
        (e for e in repo.list_journal_entries(user_id) if e.job_id == job_id),
        key=lambda e: e.occurred_at,
        reverse=True,
    )

    return {
        "status": "ok",
        "job": {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "remote": job.remote,
            "comp": job.comp,
            "required_count": sum(1 for r in job.requirements if r.kind == "required"),
            "preferred_count": sum(
                1 for r in job.requirements if r.kind == "preferred"
            ),
        },
        "fit_report": None
        if report is None
        else {
            "score": report.score,
            "summary": report.summary,
            "met_count": len(report.met),
            "unmet_count": len(report.unmet),
            "blockers": [u.requirement.text for u in report.blockers],
        },
        "resume": None
        if resume is None
        else {
            "validation_passed": bool(resume.validation and resume.validation.passed),
            "section_count": len(resume.sections),
        },
        "application_events": [
            {
                "kind": e.kind,
                "occurred_at": e.occurred_at.isoformat(),
                "summary": e.summary,
            }
            for e in events
        ],
    }


def list_jobs(tool_context: ToolContext | None = None) -> dict:
    """List the postings already saved, newest first.

    Use this when the user refers to a job without giving you an id.

    Returns:
        Each saved posting's id, company, title, and requirement count.
    """
    jobs = repository().list_jobs(current_user_id(tool_context))
    return {
        "status": "ok",
        "count": len(jobs),
        "jobs": [
            {
                "job_id": j.id,
                "company": j.company,
                "title": j.title,
                "requirement_count": len(j.requirements),
                "saved_at": j.created_at.isoformat(),
            }
            for j in jobs
        ],
    }
