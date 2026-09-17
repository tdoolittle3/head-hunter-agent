"""The Intake agent's tools: turning a pasted posting into a stored JobPosting.

The split of labour here follows AGENTS.md rule 4. Stripping site furniture is
deterministic, so :mod:`head_hunter.jd_text` does it in plain Python before the
model ever sees the text. Deciding which sentences are requirements, and whether
each is required or preferred, is judgment, so the model does that and hands the
result back through :func:`save_job_posting`.
"""

from __future__ import annotations

from head_hunter.jd_text import clean_job_text, looks_like_job_posting
from head_hunter.schemas import JobPosting, Requirement
from head_hunter.tools._base import ToolError, current_user_id, repository

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

    job = JobPosting(
        user_id=current_user_id(),
        source="paste",
        company=company,
        title=title,
        location=location,
        remote=remote,
        comp=comp,
        requirements=parsed,
        raw_text=raw_text,
        url=url,
    )
    repository().save_job(job)

    return {
        "status": "saved",
        "job_id": job.id,
        "company": company,
        "title": title,
        "required_count": sum(1 for r in parsed if r.kind == "required"),
        "preferred_count": sum(1 for r in parsed if r.kind == "preferred"),
    }


def list_jobs() -> dict:
    """List the postings already saved, newest first.

    Use this when the user refers to a job without giving you an id.

    Returns:
        Each saved posting's id, company, title, and requirement count.
    """
    jobs = repository().list_jobs(current_user_id())
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
