"""The Coach's tools: recording job-search events and reading the funnel back.

The Coach decides what happened and what the user made of it. Counting is not
its job: :func:`get_application_funnel` returns numbers computed in plain Python
by :func:`head_hunter.funnel.compute_funnel`, so the model never tallies
applications itself (AGENTS.md rule 4).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import get_args

from google.adk.tools import ToolContext

from head_hunter.funnel import compute_funnel, describe_applications
from head_hunter.schemas import JournalEntry, utc_now
from head_hunter.schemas.journal import JournalEventKind
from head_hunter.tools._base import ToolError, current_user_id, repository

EVENT_KINDS: tuple[str, ...] = get_args(JournalEventKind)


def _parse_day(value: str | None) -> datetime:
    """Read a ``YYYY-MM-DD`` date the user gave, defaulting to now."""
    if not value:
        return utc_now()
    try:
        day = date.fromisoformat(value.strip()[:10])
    except ValueError:
        raise ToolError(
            f"{value!r} is not a date. Use YYYY-MM-DD, or leave it out if it "
            "happened today."
        ) from None
    moment = datetime.combine(day, time(12, 0), tzinfo=UTC)
    if moment > utc_now():
        raise ToolError(f"{value} is in the future. Ask the user when it happened.")
    return moment


def log_application_event(
    kind: str,
    summary: str,
    job_id: str | None = None,
    company: str | None = None,
    title: str | None = None,
    occurred_on: str | None = None,
    reflection: str | None = None,
    went_well: list[str] | None = None,
    to_improve: list[str] | None = None,
    tool_context: ToolContext | None = None,
) -> dict:
    """Record one thing that happened in an application.

    ``kind`` is one of:
      - ``applied``: the user sent an application
      - ``screen``: a recruiter or phone screen happened
      - ``interview``: the first interview with the team
      - ``next_round``: a second or later interview round
      - ``final_round``: the last round before a decision
      - ``offer``: the user received an offer
      - ``rejection``: the company said no, at any stage
      - ``withdrawn``: the user pulled out
      - ``note``: a reflection that is not a stage change

    Name the application with ``job_id`` when a posting is saved (see
    list_jobs). Otherwise give both ``company`` and ``title``. Use the same
    wording every time for the same application, so events line up.

    Args:
        kind: What happened, from the list above.
        summary: One or two lines, in the user's words where possible.
        job_id: The saved posting this concerns.
        company: Hiring company, if there is no saved posting.
        title: Role title, if there is no saved posting.
        occurred_on: When it happened, as YYYY-MM-DD. Omit for today.
        reflection: How the user felt it went, in their own words.
        went_well: Things that worked, as the user said them.
        to_improve: Things the user wants to do better.
        tool_context: Supplied by the system to say whose records these are.
            Never fill this in.

    Returns:
        The saved entry's id and which application it was filed under.
    """
    kind = kind.strip().lower()
    if kind not in EVENT_KINDS:
        raise ToolError(
            f"Unknown event kind {kind!r}; must be one of {', '.join(EVENT_KINDS)}."
        )
    if not summary.strip():
        raise ToolError("An entry needs a summary of what happened.")

    repo = repository()
    user_id = current_user_id(tool_context)

    if job_id:
        job = repo.get_job(user_id, job_id)
        if job is None:
            raise ToolError(
                f"No saved posting with id {job_id!r}. Call list_jobs, or give "
                "the company and title instead."
            )
        company = company or job.company
        title = title or job.title
    elif not (company and company.strip() and title and title.strip()):
        raise ToolError(
            "Say which application this is: a job_id from list_jobs, or both the "
            "company and the role title. Ask the user if you do not know."
        )

    entry = repo.save_journal_entry(
        JournalEntry(
            user_id=user_id,
            job_id=job_id or None,
            company=company.strip() if company else None,
            title=title.strip() if title else None,
            kind=kind,  # type: ignore[arg-type]
            occurred_at=_parse_day(occurred_on),
            summary=summary.strip(),
            reflection=reflection.strip() if reflection else None,
            went_well=[w.strip() for w in went_well or [] if w.strip()],
            to_improve=[t.strip() for t in to_improve or [] if t.strip()],
        )
    )
    return {
        "status": "saved",
        "entry_id": entry.id,
        "kind": entry.kind,
        "company": entry.company,
        "title": entry.title,
        "occurred_on": entry.occurred_at.date().isoformat(),
    }


def list_applications(tool_context: ToolContext | None = None) -> dict:
    """List every application on record and where each one stands.

    Use this before logging an event, to find the right application and reuse its
    exact company and title wording.

    Returns:
        One line per application: company, title, furthest stage reached, and
        status (rejected, withdrawn, no_response, in_progress, or offer).
    """
    entries = repository().list_journal_entries(current_user_id(tool_context))
    applications = describe_applications(entries)
    return {"status": "ok", "count": len(applications), "applications": applications}


def get_application_funnel(tool_context: ToolContext | None = None) -> dict:
    """Get the counts behind the application funnel graph.

    Quote these numbers exactly. Do not add or estimate any yourself.

    Returns:
        The total, and for each stage how many applications reached it and how
        the rest ended there: rejected, withdrawn, no_response (silent for 21
        days), or in_progress (still waiting).
    """
    entries = repository().list_journal_entries(current_user_id(tool_context))
    funnel = compute_funnel(entries)
    return {"status": "ok", **funnel.model_dump()}
