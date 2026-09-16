"""The Head Hunter coordinator: the agent the user actually talks to.

Phase 0 is a greeter with no tools and no sub-agents. Phase 1 gives it the
Interviewer, Intake, and Fit Analyst to route between.
"""

from __future__ import annotations

from google.adk.agents import Agent

from head_hunter import config
from head_hunter.prompts import load_prompt

root_agent = Agent(
    name="head_hunter",
    model=config.model(),
    description=(
        "Front door of the job-search system. Explains what it can do and, "
        "from Phase 1, routes to the right specialist."
    ),
    instruction=load_prompt(__file__),
)
