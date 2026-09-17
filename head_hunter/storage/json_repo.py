"""JSON file backend for the repository.

Phase 1 storage. Writes one indented, UTF-8 JSON file per record under
``HH_DATA_DIR``, because AGENTS.md rule 5 says a non-programmer has to be able
to open these files and read them:

    data/
      profile.json
      jobs/<job_id>.json
      fit_reports/<job_id>.json
      resumes/<job_id>.json   the record
      resumes/<job_id>.md     the canonical rendering
      resumes/<job_id>.docx   the file you send

Writes go to a temporary file and are then moved into place, so a crash
mid-write cannot leave a half-written profile behind. The temporary name is
unique per write: two processes saving at once used to share one ``.tmp`` file
and could interleave their bytes into it.

Concurrency beyond that is handled two ways. New records are created with
``create_only``, so a duplicate id cannot silently overwrite an existing
posting. The profile -- the one record every tool does load, modify, save on --
is written with an optimistic version check: if it changed on disk since the
caller read it, the write is refused rather than clobbering the other update.
"""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import TypeVar

from pydantic import ValidationError

from head_hunter import config
from head_hunter.schemas import FitReport, JobPosting, Profile, Resume
from head_hunter.storage.repository import Repository

_Record = TypeVar("_Record", Profile, JobPosting, FitReport, Resume)

_UNSAFE_ID_PARTS = ("/", "\\", "..", "\0")


class StorageError(RuntimeError):
    """Something went wrong reading or writing the store.

    Raised rather than swallowed so the agent can tell the user what failed
    (AGENTS.md rule 6).
    """


def _check_id(value: str, label: str) -> str:
    """Reject ids that would let a record escape the data directory."""
    if not value or any(part in value for part in _UNSAFE_ID_PARTS):
        raise StorageError(f"Unsafe {label}: {value!r}")
    return value


class JsonRepository(Repository):
    """Repository backed by readable JSON files on local disk."""

    def __init__(self, root: Path | None = None) -> None:
        """Create a repository rooted at ``root``, defaulting to ``HH_DATA_DIR``."""
        self.root = Path(root) if root is not None else config.data_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def profile_path(self) -> Path:
        """Where the single profile file lives."""
        return self.root / "profile.json"

    def job_path(self, job_id: str) -> Path:
        """Where one posting lives."""
        return self.root / "jobs" / f"{_check_id(job_id, 'job_id')}.json"

    def fit_report_path(self, job_id: str) -> Path:
        """Where the fit report for one posting lives."""
        return self.root / "fit_reports" / f"{_check_id(job_id, 'job_id')}.json"

    def resume_path(self, job_id: str, suffix: str = "json") -> Path:
        """Where the resume record or a rendering of it lives."""
        return (
            self.root
            / "resumes"
            / f"{_check_id(job_id, 'job_id')}.{_check_id(suffix, 'suffix')}"
        )

    # Reading and writing -------------------------------------------------

    @staticmethod
    def _tmp_path(path: Path) -> Path:
        """A temporary name no other writer will pick, next to the target."""
        return path.with_name(f"{path.name}.{os.getpid()}-{secrets.token_hex(4)}.tmp")

    def _write(self, path: Path, record: _Record, create_only: bool = False) -> _Record:
        """Write one record, replacing the file at ``path`` atomically.

        Args:
            path: Where the record belongs.
            record: The record to write. Its ``updated_at`` is set here.
            create_only: Refuse to write if something is already there. Use this
                for new records, so an id collision surfaces as an error instead
                of overwriting somebody else's posting.
        """
        record.touch()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = record.model_dump_json(indent=2) + "\n"
        tmp = self._tmp_path(path)
        try:
            tmp.write_text(payload, encoding="utf-8")
            if create_only:
                # O_EXCL reserves the name atomically; the replace below fills
                # it. A crash in between leaves an empty file, which _read
                # rejects loudly rather than treating it as valid data.
                try:
                    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                except FileExistsError:
                    raise StorageError(
                        f"{path} already exists. Refusing to overwrite an "
                        "existing record with a new one."
                    ) from None
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f"Could not write {path}: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
        return record

    def _read(self, path: Path, model: type[_Record]) -> _Record | None:
        if not path.exists():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise StorageError(f"Could not read {path}: {exc}") from exc
        try:
            return model.model_validate_json(raw)
        except (ValidationError, json.JSONDecodeError) as exc:
            raise StorageError(
                f"{path} is not a valid {model.__name__}. "
                f"Fix or delete the file and try again. Details: {exc}"
            ) from exc

    # Repository interface ------------------------------------------------

    def get_profile(self, user_id: str) -> Profile | None:
        """Load the profile, or None if nobody has been interviewed yet."""
        profile = self._read(self.profile_path, Profile)
        if profile is None:
            return None
        if profile.user_id != user_id:
            raise StorageError(
                f"{self.profile_path} belongs to user {profile.user_id!r}, "
                f"but {user_id!r} was requested. Check HH_USER_ID."
            )
        return profile

    def save_profile(self, profile: Profile) -> Profile:
        """Write the profile to ``data/profile.json``.

        Refuses the write if the stored profile changed since this one was
        loaded. Every Interviewer tool reads the whole profile, appends to it,
        and writes it back, so without this check two overlapping sessions would
        each save their own copy and the later one would erase the earlier one's
        accomplishment.
        """
        stored = self._read(self.profile_path, Profile)
        if stored is not None and stored.updated_at > profile.updated_at:
            raise StorageError(
                f"{self.profile_path} changed since it was loaded "
                f"(stored {stored.updated_at.isoformat()}, writing "
                f"{profile.updated_at.isoformat()}). Load the profile again and "
                "redo this change so the other update is not lost."
            )
        return self._write(self.profile_path, profile)

    def list_jobs(self, user_id: str) -> list[JobPosting]:
        """Return every posting belonging to ``user_id``, newest first."""
        jobs_dir = self.root / "jobs"
        if not jobs_dir.is_dir():
            return []
        jobs = []
        for path in sorted(jobs_dir.glob("*.json")):
            job = self._read(path, JobPosting)
            if job is not None and job.user_id == user_id:
                jobs.append(job)
        return sorted(jobs, key=lambda j: j.created_at, reverse=True)

    def get_job(self, user_id: str, job_id: str) -> JobPosting | None:
        """Load one posting, or None if there is no such job for this user."""
        job = self._read(self.job_path(job_id), JobPosting)
        if job is None or job.user_id != user_id:
            return None
        return job

    def save_job(self, job: JobPosting, create_only: bool = False) -> JobPosting:
        """Write a posting to ``data/jobs/<job_id>.json``.

        Args:
            job: The posting to store.
            create_only: Refuse to overwrite an existing posting with this id.
        """
        return self._write(self.job_path(job.id), job, create_only=create_only)

    def save_fit_report(self, report: FitReport) -> FitReport:
        """Write a report to ``data/fit_reports/<job_id>.json``."""
        return self._write(self.fit_report_path(report.job_id), report)

    def get_fit_report(self, user_id: str, job_id: str) -> FitReport | None:
        """Load the report for one job, or None if it has not been run."""
        report = self._read(self.fit_report_path(job_id), FitReport)
        if report is None or report.user_id != user_id:
            return None
        return report

    def save_resume(self, resume: Resume) -> Resume:
        """Write a resume to ``data/resumes/<job_id>.json``."""
        return self._write(self.resume_path(resume.job_id), resume)

    def get_resume(self, user_id: str, job_id: str) -> Resume | None:
        """Load the resume for one job, or None if none has been written."""
        resume = self._read(self.resume_path(job_id), Resume)
        if resume is None or resume.user_id != user_id:
            return None
        return resume

    def save_resume_document(
        self, user_id: str, job_id: str, suffix: str, content: bytes
    ) -> str:
        """Write a rendering next to the record and return its path."""
        path = self.resume_path(job_id, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._tmp_path(path)
        try:
            tmp.write_bytes(content)
            os.replace(tmp, path)
        except OSError as exc:
            raise StorageError(f"Could not write {path}: {exc}") from exc
        finally:
            tmp.unlink(missing_ok=True)
        return str(path)
