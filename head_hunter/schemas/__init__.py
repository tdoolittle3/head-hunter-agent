"""Pydantic models. This package is the source of truth for the data shapes."""

from head_hunter.schemas.base import HeadHunterModel, StoredRecord, utc_now
from head_hunter.schemas.evidence import Evidence, EvidenceSource
from head_hunter.schemas.fit import (
    FitReport,
    GapKind,
    MetRequirement,
    UnmetRequirement,
)
from head_hunter.schemas.ids import new_id
from head_hunter.schemas.job import (
    JobPosting,
    PostingSource,
    Requirement,
    RequirementCategory,
    RequirementKind,
)
from head_hunter.schemas.journal import JournalEntry, JournalEventKind
from head_hunter.schemas.profile import (
    Accomplishment,
    Constraints,
    Education,
    Identity,
    OpenQuestion,
    OpenQuestionStatus,
    Profile,
    Role,
    Skill,
    SkillLevel,
)
from head_hunter.schemas.resume import (
    Resume,
    ResumeBullet,
    ResumeSection,
    ValidationFailure,
    ValidationResult,
)

__all__ = [
    "Accomplishment",
    "Constraints",
    "Education",
    "Evidence",
    "EvidenceSource",
    "FitReport",
    "GapKind",
    "HeadHunterModel",
    "Identity",
    "JobPosting",
    "JournalEntry",
    "JournalEventKind",
    "MetRequirement",
    "OpenQuestion",
    "OpenQuestionStatus",
    "PostingSource",
    "Profile",
    "Requirement",
    "RequirementCategory",
    "RequirementKind",
    "Resume",
    "ResumeBullet",
    "ResumeSection",
    "Role",
    "Skill",
    "SkillLevel",
    "StoredRecord",
    "UnmetRequirement",
    "ValidationFailure",
    "ValidationResult",
    "new_id",
    "utc_now",
]
