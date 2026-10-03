"""The deploy files put a public, paid endpoint on the internet.

None of this runs the deploy. It pins the properties that must not quietly
change: secrets stay out of the image, the old single-user switch cannot ride
along into production, and the live service is smoke-tested for the login check.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read(name: str) -> str:
    return (REPO / name).read_text(encoding="utf-8")


def code(name: str) -> str:
    """The file without its comment lines, which are free to name what they ban."""
    lines = read(name).splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_the_image_takes_its_adk_pin_from_the_root_requirements() -> None:
    assert re.search(r"^google-adk==\S+", read("requirements.txt"), re.M)
    dockerfile = read("Dockerfile")
    assert "grep -E '^google-adk=='" in dockerfile
    assert not re.search(r"google-adk==\d", dockerfile), "do not pin it twice"


def test_the_image_runs_the_signed_in_server_not_the_dev_ui() -> None:
    dockerfile = code("Dockerfile")
    assert "head_hunter.server:create_app" in dockerfile
    assert "adk web" not in dockerfile
    assert "USER app" in dockerfile


def test_secrets_and_local_data_are_kept_out_of_the_upload_and_the_image() -> None:
    for name in (".dockerignore", ".gcloudignore"):
        lines = {line.strip() for line in read(name).splitlines()}
        assert ".env" in lines, f"{name} must exclude .env"
        assert {"data", "data/"} & lines, f"{name} must exclude data/"
    assert "COPY . " not in read("Dockerfile")


def test_a_deploy_cannot_carry_the_single_user_switch() -> None:
    makefile = code("Makefile")
    run_env = next(line for line in makefile.splitlines() if line.startswith("run_env"))
    assert "HH_SINGLE_USER" not in run_env
    assert "HH_USER_ID" not in run_env
    # Replacing, not merging, the environment is what drops a leftover value.
    assert "--set-env-vars" in makefile
    assert "--update-env-vars" not in makefile


def test_the_public_service_is_capped_and_uses_firestore() -> None:
    makefile = read("Makefile")
    assert "--allow-unauthenticated" in makefile
    assert "--max-instances=$(MAX_INSTANCES)" in makefile
    assert "HH_STORAGE=firestore" in makefile
    assert "--no-allow-unauthenticated" not in makefile


def test_the_workflow_proves_anonymous_chat_is_refused() -> None:
    workflow = read(".github/workflows/deploy.yml")
    assert "/api/chat" in workflow
    assert '"$code" != "401"' in workflow
