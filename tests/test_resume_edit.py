"""Editing a resume after it was written: by hand, and at the agent's hands."""

from __future__ import annotations

from pathlib import Path

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

from head_hunter import server
from head_hunter.resume_edit import ResumeEditError, apply_agent_edit
from head_hunter.resume_render import render_markdown
from head_hunter.schemas import (
    Evidence,
    Identity,
    JobPosting,
    Profile,
    Resume,
    ResumeBullet,
    ResumeSection,
)
from head_hunter.storage import JsonRepository
from head_hunter.tools import ToolError, edit_resume

USER = "alice-uid"
QUOTE = "I cut month-end close from nine days to two at Acme."


def make_profile(user_id: str = USER) -> Profile:
    return Profile(
        user_id=user_id,
        identity=Identity(
            full_name="Alice Smith",
            headline="US Native Citizen | B.S. Mechanical Engineering | Operations",
        ),
        evidence=[Evidence(id="ev1", source_text=QUOTE)],
    )


def make_resume(user_id: str = USER) -> Resume:
    return Resume(
        user_id=user_id,
        job_id="job-a",
        sections=[
            ResumeSection(
                title="Acme",
                bullets=[
                    ResumeBullet(
                        text="Cut month-end close from nine days to two.",
                        evidence_ids=["ev1"],
                    ),
                    ResumeBullet(
                        text="Cut month-end close again.", evidence_ids=["ev1"]
                    ),
                ],
            )
        ],
    )


def test_a_headline_edit_is_this_resumes_own_and_leaves_the_profile_alone() -> None:
    profile, resume = make_profile(), make_resume()

    apply_agent_edit(resume, profile, headline="US Citizen | Operations")

    assert "US Citizen | Operations" in render_markdown(resume, profile)
    assert "Native" not in render_markdown(resume, profile)
    assert profile.identity.headline.startswith("US Native Citizen")


def test_an_empty_headline_removes_it() -> None:
    profile, resume = make_profile(), make_resume()

    apply_agent_edit(resume, profile, headline="")

    assert "Operations" not in render_markdown(resume, profile)


def test_a_headline_cannot_gain_a_claim_the_profile_lacks() -> None:
    with pytest.raises(ResumeEditError, match="Kubernetes"):
        apply_agent_edit(
            make_resume(), make_profile(), headline="Operations | Kubernetes expert"
        )


def test_a_piece_of_a_bullet_can_be_swapped_and_the_result_is_rechecked() -> None:
    profile, resume = make_profile(), make_resume()

    apply_agent_edit(
        resume,
        profile,
        replacements=[{"find": "nine days to two", "replace": "9 days to 2"}],
    )
    assert resume.sections[0].bullets[0].text == "Cut month-end close from 9 days to 2."
    assert resume.validation.passed

    apply_agent_edit(
        resume,
        profile,
        replacements=[{"find": "9 days", "replace": "40 days"}],
    )
    assert not resume.validation.passed


def test_an_ambiguous_target_is_refused() -> None:
    with pytest.raises(ResumeEditError, match="2 bullets"):
        apply_agent_edit(make_resume(), make_profile(), remove_bullets=["Cut month"])


def test_bullets_and_sections_can_be_removed_but_not_all_of_them() -> None:
    resume = make_resume()
    apply_agent_edit(resume, make_profile(), remove_bullets=["again"])
    assert len(resume.sections[0].bullets) == 1

    with pytest.raises(ResumeEditError, match="no bullets"):
        apply_agent_edit(resume, make_profile(), remove_sections=["Acme"])
    with pytest.raises(ResumeEditError, match="No section"):
        apply_agent_edit(resume, make_profile(), remove_sections=["Nope"])


# The tool and the endpoints --------------------------------------------


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JsonRepository:
    monkeypatch.setenv("HH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("HH_SINGLE_USER", "local")
    return JsonRepository(tmp_path)


def test_the_tool_edits_the_stored_resume(store: JsonRepository) -> None:
    store.save_profile(make_profile("local"))
    store.save_resume(make_resume("local"))

    result = edit_resume("job-a", headline="US Citizen | Operations")

    assert result["status"] == "validated"
    assert store.get_resume("local", "job-a").headline == "US Citizen | Operations"


def test_the_tool_says_when_there_is_no_resume(store: JsonRepository) -> None:
    store.save_profile(make_profile("local"))
    with pytest.raises(ToolError, match="save_resume"):
        edit_resume("job-a", headline="x")


@pytest.fixture
def api(store: JsonRepository, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("HH_SINGLE_USER", raising=False)
    app = server.create_app(
        project_id=PROJECT,
        verifier=fake_verifier({"alice-token": claims()}),
        runner=FakeRunner(),
        web_config=WEB_CONFIG,
        repo_factory=lambda: store,
    )
    store.save_job(
        JobPosting(
            id="job-a",
            user_id=USER,
            source="paste",
            company="Acme",
            title="Engineer",
            raw_text="the posting",
        )
    )
    store.save_profile(make_profile())
    store.save_resume(make_resume())
    return TestClient(app)


def test_typed_edits_are_saved_as_the_users_own_word(
    api: TestClient, store: JsonRepository
) -> None:
    got = api.get("/api/jobs/job-a/resume", headers=bearer("alice-token"))
    assert got.status_code == 200
    body = got.json()
    assert body["headline"].startswith("US Native Citizen")

    body["headline"] = "US Citizen | Operations"
    body["sections"][0]["bullets"][0]["text"] = (
        "Shortened close to 2 days, in my words."
    )
    body["sections"][0]["bullets"].append(
        {"text": "Won a safety award.", "evidence_ids": []}
    )
    saved = api.put("/api/jobs/job-a/resume", json=body, headers=bearer("alice-token"))

    assert saved.status_code == 200, saved.text
    assert saved.json()["validation_passed"] is True
    resume = store.get_resume(USER, "job-a")
    assert resume.headline == "US Citizen | Operations"
    typed = {
        e.source_text
        for e in store.get_profile(USER).evidence
        if e.source == "user_edit"
    }
    assert typed == {"Shortened close to 2 days, in my words.", "Won a safety award."}

    markdown = api.get("/api/jobs/job-a/resume.md", headers=bearer("alice-token"))
    assert "US Citizen | Operations" in markdown.text
    assert "Won a safety award." in markdown.text


def test_an_empty_resume_cannot_be_saved(api: TestClient) -> None:
    saved = api.put(
        "/api/jobs/job-a/resume",
        json={"headline": "", "sections": []},
        headers=bearer("alice-token"),
    )
    assert saved.status_code == 422


def test_editing_a_resume_that_does_not_exist_is_a_404(api: TestClient) -> None:
    saved = api.put(
        "/api/jobs/job-zzz/resume",
        json={"headline": "", "sections": []},
        headers=bearer("alice-token"),
    )
    assert saved.status_code == 404
