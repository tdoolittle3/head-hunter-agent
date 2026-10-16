"""A document the user handed us, kept as the text we extracted from it.

Only the extracted text is stored, never the original file: the text is what the
agents read, and the file would be a second copy of personal data to protect.
An upload is raw material for the Interviewer. It is *not* the profile -- a
claim only becomes part of the profile when it is recorded as evidence with a
verbatim excerpt (see ``add_accomplishment``'s ``upload_id``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from head_hunter.schemas.base import StoredRecord
from head_hunter.schemas.ids import new_id

UploadKind = Literal["resume"]


class UploadedDocument(StoredRecord):
    """The text of one uploaded file, filed under the user who uploaded it."""

    id: str = Field(default_factory=lambda: new_id("up"), description="Upload id.")
    kind: UploadKind = Field(default="resume", description="What the file is.")
    filename: str = Field(description="The name the user's file had, for display.")
    text: str = Field(description="The text extracted from the file.")
    pages: int | None = Field(
        default=None, description="Page count, when the format has pages."
    )
