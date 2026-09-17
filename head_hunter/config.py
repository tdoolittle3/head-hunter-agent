"""Runtime configuration, read from the environment.

Secrets and per-machine settings only ever arrive as environment variables
(AGENTS.md, "Repo conventions"). Values are read at call time rather than at
import time so a test can point ``HH_DATA_DIR`` somewhere temporary without
reloading the module.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MODEL = "gemini-2.5-flash"
"""The Gemini model every agent uses, unless ``HH_MODEL`` overrides it.

Not ADK's own default (`gemini-3.5-flash`), deliberately. That model returned
404 NOT_FOUND on Vertex in both Google Cloud projects this was tried in,
including `head-hunter-agent` in us-central1. `gemini-2.5-flash` is served in
both, and is what Phase 1 was actually built and verified against.

Vertex only serves the models a given project and region are entitled to, so if
`adk web` reports a 404 for this one, set ``HH_MODEL`` in `.env` to a model your
project does have rather than editing code. To find out which those are:

    gcloud auth print-access-token  # then POST to the :generateContent endpoint
    # or just try one and read the error -- it names the model and region.
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
