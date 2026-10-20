"""Deleting a chat entirely takes what that chat added — and nothing else.

The promise under test has two halves. Everything a chat created must go with
it: profile entries, jobs, their reports and resumes, journal events. And
everything other chats created must survive, even when it leans on something
the deleted chat introduced first.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from head_hunter.purge import purge_session_records
from head_hunter.schemas import FitReport, Resume
from head_hunter.storage import JsonRepository
from head_hunter.tools import (
    add_accomplishment,
    add_education,
    add_open_question,
    add_role,
    add_skill,
    log_application_event,
    save_job_posting,
)

USER = "local"

QUOTE_A = (
    "I rewrote the billing pipeline and cut month-end close from nine days to two."
)
QUOTE_B = "I ran the support rotation and got response times under ten minutes."


def ctx(session_id: str) -> SimpleNamespace:
    """Enough of an ADK ToolContext for the tools: a user and a session."""
    return SimpleNamespace(user_id=USER, session=SimpleNamespace(id=session_id))


@pytest.fixture(autouse=True)
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HH_SINGLE_USER", USER)


def repo() -> JsonRepository:
    return JsonRepository()


def a_job(session_id: str, title: str = "Data Engineer") -> str:
    return save_job_posting(
        raw_text="Globex is hiring...",
        company="Globex",
        title=title,
        requirements=[{"text": "Python", "kind": "required", "category": "skill"}],
        tool_context=ctx(session_id),
    )["job_id"]


# Provenance: every record knows the chat that wrote it ----------------------


def test_tools_stamp_the_session_that_wrote_them() -> None:
    role_id = add_role(company="Acme", title="Engineer", tool_context=ctx("sess-a"))[
        "role_id"
    ]
    add_accomplishment(
        role_id=role_id,
        situation="s",
        action="a",
        result="r",
        source_text=QUOTE_A,
        tool_context=ctx("sess-a"),
    )
    job_id = a_job("sess-a")
    log_application_event(
        kind="applied", summary="Sent it.", job_id=job_id, tool_context=ctx("sess-a")
    )

    profile = repo().get_profile(USER)
    assert profile.roles[0].session_id == "sess-a"
    assert profile.accomplishments[0].session_id == "sess-a"
    assert profile.evidence[0].session_id == "sess-a"
    assert repo().get_job(USER, job_id).session_id == "sess-a"
    assert repo().list_journal_entries(USER)[0].session_id == "sess-a"


def test_records_written_outside_a_chat_are_never_purged() -> None:
    role_id = add_role(company="Acme", title="Engineer")["role_id"]
    add_accomplishment(
        role_id=role_id, situation="s", action="a", result="r", source_text=QUOTE_A
    )

    removed = purge_session_records(repo(), USER, "sess-a")

    assert all(count == 0 for count in removed.values())
    profile = repo().get_profile(USER)
    assert len(profile.roles) == 1
    assert len(profile.accomplishments) == 1


# The cascade ----------------------------------------------------------------


def test_purging_a_chat_removes_what_it_added_and_nothing_else() -> None:
    acme = add_role(company="Acme", title="Engineer", tool_context=ctx("sess-a"))[
        "role_id"
    ]
    add_accomplishment(
        role_id=acme,
        situation="s",
        action="a",
        result="r",
        source_text=QUOTE_A,
        tool_context=ctx("sess-a"),
    )
    add_education(institution="State U", credential="B.S.", tool_context=ctx("sess-a"))
    add_open_question(question="Did they lead it?", tool_context=ctx("sess-a"))
    add_skill(name="Airflow", source_text=QUOTE_A, tool_context=ctx("sess-a"))

    globex = add_role(company="Globex", title="Lead", tool_context=ctx("sess-b"))[
        "role_id"
    ]
    add_accomplishment(
        role_id=globex,
        situation="s",
        action="a",
        result="r",
        source_text=QUOTE_B,
        tool_context=ctx("sess-b"),
    )
    add_skill(name="Python", source_text=QUOTE_B, tool_context=ctx("sess-b"))

    removed = purge_session_records(repo(), USER, "sess-a")

    assert removed["roles"] == 1
    assert removed["accomplishments"] == 1
    assert removed["evidence"] == 2  # the accomplishment's and the skill's
    assert removed["skills"] == 1
    assert removed["education"] == 1
    assert removed["open_questions"] == 1

    profile = repo().get_profile(USER)
    assert [r.company for r in profile.roles] == ["Globex"]
    assert [a.source_text for a in profile.accomplishments] == [QUOTE_B]
    assert [s.name for s in profile.skills] == ["Python"]
    assert profile.education == []
    assert profile.open_questions == []


def test_a_role_other_chats_built_on_survives() -> None:
    """Deleting the chat that first mentioned Acme must not take chat B's work."""
    acme = add_role(company="Acme", title="Engineer", tool_context=ctx("sess-a"))[
        "role_id"
    ]
    add_accomplishment(
        role_id=acme,
        situation="s",
        action="a",
        result="r",
        source_text=QUOTE_B,
        tool_context=ctx("sess-b"),
    )

    removed = purge_session_records(repo(), USER, "sess-a")

    assert removed["roles"] == 0
    profile = repo().get_profile(USER)
    assert [r.company for r in profile.roles] == ["Acme"]
    assert len(profile.accomplishments) == 1


def test_a_skill_claimed_in_two_chats_survives_one_deletion() -> None:
    add_skill(name="SQL", source_text=QUOTE_A, tool_context=ctx("sess-a"))
    add_skill(
        name="SQL", level="strong", source_text=QUOTE_B, tool_context=ctx("sess-b")
    )

    removed = purge_session_records(repo(), USER, "sess-a")

    assert removed["skills"] == 0
    assert removed["evidence"] == 1
    (skill,) = repo().get_profile(USER).skills
    assert skill.name == "SQL"
    assert len(skill.evidence_ids) == 1, "only the other chat's evidence remains"


def test_purging_removes_the_chats_jobs_with_their_reports_and_files() -> None:
    doomed = a_job("sess-a")
    surviving = a_job("sess-b", title="Support Lead")
    store = repo()
    store.save_fit_report(
        FitReport(
            user_id=USER, job_id=doomed, score=50, summary="s", session_id="sess-b"
        )
    )
    store.save_resume(Resume(user_id=USER, job_id=doomed, session_id="sess-b"))
    store.save_resume_document(USER, doomed, "md", b"# resume")
    # A report written by the doomed chat against a job that survives.
    store.save_fit_report(
        FitReport(
            user_id=USER, job_id=surviving, score=60, summary="s", session_id="sess-a"
        )
    )

    removed = purge_session_records(store, USER, "sess-a")

    assert removed["jobs"] == 1
    # The doomed job's report and resume go with it even though another chat
    # wrote them: they describe a posting that no longer exists.
    assert removed["fit_reports"] == 2
    assert removed["resumes"] == 1
    assert store.get_job(USER, doomed) is None
    assert not store.resume_path(doomed, "md").exists()
    assert store.get_job(USER, surviving) is not None
    assert store.get_fit_report(USER, surviving) is None


def test_purging_removes_only_the_chats_journal_entries() -> None:
    job_id = a_job("sess-b")
    log_application_event(
        kind="applied", summary="Sent it.", job_id=job_id, tool_context=ctx("sess-a")
    )
    log_application_event(
        kind="screen", summary="They called.", job_id=job_id, tool_context=ctx("sess-b")
    )

    removed = purge_session_records(repo(), USER, "sess-a")

    assert removed["journal_entries"] == 1
    (entry,) = repo().list_journal_entries(USER)
    assert entry.kind == "screen"


def test_purging_twice_is_a_no_op() -> None:
    role_id = add_role(company="Acme", title="Engineer", tool_context=ctx("sess-a"))[
        "role_id"
    ]
    add_accomplishment(
        role_id=role_id,
        situation="s",
        action="a",
        result="r",
        source_text=QUOTE_A,
        tool_context=ctx("sess-a"),
    )
    a_job("sess-a")

    first = purge_session_records(repo(), USER, "sess-a")
    second = purge_session_records(repo(), USER, "sess-a")

    assert first["roles"] == 1 and first["jobs"] == 1
    assert all(count == 0 for count in second.values())
