"""The profile export holds everything, quotes the user exactly, and re-uploads."""

from __future__ import annotations

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
from head_hunter.doc_text import extract_text, is_excerpt
from head_hunter.profile_export import EXPORT_MARKER, render_profile_markdown
from head_hunter.schemas import (
    Accomplishment,
    Education,
    Evidence,
    Identity,
    OpenQuestion,
    Profile,
    Role,
    Skill,
)
from head_hunter.storage import FirestoreRepository

QUOTE = "Cut the nightly build from 40 minutes to 24 using remote caching."


def make_profile() -> Profile:
    role = Role(id="role-1", company="Acme", title="Engineer", start_date="2021-03")
    evidence = Evidence(id="ev-1", source_text=QUOTE, session_id="chat-1")
    return Profile(
        user_id="alice-uid",
        identity=Identity(full_name="Alice Smith", links=["https://example.com/a"]),
        goals=["Lead a platform team"],
        roles=[role],
        accomplishments=[
            Accomplishment(
                role_id="role-1",
                situation="Slow builds",
                action="Added remote caching",
                result="40 to 24 minutes",
                metrics=["40%"],
                tools=["Bazel"],
                evidence_id="ev-1",
                source_text=QUOTE,
                interpretation="Probably owned the build system.",
            )
        ],
        skills=[Skill(name="Bazel", level="strong", years=3, evidence_ids=["ev-1"])],
        education=[Education(institution="State U", credential="BS", field="CS")],
        evidence=[evidence],
        open_questions=[
            OpenQuestion(
                question="How big was the team?",
                hypothesis="Maybe six engineers.",
                reason="no scope given",
            )
        ],
    )


def test_the_export_holds_every_part_of_the_profile() -> None:
    text = render_profile_markdown(make_profile(), "2026-10-21")

    assert text.startswith(EXPORT_MARKER)
    for expected in [
        "Alice Smith",
        "https://example.com/a",
        "Lead a platform team",
        "Engineer at Acme",
        "2021-03 – present",
        "Added remote caching",
        "Bazel",
        "level: strong",
        "State U",
        "How big was the team?",
        "ev-1",
    ]:
        assert expected in text


def test_the_agents_own_guesses_are_labelled_as_such() -> None:
    text = render_profile_markdown(make_profile(), "2026-10-21")

    assert "Agent's reading (not evidence, never cited): Probably owned" in text
    assert "Agent's hunch (not confirmed, not a fact): Maybe six engineers." in text


def test_internal_chat_ids_are_not_exported() -> None:
    assert "chat-1" not in render_profile_markdown(make_profile(), "2026-10-21")


def test_an_empty_profile_still_exports() -> None:
    text = render_profile_markdown(Profile(user_id="alice-uid"), "2026-10-21")

    assert text.startswith(EXPORT_MARKER)
    assert "## Roles" in text


def test_the_export_survives_the_upload_path_with_quotes_intact() -> None:
    """The file is read back through the same extractor and quote check."""
    data = render_profile_markdown(make_profile(), "2026-10-21").encode()

    extracted = extract_text("career-profile-2026-10-21.md", data)

    assert extracted.text.startswith(EXPORT_MARKER)
    assert is_excerpt(QUOTE, extracted.text)


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)
    store = FirestoreRepository(client=FakeClient())
    store.save_profile(make_profile())
    tokens = {
        "alice-token": claims(),
        "bob-token": claims(sub="bob-uid", email="bob@example.com", name="Bob"),
    }
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier(tokens),
        runner=FakeRunner(),
        web_config=WEB_CONFIG,
        repo_factory=lambda: store,
    )
    return TestClient(app)


def test_the_endpoint_requires_sign_in(api: TestClient) -> None:
    assert api.get("/api/profile.md").status_code == 401


def test_the_endpoint_downloads_the_callers_profile(api: TestClient) -> None:
    response = api.get("/api/profile.md", headers=bearer("alice-token"))

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "career-profile-" in response.headers["content-disposition"]
    assert QUOTE in response.text


def test_the_endpoint_never_shows_another_users_profile(api: TestClient) -> None:
    response = api.get("/api/profile.md", headers=bearer("bob-token"))

    assert response.status_code == 404
    assert "Alice" not in response.text
