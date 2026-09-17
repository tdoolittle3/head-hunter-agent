"""Cleaning a pasted posting must never eat a real requirement."""

from __future__ import annotations

from head_hunter.jd_text import clean_job_text, looks_like_job_posting

POSTING = """\
Skip to main content
Home
Apply Now

Senior Data Engineer
Globex, Remote (US)

We use cookies to improve your experience.

About the role
You will own our ingestion pipelines.

Requirements
- 5+ years building data pipelines
- Active Secret clearance
- Experience with Airflow preferred

Share this job
Facebook
LinkedIn
Posted 3 days ago
© 2026 Globex. All rights reserved.
"""


def test_real_content_survives() -> None:
    cleaned = clean_job_text(POSTING)

    assert "Senior Data Engineer" in cleaned
    assert "5+ years building data pipelines" in cleaned
    assert "Active Secret clearance" in cleaned
    assert "Experience with Airflow preferred" in cleaned
    assert "You will own our ingestion pipelines." in cleaned


def test_site_furniture_is_removed() -> None:
    cleaned = clean_job_text(POSTING).lower()

    for noise in [
        "skip to main content",
        "apply now",
        "we use cookies",
        "share this job",
        "facebook",
        "linkedin",
        "posted 3 days ago",
        "all rights reserved",
    ]:
        assert noise not in cleaned, f"should have stripped: {noise}"


def test_blank_runs_collapse_and_edges_are_trimmed() -> None:
    cleaned = clean_job_text("\n\n\nreal line\n\n\n\nanother line\n\n\n")

    assert cleaned == "real line\n\nanother line"


def test_whitespace_inside_lines_is_normalized() -> None:
    assert clean_job_text("5+   years\tof   Python") == "5+ years of Python"


def test_windows_and_mac_line_endings_are_handled() -> None:
    assert clean_job_text("a\r\nb\rc") == "a\nb\nc"


def test_decoration_only_lines_are_dropped() -> None:
    cleaned = clean_job_text("Requirements\n---\n*\n- 5 years Python")

    assert "5 years Python" in cleaned
    assert "---" not in cleaned


def test_a_posting_made_entirely_of_noise_comes_back_empty() -> None:
    """Better to return nothing and say so than to hand a model garbage."""
    assert clean_job_text("Apply Now\nShare\nFacebook\n© 2026") == ""


def test_too_short_to_be_a_posting_is_rejected() -> None:
    assert not looks_like_job_posting("Senior Data Engineer at Globex")
    assert not looks_like_job_posting("")
    assert not looks_like_job_posting("Apply Now\nFacebook")


def test_a_real_posting_is_accepted() -> None:
    assert looks_like_job_posting(POSTING * 3)


def test_bullet_prefixes_are_kept() -> None:
    """The dash matters -- it is how the model spots a requirements list."""
    cleaned = clean_job_text("Requirements\n- 5+ years of Python\n- AWS")

    assert "- 5+ years of Python" in cleaned
