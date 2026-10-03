"""The signed-in server decides who is calling, so these tests try to fool it.

Token *signatures* are Google's to check and need the network, so a fake
verifier stands in for that step. Everything this repo is responsible for is
exercised for real: the claims checks, the 401s, and above all that the user id
the agent runs under is the one in the token and nothing a client can send.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.adk.sessions import InMemorySessionService
from google.auth.exceptions import InvalidValue

from head_hunter import auth, config, server
from head_hunter.ratelimit import RateLimiter

PROJECT = "head-hunter-agent"
WEB_CONFIG = {"projectId": PROJECT, "apiKey": "k", "authDomain": "a", "appId": "i"}


def claims(**overrides: Any) -> dict[str, Any]:
    """The claims of a good Google sign-in token, with ``overrides`` applied."""
    good: dict[str, Any] = {
        "sub": "alice-uid",
        "aud": PROJECT,
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "email": "alice@example.com",
        "email_verified": True,
        "name": "Alice Adams",
        "firebase": {"sign_in_provider": "google.com"},
    }
    good.update(overrides)
    return good


def fake_verifier(table: Mapping[str, Mapping[str, Any]]) -> auth.TokenVerifier:
    """Accept only the tokens in ``table``; reject the rest like Google would."""

    def verify(token: str, project_id: str) -> Mapping[str, Any]:
        try:
            return table[token]
        except KeyError:
            raise InvalidValue("bad signature") from None

    return verify


class FakeEvent:
    """The two things the server reads from an ADK event."""

    def __init__(self, author: str, text: str, final: bool = True) -> None:
        self.author = author
        self.content = SimpleNamespace(parts=[SimpleNamespace(text=text)])
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    """Records who the agent was run as, and replies with a fixed answer."""

    def __init__(self) -> None:
        self.session_service = InMemorySessionService()
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    async def run_async(self, *, user_id: str, session_id: str, new_message: Any):
        self.calls.append({"user_id": user_id, "session_id": session_id})
        if self.fail:
            raise RuntimeError("secret internal detail /srv/secret")
        yield FakeEvent("head_hunter", "thinking...", final=False)
        yield FakeEvent("head_hunter", f"hello {user_id}")


@pytest.fixture(autouse=True)
def multi_user_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def client(runner: FakeRunner) -> TestClient:
    tokens = {
        "alice-token": claims(),
        "bob-token": claims(sub="bob-uid", email="bob@example.com", name="Bob"),
    }
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier(tokens),
        runner=runner,
        web_config=WEB_CONFIG,
    )
    return TestClient(app)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# Claims checks ------------------------------------------------------------


def verify(token_claims: dict[str, Any]) -> auth.VerifiedUser:
    return auth.verify_user("Bearer t", PROJECT, lambda token, project: token_claims)


def test_a_good_token_identifies_the_user() -> None:
    user = verify(claims())
    assert (user.uid, user.email, user.name) == (
        "alice-uid",
        "alice@example.com",
        "Alice Adams",
    )


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"aud": "someone-elses-project"}, "different project"),
        ({"iss": "https://securetoken.google.com/someone-elses-project"}, "issued"),
        ({"iss": "https://evil.example.com"}, "issued"),
        ({"firebase": {"sign_in_provider": "anonymous"}}, "Google sign-in"),
        ({"firebase": {"sign_in_provider": "password"}}, "Google sign-in"),
        ({"firebase": {}}, "Google sign-in"),
        ({"email_verified": False}, "not verified"),
        ({"email_verified": "true"}, "not verified"),
        ({"sub": ""}, "does not say who"),
        ({"sub": None}, "does not say who"),
    ],
)
def test_a_token_with_the_wrong_claims_is_refused(
    override: dict[str, Any], why: str
) -> None:
    with pytest.raises(auth.AuthError, match=why):
        verify(claims(**override))


@pytest.mark.parametrize(
    "header", [None, "", "Bearer", "Bearer ", "Basic abc", "abc", "bearer"]
)
def test_a_malformed_authorization_header_is_refused(header: str | None) -> None:
    with pytest.raises(auth.AuthError):
        auth.verify_user(header, PROJECT, lambda t, p: claims())


def test_an_invalid_signature_is_refused() -> None:
    def reject(token: str, project_id: str) -> Mapping[str, Any]:
        raise InvalidValue("Token expired")

    with pytest.raises(auth.AuthError, match="invalid or has expired"):
        auth.verify_user("Bearer t", PROJECT, reject)


# The routes ---------------------------------------------------------------


def test_health_check_needs_no_sign_in(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_me_refuses_the_anonymous_and_the_forged(client: TestClient) -> None:
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers=bearer("forged")).status_code == 401


def test_chat_refuses_the_anonymous_and_never_runs_the_agent(
    client: TestClient, runner: FakeRunner
) -> None:
    assert client.post("/api/chat", json={"message": "hi"}).status_code == 401
    forged = client.post("/api/chat", json={"message": "hi"}, headers=bearer("nope"))
    assert forged.status_code == 401
    assert runner.calls == []


def test_me_reports_the_verified_identity(client: TestClient) -> None:
    body = client.get("/api/me", headers=bearer("alice-token")).json()
    assert body["uid"] == "alice-uid"


def test_the_agent_runs_as_the_user_in_the_token(
    client: TestClient, runner: FakeRunner
) -> None:
    response = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("bob-token")
    )

    assert response.status_code == 200
    assert runner.calls[0]["user_id"] == "bob-uid"
    # Only the finished answer comes back, not the intermediate chatter.
    assert response.json()["replies"] == [
        {"author": "head_hunter", "text": "hello bob-uid"}
    ]


def test_a_client_cannot_name_the_user_it_wants_to_be(
    client: TestClient, runner: FakeRunner
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "hi", "user_id": "alice-uid"},
        headers=bearer("bob-token"),
    )

    assert response.status_code == 422
    assert runner.calls == []


def test_a_conversation_can_be_continued(client: TestClient) -> None:
    first = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
    ).json()
    again = client.post(
        "/api/chat",
        json={"message": "more", "session_id": first["session_id"]},
        headers=bearer("alice-token"),
    )

    assert again.status_code == 200
    assert again.json()["session_id"] == first["session_id"]


def test_one_user_cannot_use_anothers_conversation(
    client: TestClient, runner: FakeRunner
) -> None:
    alices = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
    ).json()
    runner.calls.clear()

    stolen = client.post(
        "/api/chat",
        json={"message": "show me her profile", "session_id": alices["session_id"]},
        headers=bearer("bob-token"),
    )

    assert stolen.status_code == 404
    assert runner.calls == []


def test_an_agent_failure_does_not_leak_details(
    client: TestClient, runner: FakeRunner
) -> None:
    runner.fail = True
    response = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
    )

    assert response.status_code == 500
    assert "secret" not in response.text


@pytest.mark.parametrize("message", ["", "x" * (server.MAX_MESSAGE_CHARS + 1)])
def test_empty_and_oversized_messages_are_refused(
    client: TestClient, message: str
) -> None:
    response = client.post(
        "/api/chat", json={"message": message}, headers=bearer("alice-token")
    )
    assert response.status_code == 422


# Refusing to start unsafely -----------------------------------------------


def test_the_server_will_not_start_with_everyone_pinned_to_one_profile(
    monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.setenv("HH_SINGLE_USER", "local")
    with pytest.raises(RuntimeError, match="HH_SINGLE_USER"):
        server.create_app(project_id=PROJECT, runner=runner, web_config=WEB_CONFIG)


def test_the_server_trusts_the_project_the_page_signs_in_against(
    monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.delenv("HH_FIREBASE_PROJECT", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "the-agents-own-project")

    # Firebase may be a different project from the one hosting the agent, so the
    # Cloud project must not be mistaken for it.
    assert server.create_app(runner=runner, web_config=WEB_CONFIG) is not None
    assert config.firebase_project() is None


def test_an_explicit_firebase_project_must_match_the_page(
    monkeypatch: pytest.MonkeyPatch, runner: FakeRunner
) -> None:
    monkeypatch.setenv("HH_FIREBASE_PROJECT", "some-other-project")
    with pytest.raises(ValueError, match="some-other-project"):
        server.create_app(runner=runner, web_config=WEB_CONFIG)


def test_the_real_agent_builds_behind_the_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default wiring constructs, so a typo here fails in CI, not in prod."""
    monkeypatch.delenv("HH_FIREBASE_PROJECT", raising=False)
    assert server.create_app() is not None


# The login page ---------------------------------------------------------------


def test_the_login_page_loads_without_signing_in(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Sign in with Google" in response.text
    assert response.headers["x-frame-options"] == "DENY"


def test_the_page_never_puts_agent_text_into_html(client: TestClient) -> None:
    """Agent replies and pasted postings are untrusted; only textContent is safe."""
    assert "innerHTML" not in client.get("/").text


def test_the_page_is_given_its_firebase_settings(client: TestClient) -> None:
    assert client.get("/firebase-config.json").json() == WEB_CONFIG


def test_a_page_signing_into_another_project_is_caught_at_startup(
    runner: FakeRunner,
) -> None:
    other = {**WEB_CONFIG, "projectId": "some-other-project"}
    with pytest.raises(ValueError, match="some-other-project"):
        server.create_app(project_id=PROJECT, runner=runner, web_config=other)


def test_the_shipped_web_config_is_complete() -> None:
    shipped = server._load_web_config()
    assert {"apiKey", "authDomain", "projectId", "appId"} <= shipped.keys()
    assert shipped["authDomain"] == f"{shipped['projectId']}.firebaseapp.com"


# Cost protection and persistence ------------------------------------------


def limited_client(runner: FakeRunner, limit: int) -> TestClient:
    tokens = {
        "alice-token": claims(),
        "bob-token": claims(sub="bob-uid", email="bob@example.com", name="Bob"),
    }
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier(tokens),
        runner=runner,
        web_config=WEB_CONFIG,
        limiter=RateLimiter([(limit, 60)]),
    )
    return TestClient(app)


def test_a_user_over_the_limit_gets_a_429_and_the_agent_is_not_run(
    runner: FakeRunner,
) -> None:
    client = limited_client(runner, limit=2)
    for _ in range(2):
        ok = client.post(
            "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
        )
        assert ok.status_code == 200

    over = client.post(
        "/api/chat", json={"message": "hi"}, headers=bearer("alice-token")
    )

    assert over.status_code == 429
    assert int(over.headers["retry-after"]) >= 1
    assert len(runner.calls) == 2


def test_one_users_limit_does_not_use_up_anothers(runner: FakeRunner) -> None:
    client = limited_client(runner, limit=1)
    client.post("/api/chat", json={"message": "hi"}, headers=bearer("alice-token"))

    bob = client.post("/api/chat", json={"message": "hi"}, headers=bearer("bob-token"))
    assert bob.status_code == 200


def test_an_anonymous_flood_is_refused_before_it_is_counted(
    runner: FakeRunner,
) -> None:
    client = limited_client(runner, limit=1)
    for _ in range(5):
        assert client.post("/api/chat", json={"message": "x"}).status_code == 401

    ok = client.post("/api/chat", json={"message": "hi"}, headers=bearer("alice-token"))
    assert ok.status_code == 200


def test_firestore_storage_keeps_conversations_in_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from google.adk.integrations.firestore.firestore_session_service import (
        FirestoreSessionService,
    )
    from google.cloud import firestore

    monkeypatch.setenv("HH_STORAGE", "firestore")
    monkeypatch.setattr(firestore, "AsyncClient", MagicMock())

    assert isinstance(server._build_session_service(), FirestoreSessionService)


def test_json_storage_keeps_conversations_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HH_STORAGE", "json")
    assert isinstance(server._build_session_service(), InMemorySessionService)
