"""Deterministic clean-up of pasted job-description text.

Pasted postings arrive wrapped in site furniture: nav links, "Apply now"
buttons, cookie notices, social share rows. Stripping those in Python rather
than asking a model to ignore them is cheaper, repeatable, and keeps the model's
attention on the actual requirements.

This is deliberately conservative. Dropping a real requirement would be far
worse than leaving a stray line in, so a line is only removed when it matches a
known-noise pattern outright. The untouched original is still stored as
``JobPosting.raw_text``, so nothing is ever lost.
"""

from __future__ import annotations

import re

_NOISE_PATTERNS = [
    r"^apply(\s+now|\s+for\s+this\s+job)?$",
    r"^(easy\s+)?apply$",
    r"^save(\s+job)?$",
    r"^share(\s+this\s+job)?$",
    r"^(back\s+to|view\s+all)\s+(jobs|search|results)",
    r"^(print|email)\s+this\s+job$",
    r"^show\s+more$",
    r"^see\s+more\s+jobs",
    r"^(sign\s+in|log\s+in|register|create\s+an?\s+account)$",
    r"^(home|jobs|careers|search|menu|skip\s+to\s+(main\s+)?content)$",
    r"^cookies?\b.*\b(policy|consent|settings|accept)",
    r"^we\s+use\s+cookies",
    r"^(accept|reject)\s+(all\s+)?cookies",
    r"^(facebook|twitter|linkedin|instagram|copy\s+link)$",
    r"^\d+\s+(days?|hours?|weeks?|months?)\s+ago$",
    r"^posted\s+\d+",
    r"^job\s+id[:\s]",
    r"^©|^copyright\b",
    r"^all\s+rights\s+reserved",
    r"^powered\s+by\b",
]

_NOISE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

# A bare bullet glyph or a run of punctuation carries no information.
_DECORATION_ONLY = re.compile(r"^[\s\W_]+$")


def _is_noise(line: str) -> bool:
    """Report whether a single stripped line is site furniture."""
    if not line:
        return False
    if _DECORATION_ONLY.match(line):
        return True
    return bool(_NOISE.match(line))


def clean_job_text(raw: str) -> str:
    """Strip obvious boilerplate from a pasted posting.

    Args:
        raw: The posting exactly as the user pasted it.

    Returns:
        The same text with noise lines removed, whitespace normalized, and
        runs of blank lines collapsed to one. Never returns None; if everything
        looked like noise, returns an empty string and the caller should say so
        rather than pretend it parsed.
    """
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    kept: list[str] = []
    for line in lines:
        stripped = " ".join(line.split())
        if _is_noise(stripped):
            continue
        if not stripped and kept and not kept[-1]:
            continue  # collapse repeated blank lines
        kept.append(stripped)

    while kept and not kept[0]:
        kept.pop(0)
    while kept and not kept[-1]:
        kept.pop()

    return "\n".join(kept)


def looks_like_job_posting(text: str) -> bool:
    """Cheap sanity check that the user pasted a posting and not a sentence.

    Used to fail fast with a clear message instead of sending two words to the
    model and getting a confidently empty JobPosting back.
    """
    cleaned = clean_job_text(text)
    return len(cleaned) >= 200 and len(cleaned.split()) >= 40
