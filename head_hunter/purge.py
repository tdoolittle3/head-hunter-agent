"""Deleting a chat entirely: everything that chat added goes with it.

Deterministic Python, never a model's opinion (AGENTS.md rule 4). Every record
a tool creates is stamped with the ``session_id`` of the chat it was created
in, and this module is the one place that stamp is acted on.

What "added as a result of that chat" means here, record by record:

- **Evidence, accomplishments, education, open questions** created in the chat
  are removed outright. An accomplishment and its evidence are always created
  together, so they leave together.
- **Skills** lose the evidence captured in the chat. A skill only disappears
  when no evidence from any other chat is left backing it — a skill you claimed
  twice is not unclaimed by deleting one of the chats.
- **Roles** created in the chat are removed unless a surviving accomplishment
  from another chat still hangs on them. Deleting the chat that first mentioned
  Acme must not silently destroy what a later chat recorded about Acme.
- **Jobs** saved in the chat are removed along with their fit report and
  resume, whoever wrote those: they describe a posting that no longer exists.
- **Fit reports and resumes** written in the chat are removed even when their
  job survives; the job itself was someone else's work.
- **Journal entries** logged in the chat are removed. Entries from other chats
  about a removed job are kept — the record that you applied somewhere is not
  undone by deleting the chat that pasted the posting.

Records with no ``session_id`` (written before chats were stamped, or outside
one) are never purged.
"""

from __future__ import annotations

from head_hunter.storage.repository import Repository


def purge_session_records(
    repo: Repository, user_id: str, session_id: str
) -> dict[str, int]:
    """Remove everything a chat added, and say how much was removed.

    Args:
        repo: The store to purge.
        user_id: Whose records these are.
        session_id: The chat being deleted entirely.

    Returns:
        Counts of what was removed, keyed by record kind. All zeros when the
        chat never wrote anything.
    """
    counts = {
        "evidence": 0,
        "accomplishments": 0,
        "skills": 0,
        "roles": 0,
        "education": 0,
        "open_questions": 0,
        "jobs": 0,
        "fit_reports": 0,
        "resumes": 0,
        "journal_entries": 0,
    }

    profile = repo.get_profile(user_id)
    if profile is not None:
        removed_evidence = {
            e.id for e in profile.evidence if e.session_id == session_id
        }
        counts["evidence"] = len(removed_evidence)
        profile.evidence = [e for e in profile.evidence if e.id not in removed_evidence]

        before = len(profile.accomplishments)
        profile.accomplishments = [
            a for a in profile.accomplishments if a.session_id != session_id
        ]
        counts["accomplishments"] = before - len(profile.accomplishments)

        kept_skills = []
        for skill in profile.skills:
            skill.evidence_ids = [
                eid for eid in skill.evidence_ids if eid not in removed_evidence
            ]
            if skill.evidence_ids:
                kept_skills.append(skill)
            else:
                counts["skills"] += 1
        profile.skills = kept_skills

        # A role born in this chat survives if another chat's accomplishment
        # still hangs on it.
        still_used = {a.role_id for a in profile.accomplishments}
        before = len(profile.roles)
        profile.roles = [
            r for r in profile.roles if r.session_id != session_id or r.id in still_used
        ]
        counts["roles"] = before - len(profile.roles)

        before = len(profile.education)
        profile.education = [e for e in profile.education if e.session_id != session_id]
        counts["education"] = before - len(profile.education)

        before = len(profile.open_questions)
        profile.open_questions = [
            q for q in profile.open_questions if q.session_id != session_id
        ]
        counts["open_questions"] = before - len(profile.open_questions)

        if any(counts.values()):
            repo.save_profile(profile)

    for job in repo.list_jobs(user_id):
        if job.session_id == session_id:
            # The posting goes, so everything describing it goes too.
            if repo.get_resume(user_id, job.id) is not None:
                repo.delete_resume(user_id, job.id)
                counts["resumes"] += 1
            if repo.get_fit_report(user_id, job.id) is not None:
                repo.delete_fit_report(user_id, job.id)
                counts["fit_reports"] += 1
            repo.delete_job(user_id, job.id)
            counts["jobs"] += 1
            continue
        report = repo.get_fit_report(user_id, job.id)
        if report is not None and report.session_id == session_id:
            repo.delete_fit_report(user_id, job.id)
            counts["fit_reports"] += 1
        resume = repo.get_resume(user_id, job.id)
        if resume is not None and resume.session_id == session_id:
            repo.delete_resume(user_id, job.id)
            counts["resumes"] += 1

    for entry in repo.list_journal_entries(user_id):
        if entry.session_id == session_id:
            repo.delete_journal_entry(user_id, entry.id)
            counts["journal_entries"] += 1

    return counts
