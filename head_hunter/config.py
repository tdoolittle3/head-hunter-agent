"""Runtime configuration, read from the environment.

Secrets and per-machine settings only ever arrive as environment variables
(AGENTS.md, "Repo conventions"). Values are read at call time rather than at
import time so a test can point ``HH_DATA_DIR`` somewhere temporary without
reloading the module.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "gemini-3.5-flash"
"""The Gemini model every agent uses, unless ``HH_MODEL`` overrides it.

Vertex only serves the models your project and region are entitled to, and that
varies between projects. If `adk web` reports a 404 for this model, set
``HH_MODEL`` in `.env` to one your project does have, rather than editing code.
"""


def model() -> str:
    """Return the Gemini model id the agents should use."""
    return os.environ.get("HH_MODEL", DEFAULT_MODEL)


def user_id() -> str:
    """Return the id the stored records belong to.

    Single user for now, but the value is threaded through every record because
    this becomes a multi-user product.
    """
    return os.environ.get("HH_USER_ID", "local")


def data_dir() -> Path:
    """Return the directory the JSON store writes to, creating it if needed."""
    path = Path(os.environ.get("HH_DATA_DIR", "./data")).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path
