"""The coordinator must import cleanly and be the agent `adk web` will find.

These are cheap structural checks, not model calls. They catch the failure mode
where `adk web` starts but shows an empty agent list.
"""

from __future__ import annotations

import pytest
from google.adk.agents import BaseAgent

from head_hunter import agent as entry_point
from head_hunter import config
from head_hunter.agents.head_hunter.agent import root_agent
from head_hunter.prompts import load_prompt


def test_entry_point_exposes_the_coordinator() -> None:
    assert entry_point.root_agent is root_agent


def test_root_agent_is_an_adk_agent() -> None:
    assert isinstance(root_agent, BaseAgent)
    assert root_agent.name == "head_hunter"
    assert root_agent.model == config.model()


def test_instruction_comes_from_the_markdown_prompt() -> None:
    assert root_agent.instruction.startswith("You are the Head Hunter")
    assert "No invented experience" in root_agent.instruction


def test_coordinator_routes_to_the_four_specialists() -> None:
    assert [a.name for a in root_agent.sub_agents] == [
        "interviewer",
        "intake",
        "fit_analyst",
        "resume_tailor",
    ]


def test_only_the_interviewer_can_write_career_facts() -> None:
    """Rule 2: the profile has one author. Nothing else may invent facts."""
    writers = {"add_accomplishment", "add_skill", "add_role", "save_profile"}

    by_agent = {a.name: {t.__name__ for t in a.tools} for a in root_agent.sub_agents}
    by_agent[root_agent.name] = {t.__name__ for t in root_agent.tools}

    assert writers <= by_agent["interviewer"]
    for name in ("intake", "fit_analyst", "resume_tailor", "head_hunter"):
        assert not (writers & by_agent[name]), f"{name} can write career facts"


def test_every_agent_explains_tool_failures_instead_of_crashing() -> None:
    """Verified against ADK 2.9.1: without this the run dies with a traceback."""
    for agent in [root_agent, *root_agent.sub_agents]:
        assert agent.on_tool_error_callback is not None, agent.name


def test_the_fit_analyst_cannot_be_handed_a_score() -> None:
    """Rule 4: scoring is Python. The tool must not expose a score parameter."""
    import inspect

    from head_hunter.tools import save_fit_report

    assert "score" not in inspect.signature(save_fit_report).parameters


def test_the_resume_tailor_cannot_render_without_validating_first() -> None:
    """Rule 2: rendering is a separate call, so it can refuse an unchecked draft.

    If these ever became one tool, a failing draft could reach a .docx.
    """
    from head_hunter.tools import RESUME_TAILOR_TOOLS

    names = {tool.__name__ for tool in RESUME_TAILOR_TOOLS}
    assert names == {"load_tailoring_context", "save_resume", "render_resume"}


def test_missing_prompt_file_raises() -> None:
    with pytest.raises(FileNotFoundError, match="nope.md"):
        load_prompt(__file__, "nope.md")
