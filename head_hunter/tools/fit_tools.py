"""The Fit Analyst's tools.

The division is the point. :func:`load_job_and_profile` hands the model
everything it needs to judge; :func:`save_fit_report` takes that judgment and
does the bookkeeping. The score is never a parameter -- the model cannot
propose one. It is computed by :func:`head_hunter.scoring.score_fit` from the
met and unmet lists, so the same analysis always produces the same number
(AGENTS.md rule 4).

Citations are enforced three ways. ``MetRequirement`` refuses to construct with
an empty ``evidence_ids``; the schema rejects blank ids inside the list; and
:func:`save_fit_report` loads the profile and checks that every id cited is an
Evidence record that actually exists. Without that last check a model could cite
``ev-does-not-exist`` for a security clearance and score 100/100, which is the
difference between a citation and the appearance of one.
"""

from __future__ import annotations

from head_hunter.schemas import (
    FitReport,
    MetRequirement,
    Requirement,
    UnmetRequirement,
)
from head_hunter.scoring import score_fit
from head_hunter.tools._base import ToolError, current_user_id, repository

GAP_KINDS = ("stretch", "blocker")


def load_job_and_profile(job_id: str) -> dict:
    """Load one posting and the user's profile, ready to compare.

    Args:
        job_id: The posting to analyse, from save_job_posting or list_jobs.

    Returns:
        The posting's requirements (each with its id) and the profile's
        accomplishments, skills, and evidence, so you can cite evidence ids.
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
            "There is no career profile yet, so there is nothing to compare "
            "this posting against. Hand back to the Head Hunter so the "
            "Interviewer can build one first."
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
            "requirements": [
                {
                    "requirement_id": r.id,
                    "text": r.text,
                    "kind": r.kind,
                    "category": r.category,
                }
                for r in job.requirements
            ],
        },
        "profile": {
            "is_thin": profile.is_thin(),
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
                    "last_used": s.last_used,
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


def _citations(
    entry: dict,
    index: int,
    requirement: Requirement,
    known_evidence: set[str],
) -> list[str]:
    """Return the evidence ids one met entry cites, or explain why they are unusable.

    Presence is not enough. An id that names no Evidence record is worse than no
    citation at all, because it looks like proof in the saved report.
    """
    raw = entry.get("evidence_ids")
    if isinstance(raw, str):
        raise ToolError(
            f"met entry {index} ({requirement.text!r}) passed evidence_ids as a "
            "single string. It must be a list, even for one id: "
            "['ev-20260916-1a2b3c4d']."
        )
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ToolError(
            f"met entry {index} ({requirement.text!r}) has evidence_ids of type "
            f"{type(raw).__name__}; it must be a list of evidence ids."
        )

    evidence_ids = [str(e).strip() for e in raw]
    if not evidence_ids or any(not e for e in evidence_ids):
        raise ToolError(
            f"met entry {index} ({requirement.text!r}) cites no evidence. "
            "A requirement with no evidence behind it is unmet, not met. "
            "Move it to unmet or cite the evidence id that proves it."
        )

    unknown = [e for e in evidence_ids if e not in known_evidence]
    if unknown:
        raise ToolError(
            f"met entry {index} ({requirement.text!r}) cites evidence that is "
            "not in the profile: " + ", ".join(sorted(unknown)) + ". Use the "
            "evidence ids exactly as load_job_and_profile returned them. If "
            "nothing in the profile supports this requirement, it is unmet."
        )
    return evidence_ids


def save_fit_report(
    job_id: str,
    met: list[dict],
    unmet: list[dict],
    summary: str,
) -> dict:
    """Save your analysis. The score is computed here, not by you.

    Every entry in ``met`` must be a dict with:
      - ``requirement_id``: the id from load_job_and_profile
      - ``evidence_ids``: a non-empty list of evidence ids that prove it.
        Each one must be an id load_job_and_profile actually returned; an id
        that is not in the profile is rejected, not quietly accepted.
      - ``note``: one line on how the evidence meets it (optional)

    Every entry in ``unmet`` must be a dict with:
      - ``requirement_id``: the id from load_job_and_profile
      - ``gap``: 'stretch' if they could learn or grow into it,
        'blocker' if they cannot (a credential, clearance, licence, or a hard
        years-of-experience floor they are far from)
      - ``note``: one line on why

    Every requirement in the posting must appear in exactly one of the two
    lists. A requirement you cannot find evidence for is unmet, not omitted.

    Args:
        job_id: The posting being analysed.
        met: Requirements the profile satisfies, with citations.
        unmet: Requirements it does not, each tagged stretch or blocker.
        summary: Plain-language read on the fit, for the user.

    Returns:
        The saved report including the computed score.
    """
    repo = repository()
    user_id = current_user_id()

    job = repo.get_job(user_id, job_id)
    if job is None:
        raise ToolError(f"No saved posting with id {job_id!r}.")

    profile = repo.get_profile(user_id)
    if profile is None:
        raise ToolError(
            "There is no career profile to cite, so no requirement can be "
            "judged met. Hand back to the Head Hunter so the Interviewer can "
            "build one first."
        )
    known_evidence = {e.id for e in profile.evidence}

    by_id: dict[str, Requirement] = {r.id: r for r in job.requirements}
    seen: set[str] = set()

    def take(entry: dict, index: int, bucket: str) -> Requirement:
        if not isinstance(entry, dict):
            raise ToolError(
                f"{bucket} entry {index} must be a dict; got {type(entry).__name__}."
            )
        requirement_id = str(entry.get("requirement_id", "")).strip()
        requirement = by_id.get(requirement_id)
        if requirement is None:
            raise ToolError(
                f"{bucket} entry {index} refers to requirement_id "
                f"{requirement_id!r}, which is not in this posting. Use the "
                "ids exactly as load_job_and_profile returned them."
            )
        if requirement_id in seen:
            raise ToolError(
                f"Requirement {requirement_id!r} ({requirement.text!r}) appears "
                "more than once. Each requirement belongs in met or unmet, "
                "not both."
            )
        seen.add(requirement_id)
        return requirement

    met_records: list[MetRequirement] = []
    for index, entry in enumerate(met, start=1):
        requirement = take(entry, index, "met")
        evidence_ids = _citations(entry, index, requirement, known_evidence)
        met_records.append(
            MetRequirement(
                requirement=requirement,
                evidence_ids=evidence_ids,
                note=entry.get("note"),
            )
        )

    unmet_records: list[UnmetRequirement] = []
    for index, entry in enumerate(unmet, start=1):
        requirement = take(entry, index, "unmet")
        gap = str(entry.get("gap", "")).strip().lower()
        if gap not in GAP_KINDS:
            raise ToolError(
                f"unmet entry {index} ({requirement.text!r}) has gap {gap!r}; "
                f"must be one of {', '.join(GAP_KINDS)}."
            )
        note = str(entry.get("note", "")).strip()
        if not note:
            raise ToolError(
                f"unmet entry {index} ({requirement.text!r}) needs a one-line "
                "note saying why it is a stretch or a blocker."
            )
        unmet_records.append(
            UnmetRequirement(requirement=requirement, gap=gap, note=note)
        )

    missing = [r.text for r in job.requirements if r.id not in seen]
    if missing:
        raise ToolError(
            "Every requirement must be judged. These were left out: "
            + "; ".join(missing)
            + ". Put each in met (with evidence) or unmet (with a reason)."
        )

    report = FitReport(
        user_id=user_id,
        job_id=job_id,
        score=score_fit(met_records, unmet_records),
        met=met_records,
        unmet=unmet_records,
        summary=summary,
    )
    repo.save_fit_report(report)

    return {
        "status": "saved",
        "job_id": job_id,
        "score": report.score,
        "met_count": len(met_records),
        "unmet_count": len(unmet_records),
        "blockers": [u.requirement.text for u in report.blockers],
        "stretches": [u.requirement.text for u in report.unmet if u.gap == "stretch"],
    }


def get_fit_report(job_id: str) -> dict:
    """Load a fit report that was already produced for a posting.

    Args:
        job_id: The posting whose report to load.

    Returns:
        The stored report, or a note that none has been run yet.
    """
    report = repository().get_fit_report(current_user_id(), job_id)
    if report is None:
        return {
            "status": "none",
            "message": f"No fit report has been run for {job_id!r} yet.",
        }
    return {"status": "ok", "report": report.model_dump(mode="json")}
