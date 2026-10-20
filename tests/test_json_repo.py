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
    UploadedDocument,
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


def test_deletes_remove_the_record_and_tolerate_repeats(repo: JsonRepository) -> None:
    job = repo.save_job(make_job("job-a"))
    repo.save_fit_report(FitReport(user_id=USER, job_id=job.id, score=50, summary="s"))

    repo.delete_fit_report(USER, job.id)
    repo.delete_job(USER, job.id)
    repo.delete_job(USER, job.id)  # already gone: a no-op, not an error

    assert repo.get_job(USER, "job-a") is None
    assert repo.get_fit_report(USER, "job-a") is None


def test_deleting_a_resume_takes_its_rendered_files(repo: JsonRepository) -> None:
    from head_hunter.schemas import Resume

    repo.save_resume(Resume(user_id=USER, job_id="job-a"))
    repo.save_resume_document(USER, "job-a", "md", b"# resume")
    repo.save_resume_document(USER, "job-a", "docx", b"bytes")

    repo.delete_resume(USER, "job-a")

    assert repo.get_resume(USER, "job-a") is None
    assert not repo.resume_path("job-a", "md").exists()
    assert not repo.resume_path("job-a", "docx").exists()


def test_one_user_cannot_delete_anothers_records(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a", user_id="someone-else"))

    repo.delete_job(USER, "job-a")

    assert repo.get_job("someone-else", "job-a") is not None


def test_profile_for_the_wrong_user_raises(repo: JsonRepository) -> None:
    repo.save_profile(Profile(user_id="someone-else"))

    with pytest.raises(StorageError, match="HH_SINGLE_USER"):
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


def test_a_new_job_cannot_overwrite_an_existing_one(repo: JsonRepository) -> None:
    repo.save_job(make_job("job-a"))

    with pytest.raises(StorageError, match="Refusing to overwrite"):
        repo.save_job(make_job("job-a"), create_only=True)

    # Without create_only it is still an ordinary update.
    repo.save_job(make_job("job-a"))


@pytest.fixture
def ticking_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``touch()`` land on a distinct, increasing timestamp.

    The stale-write guard compares ``updated_at`` values, and Windows' clock
    granularity is coarse enough that two saves in quick succession can read
    back the *same* instant, in which case the guard sees no change. The
    Firestore suite has always pinned the clock for this; the JSON one relied
    on file I/O being slow enough to cross a tick, which stopped being true.
    """
    import itertools
    from datetime import UTC, datetime, timedelta

    from head_hunter.schemas import base

    start = datetime.now(UTC)
    counter = itertools.count()

    def advancing_now() -> datetime:
        return start + timedelta(seconds=next(counter))

    monkeypatch.setattr(base, "utc_now", advancing_now)


def test_a_stale_profile_write_is_refused(
    repo: JsonRepository, ticking_clock: None
) -> None:
    """Two sessions that both loaded the profile must not silently clobber."""
    repo.save_profile(Profile(user_id=USER, goals=["First."]))

    first = repo.get_profile(USER)
    second = repo.get_profile(USER)
    assert first is not None and second is not None

    first.goals = ["First session's answer."]
    repo.save_profile(first)

    second.goals = ["Second session's answer."]
    with pytest.raises(StorageError, match="changed since it was loaded"):
        repo.save_profile(second)

    stored = repo.get_profile(USER)
    assert stored is not None
    assert stored.goals == ["First session's answer."]


def test_temporary_files_do_not_collide_between_writers(repo: JsonRepository) -> None:
    path = repo.profile_path
    names = {repo._tmp_path(path).name for _ in range(50)}
    assert len(names) == 50
    assert all(name.endswith(".tmp") for name in names)


def test_no_temporary_files_are_left_behind(repo: JsonRepository) -> None:
    repo.save_profile(Profile(user_id=USER))
    repo.save_job(make_job("job-a"), create_only=True)
    repo.save_resume_document(USER, "job-a", "md", b"# Resume\n")

    assert list(repo.root.rglob("*.tmp")) == []


# Uploaded files -----------------------------------------------------------


def make_upload(upload_id: str, user_id: str = USER) -> UploadedDocument:
    return UploadedDocument(
        user_id=user_id,
        id=upload_id,
        filename="jane.pdf",
        text="Jane Doe, Staff Engineer at Acme Foods since 2019.",
        pages=1,
    )


def test_an_upload_round_trips_and_lists_newest_first(repo: JsonRepository) -> None:
    first = repo.save_upload(make_upload("up-1"))
    second = repo.save_upload(make_upload("up-2"))
    second.created_at = first.created_at.replace(year=first.created_at.year + 1)
    repo._write(repo.upload_path("up-2"), second)

    assert repo.get_upload(USER, "up-1").text == first.text
    assert [u.id for u in repo.list_uploads(USER)] == ["up-2", "up-1"]


def test_missing_uploads_return_none_or_empty(repo: JsonRepository) -> None:
    assert repo.get_upload(USER, "up-nope") is None
    assert repo.list_uploads(USER) == []


def test_other_users_uploads_are_not_returned(repo: JsonRepository) -> None:
    repo.save_upload(make_upload("up-a", user_id="someone-else"))

    assert repo.get_upload(USER, "up-a") is None
    assert repo.list_uploads(USER) == []


def test_an_upload_cannot_overwrite_another(repo: JsonRepository) -> None:
    repo.save_upload(make_upload("up-a"))

    with pytest.raises(StorageError, match="Refusing to overwrite"):
        repo.save_upload(make_upload("up-a"))


def test_an_upload_id_cannot_escape_the_data_directory(repo: JsonRepository) -> None:
    with pytest.raises(StorageError, match="Unsafe upload_id"):
        repo.get_upload(USER, "../../profile")


def test_uploads_are_stored_as_readable_json(
    repo: JsonRepository, tmp_path: Path
) -> None:
    repo.save_upload(make_upload("up-a"))

    data = json.loads((tmp_path / "uploads" / "up-a.json").read_text("utf-8"))
    assert data["filename"] == "jane.pdf"
    assert data["text"].startswith("Jane Doe")
