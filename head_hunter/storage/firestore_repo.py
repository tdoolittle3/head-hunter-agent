"""Firestore backend for the repository.

Phase 3 storage, and the reason a deployed Head Hunter stops forgetting. Cloud
Run filesystems are per-instance and wiped on restart, so the JSON backend can
only ever be a laptop story.

The layout mirrors the JSON one, because AGENTS.md rule 5 asks that a
non-programmer can open the data and read it -- in the Firestore console here
rather than a text editor::

    users/<user_id>/profile/current
    users/<user_id>/jobs/<job_id>
    users/<user_id>/fit_reports/<job_id>
    users/<user_id>/resumes/<job_id>
    users/<user_id>/resume_documents/<job_id>.<suffix>

Records are stored as plain fields rather than one JSON blob, so the console
shows named values a person can scan.

Concurrency matches the JSON backend rather than improving on it, so the two
behave identically: new postings are created with Firestore's ``create()``,
which refuses a duplicate id atomically, and the profile is guarded by the same
optimistic ``updated_at`` check. That check is read-then-write, so two writers
landing in the same instant could still interleave. Firestore transactions
would close that window; it is deliberately left for when multi-user auth
arrives and concurrent writers become real, because today there is one user.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import ValidationError

from head_hunter import config
from head_hunter.schemas import FitReport, JobPosting, Profile, Resume
from head_hunter.storage.json_repo import StorageError
from head_hunter.storage.repository import Repository

_Record = TypeVar("_Record", Profile, JobPosting, FitReport, Resume)

_UNSAFE_ID_PARTS = ("/", "\\", "..", "\0")

_PROFILE_DOC = "current"

MAX_DOCUMENT_BYTES = 1_000_000
"""Firestore refuses documents over 1 MiB.

Rendered resumes are tens of kilobytes, so this is a guard rail rather than a
real constraint -- but it fails with an explanation instead of a Firestore
error nobody can act on.
"""


def _check_id(value: str, label: str) -> str:
    """Reject ids that would escape their collection or break a document path."""
    if not value or any(part in value for part in _UNSAFE_ID_PARTS):
        raise StorageError(f"Unsafe {label}: {value!r}")
    return value


class FirestoreRepository(Repository):
    """Repository backed by Firestore, for deployments that must remember."""

    def __init__(self, client: Any | None = None) -> None:
        """Create a repository.

        Args:
            client: A Firestore client. Defaults to one built from the ambient
                credentials, which is what Cloud Run provides. Injectable so the
                tests can run against a fake instead of a live database.
        """
        self._client = client if client is not None else _default_client()

    # Paths ---------------------------------------------------------------

    def _user_doc(self, user_id: str) -> Any:
        return self._client.collection("users").document(_check_id(user_id, "user_id"))

    def _doc(self, user_id: str, collection: str, doc_id: str) -> Any:
        return self._user_doc(user_id).collection(collection).document(doc_id)

    # Reading and writing -------------------------------------------------

    def _read(self, ref: Any, model: type[_Record]) -> _Record | None:
        """Load one document into ``model``, or None when it does not exist."""
        try:
            snapshot = ref.get()
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            raise StorageError(f"Could not read {ref.path}: {exc}") from exc
        if not snapshot.exists:
            return None
        try:
            return model.model_validate(snapshot.to_dict())
        except ValidationError as exc:
            raise StorageError(
                f"{ref.path} is not a valid {model.__name__}. "
                f"Fix or delete the document and try again. Details: {exc}"
            ) from exc

    def _write(self, ref: Any, record: _Record, create_only: bool = False) -> _Record:
        """Write one record, stamping ``updated_at`` first.

        Args:
            ref: The document to write.
            record: The record to store.
            create_only: Use Firestore's ``create``, which refuses an id that is
                already taken rather than overwriting it.
        """
        record.touch()
        payload = record.model_dump(mode="json")
        try:
            if create_only:
                ref.create(payload)
            else:
                ref.set(payload)
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            if _is_already_exists(exc):
                raise StorageError(
                    f"{ref.path} already exists. Refusing to overwrite an "
                    "existing record with a new one."
                ) from None
            raise StorageError(f"Could not write {ref.path}: {exc}") from exc
        return record

    # Repository interface ------------------------------------------------

    def get_profile(self, user_id: str) -> Profile | None:
        """Load the profile, or None if nobody has been interviewed yet."""
        ref = self._doc(user_id, "profile", _PROFILE_DOC)
        profile = self._read(ref, Profile)
        if profile is None:
            return None
        if profile.user_id != user_id:
            raise StorageError(
                f"{ref.path} belongs to user {profile.user_id!r}, "
                f"but {user_id!r} was requested. Check HH_USER_ID."
            )
        return profile

    def save_profile(self, profile: Profile) -> Profile:
        """Write the profile.

        Refuses the write if the stored profile changed since this one was
        loaded, for the same reason the JSON backend does: every Interviewer
        tool reads the whole profile, appends to it and writes it back, so a
        blind write would erase another session's accomplishment.
        """
        ref = self._doc(profile.user_id, "profile", _PROFILE_DOC)
        stored = self._read(ref, Profile)
        if stored is not None and stored.updated_at > profile.updated_at:
            raise StorageError(
                f"{ref.path} changed since it was loaded "
                f"(stored {stored.updated_at.isoformat()}, writing "
                f"{profile.updated_at.isoformat()}). Load the profile again and "
                "redo this change so the other update is not lost."
            )
        return self._write(ref, profile)

    def list_jobs(self, user_id: str) -> list[JobPosting]:
        """Return every posting belonging to ``user_id``, newest first."""
        collection = self._user_doc(user_id).collection("jobs")
        try:
            snapshots = list(collection.stream())
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            raise StorageError(f"Could not list jobs for {user_id}: {exc}") from exc
        jobs = []
        for snapshot in snapshots:
            try:
                job = JobPosting.model_validate(snapshot.to_dict())
            except ValidationError as exc:
                raise StorageError(
                    f"Job {snapshot.id} is not a valid JobPosting. Details: {exc}"
                ) from exc
            if job.user_id == user_id:
                jobs.append(job)
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def get_job(self, user_id: str, job_id: str) -> JobPosting | None:
        """Load one posting, or None if there is no such job for this user."""
        ref = self._doc(user_id, "jobs", _check_id(job_id, "job_id"))
        job = self._read(ref, JobPosting)
        if job is None or job.user_id != user_id:
            return None
        return job

    def save_job(self, job: JobPosting, create_only: bool = False) -> JobPosting:
        """Write a posting.

        Args:
            job: The posting to store.
            create_only: Refuse to overwrite an existing posting with this id.
        """
        ref = self._doc(job.user_id, "jobs", _check_id(job.id, "job_id"))
        return self._write(ref, job, create_only=create_only)

    def save_fit_report(self, report: FitReport) -> FitReport:
        """Write a report, filed under the job it scores."""
        ref = self._doc(
            report.user_id, "fit_reports", _check_id(report.job_id, "job_id")
        )
        return self._write(ref, report)

    def get_fit_report(self, user_id: str, job_id: str) -> FitReport | None:
        """Load the report for one job, or None if it has not been run."""
        ref = self._doc(user_id, "fit_reports", _check_id(job_id, "job_id"))
        report = self._read(ref, FitReport)
        if report is None or report.user_id != user_id:
            return None
        return report

    def save_resume(self, resume: Resume) -> Resume:
        """Write a resume record, filed under the job it targets."""
        ref = self._doc(resume.user_id, "resumes", _check_id(resume.job_id, "job_id"))
        return self._write(ref, resume)

    def get_resume(self, user_id: str, job_id: str) -> Resume | None:
        """Load the resume for one job, or None if none has been written."""
        ref = self._doc(user_id, "resumes", _check_id(job_id, "job_id"))
        resume = self._read(ref, Resume)
        if resume is None or resume.user_id != user_id:
            return None
        return resume

    def save_resume_document(
        self, user_id: str, job_id: str, suffix: str, content: bytes
    ) -> str:
        """Store a rendered resume beside its record and return where it landed.

        The file lives in Firestore rather than object storage. Rendered
        resumes are tens of kilobytes, so a second storage system would be one
        more thing to provision, secure and bill for, to hold something that
        fits comfortably in a document.
        """
        if len(content) > MAX_DOCUMENT_BYTES:
            raise StorageError(
                f"Rendered {suffix} for {job_id} is {len(content)} bytes, over "
                f"Firestore's {MAX_DOCUMENT_BYTES}-byte document limit. "
                "Store it in object storage instead."
            )
        doc_id = f"{_check_id(job_id, 'job_id')}.{_check_id(suffix, 'suffix')}"
        ref = self._doc(user_id, "resume_documents", doc_id)
        try:
            ref.set(
                {
                    "user_id": user_id,
                    "job_id": job_id,
                    "suffix": suffix,
                    "content": content,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            raise StorageError(f"Could not write {ref.path}: {exc}") from exc
        return f"firestore://{ref.path}"

    def get_resume_document(
        self, user_id: str, job_id: str, suffix: str
    ) -> bytes | None:
        """Load a rendered resume back out, or None if it was never written.

        Not part of :class:`Repository`. The JSON backend leaves a file a person
        can open; this one does not, so something has to be able to hand the
        bytes back.
        """
        doc_id = f"{_check_id(job_id, 'job_id')}.{_check_id(suffix, 'suffix')}"
        ref = self._doc(user_id, "resume_documents", doc_id)
        try:
            snapshot = ref.get()
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            raise StorageError(f"Could not read {ref.path}: {exc}") from exc
        if not snapshot.exists:
            return None
        content = snapshot.to_dict().get("content")
        if content is None:
            raise StorageError(f"{ref.path} has no content field.")
        return bytes(content)


def _is_already_exists(exc: Exception) -> bool:
    """Say whether Firestore refused a ``create`` because the id was taken."""
    return type(exc).__name__ == "AlreadyExists" or "already exists" in str(exc).lower()


def _default_client() -> Any:
    """Build a Firestore client from the ambient credentials.

    Imported here rather than at module scope so that a laptop running the JSON
    backend never needs ``google-cloud-firestore`` installed or a project
    configured.
    """
    try:
        from google.cloud import firestore
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise StorageError(
            "HH_STORAGE=firestore needs the google-cloud-firestore package. "
            "Install it with: pip install -r requirements.txt"
        ) from exc
    return firestore.Client(database=config.firestore_database())
