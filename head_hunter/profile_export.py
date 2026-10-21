"""The career profile as one Markdown document the user can read and edit.

Plain Python on purpose (AGENTS.md rule 4): everything the system holds about
the user goes out, nothing is summarised, and the user's own words are quoted
exactly. The file comes back in through the chat's Upload button like any other
document, so the first line is a fixed marker the agents recognise.
"""

from __future__ import annotations

from head_hunter.schemas import Profile
from head_hunter.schemas.profile import Accomplishment, Role

EXPORT_MARKER = "# Career profile export"
"""First line of every export; the agents use it to tell one from a resume."""

NO_VALUE = "—"


def _clean(text: str) -> str:
    """Collapse a value onto one line so it cannot break the list around it."""
    return " ".join(text.split())


def _field(label: str, value: str | float | None) -> str | None:
    if value is None or value == "":
        return None
    shown = f"{value:g}" if isinstance(value, float) else _clean(str(value))
    return f"- {label}: {shown}"


def _lines(*items: str | None) -> list[str]:
    return [item for item in items if item]


def _span(role: Role) -> str:
    start = role.start_date or "?"
    end = "present" if role.is_current or not role.end_date else role.end_date
    return f"{start} – {end}"


def _accomplishment(item: Accomplishment) -> list[str]:
    lines = [f"- “{_clean(item.source_text)}”"]
    detail = _lines(
        _field("Situation", item.situation),
        _field("Action", item.action),
        _field("Result", item.result),
        _field("Numbers", "; ".join(item.metrics)),
        _field("Tools", ", ".join(item.tools)),
        _field("Evidence", item.evidence_id),
        _field("Agent's reading (not evidence, never cited)", item.interpretation),
    )
    return lines + [f"  {line}" for line in detail]


def render_profile_markdown(profile: Profile, exported_on: str) -> str:
    """Render the whole profile as Markdown.

    Args:
        profile: The user's profile.
        exported_on: Date to print in the header, as text, so the output is a
            pure function of the profile.
    """
    out: list[str] = [
        EXPORT_MARKER,
        "",
        f"Exported {exported_on}. This is everything the agent holds about you.",
        "",
        "**To change anything:** edit this file, then attach it in a chat with "
        "the paperclip. The agent reads it, records what you changed in your own "
        "words, and tells you what it saved. Removing a line here does not "
        "remove it from your profile; ask in the chat to have it taken out.",
        "",
    ]

    identity = profile.identity
    out += ["## Identity", ""]
    out += _lines(
        _field("Name", identity.full_name),
        _field("Email", identity.email),
        _field("Phone", identity.phone),
        _field("Location", identity.location),
        _field("Headline", identity.headline),
        _field("Links", ", ".join(identity.links)),
    ) or [NO_VALUE]

    out += ["", "## Goals", ""]
    out += [f"- {_clean(goal)}" for goal in profile.goals] or [NO_VALUE]

    constraints = profile.constraints
    out += ["", "## Constraints", ""]
    out += _lines(
        _field("Places I would work", ", ".join(constraints.locations)),
        _field("Remote", constraints.remote),
        _field(
            f"Lowest base pay ({constraints.comp_currency})", constraints.comp_floor
        ),
        _field("Earliest start", constraints.earliest_start),
        _field("Notes", constraints.notes),
    ) or [NO_VALUE]

    out += ["", "## Roles"]
    known_roles = {role.id for role in profile.roles}
    for role in profile.roles:
        out += ["", f"### {_clean(role.title)} at {_clean(role.company)}", ""]
        out += _lines(
            _field("Dates", _span(role)),
            _field("Location", role.location),
            _field("Type", role.employment_type),
            _field("About the role", role.summary),
        )
        mine = [a for a in profile.accomplishments if a.role_id == role.id]
        out += ["", "#### Accomplishments", ""]
        for item in mine:
            out += _accomplishment(item)
        if not mine:
            out.append(NO_VALUE)
    orphans = [a for a in profile.accomplishments if a.role_id not in known_roles]
    if orphans:
        out += ["", "### Not attached to a role", "", "#### Accomplishments", ""]
        for item in orphans:
            out += _accomplishment(item)

    out += ["", "## Skills", ""]
    for skill in profile.skills:
        facts = _lines(
            f"level: {skill.level}" if skill.level else "level: not rated",
            f"years: {skill.years:g}" if skill.years is not None else None,
            f"last used: {skill.last_used}" if skill.last_used else None,
            f"evidence: {', '.join(skill.evidence_ids)}",
        )
        out.append(f"- {_clean(skill.name)} ({'; '.join(facts)})")
    if not profile.skills:
        out.append(NO_VALUE)

    out += ["", "## Education", ""]
    for school in profile.education:
        title = ", ".join(
            _lines(school.credential, school.field and f"in {school.field}")
        )
        dates = " – ".join(_lines(school.start_date, school.end_date))
        status = "" if school.completed else "in progress"
        extras = "; ".join(_lines(dates, status))
        out.append(
            f"- {_clean(title) + ', ' if title else ''}{_clean(school.institution)}"
            + (f" ({extras})" if extras else "")
        )
    if not profile.education:
        out.append(NO_VALUE)

    out += ["", "## Open questions", ""]
    for question in profile.open_questions:
        out.append(f"- {_clean(question.question)} [{question.status}]")
        out += [
            f"  {line}"
            for line in _lines(
                _field(
                    "Agent's hunch (not confirmed, not a fact)", question.hypothesis
                ),
                _field("Why it matters", question.reason),
            )
        ]
    if not profile.open_questions:
        out.append(NO_VALUE)

    out += ["", "## Everything you have said", ""]
    for item in profile.evidence:
        stamp = item.captured_at.date().isoformat()
        out.append(
            f"- {item.id} ({item.source}, {stamp}): “{_clean(item.source_text)}”"
        )
        if item.note:
            out.append(f"  - Context: {_clean(item.note)}")
    if not profile.evidence:
        out.append(NO_VALUE)

    return "\n".join(out) + "\n"
