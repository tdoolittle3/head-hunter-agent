"""The Head Hunter coordinator: the agent the user actually talks to.

It owns no career facts of its own. It reads enough of the profile to route
sensibly -- and to warn when a fit analysis is about to run against a profile
too thin to support one -- then hands off to a specialist.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.agents.fit_analyst.agent import root_agent as fit_analyst
from head_hunter.agents.intake.agent import root_agent as intake
from head_hunter.agents.interviewer.agent import root_agent as interviewer
from head_hunter.prompts import load_prompt
from head_hunter.tools import COORDINATOR_TOOLS, report_tool_error

root_agent = Agent(
    name="head_hunter",
    model=config.model(),
    description=(
        "Front door of the job-search system. Works out what the user needs "
        "and routes to the Interviewer, Intake, or Fit Analyst."
    ),
    instruction=load_prompt(__file__),
    tools=COORDINATOR_TOOLS,
    sub_agents=[interviewer, intake, fit_analyst],
    # Without this a raising tool takes the whole run down with a stack trace
    # instead of the agent explaining the failure (AGENTS.md rule 6).
    on_tool_error_callback=report_tool_error,
)
