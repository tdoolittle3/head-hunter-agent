"""The JSON store has to round-trip records and stay readable to a human."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from head_hunter.schemas import (
    FitReport,
    JobPosting,
    MetRequirement,
    Profile,
    Requirement,
)
from head_hunter.storage import JsonRepository, StorageError

USER = "local"


@pytest.fixture
def repo(tmp_path: Path) -> JsonRepository:
    return JsonRepository(root=tmp_path)


def make_job(job_id: str, user_id: str = USER) -> JobPosting:
    return JobPosting(
        user_id=user_id,
        id=job_id,
        source="paste",
        company="Globex",
        title="Senior Data Engineer",
        requirements=[
            Requirement(
                id="req-1", text="5+ years of Python", kind="required", category="skill"
            )
        ],
        raw_text="Globex is hiring...",
    )


def test_missing_records_return_none(repo: JsonRepository) -> None:
    assert repo.get_profile(USER) is None
    assert repo.get_job(USER, "job-nope") is None
    assert repo.get_fit_report(USER, "job-nope") is None
    assert repo.list_jobs(USER) == []


def test_profile_round_trips(repo: JsonRepository) -> None:
    profile = Profile(user_id=USER, goals=["Staff data platform role."])
    repo.save_profile(profile)

    loaded = repo.get_profile(USER)
    assert loaded is not None
    assert loaded.goals == ["Staff data platform role."]


def test_job_round_trips_and_lists(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a"))
    repo.save_job(make_job("job-b"))

    assert repo.get_job(USER, "job-a").company == "Globex"
    assert {j.id for j in repo.list_jobs(USER)} == {"job-a", "job-b"}


def test_fit_report_is_filed_under_its_job(repo: JsonRepository) -> None:
    job = repo.save_job(make_job("job-a"))
    report = FitReport(
        user_id=USER,
        job_id=job.id,
        score=72,
        met=[MetRequirement(requirement=job.requirements[0], evidence_ids=["ev-1"])],
        summary="Good fit on the Python work.",
    )
    repo.save_fit_report(report)

    assert (repo.root / "fit_reports" / "job-a.json").exists()
    assert repo.get_fit_report(USER, "job-a").score == 72


def test_saving_creates_directories(tmp_path: Path) -> None:
    repo = JsonRepository(root=tmp_path / "nested" / "data")
    repo.save_job(make_job("job-a"))
    assert (repo.root / "jobs" / "job-a.json").is_file()


def test_saving_stamps_updated_at(repo: JsonRepository) -> None:
    profile = Profile(user_id=USER)
    before = profile.updated_at
    repo.save_profile(profile)
    assert profile.updated_at >= before


def test_files_are_human_readable(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a"))
    text = (repo.root / "jobs" / "job-a.json").read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert "\n  " in text, "expected indentation"
    assert '"company": "Globex"' in text
    assert json.loads(text)["title"] == "Senior Data Engineer"


def test_other_users_records_are_not_returned(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a", user_id="someone-else"))

    assert repo.get_job(USER, "job-a") is None
    assert repo.list_jobs(USER) == []


def test_profile_for_the_wrong_user_raises(repo: JsonRepository) -> None:
    repo.save_profile(Profile(user_id="someone-else"))

    with pytest.raises(StorageError, match="HH_USER_ID"):
        repo.get_profile(USER)


def test_corrupt_file_raises_instead_of_returning_none(repo: JsonRepository) -> None:
    repo.profile_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(StorageError, match="not a valid Profile"):
        repo.get_profile(USER)


def test_ids_cannot_escape_the_data_directory(repo: JsonRepository) -> None:
    with pytest.raises(StorageError, match="Unsafe job_id"):
        repo.get_job(USER, "../../etc/passwd")


def test_no_temp_files_are_left_behind(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a"))
    assert list(repo.root.rglob("*.tmp")) == []
