"""Fit checks that run on their own after a job is saved.

Nobody should sit waiting for a fit analysis: the moment a posting is saved,
:func:`start_fit_check` hands it to the Fit Analyst on a background thread and
returns at once. The report lands in the store when it is done, and the Jobs
page shows it from there.

The check is the same Fit Analyst the chat uses, with the same tools, so the
same rules hold: every met requirement cites profile evidence and the score is
computed in Python. A failure is logged and leaves the job unscored; the user
can still ask for the analysis in chat.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from google.genai import types

from head_hunter import config
from head_hunter.tools._base import repository

logger = logging.getLogger(__name__)

APP_NAME = "head_hunter_fit_check"

_running: set[tuple[str, str]] = set()
_lock = threading.Lock()


async def _run_fit_analyst(user_id: str, job_id: str, session_id: str | None) -> None:
    """Run the Fit Analyst once, in a throwaway in-memory session.

    The session reuses the originating chat's id when there is one, so the
    report is stamped with it and deleting that chat still removes the report.
    """
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService

    from head_hunter.agents.fit_analyst.agent import root_agent

    service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=service)
    session = await service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state={"job_ids": [job_id]},
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text=f"Run the fit analysis for job_id {job_id}.")],
    )
    async for _ in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=message
    ):
        pass


def _work(user_id: str, job_id: str, session_id: str | None) -> None:
    key = (user_id, job_id)
    try:
        repo = repository()
        if repo.get_profile(user_id) is None:
            logger.info("Skipping fit check for %s: no profile yet.", job_id)
            return
        if repo.get_fit_report(user_id, job_id) is not None:
            return
        asyncio.run(_run_fit_analyst(user_id, job_id, session_id))
    except Exception:
        logger.exception("Background fit check failed for job %s", job_id)
    finally:
        with _lock:
            _running.discard(key)


def start_fit_check(user_id: str, job_id: str, session_id: str | None = None) -> bool:
    """Start a fit check for a saved job without waiting for it.

    Returns True if one was started, False if switched off or already running
    for this job.
    """
    if not config.auto_fit_check():
        return False
    key = (user_id, job_id)
    with _lock:
        if key in _running:
            return False
        _running.add(key)
    threading.Thread(
        target=_work,
        args=(user_id, job_id, session_id),
        name=f"fit-check-{job_id}",
        daemon=True,
    ).start()
    return True
