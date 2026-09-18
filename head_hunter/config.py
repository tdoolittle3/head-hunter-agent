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


def storage_backend() -> str:
    """Return which store the tools read and write through: ``json`` or ``firestore``.

    Defaults to ``json`` so a laptop checkout keeps working with no Google Cloud
    project and no credentials. Deployments set ``HH_STORAGE=firestore``,
    because a Cloud Run filesystem does not survive a restart.
    """
    value = os.environ.get("HH_STORAGE", "json").strip().lower()
    if value not in ("json", "firestore"):
        raise ValueError(f"HH_STORAGE must be 'json' or 'firestore', not {value!r}.")
    return value


def firestore_database() -> str:
    """Return the Firestore database id to use.

    ``(default)`` is the database a project gets when it has only one, and is
    what ``gcloud firestore databases create`` makes unless told otherwise.
    """
    return os.environ.get("HH_FIRESTORE_DATABASE", "(default)")
