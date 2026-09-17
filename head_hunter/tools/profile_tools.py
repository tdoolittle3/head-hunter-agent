"""The Interviewer's tools: everything that writes to the Career Profile.

Rule 1 is enforced here rather than left to the prompt. Every tool that records
a *fact* demands ``source_text`` -- the user's own words -- and creates an
Evidence record from it. There is no way to add an accomplishment or a skill
without saying what the user actually said. An inference has nowhere to go
except :func:`add_open_question`, which is the only tool that accepts a guess,
and it stores it in a field named ``hypothesis`` that no resume can ever cite.
"""

from __future__ import annotations

from head_hunter.schemas import (
    Accomplishment,
    Evidence,
    OpenQuestion,
    Profile,
    Role,
    Skill,
)
from head_hunter.tools._base import ToolError, current_user_id, repository

SKILL_LEVELS = ("aware", "working", "strong", "expert")

MIN_SOURCE_TEXT_WORDS = 4


def _load_or_create() -> Profile:
    """Return the stored profile, or a fresh empty one for a new user."""
    return repository().get_profile(current_user_id()) or Profile(
        user_id=current_user_id()
    )


def _require_source_text(source_text: str, what: str) -> str:
    """Reject an empty or throwaway ``source_text``.

    A one-word quote is not evidence, and a resume bullet cited against it
    could not be validated later. Better to make the Interviewer go back and
    ask than to store something unusable.
    """
    cleaned = " ".join(source_text.split())
    if len(cleaned.split()) < MIN_SOURCE_TEXT_WORDS:
        raise ToolError(
            f"Cannot record {what} without the user's own words. Pass the "
            "relevant part of what they actually said as source_text "
            f"(at least {MIN_SOURCE_TEXT_WORDS} words). If they have not said "
            "it yet, ask them first."
        )
    return cleaned


def _add_evidence(profile: Profile, source_text: str, note: str | None) -> Evidence:
    """Append a new Evidence record and return it."""
    evidence = Evidence(source_text=source_text, source="interview", note=note)
    profile.evidence.append(evidence)
    return evidence


def load_profile() -> dict:
    """Load the current state of the user's career profile.

    Call this at the start of every interview session so you can pick up where
    the last one stopped instead of asking the same questions again.

    Returns:
        A summary of what is already recorded: identity, goals, roles,
        how many accomplishments and skills exist, and the open questions
        left over from previous sessions.
    """
    profile = repository().get_profile(current_user_id())
    if profile is None:
        return {
            "status": "empty",
            "message": (
                "No profile yet. This is a first session: start by asking who "
                "they are and what they are looking for."
            ),
        }

    return {
        "status": "ok",
        "identity": profile.identity.model_dump(exclude_none=True),
        "goals": profile.goals,
        "constraints": profile.constraints.model_dump(exclude_none=True),
        "roles": [
            {
                "role_id": r.id,
                "company": r.company,
                "title": r.title,
                "start_date": r.start_date,
                "end_date": r.end_date,
                "is_current": r.is_current,
                "accomplishments_recorded": sum(
                    1 for a in profile.accomplishments if a.role_id == r.id
                ),
            }
            for r in profile.roles
        ],
        "skills": [
            {"name": s.name, "level": s.level, "years": s.years} for s in profile.skills
        ],
        "education": [e.model_dump(exclude_none=True) for e in profile.education],
        "accomplishment_count": len(profile.accomplishments),
        "open_questions": [
            {
                "id": q.id,
                "question": q.question,
                "hypothesis": q.hypothesis,
                "reason": q.reason,
            }
            for q in profile.open_questions
            if q.status == "open"
        ],
        "is_thin": profile.is_thin(),
    }


def save_profile(
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    location: str | None = None,
    headline: str | None = None,
    goals: list[str] | None = None,
    target_locations: list[str] | None = None,
    remote_preference: str | None = None,
    comp_floor: float | None = None,
    earliest_start: str | None = None,
) -> dict:
    """Save the user's identity, goals, and constraints.

    Only pass the fields the user has actually told you. Anything left out
    keeps its current value, so you can call this repeatedly as you learn more.

    Args:
        full_name: Name as it should appear on a resume.
        email: Contact email.
        phone: Contact phone.
        location: Where they live now.
        headline: One line they use to describe themselves.
        goals: What they want next, in their words.
        target_locations: Places they would work.
        remote_preference: One of remote, hybrid, onsite, flexible.
        comp_floor: Lowest base compensation they would accept.
        earliest_start: When they could start, in their words.

    Returns:
        A confirmation of what is now stored.
    """
    profile = _load_or_create()

    for field, value in [
        ("full_name", full_name),
        ("email", email),
        ("phone", phone),
        ("location", location),
        ("headline", headline),
    ]:
        if value is not None:
            setattr(profile.identity, field, value)

    if goals is not None:
        profile.goals = goals
    if target_locations is not None:
        profile.constraints.locations = target_locations
    if remote_preference is not None:
        allowed = ("remote", "hybrid", "onsite", "flexible")
        if remote_preference not in allowed:
            raise ToolError(
                f"remote_preference must be one of {', '.join(allowed)}; "
                f"got {remote_preference!r}."
            )
        profile.constraints.remote = remote_preference
    if comp_floor is not None:
        profile.constraints.comp_floor = comp_floor
    if earliest_start is not None:
        profile.constraints.earliest_start = earliest_start

    repository().save_profile(profile)
    return {
        "status": "saved",
        "identity": profile.identity.model_dump(exclude_none=True),
        "goals": profile.goals,
        "constraints": profile.constraints.model_dump(exclude_none=True),
    }


def add_role(
    company: str,
    title: str,
    start_date: str | None = None,
    end_date: str | None = None,
    is_current: bool = False,
    location: str | None = None,
    employment_type: str | None = None,
    summary: str | None = None,
) -> dict:
    """Record one job the user has held.

    Add the role before its accomplishments: every accomplishment needs the
    ``role_id`` this returns.

    Args:
        company: Employer or client.
        title: Job title as it was actually used.
        start_date: When they started, e.g. '2021-03'.
        end_date: When they left, e.g. '2024-11'. Omit if current.
        is_current: True if this is their current job.
        location: Where the role was based.
        employment_type: Full-time, contract, founder, and so on.
        summary: What the role was, in one or two sentences.

    Returns:
        The new ``role_id``, which you need for add_accomplishment.
    """
    profile = _load_or_create()
    role = Role(
        company=company,
        title=title,
        start_date=start_date,
        end_date=end_date,
        is_current=is_current,
        location=location,
        employment_type=employment_type,
        summary=summary,
    )
    profile.roles.append(role)
    repository().save_profile(profile)
    return {"status": "saved", "role_id": role.id, "company": company, "title": title}


def add_accomplishment(
    role_id: str,
    situation: str,
    action: str,
    result: str,
    source_text: str,
    metrics: list[str] | None = None,
    tools: list[str] | None = None,
) -> dict:
    """Record something the user did, in situation / action / result form.

    Only record what the user actually told you. If you are inferring scope,
    seniority, or impact they did not state, use add_open_question instead.

    Args:
        role_id: The role this belongs to, from add_role or load_profile.
        situation: The problem or context.
        action: What the user personally did.
        result: What changed because of it.
        source_text: The user's own words describing this, lightly cleaned.
            This is the evidence a resume bullet will later have to cite.
        metrics: Numbers they gave, e.g. ['cut close from 9 days to 2'].
        tools: Technologies or systems they named.

    Returns:
        The new accomplishment id and the evidence id backing it.
    """
    profile = _load_or_create()

    if not any(r.id == role_id for r in profile.roles):
        known = ", ".join(f"{r.id} ({r.company})" for r in profile.roles) or "none yet"
        raise ToolError(
            f"No role with id {role_id!r}. Known roles: {known}. "
            "Call add_role first, or use load_profile to get the right id."
        )

    cleaned = _require_source_text(source_text, "an accomplishment")
    evidence = _add_evidence(profile, cleaned, note=f"accomplishment at {role_id}")

    accomplishment = Accomplishment(
        role_id=role_id,
        situation=situation,
        action=action,
        result=result,
        metrics=metrics or [],
        tools=tools or [],
        evidence_id=evidence.id,
        source_text=cleaned,
    )
    profile.accomplishments.append(accomplishment)
    repository().save_profile(profile)

    return {
        "status": "saved",
        "accomplishment_id": accomplishment.id,
        "evidence_id": evidence.id,
        "has_metrics": bool(accomplishment.metrics),
    }


def add_skill(
    name: str,
    level: str,
    source_text: str,
    years: float | None = None,
    last_used: str | None = None,
) -> dict:
    """Record a skill the user has, backed by what they said about it.

    Do not add a skill just because it appears in a job description, or because
    it seems implied by their role. It goes in only if they claimed it.

    Args:
        name: The skill, e.g. 'Airflow' or 'contract negotiation'.
        level: One of aware, working, strong, expert.
        source_text: The user's own words about this skill.
        years: Years of real use.
        last_used: Roughly when last used, e.g. '2024' or 'current'.

    Returns:
        Confirmation and the evidence id backing the skill.
    """
    if level not in SKILL_LEVELS:
        raise ToolError(
            f"level must be one of {', '.join(SKILL_LEVELS)}; got {level!r}. "
            "If the user was vague, ask them to place it on that scale."
        )

    profile = _load_or_create()
    cleaned = _require_source_text(source_text, f"the skill {name!r}")
    evidence = _add_evidence(profile, cleaned, note=f"skill: {name}")

    existing = next((s for s in profile.skills if s.name.lower() == name.lower()), None)
    if existing is not None:
        existing.level = level
        existing.evidence_ids.append(evidence.id)
        if years is not None:
            existing.years = years
        if last_used is not None:
            existing.last_used = last_used
        action = "updated"
    else:
        profile.skills.append(
            Skill(
                name=name,
                level=level,
                years=years,
                evidence_ids=[evidence.id],
                last_used=last_used,
            )
        )
        action = "added"

    repository().save_profile(profile)
    return {
        "status": action,
        "skill": name,
        "level": level,
        "evidence_id": evidence.id,
    }


def add_open_question(
    question: str,
    hypothesis: str | None = None,
    about_role_id: str | None = None,
    about_skill: str | None = None,
    reason: str | None = None,
) -> dict:
    """Record something you still need to ask, including a hunch you cannot confirm.

    This is the only place an inference is allowed to live. If you suspect the
    user led a team, drove a decision, or has a skill they have not claimed,
    put the guess in ``hypothesis`` and the question you would ask in
    ``question``. It will never be treated as a fact.

    Also use this at the end of a session to record the gaps you noticed:
    roles with no metrics, skills with no evidence, periods you skipped.

    Args:
        question: What to ask the user next time.
        hypothesis: What you suspect but have NOT been told.
        about_role_id: The role this concerns, if any.
        about_skill: The skill this concerns, if any.
        reason: Why this gap matters.

    Returns:
        Confirmation and the new question id.
    """
    profile = _load_or_create()
    open_question = OpenQuestion(
        question=question,
        hypothesis=hypothesis,
        about_role_id=about_role_id,
        about_skill=about_skill,
        reason=reason,
    )
    profile.open_questions.append(open_question)
    repository().save_profile(profile)
    return {
        "status": "saved",
        "question_id": open_question.id,
        "open_question_count": sum(
            1 for q in profile.open_questions if q.status == "open"
        ),
    }
