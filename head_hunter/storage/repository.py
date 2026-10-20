"""The storage interface every agent goes through.

Agents never touch a backend directly (AGENTS.md, "Stack"). Phase 1 uses the
JSON file backend; Phase 3 swaps in Firestore by implementing this same class.

Every method raises rather than returning a sentinel on failure, except the
``get_*`` lookups, which return ``None`` when a record simply does not exist yet
(AGENTS.md rule 6: no silent tool failures).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from head_hunter.schemas import (
    FitReport,
    JobPosting,
    JournalEntry,
    Profile,
    Resume,
    UploadedDocument,
)


class Repository(ABC):
    """Read and write the records the agents share."""

    @abstractmethod
    def get_profile(self, user_id: str) -> Profile | None:
        """Load a user's profile, or None if they have never been interviewed."""

    @abstractmethod
    def save_profile(self, profile: Profile) -> Profile:
        """Write a profile, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def list_jobs(self, user_id: str) -> list[JobPosting]:
        """Return every posting saved for a user, newest first."""

    @abstractmethod
    def get_job(self, user_id: str, job_id: str) -> JobPosting | None:
        """Load one posting, or None if there is no such job."""

    @abstractmethod
    def save_job(self, job: JobPosting, create_only: bool = False) -> JobPosting:
        """Write a posting, stamping ``updated_at``. Returns what was stored.

        With ``create_only``, a posting whose id is already taken must be
        refused rather than overwritten.
        """

    @abstractmethod
    def delete_job(self, user_id: str, job_id: str) -> None:
        """Remove one posting. Deleting a job that is not there is a no-op.

        All the delete methods are idempotent so the purge that runs when a
        chat is deleted entirely can be retried after a partial failure.
        """

    @abstractmethod
    def save_fit_report(self, report: FitReport) -> FitReport:
        """Write a fit report, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def get_fit_report(self, user_id: str, job_id: str) -> FitReport | None:
        """Load the fit report for one job, or None if it has not been run."""

    @abstractmethod
    def delete_fit_report(self, user_id: str, job_id: str) -> None:
        """Remove the fit report for one job, if there is one."""

    @abstractmethod
    def save_resume(self, resume: Resume) -> Resume:
        """Write a tailored resume, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def get_resume(self, user_id: str, job_id: str) -> Resume | None:
        """Load the resume written for one job, or None if there is not one yet."""

    @abstractmethod
    def delete_resume(self, user_id: str, job_id: str) -> None:
        """Remove the resume for one job, with its rendered files, if any."""

    @abstractmethod
    def save_upload(self, upload: UploadedDocument) -> UploadedDocument:
        """Write the text of an uploaded file. Refuses to overwrite an id."""

    @abstractmethod
    def get_upload(self, user_id: str, upload_id: str) -> UploadedDocument | None:
        """Load one upload, or None if this user has no such upload."""

    @abstractmethod
    def list_uploads(self, user_id: str) -> list[UploadedDocument]:
        """Return a user's uploads, newest first."""

    @abstractmethod
    def save_journal_entry(self, entry: JournalEntry) -> JournalEntry:
        """Write one journal entry. Refuses to overwrite an existing id."""

    @abstractmethod
    def list_journal_entries(self, user_id: str) -> list[JournalEntry]:
        """Return a user's journal entries, oldest first."""

    @abstractmethod
    def delete_journal_entry(self, user_id: str, entry_id: str) -> None:
        """Remove one journal entry, if it is there."""

    @abstractmethod
    def save_resume_document(
        self, user_id: str, job_id: str, suffix: str, content: bytes
    ) -> str:
        """Write a rendered resume file and say where it landed.

        The record in :meth:`save_resume` is the data; this is the artefact a
        person opens or emails. Kept separate because the two go to different
        places once this is not a laptop: Firestore for the record, object
        storage for the file.

        Args:
            user_id: Whose resume this is.
            job_id: The posting it targets.
            suffix: File extension without the dot, ``md`` or ``docx``.
            content: The rendered bytes.

        Returns:
            A human-readable location, e.g. a path or a URL.
        """
