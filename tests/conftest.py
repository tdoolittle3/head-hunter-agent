"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def no_background_fit_check(monkeypatch):
    """Saving a job must not start a real Gemini call from a test."""
    monkeypatch.setenv("HH_AUTO_FIT_CHECK", "0")
