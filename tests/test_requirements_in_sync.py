"""The two requirements files must not drift apart.

`adk deploy` copies only `head_hunter/` into the container and installs the
requirements.txt inside it, so that file is a second, easily-forgotten copy of
our pinned versions. AGENTS.md already warns about keeping dependency lists in
sync; this makes it a test failure instead of a production surprise.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT_REQUIREMENTS = REPO_ROOT / "requirements.txt"
CONTAINER_REQUIREMENTS = REPO_ROOT / "head_hunter" / "requirements.txt"

# Installed by the Dockerfile ADK generates, not by our requirements file.
PROVIDED_BY_IMAGE = {"google-adk"}

# Development tools, deliberately kept out of the production image.
DEV_ONLY = {"pytest", "ruff"}


def parse_pins(path: Path) -> dict[str, str]:
    """Return ``{package: version}`` for every ``name==version`` line."""
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[name.strip().lower()] = version.strip()
    return pins


def test_container_requirements_are_a_subset_of_the_root_list() -> None:
    root = parse_pins(ROOT_REQUIREMENTS)
    container = parse_pins(CONTAINER_REQUIREMENTS)

    assert container, "head_hunter/requirements.txt pins nothing"
    missing = set(container) - set(root)
    assert not missing, f"pinned for the container but not at the repo root: {missing}"


def test_pinned_versions_match_exactly() -> None:
    root = parse_pins(ROOT_REQUIREMENTS)
    container = parse_pins(CONTAINER_REQUIREMENTS)

    drifted = {
        name: (root[name], version)
        for name, version in container.items()
        if root[name] != version
    }
    assert not drifted, f"version drift (root, container): {drifted}"


def test_every_runtime_dependency_reaches_the_container() -> None:
    """Anything at the root that is not dev-only or image-provided must ship."""
    root = parse_pins(ROOT_REQUIREMENTS)
    container = parse_pins(CONTAINER_REQUIREMENTS)

    expected = set(root) - DEV_ONLY - PROVIDED_BY_IMAGE
    assert expected <= set(container), (
        "these would be missing from the deployed image: "
        f"{sorted(expected - set(container))}"
    )
