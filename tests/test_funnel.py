"""The funnel graph is arithmetic over journal entries, so these test the sums.

Every application lands in exactly one place, and the ribbons add up.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_auth_server import (
    PROJECT,
    WEB_CONFIG,
    FakeRunner,
    bearer,
    claims,
    fake_verifier,
)
from test_firestore_repo import FakeClient

from head_hunter import server
from head_hunter.funnel import STAGES, compute_funnel, describe_applications
from head_hunter.schemas import JournalEntry
from head_hunter.storage import FirestoreRepository, JsonRepository, StorageError
from head_hunter.tools import (
    ToolError,
    get_application_funnel,
    list_applications,
    log_application_event,
    save_job_posting,
)

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
USER = "local"


def event(kind: str, company: str, days_ago: int, user: str = USER) -> JournalEntry:
    return JournalEntry(
        user_id=user,
        company=company,
        title="Engineer",
        kind=kind,  # type: ignore[arg-type]
        occurred_at=NOW - timedelta(days=days_ago),
        summary=f"{kind} at {company}",
    )


def journey(company: str, kinds: list[str], last_days_ago: int) -> list[JournalEntry]:
    """Events one day apart, the last of them ``last_days_ago`` days ago."""
    return [
        event(kind, company, last_days_ago + (len(kinds) - 1 - i))
        for i, kind in enumerate(kinds)
    ]


SCENARIO = [
    *journey("A", ["applied", "screen", "interview", "rejection"], 5),
    *journey("B", ["applied"], 40),
    *journey("C", ["applied"], 2),
    *journey(
        "D", ["applied", "screen", "interview", "next_round", "final_round", "offer"], 3
    ),
    *journey("E", ["applied", "withdrawn"], 8),
    *journey("F", ["applied", "screen"], 10),
]


def stage(funnel, key: str):
    return next(s for s in funnel.stages if s.key == key)


def test_every_application_lands_in_the_right_column() -> None:
    funnel = compute_funnel(SCENARIO, now=NOW)

    assert funnel.total == 6
    assert [s.count for s in funnel.stages] == [6, 3, 2, 1, 1, 1]
    assert stage(funnel, "applied").exits == {
        "rejected": 0,
        "withdrawn": 1,
        "no_response": 1,
        "in_progress": 1,
    }
    assert stage(funnel, "screen").exits["in_progress"] == 1
    assert stage(funnel, "interview").exits["rejected"] == 1
    assert stage(funnel, "offer").exits == {}


def test_each_stage_equals_the_next_plus_what_left_it() -> None:
    funnel = compute_funnel(SCENARIO, now=NOW)
    for here, after in zip(funnel.stages, funnel.stages[1:], strict=False):
        assert here.count == after.count + sum(here.exits.values()), here.key


def test_silence_becomes_no_response_only_after_the_threshold() -> None:
    entries = journey("Quiet", ["applied"], 21)
    assert stage(compute_funnel(entries, now=NOW), "applied").exits["in_progress"] == 1

    entries = journey("Quiet", ["applied"], 22)
    assert stage(compute_funnel(entries, now=NOW), "applied").exits["no_response"] == 1


def test_a_later_event_overrides_an_earlier_rejection() -> None:
    entries = journey("Reopened", ["applied", "rejection", "interview"], 1)
    funnel = compute_funnel(entries, now=NOW)
    assert stage(funnel, "interview").exits["in_progress"] == 1


def test_declining_an_offer_still_counts_as_an_offer() -> None:
    entries = journey("Declined", ["applied", "offer", "withdrawn"], 1)
    funnel = compute_funnel(entries, now=NOW)
    assert stage(funnel, "offer").count == 1


def test_skipped_stages_still_count_in_the_stages_passed() -> None:
    funnel = compute_funnel(journey("Fast", ["applied", "final_round"], 1), now=NOW)
    assert [s.count for s in funnel.stages] == [1, 1, 1, 1, 1, 0]


def test_notes_and_unattached_entries_are_ignored() -> None:
    nameless = JournalEntry(user_id=USER, kind="applied", summary="applied somewhere")
    note = event("note", "A", 1)
    assert compute_funnel([nameless, note], now=NOW).total == 0


def test_company_and_title_match_ignores_case_and_spacing() -> None:
    first = event("applied", "Acme", 5)
    second = event("screen", " acme ", 3)
    assert compute_funnel([first, second], now=NOW).total == 1


def test_job_id_groups_events_regardless_of_company_wording() -> None:
    entries = [
        JournalEntry(
            user_id=USER,
            job_id="job-1",
            kind="applied",
            summary="x",
            occurred_at=NOW - timedelta(days=4),
        ),
        JournalEntry(
            user_id=USER,
            job_id="job-1",
            company="Acme Inc",
            title="Eng",
            kind="screen",
            summary="y",
            occurred_at=NOW - timedelta(days=2),
        ),
    ]
    funnel = compute_funnel(entries, now=NOW)
    assert funnel.total == 1
    assert stage(funnel, "screen").count == 1


def test_an_empty_journal_gives_an_empty_funnel() -> None:
    funnel = compute_funnel([], now=NOW)
    assert funnel.total == 0
    assert [s.label for s in funnel.stages] == [label for _, label in STAGES]
    assert all(s.count == 0 for s in funnel.stages)


def test_describe_applications_says_where_each_one_stands() -> None:
    rows = {r["company"]: r for r in describe_applications(SCENARIO, now=NOW)}
    assert rows["A"]["furthest_stage"] == "Interview"
    assert rows["A"]["status"] == "rejected"
    assert rows["B"]["status"] == "no_response"
    assert rows["D"]["status"] == "offer"


# Storage -------------------------------------------------------------------


@pytest.fixture(params=["json", "firestore"])
def repo(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "json":
        return JsonRepository(root=tmp_path)
    return FirestoreRepository(client=FakeClient())


def test_journal_entries_round_trip_oldest_first(repo) -> None:
    later, earlier = event("screen", "A", 1), event("applied", "A", 9)
    repo.save_journal_entry(later)
    repo.save_journal_entry(earlier)
    assert [e.kind for e in repo.list_journal_entries(USER)] == ["applied", "screen"]


def test_one_users_journal_is_invisible_to_another(repo) -> None:
    repo.save_journal_entry(event("applied", "A", 1, user="alice"))
    assert repo.list_journal_entries("bob") == []


def test_an_entry_id_cannot_be_overwritten(repo) -> None:
    entry = event("applied", "A", 1)
    repo.save_journal_entry(entry)
    with pytest.raises(StorageError, match="already exists"):
        repo.save_journal_entry(entry)


# Tools ---------------------------------------------------------------------


@pytest.fixture
def local_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JsonRepository:
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HH_SINGLE_USER", USER)
    return JsonRepository(root=tmp_path)


def test_logging_needs_an_application_to_attach_to(local_store) -> None:
    with pytest.raises(ToolError, match="company and the role title"):
        log_application_event("applied", "Sent it")
    with pytest.raises(ToolError, match="company and the role title"):
        log_application_event("applied", "Sent it", company="Acme")


def test_an_unknown_kind_is_refused(local_store) -> None:
    with pytest.raises(ToolError, match="Unknown event kind"):
        log_application_event("ghosted", "x", company="Acme", title="Eng")


def test_a_future_date_is_refused(local_store) -> None:
    with pytest.raises(ToolError, match="future"):
        log_application_event(
            "applied", "x", company="Acme", title="Eng", occurred_on="2999-01-01"
        )


def test_a_bad_date_is_refused(local_store) -> None:
    with pytest.raises(ToolError, match="not a date"):
        log_application_event(
            "applied", "x", company="Acme", title="Eng", occurred_on="last tuesday"
        )


def test_an_unknown_job_id_is_refused(local_store) -> None:
    with pytest.raises(ToolError, match="No saved posting"):
        log_application_event("applied", "x", job_id="job-nope")


def test_logging_against_a_saved_posting_borrows_its_company_and_title(
    local_store,
) -> None:
    saved = save_job_posting(
        raw_text="Build things. " * 20,
        requirements=[{"text": "Python", "kind": "required", "category": "skill"}],
        company="Acme",
        title="Engineer",
    )
    result = log_application_event("applied", "Sent", job_id=saved["job_id"])
    assert (result["company"], result["title"]) == ("Acme", "Engineer")


def test_logged_events_flow_into_the_funnel_tool(local_store) -> None:
    for kind in ("applied", "screen"):
        log_application_event(kind, kind, company="Acme", title="Eng")
    log_application_event("applied", "applied", company="Beta", title="Eng")

    funnel = get_application_funnel()
    assert funnel["total"] == 2
    assert [s["count"] for s in funnel["stages"]][:2] == [2, 1]
    assert list_applications()["count"] == 2


# Endpoint ------------------------------------------------------------------


@pytest.fixture
def api(local_store, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)
    tokens = {
        "alice-token": claims(),
        "bob-token": claims(sub="bob-uid", email="bob@example.com", name="Bob"),
    }
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier(tokens),
        runner=FakeRunner(),
        web_config=WEB_CONFIG,
        repo_factory=lambda: local_store,
    )
    return TestClient(app)


def test_the_funnel_endpoint_requires_sign_in(api: TestClient) -> None:
    assert api.get("/api/funnel").status_code == 401


def test_the_funnel_endpoint_shows_only_the_callers_applications(
    api: TestClient, local_store: JsonRepository
) -> None:
    local_store.save_journal_entry(event("applied", "A", 1, user="alice-uid"))
    local_store.save_journal_entry(event("applied", "B", 1, user="bob-uid"))
    local_store.save_journal_entry(event("screen", "B", 1, user="bob-uid"))

    alice = api.get("/api/funnel", headers=bearer("alice-token")).json()
    bob = api.get("/api/funnel", headers=bearer("bob-token")).json()

    assert alice["total"] == 1
    assert bob["total"] == 1
    assert alice["stages"][1]["count"] == 0
    assert bob["stages"][1]["count"] == 1


def test_the_graph_script_is_served(api: TestClient) -> None:
    response = api.get("/funnel.js")
    assert response.status_code == 200
    assert "HHFunnel" in response.text
