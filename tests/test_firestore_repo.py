"""The Firestore store has to behave exactly like the JSON one.

Two backends that disagree about whether a stale write is refused, or whether
another user's record is visible, would be a bug you only find in production.
So these mirror ``test_json_repo.py`` case for case, minus the ones about files
on disk.

They run against a fake client rather than a live database or the emulator: the
emulator needs a Java runtime, which would make ``pytest`` stop working on a
clean checkout. The fake implements only the handful of Firestore calls
:class:`FirestoreRepository` actually makes, so it cannot drift far from the
real thing without the repository changing too.
"""

from __future__ import annotations

import copy
import itertools
from typing import Any

import pytest

from head_hunter.schemas import (
    FitReport,
    JobPosting,
    MetRequirement,
    Profile,
    Requirement,
    base,
)
from head_hunter.storage import (
    FirestoreRepository,
    JsonRepository,
    StorageError,
    firestore_repo,
)
from head_hunter.tools import _base

USER = "local"


class AlreadyExists(Exception):
    """Stands in for google.api_core.exceptions.AlreadyExists."""


class FakeSnapshot:
    """What Firestore hands back from ``get()`` or ``stream()``."""

    def __init__(self, doc_id: str, data: dict[str, Any] | None) -> None:
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data)


class FakeDocument:
    """One document, addressed by path."""

    def __init__(self, store: dict[str, dict[str, Any]], path: str) -> None:
        self._store = store
        self.path = path
        self.id = path.rsplit("/", 1)[-1]

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self._store, f"{self.path}/{name}")

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self.id, self._store.get(self.path))

    def set(self, data: dict[str, Any]) -> None:
        self._store[self.path] = copy.deepcopy(data)

    def create(self, data: dict[str, Any]) -> None:
        if self.path in self._store:
            raise AlreadyExists(f"Document already exists: {self.path}")
        self._store[self.path] = copy.deepcopy(data)


class FakeCollection:
    """A collection, which in Firestore is just a path prefix."""

    def __init__(self, store: dict[str, dict[str, Any]], path: str) -> None:
        self._store = store
        self.path = path

    def document(self, doc_id: str) -> FakeDocument:
        return FakeDocument(self._store, f"{self.path}/{doc_id}")

    def stream(self) -> list[FakeSnapshot]:
        depth = self.path.count("/") + 1
        return [
            FakeSnapshot(path.rsplit("/", 1)[-1], data)
            for path, data in sorted(self._store.items())
            if path.startswith(f"{self.path}/") and path.count("/") == depth
        ]


class FakeClient:
    """Enough of a Firestore client for the repository to run against."""

    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self.store, name)


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def repo(client: FakeClient) -> FirestoreRepository:
    return FirestoreRepository(client=client)


@pytest.fixture
def ticking_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every ``touch()`` land on a distinct, increasing timestamp.

    The stale-write guard compares ``updated_at`` values, and Windows' clock
    granularity is around 15ms -- coarse enough that two saves in quick
    succession read back the *same* instant and the guard sees no change. The
    JSON suite only avoids this because real file I/O is slow enough to cross a
    tick, which is luck, not a test.
    """
    from datetime import UTC, datetime, timedelta

    start = datetime.now(UTC)
    counter = itertools.count()

    def advancing_now() -> datetime:
        return start + timedelta(seconds=next(counter))

    monkeypatch.setattr(base, "utc_now", advancing_now)


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


def test_missing_records_return_none(repo: FirestoreRepository) -> None:
    assert repo.get_profile(USER) is None
    assert repo.get_job(USER, "job-nope") is None
    assert repo.get_fit_report(USER, "job-nope") is None
    assert repo.get_resume(USER, "job-nope") is None
    assert repo.list_jobs(USER) == []


def test_profile_round_trips(repo: FirestoreRepository) -> None:
    repo.save_profile(Profile(user_id=USER, goals=["Staff data platform role."]))

    loaded = repo.get_profile(USER)
    assert loaded is not None
    assert loaded.goals == ["Staff data platform role."]


def test_job_round_trips_and_lists(repo: FirestoreRepository) -> None:
    repo.save_job(make_job("job-a"))
    repo.save_job(make_job("job-b"))

    stored = repo.get_job(USER, "job-a")
    assert stored is not None and stored.company == "Globex"
    assert {j.id for j in repo.list_jobs(USER)} == {"job-a", "job-b"}


def test_fit_report_is_filed_under_its_job(repo: FirestoreRepository) -> None:
    job = repo.save_job(make_job("job-a"))
    repo.save_fit_report(
        FitReport(
            user_id=USER,
            job_id=job.id,
            score=72,
            met=[
                MetRequirement(requirement=job.requirements[0], evidence_ids=["ev-1"])
            ],
            summary="Strong on Python.",
        )
    )

    report = repo.get_fit_report(USER, "job-a")
    assert report is not None and report.score == 72


def test_saving_stamps_updated_at(repo: FirestoreRepository) -> None:
    profile = Profile(user_id=USER)
    before = profile.updated_at
    repo.save_profile(profile)
    assert profile.updated_at >= before


def test_other_users_records_are_not_returned(repo: FirestoreRepository) -> None:
    repo.save_job(make_job("job-a", user_id="someone-else"))

    assert repo.get_job(USER, "job-a") is None
    assert repo.list_jobs(USER) == []


def test_profile_for_the_wrong_user_raises(repo: FirestoreRepository) -> None:
    stored = Profile(user_id="someone-else")
    # Write it where USER's profile would live, so the mismatch is detectable.
    client = repo._client  # noqa: SLF001 - the point of the test
    client.store["users/local/profile/current"] = stored.model_dump(mode="json")

    with pytest.raises(StorageError, match="HH_USER_ID"):
        repo.get_profile(USER)


def test_corrupt_document_raises_instead_of_returning_none(
    repo: FirestoreRepository, client: FakeClient
) -> None:
    client.store["users/local/profile/current"] = {"not": "a profile"}

    with pytest.raises(StorageError, match="not a valid Profile"):
        repo.get_profile(USER)


def test_ids_cannot_escape_their_collection(repo: FirestoreRepository) -> None:
    with pytest.raises(StorageError, match="Unsafe job_id"):
        repo.get_job(USER, "../../etc/passwd")


def test_a_new_job_cannot_overwrite_an_existing_one(repo: FirestoreRepository) -> None:
    repo.save_job(make_job("job-a"))

    with pytest.raises(StorageError, match="Refusing to overwrite"):
        repo.save_job(make_job("job-a"), create_only=True)

    # Without create_only it is still an ordinary update.
    repo.save_job(make_job("job-a"))


def test_a_stale_profile_write_is_refused(
    repo: FirestoreRepository, ticking_clock: None
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


def test_resume_documents_round_trip(repo: FirestoreRepository) -> None:
    where = repo.save_resume_document(USER, "job-a", "docx", b"PK\x03\x04 pretend")

    assert where.startswith("firestore://")
    assert repo.get_resume_document(USER, "job-a", "docx") == b"PK\x03\x04 pretend"
    assert repo.get_resume_document(USER, "job-a", "md") is None


def test_an_oversized_document_is_refused_with_an_explanation(
    repo: FirestoreRepository,
) -> None:
    with pytest.raises(StorageError, match="document limit"):
        repo.save_resume_document(USER, "job-a", "docx", b"x" * 1_000_001)


def test_records_are_stored_as_readable_fields(
    repo: FirestoreRepository, client: FakeClient
) -> None:
    """A person opening the Firestore console should see named values."""
    repo.save_job(make_job("job-a"))

    stored = client.store["users/local/jobs/job-a"]
    assert stored["company"] == "Globex"
    assert stored["title"] == "Senior Data Engineer"
    assert isinstance(stored["requirements"], list)


# Which backend the tools pick ---------------------------------------------
#
# The deployment's whole persistence story is one branch in `repository()`, so
# it gets tested rather than assumed.


def test_the_default_backend_is_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HH_STORAGE", raising=False)
    assert isinstance(_base.repository(), JsonRepository)


def test_hh_storage_firestore_selects_firestore(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HH_STORAGE", "firestore")
    # Building a real client would need credentials, so stand one in.
    monkeypatch.setattr(firestore_repo, "_default_client", FakeClient)

    assert isinstance(_base.repository(), FirestoreRepository)


def test_an_unknown_backend_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HH_STORAGE", "postgres")

    with pytest.raises(ValueError, match="HH_STORAGE"):
        _base.repository()
