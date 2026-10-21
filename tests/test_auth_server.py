"""The signed-in server decides who is calling, so these tests try to fool it.

Token *signatures* are Google's to check and need the network, so a fake
verifier stands in for that step. Everything this repo is responsible for is
exercised for real: the claims checks, the 401s, and above all that the user id
the agent runs under is the one in the token and nothing a client can send.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Mapping
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from google.adk.events import Event
from google.adk.sessions import InMemorySessionService
from google.auth.exceptions import InvalidValue
from google.genai import types

from head_hunter import auth, config, server
from head_hunter.ratelimit import RateLimiter
from head_hunter.schemas import JobPosting, Requirement
from head_hunter.storage import JsonRepository

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
    """The things the server reads from an ADK event."""

    def __init__(
        self, author: str, text: str, final: bool = True, partial: bool = False
    ) -> None:
        self.author = author
        self.partial = partial
        self.content = SimpleNamespace(parts=[SimpleNamespace(text=text)])
        self._final = final

    def is_final_response(self) -> bool:
        return self._final


class FakeRunner:
    """Records who the agent was run as, and replies with a fixed answer.

    The reply arrives the way the real runner's does when the model streams:
    pieces marked partial, then one finished event carrying the whole text.
    """

    def __init__(self) -> None:
        self.session_service = InMemorySessionService()
        self.calls: list[dict[str, Any]] = []
        self.fail = False

    async def run_async(
        self,
        *,
        user_id: str,
        session_id: str,
        new_message: Any,
        run_config: Any = None,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "run_config": run_config,
            }
        )
        if self.fail:
            raise RuntimeError("secret internal detail /srv/secret")
        yield FakeEvent("head_hunter", "thinking...", final=False)
        yield FakeEvent("head_hunter", "hello ", final=False, partial=True)
        yield FakeEvent("head_hunter", user_id, final=False, partial=True)
        yield FakeEvent("head_hunter", f"hello {user_id}")


@pytest.fixture(autouse=True)
def multi_user_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)
    # The server reads the store for job labels and job-tagged chats; point it
    # at a throwaway directory so tests never see a developer's own data/.
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))


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
    assert client.get("/api/health").json() == {"status": "ok"}


def test_no_route_sits_on_a_path_cloud_run_reserves(client: TestClient) -> None:
    """Cloud Run's front end answers ``/healthz`` itself, with its own 404.

    A health route there is unreachable once deployed, and a smoke test pointed
    at it fails on a healthy service. Local runs cannot show this, so guard it.
    """
    paths = {getattr(route, "path", "") for route in client.app.routes}
    assert "/healthz" not in paths


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


# The streaming endpoint -----------------------------------------------------


def sse_payloads(body: str) -> list[dict[str, Any]]:
    """The JSON payloads of a server-sent-event response, in order."""
    prefix = "data: "
    return [
        json.loads(line[len(prefix) :])
        for line in body.splitlines()
        if line.startswith(prefix)
    ]


def test_stream_refuses_the_anonymous_and_never_runs_the_agent(
    client: TestClient, runner: FakeRunner
) -> None:
    anonymous = client.post("/api/chat/stream", json={"message": "hi"})
    assert anonymous.status_code == 401
    assert runner.calls == []


def test_stream_delivers_deltas_then_the_finished_reply(
    client: TestClient, runner: FakeRunner
) -> None:
    response = client.post(
        "/api/chat/stream", json={"message": "hi"}, headers=bearer("bob-token")
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = sse_payloads(response.text)
    assert events[0]["type"] == "session"
    assert events[0]["session_id"]
    assert {"type": "agent", "author": "head_hunter"} in events
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert "".join(deltas) == "hello bob-uid"
    # The reply carries the whole answer again, so a client can replace its
    # accumulated deltas with the text the non-streaming endpoint would return.
    assert {"type": "reply", "author": "head_hunter", "text": "hello bob-uid"} in events
    assert events[-1] == {"type": "done"}
    assert runner.calls[0]["user_id"] == "bob-uid"


def test_stream_asks_the_model_to_stream(
    client: TestClient, runner: FakeRunner
) -> None:
    from google.adk.agents.run_config import StreamingMode

    client.post(
        "/api/chat/stream", json={"message": "hi"}, headers=bearer("alice-token")
    )

    run_config = runner.calls[0]["run_config"]
    assert run_config is not None
    assert run_config.streaming_mode is StreamingMode.SSE


def test_stream_guards_conversations_like_chat_does(
    client: TestClient, runner: FakeRunner
) -> None:
    first = sse_payloads(
        client.post(
            "/api/chat/stream", json={"message": "hi"}, headers=bearer("alice-token")
        ).text
    )
    session_id = first[0]["session_id"]

    again = client.post(
        "/api/chat/stream",
        json={"message": "more", "session_id": session_id},
        headers=bearer("alice-token"),
    )
    assert sse_payloads(again.text)[0]["session_id"] == session_id

    runner.calls.clear()
    stolen = client.post(
        "/api/chat/stream",
        json={"message": "hi", "session_id": session_id},
        headers=bearer("bob-token"),
    )
    assert stolen.status_code == 404
    assert runner.calls == []


def test_a_mid_stream_failure_is_an_event_and_does_not_leak(
    client: TestClient, runner: FakeRunner
) -> None:
    runner.fail = True
    response = client.post(
        "/api/chat/stream", json={"message": "hi"}, headers=bearer("alice-token")
    )

    # The 200 and the session event are already out when the agent fails, so
    # the failure arrives as the last event rather than as a status code.
    assert response.status_code == 200
    assert sse_payloads(response.text)[-1]["type"] == "error"
    assert "secret" not in response.text


def test_stream_counts_against_the_same_message_limit(runner: FakeRunner) -> None:
    client = limited_client(runner, limit=1)
    ok = client.post(
        "/api/chat/stream", json={"message": "hi"}, headers=bearer("alice-token")
    )
    assert ok.status_code == 200

    over = client.post(
        "/api/chat/stream", json={"message": "hi"}, headers=bearer("alice-token")
    )
    assert over.status_code == 429
    assert len(runner.calls) == 1


# Past conversations ---------------------------------------------------------


# "Newest first" cannot order two conversations whose last events land in the
# same clock tick, and on Windows the clock ticks coarsely enough for seeds to
# tie. Each seeded conversation gets strictly later event timestamps.
_conversation_clock = count()


def seed_conversation(
    runner: FakeRunner,
    user_id: str,
    opener: str,
    reply: str = "Noted.",
    state: dict[str, Any] | None = None,
) -> str:
    """Store a finished exchange the way the real runner would, return its id."""
    stamp = time.time() + next(_conversation_clock) * 1e-3

    async def build() -> str:
        svc = runner.session_service
        session = await svc.create_session(
            app_name=server.APP_NAME, user_id=user_id, state=state
        )
        await svc.append_event(
            session,
            Event(
                author="user",
                timestamp=stamp,
                content=types.Content(role="user", parts=[types.Part(text=opener)]),
            ),
        )
        await svc.append_event(
            session,
            Event(
                author="head_hunter",
                timestamp=stamp + 1e-4,
                content=types.Content(role="model", parts=[types.Part(text=reply)]),
            ),
        )
        return session.id

    return asyncio.run(build())


def test_conversations_require_sign_in(client: TestClient) -> None:
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/conversations/x").status_code == 401


def test_recent_conversations_are_listed_newest_first(
    client: TestClient, runner: FakeRunner
) -> None:
    seed_conversation(runner, "alice-uid", "First chat about Acme")
    newest = seed_conversation(runner, "alice-uid", "Second chat about Beta")

    rows = client.get("/api/conversations", headers=bearer("alice-token")).json()

    assert [r["title"] for r in rows] == [
        "Second chat about Beta",
        "First chat about Acme",
    ]
    assert rows[0]["session_id"] == newest


def test_an_empty_conversation_is_not_listed(
    client: TestClient, runner: FakeRunner
) -> None:
    asyncio.run(
        runner.session_service.create_session(
            app_name=server.APP_NAME, user_id="alice-uid"
        )
    )
    assert client.get("/api/conversations", headers=bearer("alice-token")).json() == []


def test_a_conversation_replays_only_what_was_shown(
    client: TestClient, runner: FakeRunner
) -> None:
    sid = seed_conversation(runner, "alice-uid", "hi", reply="hello there")

    body = client.get(f"/api/conversations/{sid}", headers=bearer("alice-token")).json()

    assert body["messages"] == [
        {"author": "user", "text": "hi"},
        {"author": "head_hunter", "text": "hello there"},
    ]


def test_one_user_cannot_replay_anothers_conversation(
    client: TestClient, runner: FakeRunner
) -> None:
    sid = seed_conversation(runner, "alice-uid", "private things")

    stolen = client.get(f"/api/conversations/{sid}", headers=bearer("bob-token"))

    assert stolen.status_code == 404
    assert client.get("/api/conversations", headers=bearer("bob-token")).json() == []


# Deleting conversations -------------------------------------------------------


def test_deleting_a_conversation_requires_sign_in(client: TestClient) -> None:
    assert client.delete("/api/conversations/x").status_code == 401


def test_a_deleted_conversation_is_gone(client: TestClient, runner: FakeRunner) -> None:
    sid = seed_conversation(runner, "alice-uid", "delete me")

    gone = client.delete(f"/api/conversations/{sid}", headers=bearer("alice-token"))

    assert gone.status_code == 200
    assert gone.json()["status"] == "deleted"
    replay = client.get(f"/api/conversations/{sid}", headers=bearer("alice-token"))
    assert replay.status_code == 404
    assert client.get("/api/conversations", headers=bearer("alice-token")).json() == []


def test_deleting_a_conversation_that_is_not_there_is_a_404(
    client: TestClient,
) -> None:
    gone = client.delete("/api/conversations/nope", headers=bearer("alice-token"))
    assert gone.status_code == 404


def test_one_user_cannot_delete_anothers_conversation(
    client: TestClient, runner: FakeRunner
) -> None:
    sid = seed_conversation(runner, "alice-uid", "private things")

    stolen = client.delete(f"/api/conversations/{sid}", headers=bearer("bob-token"))

    assert stolen.status_code == 404
    rows = client.get("/api/conversations", headers=bearer("alice-token")).json()
    assert [r["session_id"] for r in rows] == [sid]


# Archiving conversations ------------------------------------------------------


def test_archiving_requires_sign_in(client: TestClient) -> None:
    assert client.post("/api/conversations/x/archive").status_code == 401
    assert client.post("/api/conversations/x/unarchive").status_code == 401


def test_an_archived_conversation_is_hidden_until_restored(
    client: TestClient, runner: FakeRunner
) -> None:
    kept = seed_conversation(runner, "alice-uid", "keep this one")
    hidden = seed_conversation(runner, "alice-uid", "archive this one")

    put_away = client.post(
        f"/api/conversations/{hidden}/archive", headers=bearer("alice-token")
    )
    assert put_away.status_code == 200

    rows = client.get("/api/conversations", headers=bearer("alice-token")).json()
    assert [r["session_id"] for r in rows] == [kept]

    archived = client.get(
        "/api/conversations?archived=true", headers=bearer("alice-token")
    ).json()
    assert [r["session_id"] for r in archived] == [hidden]

    # Archiving removes nothing: the conversation still replays.
    replay = client.get(f"/api/conversations/{hidden}", headers=bearer("alice-token"))
    assert replay.status_code == 200

    restored = client.post(
        f"/api/conversations/{hidden}/unarchive", headers=bearer("alice-token")
    )
    assert restored.status_code == 200
    rows = client.get("/api/conversations", headers=bearer("alice-token")).json()
    assert {r["session_id"] for r in rows} == {kept, hidden}


def test_one_user_cannot_archive_anothers_conversation(
    client: TestClient, runner: FakeRunner
) -> None:
    sid = seed_conversation(runner, "alice-uid", "private things")

    stolen = client.post(
        f"/api/conversations/{sid}/archive", headers=bearer("bob-token")
    )

    assert stolen.status_code == 404
    rows = client.get("/api/conversations", headers=bearer("alice-token")).json()
    assert [r["session_id"] for r in rows] == [sid]


# Chats tied to a saved job ----------------------------------------------------


def seed_job(user_id: str = "alice-uid", session_id: str | None = None) -> str:
    """Put one posting in the store, the way Intake would."""
    job = JobPosting(
        id="job-globex",
        user_id=user_id,
        source="paste",
        company="Globex",
        title="Data Engineer",
        requirements=[Requirement(text="Python", kind="required", category="skill")],
        raw_text="the posting as pasted",
        session_id=session_id,
    )
    JsonRepository().save_job(job)
    return job.id


def test_deleting_a_conversation_purges_what_it_added(
    client: TestClient, runner: FakeRunner
) -> None:
    """The whole point of delete-entirely: the chat's records go with it."""
    sid = seed_conversation(runner, "alice-uid", "paste a job, save it")
    job_id = seed_job(session_id=sid)

    gone = client.delete(f"/api/conversations/{sid}", headers=bearer("alice-token"))

    assert gone.status_code == 200
    assert gone.json()["removed"]["jobs"] == 1
    assert JsonRepository().get_job("alice-uid", job_id) is None


def test_deleting_a_conversation_leaves_other_chats_records(
    client: TestClient, runner: FakeRunner
) -> None:
    other = seed_conversation(runner, "alice-uid", "the chat that saved the job")
    doomed = seed_conversation(runner, "alice-uid", "an unrelated chat")
    job_id = seed_job(session_id=other)

    gone = client.delete(f"/api/conversations/{doomed}", headers=bearer("alice-token"))

    assert gone.status_code == 200
    assert gone.json()["removed"]["jobs"] == 0
    assert JsonRepository().get_job("alice-uid", job_id) is not None


def test_a_new_chat_can_be_tied_to_a_saved_job(
    client: TestClient, runner: FakeRunner
) -> None:
    job_id = seed_job()

    response = client.post(
        "/api/chat",
        json={"message": "hi", "job_id": job_id},
        headers=bearer("alice-token"),
    )

    assert response.status_code == 200
    session = asyncio.run(
        runner.session_service.get_session(
            app_name=server.APP_NAME,
            user_id="alice-uid",
            session_id=response.json()["session_id"],
        )
    )
    assert session.state["job_id"] == job_id


def test_a_chat_cannot_be_tied_to_a_job_that_is_not_there(
    client: TestClient, runner: FakeRunner
) -> None:
    response = client.post(
        "/api/chat",
        json={"message": "hi", "job_id": "job-nope"},
        headers=bearer("alice-token"),
    )

    assert response.status_code == 404
    assert runner.calls == []


def test_a_chat_cannot_be_tied_to_another_users_job(
    client: TestClient, runner: FakeRunner
) -> None:
    job_id = seed_job(user_id="alice-uid")

    response = client.post(
        "/api/chat",
        json={"message": "hi", "job_id": job_id},
        headers=bearer("bob-token"),
    )

    assert response.status_code == 404
    assert runner.calls == []


def test_a_jobs_conversations_can_be_listed_apart(
    client: TestClient, runner: FakeRunner
) -> None:
    job_id = seed_job()
    seed_conversation(runner, "alice-uid", "general career chat")
    tagged = seed_conversation(
        runner, "alice-uid", "about the Globex job", state={"job_id": job_id}
    )

    rows = client.get(
        f"/api/conversations?job_id={job_id}", headers=bearer("alice-token")
    ).json()

    assert [r["session_id"] for r in rows] == [tagged]
    assert rows[0]["job_id"] == job_id
    assert rows[0]["job_label"] == "Data Engineer at Globex"

    everything = client.get("/api/conversations", headers=bearer("alice-token")).json()
    assert len(everything) == 2
    untagged = next(r for r in everything if r["session_id"] != tagged)
    assert untagged["job_id"] is None and untagged["job_label"] is None


def test_a_jobs_list_includes_the_chat_that_saved_it(
    client: TestClient, runner: FakeRunner
) -> None:
    """The posting remembers the chat it was pasted in; that chat is listed."""
    saver = seed_conversation(runner, "alice-uid", "paste a JD, save it")
    seed_conversation(runner, "alice-uid", "an unrelated chat")
    job_id = seed_job(session_id=saver)

    rows = client.get(
        f"/api/conversations?job_id={job_id}", headers=bearer("alice-token")
    ).json()

    assert [r["session_id"] for r in rows] == [saver]


def test_a_jobs_list_includes_chats_that_worked_on_it(
    client: TestClient, runner: FakeRunner
) -> None:
    """One list: chats started from the job and chats whose tools touched it."""
    job_id = seed_job()
    started = seed_conversation(
        runner, "alice-uid", "started from the job", state={"job_id": job_id}
    )
    mentioned = seed_conversation(
        runner, "alice-uid", "asked about the job later", state={"job_ids": [job_id]}
    )
    seed_conversation(runner, "alice-uid", "a chat about something else")

    rows = client.get(
        f"/api/conversations?job_id={job_id}", headers=bearer("alice-token")
    ).json()

    assert {r["session_id"] for r in rows} == {started, mentioned}


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


def test_the_markdown_renderer_is_served_and_builds_dom_only(
    client: TestClient,
) -> None:
    """Replies render as Markdown, but never through an HTML parser."""
    response = client.get("/markdown.js")
    assert response.status_code == 200
    assert "HHMarkdown" in response.text
    assert "innerHTML" not in response.text


def test_download_links_do_not_read_the_loop_variable_on_click(
    client: TestClient,
) -> None:
    """`m` is reassigned on every pass, so a click handler reading it is dead.

    This was why the resume links in chat did nothing.
    """
    source = client.get("/markdown.js").text
    assert "detail: m[" not in source
    assert "var path = m[7]" in source


def test_the_page_is_given_its_firebase_settings(client: TestClient) -> None:
    assert client.get("/firebase-config.json").json() == WEB_CONFIG


def test_link_previews_get_absolute_https_urls(client: TestClient) -> None:
    """Social scrapers refuse relative image URLs, and Cloud Run is https."""
    text = client.get("/").text
    assert "__BASE__" not in text
    assert 'content="https://testserver/og.png"' in text


def test_the_brand_assets_are_served(client: TestClient) -> None:
    for name, kind in [
        ("favicon.svg", "image/svg+xml"),
        ("apple-touch-icon.png", "image/png"),
        ("icon-192.png", "image/png"),
        ("icon-512.png", "image/png"),
        ("og.png", "image/png"),
        ("site.webmanifest", "application/manifest+json"),
    ]:
        response = client.get(f"/{name}")
        assert response.status_code == 200, name
        assert response.headers["content-type"].startswith(kind), name


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
