"""The automatic fit check starts without blocking and does not double up."""

import threading

from head_hunter import background


def _enable(monkeypatch):
    monkeypatch.setenv("HH_AUTO_FIT_CHECK", "1")


def test_disabled_starts_nothing(monkeypatch):
    monkeypatch.setenv("HH_AUTO_FIT_CHECK", "0")
    assert background.start_fit_check("local", "job-1") is False


def test_runs_off_the_calling_thread_and_clears_when_done(monkeypatch):
    _enable(monkeypatch)
    release = threading.Event()
    finished = threading.Event()
    seen = {}

    def fake_work(user_id, job_id, session_id):
        seen["thread"] = threading.current_thread()
        release.wait(5)
        with background._lock:
            background._running.discard((user_id, job_id))
        finished.set()

    monkeypatch.setattr(background, "_work", fake_work)
    assert background.start_fit_check("local", "job-1", "chat-1") is True
    # Still running, so a second request for the same job is refused.
    assert background.start_fit_check("local", "job-1") is False
    release.set()
    assert finished.wait(5)
    assert seen["thread"] is not threading.main_thread()


def test_failure_is_swallowed_and_cleared(monkeypatch):
    _enable(monkeypatch)

    class Repo:
        def get_profile(self, user_id):
            raise RuntimeError("store down")

    monkeypatch.setattr(background, "repository", lambda: Repo())
    background._running.add(("local", "job-2"))
    background._work("local", "job-2", None)
    assert ("local", "job-2") not in background._running


def test_skipped_without_a_profile(monkeypatch):
    class Repo:
        def get_profile(self, user_id):
            return None

    called = []
    monkeypatch.setattr(background, "repository", lambda: Repo())
    monkeypatch.setattr(background, "_run_fit_analyst", lambda *a: called.append(a))
    background._work("local", "job-3", None)
    assert called == []
