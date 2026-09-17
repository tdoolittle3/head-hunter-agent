"""The Resume Tailor's tools.

Same division as the Fit Analyst's. :func:`load_tailoring_context` hands the
model the evidence it is allowed to cite; :func:`save_resume` takes the draft
and does the bookkeeping. The bookkeeping here is the traceability check, and
it is plain Python (:func:`head_hunter.resume_validation.validate_resume`), so
the model cannot talk its way past it the way it might past a prompt.

:func:`render_resume` is deliberately a second call, and it refuses to run on a
draft that did not pass. That refusal is the whole guarantee: a ``.docx`` can
only exist for a resume whose every bullet traced back to something the user
said.
"""

from __future__ import annotations

from pydantic import ValidationError

from head_hunter.resume_render import render_docx, render_markdown
from head_hunter.resume_validation import validate_resume
from head_hunter.schemas import Resume, ResumeBullet, ResumeSection
from head_hunter.tools._base import ToolError, current_user_id, repository


def load_tailoring_context(job_id: str) -> dict:
    """Load the posting, the profile, and the fit report, ready to write from.

    The ``evidence`` list is the only thing you may cite, and the only thing
    the resume may claim. Read it before you write a single bullet.

    Args:
        job_id: The posting to write a resume for.

    Returns:
        The posting's requirements, the profile's roles, accomplishments,
        skills and evidence, and the fit report if one has been run.
    """
    repo = repository()
    user_id = current_user_id()

    job = repo.get_job(user_id, job_id)
    if job is None:
        raise ToolError(
            f"No saved posting with id {job_id!r}. Call list_jobs to see what "
            "is available, or ask the user to paste the description."
        )

    profile = repo.get_profile(user_id)
    if profile is None:
        raise ToolError(
            "There is no career profile yet, so there is nothing to write a "
            "resume from. Hand back to the Head Hunter so the Interviewer can "
            "build one first."
        )

    context: dict = {
        "status": "ok",
        "job": {
            "job_id": job.id,
            "company": job.company,
            "title": job.title,
            "requirements": [
                {"text": r.text, "kind": r.kind, "category": r.category}
                for r in job.requirements
            ],
        },
        "profile": {
            "is_thin": profile.is_thin(),
            "identity": profile.identity.model_dump(exclude_none=True),
            "roles": [
                {
                    "role_id": r.id,
                    "company": r.company,
                    "title": r.title,
                    "start_date": r.start_date,
                    "end_date": r.end_date,
                    "is_current": r.is_current,
                }
                for r in profile.roles
            ],
            "accomplishments": [
                {
                    "role_id": a.role_id,
                    "situation": a.situation,
                    "action": a.action,
                    "result": a.result,
                    "metrics": a.metrics,
                    "tools": a.tools,
                    "evidence_id": a.evidence_id,
                }
                for a in profile.accomplishments
            ],
            "skills": [
                {
                    "name": s.name,
                    "level": s.level,
                    "years": s.years,
                    "evidence_ids": s.evidence_ids,
                }
                for s in profile.skills
            ],
            "education": [e.model_dump(exclude_none=True) for e in profile.education],
            "evidence": [
                {"evidence_id": e.id, "source_text": e.source_text}
                for e in profile.evidence
            ],
        },
    }

    report = repo.get_fit_report(user_id, job_id)
    if report is None:
        context["fit_report"] = {
            "status": "none",
            "message": (
                "No fit analysis has been run for this posting. You can still "
                "write the resume, but running one first tells you which "
                "requirements to lead with."
            ),
        }
    else:
        context["fit_report"] = {
            "status": "ok",
            "score": report.score,
            "met": [
                {
                    "requirement": m.requirement.text,
                    "evidence_ids": m.evidence_ids,
                    "note": m.note,
                }
                for m in report.met
            ],
            "unmet": [
                {"requirement": u.requirement.text, "gap": u.gap, "note": u.note}
                for u in report.unmet
            ],
        }

    return context


def save_resume(job_id: str, sections: list[dict]) -> dict:
    """Save a resume draft. Every bullet is checked against its citations here.

    Every entry in ``sections`` must be a dict with:
      - ``title``: the heading, e.g. 'Staff Engineer, Acme Foods' or 'Skills'
      - ``subtitle``: dates or location (optional)
      - ``bullets``: a list of dicts, each with ``text`` and a non-empty
        ``evidence_ids`` list

    The check is a plain Python function, not a judgment call. It fails a
    bullet whose cited evidence does not contain the numbers and names the
    bullet uses. If it fails, read each reason, fix those bullets, and call
    this again -- do not argue with it and do not re-cite the same evidence
    hoping for a different answer.

    Args:
        job_id: The posting this resume targets.
        sections: The resume body, as described above.

    Returns:
        Whether it passed, and every bullet that did not, with the reason.
    """
    repo = repository()
    user_id = current_user_id()

    if not sections:
        raise ToolError("A resume with no sections is not a resume.")

    profile = repo.get_profile(user_id)
    if profile is None:
        raise ToolError(
            "There is no career profile, so no bullet could be traced. Hand "
            "back to the Head Hunter so the Interviewer can build one first."
        )
    if repo.get_job(user_id, job_id) is None:
        raise ToolError(f"No saved posting with id {job_id!r}.")

    parsed: list[ResumeSection] = []
    for index, raw in enumerate(sections, start=1):
        if not isinstance(raw, dict):
            raise ToolError(
                f"Section {index} must be a dict with title and bullets; "
                f"got {type(raw).__name__}."
            )

        title = str(raw.get("title", "")).strip()
        if not title:
            raise ToolError(f"Section {index} has no title.")

        bullets: list[ResumeBullet] = []
        for position, entry in enumerate(raw.get("bullets") or [], start=1):
            where = f"Bullet {position} of section {title!r}"
            if not isinstance(entry, dict):
                raise ToolError(
                    f"{where} must be a dict with text and evidence_ids; "
                    f"got {type(entry).__name__}."
                )
            text = str(entry.get("text", "")).strip()
            if not text:
                raise ToolError(f"{where} has no text.")
            evidence_ids = [str(e).strip() for e in entry.get("evidence_ids") or []]
            try:
                bullets.append(ResumeBullet(text=text, evidence_ids=evidence_ids))
            except ValidationError as exc:
                raise ToolError(
                    f"{where} cites no evidence. Every bullet needs at least "
                    "one evidence_id from load_tailoring_context. If nothing "
                    "in the profile supports it, leave it off the resume."
                ) from exc

        if not bullets:
            raise ToolError(
                f"Section {title!r} has no bullets. Drop the section or give "
                "it content."
            )

        parsed.append(
            ResumeSection(
                title=title,
                subtitle=(str(raw["subtitle"]).strip() or None)
                if raw.get("subtitle")
                else None,
                bullets=bullets,
            )
        )

    resume = Resume(user_id=user_id, job_id=job_id, sections=parsed)
    resume.validation = validate_resume(resume, profile)
    repo.save_resume(resume)

    result = resume.validation
    return {
        "status": "validated" if result.passed else "needs_work",
        "job_id": job_id,
        "checked_bullets": result.checked_bullets,
        "passed": result.passed,
        "failures": [
            {
                "section": f.section_title,
                "bullet": f.bullet_text,
                "reason": f.reason,
            }
            for f in result.failures
        ],
        "next_step": (
            "Call render_resume to produce the Markdown and DOCX files."
            if result.passed
            else "Fix the bullets listed above and call save_resume again."
        ),
    }


def render_resume(job_id: str) -> dict:
    """Render a validated resume to Markdown and DOCX files.

    Refuses to run on a resume that has not passed the traceability check.
    That refusal is deliberate: a file a user could send to an employer must
    not contain a claim nothing in the profile supports.

    Args:
        job_id: The posting whose resume to render.

    Returns:
        Where the two files landed, plus the Markdown itself so you can show
        the user what was written.
    """
    repo = repository()
    user_id = current_user_id()

    resume = repo.get_resume(user_id, job_id)
    if resume is None:
        raise ToolError(
            f"No resume has been written for {job_id!r} yet. Call save_resume first."
        )
    if resume.validation is None or not resume.validation.passed:
        failed = resume.validation.failures if resume.validation else []
        raise ToolError(
            f"The resume for {job_id!r} has not passed the traceability "
            f"check, so it cannot be rendered. Bullets still failing: "
            + (
                "; ".join(f.bullet_text for f in failed)
                if failed
                else "unknown -- re-run save_resume."
            )
        )

    profile = repo.get_profile(user_id)
    if profile is None:
        raise ToolError("The profile is gone, so the header cannot be written.")

    markdown = render_markdown(resume, profile)
    markdown_path = repo.save_resume_document(
        user_id, job_id, "md", markdown.encode("utf-8")
    )
    docx_path = repo.save_resume_document(
        user_id, job_id, "docx", render_docx(markdown)
    )

    return {
        "status": "rendered",
        "job_id": job_id,
        "markdown_path": markdown_path,
        "docx_path": docx_path,
        "bullet_count": resume.validation.checked_bullets,
        "markdown": markdown,
    }
