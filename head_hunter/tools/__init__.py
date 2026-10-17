"""Plain typed functions the agents call.

ADK derives each tool schema from the signature and docstring, so the
docstrings here are part of the prompt, not just documentation.
"""

from head_hunter.tools._base import ToolError, report_tool_error
from head_hunter.tools.fit_tools import (
    get_fit_report,
    load_job_and_profile,
    save_fit_report,
)
from head_hunter.tools.job_tools import list_jobs, prepare_job_text, save_job_posting
from head_hunter.tools.journal_tools import (
    get_application_funnel,
    list_applications,
    log_application_event,
)
from head_hunter.tools.profile_tools import (
    add_accomplishment,
    add_open_question,
    add_resume_accomplishment,
    add_role,
    add_skill,
    load_profile,
    save_profile,
)
from head_hunter.tools.resume_tools import (
    load_tailoring_context,
    render_resume,
    save_resume,
)
from head_hunter.tools.upload_tools import load_uploaded_resume

INTERVIEWER_TOOLS = [
    load_profile,
    load_uploaded_resume,
    save_profile,
    add_role,
    add_accomplishment,
    add_resume_accomplishment,
    add_skill,
    add_open_question,
]

INTAKE_TOOLS = [prepare_job_text, save_job_posting, list_jobs]

FIT_ANALYST_TOOLS = [load_job_and_profile, save_fit_report, get_fit_report]

RESUME_TAILOR_TOOLS = [load_tailoring_context, save_resume, render_resume]

COACH_TOOLS = [
    list_jobs,
    list_applications,
    log_application_event,
    get_application_funnel,
]

COORDINATOR_TOOLS = [load_profile, list_jobs]

__all__ = [
    "COACH_TOOLS",
    "COORDINATOR_TOOLS",
    "FIT_ANALYST_TOOLS",
    "INTAKE_TOOLS",
    "INTERVIEWER_TOOLS",
    "RESUME_TAILOR_TOOLS",
    "ToolError",
    "add_accomplishment",
    "add_open_question",
    "add_resume_accomplishment",
    "add_role",
    "add_skill",
    "get_application_funnel",
    "get_fit_report",
    "list_applications",
    "list_jobs",
    "load_job_and_profile",
    "load_profile",
    "load_tailoring_context",
    "load_uploaded_resume",
    "log_application_event",
    "prepare_job_text",
    "render_resume",
    "report_tool_error",
    "save_fit_report",
    "save_job_posting",
    "save_profile",
    "save_resume",
]
