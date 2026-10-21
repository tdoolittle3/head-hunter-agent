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

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.events import Event, EventActions
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
from head_hunter.purge import purge_session_records
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
    job_id: str | None = Field(
        default=None,
        description=(
            "Tie a brand-new conversation to this saved posting, so the Jobs "
            "page can list it later. Only read when session_id is empty: a "
            "continued conversation keeps the job it started with."
        ),
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


class ConversationSummary(BaseModel):
    """One row of the pick-up-where-you-left-off list."""

    session_id: str
    updated_at: float = Field(description="Unix seconds of the last activity.")
    title: str = Field(description="The conversation's first user message, clipped.")
    job_id: str | None = Field(
        default=None, description="The saved posting this chat was started from."
    )
    job_label: str | None = Field(
        default=None, description="That posting's title and company, for display."
    )


class ConversationMessage(BaseModel):
    """One turn as it was shown: the user's words or an agent's finished answer."""

    author: str
    text: str


class Conversation(BaseModel):
    """A past conversation, replayable into the chat log."""

    session_id: str
    messages: list[ConversationMessage]


MAX_CONVERSATIONS_LISTED = 10
TITLE_CHARS = 80


def _conversation_messages(events: list[Any]) -> list[ConversationMessage]:
    """The turns a user actually saw: their messages and final agent answers."""
    messages = []
    for event in events:
        if not event.is_final_response():
            continue
        text = _event_text(event)
        if text.strip():
            messages.append(ConversationMessage(author=event.author, text=text))
    return messages


def _sessions_that_touched(repo: Repository, user_id: str, job_id: str) -> set[str]:
    """The chats stamped on the records that exist for one posting.

    Chats from before tools noted job ids in session state still left their
    session id on what they wrote -- the posting itself, its fit report, its
    resume, its journal events -- so the Jobs page can list them without any
    migration.
    """
    records = (
        repo.get_job(user_id, job_id),
        repo.get_fit_report(user_id, job_id),
        repo.get_resume(user_id, job_id),
    )
    touched = {r.session_id for r in records if r is not None and r.session_id}
    touched.update(
        entry.session_id
        for entry in repo.list_journal_entries(user_id)
        if entry.job_id == job_id and entry.session_id
    )
    return touched


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
    def page(request: Request) -> HTMLResponse:
        # The social-preview tags need absolute URLs, and the host is only
        # known at request time. Cloud Run terminates TLS before uvicorn sees
        # the request, so a non-local http scheme really means https.
        base = str(request.base_url).rstrip("/")
        local = re.match(r"http://(localhost|127\.)", base)
        if base.startswith("http://") and not local:
            base = "https://" + base.removeprefix("http://")
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(
            html.replace("__BASE__", base),
            headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
        )

    def serve_script(name: str) -> None:
        @api.get(f"/{name}", include_in_schema=False)
        def script() -> FileResponse:
            return FileResponse(
                WEB_DIR / name,
                media_type="text/javascript",
                headers={"Cache-Control": "no-store"},
            )

    for name in ("funnel.js", "markdown.js"):
        serve_script(name)

    def serve_asset(name: str, media_type: str) -> None:
        @api.get(f"/{name}", include_in_schema=False)
        def asset() -> FileResponse:
            return FileResponse(
                WEB_DIR / name,
                media_type=media_type,
                headers={"Cache-Control": "public, max-age=86400"},
            )

    for name, media_type in {
        "favicon.svg": "image/svg+xml",
        "apple-touch-icon.png": "image/png",
        "icon-192.png": "image/png",
        "icon-512.png": "image/png",
        "og.png": "image/png",
        "site.webmanifest": "application/manifest+json",
    }.items():
        serve_asset(name, media_type)

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

    @api.delete("/api/jobs/{job_id}")
    def delete_job(
        job_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> dict[str, str]:
        """Remove one posting, with its fit report and resume.

        Those two describe a posting that no longer exists, so they go with it
        (the same rule ``head_hunter.purge`` applies). Journal entries about
        the job stay: the record that you applied somewhere is not undone by
        removing the posting. Dependents are deleted before the job itself, so
        a failure part-way leaves the job in the list to retry.
        """
        try:
            repo = open_repository()
            if repo.get_job(user.uid, job_id) is None:
                raise HTTPException(status_code=404, detail="No such job.")
            repo.delete_resume(user.uid, job_id)
            repo.delete_fit_report(user.uid, job_id)
            repo.delete_job(user.uid, job_id)
        except StorageError:
            logger.exception("Could not delete job %s for %s", job_id, user.uid)
            raise HTTPException(
                status_code=500, detail="Could not remove that job. Try again."
            ) from None
        return {"status": "deleted"}

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

    async def open_session(
        uid: str, session_id: str | None, job_id: str | None = None
    ) -> Session:
        sessions = runner.session_service
        if session_id is None:
            state = None
            if job_id is not None:
                # A job tag must point at a posting the caller actually has,
                # or the Jobs page would list chats under a job that is not
                # there.
                try:
                    job = open_repository().get_job(uid, job_id)
                except StorageError:
                    logger.exception("Could not look up job %s for %s", job_id, uid)
                    raise HTTPException(
                        status_code=500, detail="Could not look up that job."
                    ) from None
                if job is None:
                    raise HTTPException(status_code=404, detail="No such job.")
                state = {"job_id": job_id}
            return await sessions.create_session(
                app_name=APP_NAME, user_id=uid, state=state
            )
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
        session = await open_session(user.uid, body.session_id, body.job_id)

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
        session = await open_session(user.uid, body.session_id, body.job_id)
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

    @api.get("/api/conversations", response_model=list[ConversationSummary])
    async def conversations(
        user: Annotated[VerifiedUser, Depends(current_user)],
        job_id: str | None = None,
        archived: bool = False,
    ) -> list[ConversationSummary]:
        """The caller's recent conversations, newest first, empty ones left out.

        Archived chats are hidden; with ``archived=true`` they are the only
        ones listed. With ``job_id``, only the chats about that posting — the
        one that saved it, ones started from it, and any that worked on it —
        one list, the way the Jobs page shows it.

        Listings come back without events, so each candidate is fetched in
        full for its title -- bounded by ``MAX_CONVERSATIONS_LISTED``.
        """
        sessions = runner.session_service
        listing = await sessions.list_sessions(app_name=APP_NAME, user_id=user.uid)
        newest_first = sorted(
            listing.sessions, key=lambda s: s.last_update_time or 0, reverse=True
        )
        touched: set[str] = set()
        try:
            repo = open_repository()
            labels = {
                job.id: " at ".join(p for p in (job.title, job.company) if p) or job.id
                for job in repo.list_jobs(user.uid)
            }
            if job_id is not None:
                touched = _sessions_that_touched(repo, user.uid, job_id)
        except StorageError:
            # Labels and record-stamped chats are conveniences; the state
            # matches below still work without them.
            logger.exception("Could not label conversations for %s", user.uid)
            labels = {}
        rows = []
        for session in newest_first:
            if len(rows) >= MAX_CONVERSATIONS_LISTED:
                break
            full = await sessions.get_session(
                app_name=APP_NAME, user_id=user.uid, session_id=session.id
            )
            if full is None:
                continue
            state = full.state or {}
            if bool(state.get("archived")) != archived:
                continue
            session_job = state.get("job_id")
            if job_id is not None and not (
                session_job == job_id
                or job_id in (state.get("job_ids") or [])
                or session.id in touched
            ):
                continue
            messages = _conversation_messages(full.events)
            opener = next((m.text for m in messages if m.author == "user"), None)
            if opener is None:
                continue
            rows.append(
                ConversationSummary(
                    session_id=session.id,
                    updated_at=session.last_update_time or 0,
                    title=" ".join(opener.split())[:TITLE_CHARS],
                    job_id=session_job,
                    job_label=labels.get(session_job),
                )
            )
        return rows

    async def owned_session(uid: str, session_id: str) -> Session:
        """The caller's own session, or the 404 that hides everyone else's."""
        session = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=uid, session_id=session_id
        )
        if session is None:
            raise HTTPException(status_code=404, detail="No such conversation.")
        return session

    async def set_archived(uid: str, session_id: str, archived: bool) -> None:
        """Flip a conversation's archived flag via a state-delta event.

        State is only ever changed through ``append_event``, the one write path
        both session backends persist, so the flag survives restarts the same
        way the conversation does.
        """
        session = await owned_session(uid, session_id)
        await runner.session_service.append_event(
            session,
            Event(
                author="system",
                actions=EventActions(state_delta={"archived": archived}),
            ),
        )

    @api.post("/api/conversations/{session_id}/archive")
    async def archive_conversation(
        session_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> dict[str, str]:
        """Hide one conversation from the lists. Nothing else changes."""
        await set_archived(user.uid, session_id, True)
        return {"status": "archived"}

    @api.post("/api/conversations/{session_id}/unarchive")
    async def unarchive_conversation(
        session_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> dict[str, str]:
        """Bring an archived conversation back into the lists."""
        await set_archived(user.uid, session_id, False)
        return {"status": "restored"}

    @api.delete("/api/conversations/{session_id}")
    async def delete_conversation(
        session_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> dict[str, Any]:
        """Delete one conversation permanently, with everything it added.

        Every record a chat creates — profile entries, jobs, fit reports,
        resumes, journal events — is stamped with the chat's session id, and
        this removes them all (see ``head_hunter.purge``). The purge runs
        before the session goes, so a failure leaves the chat in place to
        retry rather than orphaning the records.

        Looked up under the caller's own uid first, so deleting someone else's
        session id is indistinguishable from deleting one that never existed.
        """
        await owned_session(user.uid, session_id)
        try:
            removed = purge_session_records(open_repository(), user.uid, session_id)
        except StorageError:
            logger.exception("Could not purge session %s", session_id)
            raise HTTPException(
                status_code=500,
                detail="Could not remove what that chat added. Try again.",
            ) from None
        await runner.session_service.delete_session(
            app_name=APP_NAME, user_id=user.uid, session_id=session_id
        )
        return {"status": "deleted", "removed": removed}

    @api.get("/api/conversations/{session_id}", response_model=Conversation)
    async def conversation(
        session_id: str, user: Annotated[VerifiedUser, Depends(current_user)]
    ) -> Conversation:
        """One past conversation, as the turns the user saw."""
        session = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=user.uid, session_id=session_id
        )
        if session is None:
            raise HTTPException(status_code=404, detail="No such conversation.")
        return Conversation(
            session_id=session.id, messages=_conversation_messages(session.events)
        )

    return api
