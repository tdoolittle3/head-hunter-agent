"""The storage interface every agent goes through.

Agents never touch a backend directly (AGENTS.md, "Stack"). Phase 1 uses the
JSON file backend; Phase 3 swaps in Firestore by implementing this same class.

Every method raises rather than returning a sentinel on failure, except the
``get_*`` lookups, which return ``None`` when a record simply does not exist yet
(AGENTS.md rule 6: no silent tool failures).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from head_hunter.schemas import FitReport, JobPosting, Profile, Resume


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
    def save_job(self, job: JobPosting) -> JobPosting:
        """Write a posting, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def save_fit_report(self, report: FitReport) -> FitReport:
        """Write a fit report, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def get_fit_report(self, user_id: str, job_id: str) -> FitReport | None:
        """Load the fit report for one job, or None if it has not been run."""

    @abstractmethod
    def save_resume(self, resume: Resume) -> Resume:
        """Write a tailored resume, stamping ``updated_at``. Returns what was stored."""

    @abstractmethod
    def get_resume(self, user_id: str, job_id: str) -> Resume | None:
        """Load the resume written for one job, or None if there is not one yet."""

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
