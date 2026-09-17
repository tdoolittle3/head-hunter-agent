"""Compares one posting against the profile and produces a cited FitReport.

Tools do the persisting; this module only wires the agent together.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.prompts import load_prompt
from head_hunter.tools import FIT_ANALYST_TOOLS, report_tool_error

root_agent = Agent(
    name="fit_analyst",
    model=config.model(),
    description=(
        "Scores a saved posting against the profile, citing evidence "
        "for what is met and tagging each gap as a stretch or a "
        "blocker."
    ),
    instruction=load_prompt(__file__),
    tools=FIT_ANALYST_TOOLS,
    # Without this a raising tool takes the whole run down with a stack trace
    # instead of the agent explaining the failure (AGENTS.md rule 6).
    on_tool_error_callback=report_tool_error,
)
