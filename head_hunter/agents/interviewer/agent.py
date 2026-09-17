"""Deep-intake interviewer.

The only agent that writes career facts to the profile.

Tools do the persisting; this module only wires the agent together.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.prompts import load_prompt
from head_hunter.tools import INTERVIEWER_TOOLS, report_tool_error

root_agent = Agent(
    name="interviewer",
    model=config.model(),
    description=(
        "Builds the Career Profile by interviewing the user in depth. "
        "Records only what the user actually said, as evidence."
    ),
    instruction=load_prompt(__file__),
    tools=INTERVIEWER_TOOLS,
    # Without this a raising tool takes the whole run down with a stack trace
    # instead of the agent explaining the failure (AGENTS.md rule 6).
    on_tool_error_callback=report_tool_error,
)
