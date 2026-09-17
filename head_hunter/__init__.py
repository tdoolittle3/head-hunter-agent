"""Head Hunter: an AI agent that learns your career and helps you land a job."""

__version__ = "0.1.0"

# ADK's convention, and load-bearing: `adk eval` imports this package's
# __init__ and looks for an `agent` attribute on it, unlike `adk web`, which
# imports `head_hunter.agent` directly. Without this line `adk eval` fails with
# "Agent module should have either `root_agent` or `get_agent_async`".
#
# It must be the relative form: `adk eval` loads this file under a synthetic
# module name, so `head_hunter` is not importable by name at that moment.
# Kept last so __version__ is set before the agent tree imports anything back.
from . import agent  # noqa: E402

__all__ = ["agent"]
