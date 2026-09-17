"""Normalizes a pasted job description into a stored JobPosting.

Tools do the persisting; this module only wires the agent together.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.prompts import load_prompt
from head_hunter.tools import INTAKE_TOOLS, report_tool_error

root_agent = Agent(
    name="intake",
    model=config.model(),
    description=(
        "Turns a pasted job description into a structured, stored "
        "JobPosting with individually tagged requirements."
    ),
    instruction=load_prompt(__file__),
    tools=INTAKE_TOOLS,
    # Without this a raising tool takes the whole run down with a stack trace
    # instead of the agent explaining the failure (AGENTS.md rule 6).
    on_tool_error_callback=report_tool_error,
)
