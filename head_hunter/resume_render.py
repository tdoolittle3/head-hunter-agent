"""Rendering a validated resume to Markdown and then to DOCX.

AGENTS.md: "Markdown is the canonical resume format; DOCX is rendered from it."
So there is exactly one path, and it runs in that order. :func:`render_markdown`
turns the stored record into text a person can read and edit; :func:`render_docx`
reads that same text back and lays it out in Word. Hand-edit the ``.md`` and
re-render and the change survives, which is the point of having a canonical
format at all.

The Markdown grammar is deliberately tiny -- headings, bullets, paragraphs, and
inline bold or italic -- because both ends of the round trip live in this file.
:func:`render_docx` fails loudly on anything it does not understand rather than
silently dropping a line off someone's resume.

The DOCX is plain on purpose. Applicant tracking systems parse a single column
of styled paragraphs reliably and tables, text boxes, headers, and footers
badly, so none of those appear here.
"""

from __future__ import annotations

import io
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from head_hunter.schemas import Profile, Resume

CONTACT_SEPARATOR = " · "

_BULLET_RE = re.compile(r"^[-*]\s+(.*)$")
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|\*[^*]+\*)")

BODY_FONT = "Calibri"
BODY_POINTS = 10.5


def _contact_line(profile: Profile) -> str:
    """Build the one-line contact row under the name."""
    identity = profile.identity
    parts = [identity.location, identity.email, identity.phone, *identity.links]
    return CONTACT_SEPARATOR.join(part for part in parts if part)


def render_markdown(resume: Resume, profile: Profile) -> str:
    """Render a resume as Markdown, the canonical format.

    The header comes from the profile's identity rather than from the resume,
    so a name or phone number can never be something the Resume Tailor made up.

    Args:
        resume: The resume to render. Its validation state is not consulted --
            callers decide whether an unvalidated draft may be rendered.
        profile: The profile the resume was written from.

    Returns:
        Markdown text ending in a single newline.
    """
    lines: list[str] = [f"# {profile.identity.full_name or 'Resume'}", ""]

    contact = _contact_line(profile)
    if contact:
        lines += [contact, ""]
    if profile.identity.headline:
        lines += [profile.identity.headline, ""]

    for section in resume.sections:
        lines.append(f"## {section.title}")
        if section.subtitle:
            lines += ["", f"*{section.subtitle}*"]
        lines.append("")
        for bullet in section.bullets:
            lines.append(f"- {bullet.text}")
        lines.append("")

    while lines and not lines[-1]:
        lines.pop()

    return "\n".join(lines) + "\n"


class MarkdownRenderError(ValueError):
    """The Markdown handed to :func:`render_docx` used something unsupported.

    Raised rather than skipped: a line quietly missing from a resume is worse
    than a rendering that refuses to run (AGENTS.md rule 6).
    """


def _write_runs(paragraph, text: str) -> None:
    """Add ``text`` to a paragraph, honouring inline ``**bold**`` and ``*italic*``."""
    for piece in _INLINE_RE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**"):
            paragraph.add_run(piece[2:-2]).bold = True
        elif piece.startswith("*") and piece.endswith("*"):
            paragraph.add_run(piece[1:-1]).italic = True
        else:
            paragraph.add_run(piece)


def render_docx(markdown: str) -> bytes:
    """Render canonical Markdown to an ATS-friendly DOCX.

    Args:
        markdown: Output of :func:`render_markdown`, possibly hand-edited.

    Returns:
        The ``.docx`` file as bytes, ready to write to storage.

    Raises:
        MarkdownRenderError: If the text contains Markdown this renderer does
            not support, such as a table or a fenced code block.
    """
    document = Document()

    normal = document.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_POINTS)

    # Contact details sit above the first section heading and are centred with
    # the name. Everything after it is body text, left aligned.
    in_header = True

    for number, raw in enumerate(markdown.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue

        if line.startswith("|") or line.startswith("```"):
            raise MarkdownRenderError(
                f"Line {number} uses Markdown this renderer does not support "
                f"({line[:40]!r}). Resumes here are headings, bullets, and "
                "paragraphs only -- tables and code blocks do not survive an "
                "applicant tracking system."
            )

        heading = _HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if level == 1:
                paragraph = document.add_paragraph()
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = paragraph.add_run(heading.group(2))
                run.bold = True
                run.font.size = Pt(18)
            else:
                in_header = False
                paragraph = document.add_heading(level=min(level, 3))
                paragraph.text = ""
                _write_runs(paragraph, heading.group(2))
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            paragraph = document.add_paragraph(style="List Bullet")
            _write_runs(paragraph, bullet.group(1))
            continue

        paragraph = document.add_paragraph()
        if in_header:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _write_runs(paragraph, line)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
