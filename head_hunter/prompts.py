"""Loading system prompts from the ``prompt.md`` beside each agent.

Prompts are prose in Markdown files so the non-programmer collaborator can edit
agent behaviour without touching Python (AGENTS.md, "Working with the
non-programmer collaborator"). They are read once, at import time.
"""

from __future__ import annotations

from pathlib import Path


def load_prompt(agent_file: str, filename: str = "prompt.md") -> str:
    """Read the prompt file sitting next to an agent module.

    Args:
        agent_file: The agent module's ``__file__``.
        filename: Prompt file name, in case an agent ever needs more than one.

    Returns:
        The prompt text.

    Raises:
        FileNotFoundError: If the prompt is missing, naming the path we looked
            at. A silently empty instruction would be far worse than a crash.
    """
    path = Path(agent_file).resolve().parent / filename
    if not path.is_file():
        raise FileNotFoundError(f"Missing prompt file: {path}")
    return path.read_text(encoding="utf-8").strip()
