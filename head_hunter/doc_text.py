"""Turning an uploaded file into text, deterministically.

Parsing is plain Python on purpose (AGENTS.md rule 4): the model never sees a
file, only the text this module extracts, and a file that cannot be read cleanly
is refused with a reason the user can act on rather than half-read.

The input is an untrusted file from the internet, so every limit here is a
defence: the type is decided by what the bytes are, not by what the name claims;
size, page count and expanded size are capped before the parsers do any real
work; and any failure inside a parser becomes an :class:`ExtractionError` rather
than a stack trace. Nothing is executed or fetched -- no macros, no embedded
links, no OCR.
"""

from __future__ import annotations

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

MAX_FILE_BYTES = 5 * 1024 * 1024
"""A resume is a few hundred kilobytes. Past this it is something else."""

MAX_PAGES = 20
MAX_TEXT_CHARS = 100_000
MAX_UNZIPPED_BYTES = 25 * 1024 * 1024
"""A .docx is a zip; this stops a tiny file that expands to gigabytes."""

MIN_TEXT_CHARS = 30

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".txt", ".md")


class ExtractionError(ValueError):
    """The file could not be turned into text. The message is safe to show."""


@dataclass(frozen=True)
class ExtractedText:
    """What a file said, and how many pages it had if it has pages."""

    text: str
    pages: int | None


def display_name(filename: str | None) -> str:
    """Return a safe name to show and store: no path, no control characters."""
    name = PureWindowsPath(PurePosixPath(filename or "").name).name
    name = "".join(c for c in name if c.isprintable())
    return name.strip()[:120] or "resume"


def extract_text(filename: str | None, data: bytes) -> ExtractedText:
    """Extract the text of a resume file.

    Args:
        filename: The name the user's file had. Only its extension is used, and
            only to pick a parser; the content must match it.
        data: The raw file bytes.

    Raises:
        ExtractionError: The file is too big, the wrong type, unreadable, or has
            no text in it.
    """
    if not data:
        raise ExtractionError("That file is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise ExtractionError(
            f"That file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB, which "
            "is too big for a resume."
        )

    extension = PurePosixPath(display_name(filename)).suffix.lower()
    if extension == ".doc":
        raise ExtractionError(
            "Old-style .doc files are not supported. Save it as .docx or PDF and "
            "upload that."
        )
    if extension not in SUPPORTED_EXTENSIONS:
        raise ExtractionError(
            "Upload a PDF, Word (.docx), or plain text (.txt, .md) file."
        )

    if extension == ".pdf":
        text, pages = _pdf_text(data)
    elif extension == ".docx":
        text, pages = _docx_text(data), None
    else:
        text, pages = _plain_text(data), None

    text = _tidy(text)
    if len(text) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "No readable text was found in that file."
            + (
                " If it is a scan or a photo of a page, it has no selectable text "
                "and cannot be read here. Export it from the original program as a "
                "PDF, or paste the text into the chat."
                if extension == ".pdf"
                else ""
            )
        )
    if len(text) > MAX_TEXT_CHARS:
        raise ExtractionError("That file has far more text than a resume should.")
    return ExtractedText(text=text, pages=pages)


def _tidy(text: str) -> str:
    """Drop control characters and runaway blank lines; keep the content as is."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _plain_text(data: bytes) -> str:
    if b"\x00" in data:
        raise ExtractionError("That does not look like a text file.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("That text file is in an encoding this cannot read.")


def _pdf_text(data: bytes) -> tuple[str, int]:
    if b"%PDF-" not in data[:1024]:
        raise ExtractionError("That file is not a PDF, despite its name.")
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError(
                "That PDF is password-protected. Remove the password and upload it "
                "again."
            )
        count = len(reader.pages)
        if count > MAX_PAGES:
            raise ExtractionError(
                f"That PDF has {count} pages; a resume should be {MAX_PAGES} or fewer."
            )
        pages = [page.extract_text() or "" for page in reader.pages]
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure is "unreadable"
        raise ExtractionError("That PDF could not be read. Is it damaged?") from exc
    return "\n\n".join(pages), count


def _docx_text(data: bytes) -> str:
    stream = io.BytesIO(data)
    if not zipfile.is_zipfile(stream):
        raise ExtractionError("That file is not a Word document, despite its name.")
    try:
        with zipfile.ZipFile(stream) as archive:
            if sum(info.file_size for info in archive.infolist()) > MAX_UNZIPPED_BYTES:
                raise ExtractionError("That document expands to an unreasonable size.")
            if "word/document.xml" not in archive.namelist():
                raise ExtractionError("That is a zip file, but not a Word document.")

        from docx import Document
        from docx.table import Table

        document = Document(io.BytesIO(data))
        lines: list[str] = []
        for section in document.sections:
            lines += [p.text for p in section.header.paragraphs if p.text.strip()]
            break  # contact details live in the first header; later ones repeat it
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                for row in block.rows:
                    cells: list[str] = []
                    for cell in row.cells:
                        if cell.text.strip() and cell.text not in cells:
                            cells.append(cell.text.strip())
                    lines.append(" | ".join(cells))
            else:
                lines.append(block.text)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure is "unreadable"
        raise ExtractionError("That Word document could not be read.") from exc
    return "\n".join(lines)


_MATCH_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
        "\u2026": "...",
        **{
            ord(c): " "
            for c in "\u2022\u25cf\u25aa\u25e6\u00b7\u2023\u2043\u25a0\u2219"
        },
    }
)


def normalize_for_match(text: str) -> str:
    """Flatten the differences that do not change what a sentence says.

    Case, runs of whitespace, curly versus straight quotes, dash styles, bullet
    glyphs and typographic ligatures all vary between how a resume is laid out
    and how a model repeats it. None of them can change the claim, so none of
    them should make a faithful quote fail. Words and numbers are untouched.
    """
    text = unicodedata.normalize("NFKC", text).translate(_MATCH_TRANSLATION)
    return " ".join(text.casefold().split())


def is_excerpt(quote: str, document_text: str) -> bool:
    """Say whether ``quote`` appears in ``document_text``, up to layout noise."""
    needle = normalize_for_match(quote)
    return bool(needle) and needle in normalize_for_match(document_text)
