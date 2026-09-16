"""Entry point for ``adk web`` run from the repo root.

ADK discovers agents as subdirectories of the working directory and imports
``<name>.agent`` looking for ``root_agent``. The real coordinator lives at
``head_hunter/agents/head_hunter/`` under the one-agent-per-folder convention in
AGENTS.md, so this module just re-exports it.
"""

from head_hunter.agents.head_hunter.agent import root_agent

__all__ = ["root_agent"]
