"""Changing a resume after it was written: by the user's hand, or at their word.

Two doors, one rule. The user can retype anything on their own resume (the
editor on the job page calls :func:`apply_manual_edit`); the Resume Tailor can
make the changes they ask for in chat (``edit_resume`` calls
:func:`apply_agent_edit`). Either way the record is re-validated and saved, and
the rendered files are what the server builds from that record.

The difference is where the new words come from. Text the user typed is their
own word, so it is recorded as ``user_edit`` evidence and cited -- the same
standard as anything said in an interview. Text the agent proposes is held to
the validator and to the existing evidence, so it can reword or cut but cannot
add a claim the profile does not hold.
"""

from __future__ import annotations

from head_hunter.resume_validation import check_headline, validate_resume
from head_hunter.schemas import (
    Evidence,
    Profile,
    Resume,
    ResumeBullet,
    ResumeSection,
)
from head_hunter.schemas.ids import new_id


class ResumeEditError(ValueError):
    """The requested edit cannot be applied; the message says why."""


def _clean(value: str | None) -> str:
    return (value or "").strip()


def apply_manual_edit(
    resume: Resume,
    profile: Profile,
    headline: str | None,
    sections: list[dict],
) -> Resume:
    """Replace a resume's headline and sections with what the user typed.

    Every bullet whose text is new or changed gets the user's exact words
    recorded as ``user_edit`` evidence and cited alongside what it cited
    before. Bullets with no text are dropped, and so are sections left with no
    bullets. Mutates ``resume`` and ``profile`` (new evidence); the caller
    saves both.

    Args:
        resume: The resume being edited.
        profile: Its profile, which gains the evidence.
        headline: The headline text; ``None`` goes back to the profile's.
        sections: Dicts with ``title``, ``subtitle`` and ``bullets`` (dicts
            with ``text`` and ``evidence_ids``, which new bullets leave empty).

    Raises:
        ResumeEditError: If a section has no heading or nothing would be left.
    """
    previous = {
        bullet.text for section in resume.sections for bullet in section.bullets
    }
    taken = {e.id for e in profile.evidence}

    cleaned: list[ResumeSection] = []
    for section in sections:
        title = _clean(section.get("title"))
        if not title:
            raise ResumeEditError("Every section needs a heading.")
        bullets: list[ResumeBullet] = []
        for bullet in section.get("bullets") or []:
            text = _clean(bullet.get("text"))
            if not text:
                continue
            ids = [str(i) for i in bullet.get("evidence_ids") or []]
            if text not in previous or not ids:
                evidence = Evidence(
                    id=new_id("ev", taken),
                    source_text=text,
                    source="user_edit",
                    note="Typed by the user while editing a resume.",
                )
                taken.add(evidence.id)
                profile.evidence.append(evidence)
                ids.append(evidence.id)
            bullets.append(ResumeBullet(text=text, evidence_ids=ids))
        if bullets:
            cleaned.append(
                ResumeSection(
                    title=title,
                    subtitle=_clean(section.get("subtitle")) or None,
                    bullets=bullets,
                )
            )
    if not cleaned:
        raise ResumeEditError("A resume with no bullets is not a resume.")

    resume.headline = None if headline is None else _clean(headline)
    resume.sections = cleaned
    resume.validation = validate_resume(resume, profile)
    return resume


def _matching_bullet(resume: Resume, find: str) -> tuple[ResumeSection, int]:
    """Locate the one bullet containing ``find``, or say why that is not possible."""
    needle = find.strip().lower()
    if not needle:
        raise ResumeEditError("An edit needs some text to find.")
    hits = [
        (section, index)
        for section in resume.sections
        for index, bullet in enumerate(section.bullets)
        if needle in bullet.text.lower()
    ]
    if not hits:
        raise ResumeEditError(f"No bullet contains {find!r}.")
    if len(hits) > 1:
        raise ResumeEditError(
            f"{find!r} appears in {len(hits)} bullets; use a longer piece of "
            "text so only one matches."
        )
    return hits[0]


def apply_agent_edit(
    resume: Resume,
    profile: Profile,
    headline: str | None = None,
    replacements: list[dict] | None = None,
    remove_bullets: list[str] | None = None,
    remove_sections: list[str] | None = None,
) -> Resume:
    """Make the changes a user asked for in chat, without adding any claim.

    Args:
        resume: The resume to change; mutated and returned.
        profile: The profile it was written from, for validation.
        headline: A new headline, or ``""`` to show none. Checked against
            everything the profile holds.
        replacements: ``{"find", "replace"}`` pairs. ``find`` must sit inside
            exactly one bullet; that piece of text is swapped for ``replace``.
        remove_bullets: Text identifying bullets to delete, one match each.
        remove_sections: Section titles to delete, with their bullets.

    Raises:
        ResumeEditError: If a target is missing or ambiguous, the headline
            claims something the profile does not, or nothing would be left.
    """
    if headline is not None:
        problem = check_headline(headline, profile) if headline.strip() else None
        if problem:
            raise ResumeEditError(
                f"That headline is not supported by the profile: {problem}. "
                "Ask the user about it; if they confirm it, hand back so the "
                "Interviewer records it."
            )
        resume.headline = headline.strip()

    for pair in replacements or []:
        find = str(pair.get("find", "")).strip()
        section, index = _matching_bullet(resume, find)
        bullet = section.bullets[index]
        start = bullet.text.lower().index(find.lower())
        text = (
            bullet.text[:start]
            + str(pair.get("replace", ""))
            + bullet.text[start + len(find) :]
        ).strip()
        if not text:
            raise ResumeEditError(
                "That edit would empty the bullet; use remove_bullets instead."
            )
        section.bullets[index] = ResumeBullet(
            text=text, evidence_ids=bullet.evidence_ids
        )

    for find in remove_bullets or []:
        section, index = _matching_bullet(resume, find)
        del section.bullets[index]

    drop = {_clean(title).lower() for title in remove_sections or []}
    missing = drop - {s.title.lower() for s in resume.sections}
    if missing:
        raise ResumeEditError(
            "No section titled " + ", ".join(sorted(repr(m) for m in missing)) + "."
        )
    resume.sections = [
        s for s in resume.sections if s.title.lower() not in drop and s.bullets
    ]
    if not resume.sections:
        raise ResumeEditError("A resume with no bullets is not a resume.")

    resume.validation = validate_resume(resume, profile)
    return resume
