"""Entry point for ``adk web`` and ``adk deploy``.

ADK discovers agents as subdirectories of the working directory and imports
``<name>.agent``, looking for ``app`` first and falling back to ``root_agent``.
The real coordinator lives at ``head_hunter/agents/head_hunter/`` under the
one-agent-per-folder convention in AGENTS.md, so this module re-exports it.

The ``App`` wrapper exists for ``context_cache_config``. Handing off between
agents swaps the system instruction and the tool set, so without a cache the
entire prompt is re-sent uncached after every transfer -- and this system
transfers constantly. ADK warns about exactly this at startup.

``root_agent`` is still exported: it is what the tests and any direct
``Runner`` use, and ADK falls back to it if an older CLI does not know about
``app``.
"""

from google.adk.agents.context_cache_config import ContextCacheConfig
from google.adk.apps import App

from head_hunter.agents.head_hunter.agent import root_agent

app = App(
    name="head_hunter",
    root_agent=root_agent,
    context_cache_config=ContextCacheConfig(
        # Only cache prefixes big enough to be worth it. Gemini rejects
        # explicit caches below its own floor, and our smaller agents sit
        # under it; a too-low value turns every small turn into an error.
        min_tokens=2048,
        ttl_seconds=1800,
    ),
)

__all__ = ["app", "root_agent"]
