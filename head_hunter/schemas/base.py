"""Shared base models.

Every record that gets its own file on disk carries ``user_id``, ``created_at``
and ``updated_at``. The POC is single-user, but the fields exist from day one
because this becomes a multi-user product (AGENTS.md, "Repo conventions").
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class HeadHunterModel(BaseModel):
    """Base for every schema in this package.

    Rejects unknown fields so a typo in a tool call fails loudly rather than
    silently dropping data (AGENTS.md rule 6: no silent failures).
    """

    model_config = ConfigDict(extra="forbid")


class StoredRecord(HeadHunterModel):
    """A record that is persisted on its own, as opposed to nested in another."""

    user_id: str = Field(description="Who this record belongs to.")
    created_at: datetime = Field(
        default_factory=utc_now, description="When the record was first written."
    )
    updated_at: datetime = Field(
        default_factory=utc_now, description="When the record last changed."
    )

    def touch(self) -> None:
        """Mark the record as changed just now."""
        self.updated_at = utc_now()
