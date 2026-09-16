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


def test_phase_0_has_no_tools_or_sub_agents() -> None:
    assert root_agent.tools == []
    assert root_agent.sub_agents == []


def test_missing_prompt_file_raises() -> None:
    with pytest.raises(FileNotFoundError, match="nope.md"):
        load_prompt(__file__, "nope.md")
