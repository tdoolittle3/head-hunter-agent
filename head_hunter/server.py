"""The signed-in front door to the agent.

``adk web`` has no login: it hands every browser the same user id. This app is
what stands between the internet and the agent once more than one person can
reach it. Every route except ``/healthz`` requires a Firebase token, and the
user id the agent runs under comes from that verified token and nowhere else.
The request body has no user field -- sending one is rejected -- so there is
nothing a client can set to become someone else.

Run it with ``make serve``. Which Firebase project to trust comes from
``HH_FIREBASE_PROJECT`` (see ``.env.example``).
"""

# No `from __future__ import annotations`: FastAPI resolves the Annotated
# dependencies below at runtime, and cannot see the locally defined
# `current_user` through a string annotation.

import json
import logging
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from head_hunter import config
from head_hunter.auth import (
    AuthError,
    TokenVerifier,
    VerifiedUser,
    google_verifier,
    verify_user,
)

logger = logging.getLogger(__name__)

APP_NAME = "head_hunter"
WEB_DIR = Path(__file__).parent / "web"
MAX_MESSAGE_CHARS = 20_000
"""A pasted job description is long; anything past this is not a chat message."""


class ChatRequest(BaseModel):
    """One turn from the user."""

    # forbid, not ignore: a client that sends `user_id` is either confused or
    # probing, and silently dropping the field would hide that.
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    session_id: str | None = Field(
        default=None,
        description="Continue this conversation. Omit to start a new one.",
    )


class Reply(BaseModel):
    """One finished answer from an agent."""

    author: str
    text: str


class ChatResponse(BaseModel):
    """What the agent said, and the session to continue it in."""

    session_id: str
    replies: list[Reply]


def _load_web_config() -> dict[str, str]:
    """Read the Firebase settings the login page signs in with.

    These values are public by design -- every visitor's browser receives them
    -- so they live in the repo rather than in a secret.
    """
    return json.loads((WEB_DIR / "firebase-config.json").read_text(encoding="utf-8"))


def _build_runner() -> Runner:
    # Imported here so importing this module (and its tests) does not construct
    # the agents or need Google Cloud credentials.
    from head_hunter.agent import app as agent_app

    return Runner(app=agent_app, session_service=InMemorySessionService())


def _final_replies(events: list[Any]) -> list[Reply]:
    replies = []
    for event in events:
        if not event.is_final_response() or not event.content:
            continue
        text = "".join(p.text for p in event.content.parts or [] if p.text)
        if text.strip():
            replies.append(Reply(author=event.author, text=text))
    return replies


def create_app(
    *,
    project_id: str | None = None,
    verifier: TokenVerifier | None = None,
    runner: Runner | None = None,
    web_config: dict[str, str] | None = None,
) -> FastAPI:
    """Build the web app.

    Args:
        project_id: The Firebase project to trust. Defaults to the environment.
        verifier: Token checker. Defaults to Google's; tests pass a fake.
        runner: The ADK runner. Defaults to the real Head Hunter agent.
        web_config: Firebase settings for the login page. Defaults to the file.

    Raises:
        RuntimeError: ``HH_SINGLE_USER`` is set. It pins every session to one
            profile, which would make the verified id meaningless and hand
            everyone who signs in the same career.
        ValueError: The login page signs
            in against a different project than the server trusts. That mismatch
            lets people sign in and then be refused on every request.
    """
    if config.single_user():
        raise RuntimeError(
            "HH_SINGLE_USER is set, so every user would share one profile. "
            "Unset it before running the signed-in server."
        )
    web_config = web_config if web_config is not None else _load_web_config()
    project = project_id or config.firebase_project() or web_config.get("projectId")
    if not project:
        raise ValueError("No Firebase project: set HH_FIREBASE_PROJECT.")
    if web_config.get("projectId") != project:
        raise ValueError(
            f"The login page signs in against {web_config.get('projectId')!r} but "
            f"the server trusts {project!r}. Set HH_FIREBASE_PROJECT to match "
            "head_hunter/web/firebase-config.json."
        )
    check = verifier or google_verifier
    runner = runner or _build_runner()
    api = FastAPI(title="Head Hunter", docs_url=None, redoc_url=None)

    def current_user(
        authorization: str | None = Header(default=None),
    ) -> VerifiedUser:
        try:
            return verify_user(authorization, project, check)
        except AuthError as exc:
            raise HTTPException(
                status_code=401,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @api.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(
            WEB_DIR / "index.html",
            headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
        )

    @api.get("/firebase-config.json", include_in_schema=False)
    def firebase_config() -> JSONResponse:
        return JSONResponse(web_config)

    @api.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/api/me")
    def me(
        user: Annotated[VerifiedUser, Depends(current_user)],
    ) -> dict[str, str | None]:
        return {"uid": user.uid, "email": user.email, "name": user.name}

    @api.post("/api/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> ChatResponse:
        sessions = runner.session_service
        if body.session_id is None:
            session = await sessions.create_session(app_name=APP_NAME, user_id=user.uid)
        else:
            # Looked up under the caller's own uid, so someone else's session
            # id is indistinguishable from one that does not exist.
            session = await sessions.get_session(
                app_name=APP_NAME, user_id=user.uid, session_id=body.session_id
            )
            if session is None:
                raise HTTPException(status_code=404, detail="No such conversation.")

        message = types.Content(role="user", parts=[types.Part(text=body.message)])
        try:
            events = [
                event
                async for event in runner.run_async(
                    user_id=user.uid, session_id=session.id, new_message=message
                )
            ]
        except Exception:
            # The detail goes to the log; the caller gets nothing that could
            # carry another user's data or an internal path.
            logger.exception("Agent run failed for session %s", session.id)
            raise HTTPException(
                status_code=500, detail="The agent hit an error. Try again."
            ) from None
        return ChatResponse(session_id=session.id, replies=_final_replies(events))

    return api
