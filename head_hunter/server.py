"""The signed-in front door to the agent.

``adk web`` has no login: it hands every browser the same user id. This app is
what stands between the internet and the agent once more than one person can
reach it. Every route except ``/api/health``, the login page and its static
files (``/funnel.js``, ``/firebase-config.json``) requires a Firebase token, and
the user id the agent runs under comes from that verified
token and nowhere else.
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
import re
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import BaseSessionService, InMemorySessionService, Session
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
from head_hunter.doc_text import (
    MAX_FILE_BYTES,
    ExtractionError,
    display_name,
    extract_text,
)
from head_hunter.job_views import (
    JobDetail,
    JobSummary,
    build_job_detail,
    summarize_jobs,
)
from head_hunter.overview import Overview, compute_overview
from head_hunter.ratelimit import RateLimiter
from head_hunter.resume_render import MarkdownRenderError, render_docx, render_markdown
from head_hunter.schemas import JobPosting, UploadedDocument
from head_hunter.storage import Repository, StorageError
from head_hunter.tools._base import repository as default_repository

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


class UploadResponse(BaseModel):
    """What was stored from an uploaded file."""

    upload_id: str
    filename: str
    characters: int
    pages: int | None


MAX_UPLOADS_PER_USER = 20
"""A ceiling on stored uploads, since there is no delete yet."""

UPLOAD_LIMITS = [(10, 60.0), (30, 86_400.0)]
"""Uploads cost no Gemini call, but each is parsed and stored, so they get their
own, separate limit rather than eating into the message allowance."""


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


def _build_session_service() -> BaseSessionService:
    """Keep conversations where the profile is kept.

    With Firestore storage, chat history survives a restart and is visible to
    every Cloud Run instance, so a conversation does not vanish when traffic
    lands on a different one. Sessions are filed under the user id, which is the
    same verified id the profile uses.
    """
    if config.storage_backend() != "firestore":
        return InMemorySessionService()
    # Imported here so a laptop running the JSON backend never needs Firestore.
    from google.adk.integrations.firestore.firestore_session_service import (
        FirestoreSessionService,
    )
    from google.cloud import firestore

    client = firestore.AsyncClient(database=config.firestore_database())
    return FirestoreSessionService(client=client)


def _build_runner() -> Runner:
    # Imported here so importing this module (and its tests) does not construct
    # the agents or need Google Cloud credentials.
    from head_hunter.agent import app as agent_app

    return Runner(app=agent_app, session_service=_build_session_service())


def _resume_filename(job: JobPosting, suffix: str) -> str:
    """A download name people can tell apart in a folder of resumes."""
    base = " ".join(part for part in (job.company, job.title) if part) or job.id
    slug = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower() or "resume"
    return f"resume-{slug}.{suffix}"


DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _sse(payload: dict[str, Any]) -> str:
    """One server-sent event carrying a JSON payload."""
    return f"data: {json.dumps(payload)}\n\n"


def _event_text(event: Any) -> str:
    if not event.content:
        return ""
    return "".join(p.text for p in event.content.parts or [] if p.text)


def _final_replies(events: list[Any]) -> list[Reply]:
    replies = []
    for event in events:
        if not event.is_final_response():
            continue
        text = _event_text(event)
        if text.strip():
            replies.append(Reply(author=event.author, text=text))
    return replies


def create_app(
    *,
    project_id: str | None = None,
    verifier: TokenVerifier | None = None,
    runner: Runner | None = None,
    web_config: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    upload_limiter: RateLimiter | None = None,
    repo_factory: Callable[[], Repository] | None = None,
) -> FastAPI:
    """Build the web app.

    Args:
        project_id: The Firebase project to trust. Defaults to the environment.
        verifier: Token checker. Defaults to Google's; tests pass a fake.
        runner: The ADK runner. Defaults to the real Head Hunter agent.
        web_config: Firebase settings for the login page. Defaults to the file.
        limiter: Per-user message limits. Defaults to the environment's.
        upload_limiter: Per-user upload limits. Defaults to ``UPLOAD_LIMITS``.
        repo_factory: Opens the store uploads are saved to. Defaults to the same
            backend the agent's tools use, so the Interviewer can read them.

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
    limiter = limiter or RateLimiter(config.rate_limits())
    upload_limiter = upload_limiter or RateLimiter(UPLOAD_LIMITS)
    open_repository = repo_factory or default_repository
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

    @api.get("/funnel.js", include_in_schema=False)
    def funnel_script() -> FileResponse:
        return FileResponse(
            WEB_DIR / "funnel.js",
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @api.get("/firebase-config.json", include_in_schema=False)
    def firebase_config() -> JSONResponse:
        return JSONResponse(web_config)

    @api.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/api/me")
    def me(
        user: Annotated[VerifiedUser, Depends(current_user)],
    ) -> dict[str, str | None]:
        return {"uid": user.uid, "email": user.email, "name": user.name}

    @api.get("/api/overview", response_model=Overview)
    def overview(user: Annotated[VerifiedUser, Depends(current_user)]) -> Overview:
        """Everything the Profile page shows, from the caller's own records."""
        try:
            repo = open_repository()
            profile = repo.get_profile(user.uid)
            jobs = repo.list_jobs(user.uid)
            reports = [
                report
                for job in jobs
                if (report := repo.get_fit_report(user.uid, job.id)) is not None
            ]
            resumes = sum(
                1 for job in jobs if repo.get_resume(user.uid, job.id) is not None
            )
            entries = repo.list_journal_entries(user.uid)
        except StorageError:
            logger.exception("Could not read the overview for %s", user.uid)
            raise HTTPException(
                status_code=500, detail="Could not load your overview. Try again."
            ) from None
        return compute_overview(profile, jobs, reports, resumes, entries)

    @api.get("/api/jobs", response_model=list[JobSummary])
    def jobs(user: Annotated[VerifiedUser, Depends(current_user)]) -> list[JobSummary]:
        """The caller's saved postings, each with its fit score if analysed."""
        try:
            repo = open_repository()
            saved = repo.list_jobs(user.uid)
            reports = {job.id: repo.get_fit_report(user.uid, job.id) for job in saved}
            with_resumes = {
                job.id for job in saved if repo.get_resume(user.uid, job.id) is not None
            }
        except StorageError:
            logger.exception("Could not list jobs for %s", user.uid)
            raise HTTPException(
                status_code=500, detail="Could not load your jobs. Try again."
            ) from None
        return summarize_jobs(saved, reports, with_resumes)

    @api.get("/api/jobs/{job_id}", response_model=JobDetail)
    def job_detail(
        job_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> JobDetail:
        """One posting with its fit report, the cited evidence quoted in full."""
        try:
            repo = open_repository()
            job = repo.get_job(user.uid, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="No such job.")
            report = repo.get_fit_report(user.uid, job_id)
            profile = repo.get_profile(user.uid)
            has_resume = repo.get_resume(user.uid, job_id) is not None
        except StorageError:
            logger.exception("Could not load job %s for %s", job_id, user.uid)
            raise HTTPException(
                status_code=500, detail="Could not load that job. Try again."
            ) from None
        return build_job_detail(job, report, profile, has_resume)

    def rendered_resume(user_id: str, job_id: str) -> tuple[JobPosting, str]:
        """The resume for one job as Markdown, or the HTTP error saying why not."""
        try:
            repo = open_repository()
            job = repo.get_job(user_id, job_id)
            if job is None:
                raise HTTPException(status_code=404, detail="No such job.")
            resume = repo.get_resume(user_id, job_id)
            profile = repo.get_profile(user_id)
        except StorageError:
            logger.exception("Could not load the resume for job %s", job_id)
            raise HTTPException(
                status_code=500, detail="Could not load that resume. Try again."
            ) from None
        if resume is None or profile is None:
            raise HTTPException(
                status_code=404,
                detail="No resume for this job yet. Ask for one in the chat.",
            )
        return job, render_markdown(resume, profile)

    @api.get("/api/jobs/{job_id}/resume.md")
    def resume_markdown(
        job_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> PlainTextResponse:
        job, markdown = rendered_resume(user.uid, job_id)
        return PlainTextResponse(
            markdown,
            media_type="text/markdown",
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_resume_filename(job, "md")}"'
                )
            },
        )

    @api.get("/api/jobs/{job_id}/resume.docx")
    def resume_document(
        job_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> Response:
        job, markdown = rendered_resume(user.uid, job_id)
        try:
            content = render_docx(markdown)
        except MarkdownRenderError:
            logger.exception("Could not render the resume for job %s", job_id)
            raise HTTPException(
                status_code=500, detail="Could not render the resume file."
            ) from None
        return Response(
            content,
            media_type=DOCX_MEDIA_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{_resume_filename(job, "docx")}"'
                )
            },
        )

    @api.post("/api/upload", response_model=UploadResponse)
    def upload(
        user: Annotated[VerifiedUser, Depends(current_user)],
        file: Annotated[UploadFile, File()],
    ) -> UploadResponse:
        """Turn an uploaded resume into stored text the Interviewer can read."""
        wait = upload_limiter.check(user.uid)
        if wait > 0:
            seconds = max(1, round(wait))
            raise HTTPException(
                status_code=429,
                detail=f"Too many uploads. Try again in {seconds}s.",
                headers={"Retry-After": str(seconds)},
            )

        data = file.file.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, "
                    "which is too big for a resume."
                ),
            )
        try:
            extracted = extract_text(file.filename, data)
        except ExtractionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        try:
            repo = open_repository()
            if len(repo.list_uploads(user.uid)) >= MAX_UPLOADS_PER_USER:
                raise HTTPException(
                    status_code=409,
                    detail=f"You have reached the limit of {MAX_UPLOADS_PER_USER} "
                    "uploaded files.",
                )
            record = repo.save_upload(
                UploadedDocument(
                    user_id=user.uid,
                    filename=display_name(file.filename),
                    text=extracted.text,
                    pages=extracted.pages,
                )
            )
        except StorageError:
            logger.exception("Could not store an upload for %s", user.uid)
            raise HTTPException(
                status_code=500, detail="Could not save your file. Try again."
            ) from None
        return UploadResponse(
            upload_id=record.id,
            filename=record.filename,
            characters=len(record.text),
            pages=record.pages,
        )

    def check_message_limit(uid: str) -> None:
        wait = limiter.check(uid)
        if wait > 0:
            seconds = max(1, round(wait))
            raise HTTPException(
                status_code=429,
                detail=f"Too many messages. Try again in {seconds}s.",
                headers={"Retry-After": str(seconds)},
            )

    async def open_session(uid: str, session_id: str | None) -> Session:
        sessions = runner.session_service
        if session_id is None:
            return await sessions.create_session(app_name=APP_NAME, user_id=uid)
        # Looked up under the caller's own uid, so someone else's session
        # id is indistinguishable from one that does not exist.
        session = await sessions.get_session(
            app_name=APP_NAME, user_id=uid, session_id=session_id
        )
        if session is None:
            raise HTTPException(status_code=404, detail="No such conversation.")
        return session

    @api.post("/api/chat", response_model=ChatResponse)
    async def chat(
        body: ChatRequest, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> ChatResponse:
        check_message_limit(user.uid)
        session = await open_session(user.uid, body.session_id)

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

    @api.post("/api/chat/stream")
    async def chat_stream(
        body: ChatRequest, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> StreamingResponse:
        """The same turn as ``/api/chat``, delivered as it happens.

        Server-sent events, one JSON payload each:
        ``session`` (always first), ``agent`` (a specialist started working),
        ``delta`` (a piece of text as the model writes it), ``reply`` (one
        agent's finished answer -- replaces that agent's deltas, which are
        drafts of it), ``error``, and ``done``.
        """
        check_message_limit(user.uid)
        session = await open_session(user.uid, body.session_id)
        message = types.Content(role="user", parts=[types.Part(text=body.message)])

        async def events() -> AsyncIterator[str]:
            yield _sse({"type": "session", "session_id": session.id})
            author = None
            try:
                async for event in runner.run_async(
                    user_id=user.uid,
                    session_id=session.id,
                    new_message=message,
                    run_config=RunConfig(streaming_mode=StreamingMode.SSE),
                ):
                    # Tool-call events carry no text but do carry the author,
                    # so a handoff shows up here before any words arrive.
                    if event.author and event.author != author:
                        author = event.author
                        yield _sse({"type": "agent", "author": author})
                    text = _event_text(event)
                    if not text:
                        continue
                    if event.partial:
                        yield _sse(
                            {"type": "delta", "author": event.author, "text": text}
                        )
                    elif event.is_final_response() and text.strip():
                        yield _sse(
                            {"type": "reply", "author": event.author, "text": text}
                        )
            except Exception:
                # Too late for an HTTP status -- the 200 and part of the body
                # are already out -- so the error is itself an event. The
                # detail still goes only to the log.
                logger.exception("Agent run failed for session %s", session.id)
                yield _sse(
                    {"type": "error", "detail": "The agent hit an error. Try again."}
                )
                return
            yield _sse({"type": "done"})

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return api
