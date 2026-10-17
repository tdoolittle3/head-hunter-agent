"""The application funnel: how far each application got, and how it ended.

Plain Python on purpose (AGENTS.md rule 4). The Coach decides what happened and
records it; the counts the graph shows are arithmetic over those records, so the
same journal always draws the same picture.

An *application* is the set of journal entries that share a ``job_id`` (or, when
there is no saved posting, the same company and title). Its fate is read from
its entries:

* the furthest stage it reached sets which column it counts in;
* if its last event is a rejection or a withdrawal, that is how it ended;
* if it reached an offer, it counts as an offer;
* otherwise it is *in progress*, unless nothing has happened for
  ``GHOST_DAYS``, in which case it is *no response*.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field

from head_hunter.schemas import HeadHunterModel, JournalEntry, utc_now

STAGES: tuple[tuple[str, str], ...] = (
    ("applied", "Applied"),
    ("screen", "Recruiter screen"),
    ("interview", "Interview"),
    ("next_round", "Next round"),
    ("final_round", "Final round"),
    ("offer", "Offer"),
)
"""Funnel stages in order: the journal event kind, and the label drawn for it."""

STAGE_RANK = {key: rank for rank, (key, _) in enumerate(STAGES)}

ExitKind = Literal["rejected", "withdrawn", "no_response", "in_progress"]
EXIT_KINDS: tuple[ExitKind, ...] = (
    "rejected",
    "withdrawn",
    "no_response",
    "in_progress",
)

GHOST_DAYS = 21
"""Days of silence after which an unanswered application counts as no response."""


class FunnelStage(HeadHunterModel):
    """One column of the funnel."""

    key: str = Field(description="The journal event kind for this stage.")
    label: str = Field(description="Name shown on the graph.")
    count: int = Field(description="Applications that reached this stage or beyond.")
    exits: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Of the applications whose furthest stage is this one, how many ended "
            "here, by outcome. Empty for the last stage."
        ),
    )


class Funnel(HeadHunterModel):
    """Everything the graph needs, and nothing it has to calculate."""

    total: int = Field(description="Applications counted.")
    ghost_after_days: int = Field(description="Silence threshold for no response.")
    stages: list[FunnelStage] = Field(description="Columns, first to last.")


def application_key(entry: JournalEntry) -> str | None:
    """Say which application an entry belongs to, or None if it cannot be told."""
    if entry.job_id:
        return f"job:{entry.job_id}"
    if entry.company and entry.title:
        return f"role:{entry.company.strip().lower()}|{entry.title.strip().lower()}"
    return None


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _outcome(
    events: list[JournalEntry], now: datetime, ghost_after: timedelta
) -> tuple[int, ExitKind | None]:
    """Return an application's furthest stage and how it ended.

    The second value is None when the application reached an offer, which has no
    exit column.
    """
    furthest = max((STAGE_RANK.get(e.kind, 0) for e in events), default=0)
    last = events[-1]
    if furthest == STAGE_RANK["offer"]:
        return furthest, None
    if last.kind == "rejection":
        return furthest, "rejected"
    if last.kind == "withdrawn":
        return furthest, "withdrawn"
    if now - _aware(last.occurred_at) > ghost_after:
        return furthest, "no_response"
    return furthest, "in_progress"


def group_applications(entries: list[JournalEntry]) -> dict[str, list[JournalEntry]]:
    """Group entries into applications, each in the order things happened.

    Notes and entries that cannot be attached to any application are left out.
    """
    grouped: dict[str, list[JournalEntry]] = {}
    for entry in sorted(entries, key=lambda e: _aware(e.occurred_at)):
        if entry.kind == "note":
            continue
        key = application_key(entry)
        if key is not None:
            grouped.setdefault(key, []).append(entry)
    return grouped


def describe_applications(
    entries: list[JournalEntry],
    now: datetime | None = None,
    ghost_days: int = GHOST_DAYS,
) -> list[dict[str, str | None]]:
    """One line per application: who, how far it got, and where it stands.

    The Coach uses this to find the application a user is talking about before
    logging the next event against it.
    """
    now = _aware(now) if now else utc_now()
    described = []
    for events in group_applications(entries).values():
        furthest, exit_kind = _outcome(events, now, timedelta(days=ghost_days))
        first = events[0]
        company = next((e.company for e in events if e.company), None)
        title = next((e.title for e in events if e.title), None)
        described.append(
            {
                "job_id": first.job_id,
                "company": company,
                "title": title,
                "furthest_stage": STAGES[furthest][1],
                "status": exit_kind or "offer",
                "last_event": events[-1].occurred_at.date().isoformat(),
            }
        )
    return described


def compute_funnel(
    entries: list[JournalEntry],
    now: datetime | None = None,
    ghost_days: int = GHOST_DAYS,
) -> Funnel:
    """Turn journal entries into per-stage counts.

    Args:
        entries: Every journal entry for one user, in any order.
        now: The moment to measure silence against. Defaults to the present.
        ghost_days: Days without an event before an open application counts as
            having had no response.

    Returns:
        A :class:`Funnel` where each stage's count equals the next stage's count
        plus that stage's exits, so the ribbons on the graph always add up.
    """
    now = _aware(now) if now else utc_now()
    ghost_after = timedelta(days=ghost_days)

    grouped = group_applications(entries)

    furthest_counts: Counter[int] = Counter()
    exits: dict[int, Counter[str]] = {rank: Counter() for rank in range(len(STAGES))}
    for events in grouped.values():
        furthest, exit_kind = _outcome(events, now, ghost_after)
        furthest_counts[furthest] += 1
        if exit_kind is not None:
            exits[furthest][exit_kind] += 1

    last_rank = len(STAGES) - 1
    stages = []
    for rank, (key, label) in enumerate(STAGES):
        reached = sum(n for r, n in furthest_counts.items() if r >= rank)
        stages.append(
            FunnelStage(
                key=key,
                label=label,
                count=reached,
                exits=(
                    {} if rank == last_rank else {k: exits[rank][k] for k in EXIT_KINDS}
                ),
            )
        )
    return Funnel(total=len(grouped), ghost_after_days=ghost_days, stages=stages)
