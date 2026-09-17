"""Writes an ATS-friendly resume for one posting, and cannot invent anything.

The guarantee is not in the prompt below it -- it is in `save_resume`, which
runs a deterministic traceability check over every bullet, and in
`render_resume`, which refuses to produce a file for a draft that did not pass.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.prompts import load_prompt
from head_hunter.tools import RESUME_TAILOR_TOOLS, report_tool_error

root_agent = Agent(
    name="resume_tailor",
    model=config.model(),
    description=(
        "Writes a tailored, ATS-friendly resume for one saved posting, with "
        "every bullet traced back to evidence in the profile."
    ),
    instruction=load_prompt(__file__),
    tools=RESUME_TAILOR_TOOLS,
    # Without this a raising tool takes the whole run down with a stack trace
    # instead of the agent explaining the failure (AGENTS.md rule 6).
    on_tool_error_callback=report_tool_error,
)
