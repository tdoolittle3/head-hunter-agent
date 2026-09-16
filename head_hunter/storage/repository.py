"""The storage interface every agent goes through.

Agents never touch a backend directly (AGENTS.md, "Stack"). Phase 1 uses the
JSON file backend; Phase 3 swaps in Firestore by implementing this same class.

Every method raises rather than returning a sentinel on failure, except the
``get_*`` lookups, which return ``None`` when a record simply does not exist yet
(AGENTS.md rule 6: no silent tool failures).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from head_hunter.schemas import FitReport, JobPosting, Profile


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
