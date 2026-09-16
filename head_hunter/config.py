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
"""The Gemini model every agent uses. One constant so swapping it is one edit."""


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
