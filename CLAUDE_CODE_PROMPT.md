# Claude Code kickoff prompt: Phase 0 + Phase 1

Paste everything below the line into Claude Code from the repo root. `README.md`, `AGENTS.md`, and `CLAUDE.md` should already be committed.

---

Read `README.md` and `AGENTS.md` fully before doing anything. They define the product, the logic flow, the stack, and rules that must not be weakened. Then implement Phase 0 and Phase 1 as described in the README's phase table.

## Working style

- Start by writing a short plan as `docs/PLAN.md`: the files you'll create, the order, and any decision the docs leave open. Ask me about open decisions before building on them; don't guess on anything in the "Agent design rules" section of AGENTS.md.
- Work in small commits with clear messages. Run `ruff check .` and `pytest` before each commit.
- When you finish a phase, stop and give me a plain-language summary plus exact `adk web` steps to try it, written so a non-programmer collaborator can follow them.
- Do not add dependencies beyond `google-adk`, `pydantic`, `python-docx`, `pytest`, `ruff`, and `python-dotenv` without asking.
- Verify ADK API details against the installed version (`pip show google-adk`, read the package source or `llms-full.txt` from google/adk-python) rather than assuming. ADK moves fast.

## Phase 0: scaffold

1. `pyproject.toml` with ruff config, `requirements.txt`, `.env.example` (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI=TRUE, HH_USER_ID=local, HH_DATA_DIR=./data), `.gitignore` covering `.env`, `data/`, `__pycache__`, `.venv`.
2. Package layout exactly as in the README's "Project layout" section.
3. All Pydantic schemas listed in AGENTS.md, with docstrings and a `tests/test_schemas.py` that round-trips each through JSON.
4. `storage/repository.py` abstract base with `get_profile / save_profile / list_jobs / get_job / save_job / save_fit_report / get_fit_report`, and `storage/json_repo.py` implementing it with one readable JSON file per record type under `HH_DATA_DIR`. Tests for the JSON repo.
5. A `head_hunter` root agent (the Head Hunter coordinator) that runs under `adk web`, greets the user, and explains what it can do. Confirm `adk web` starts cleanly.
6. A `Makefile` or `scripts/` with `dev` (adk web), `test`, `lint`.

Stop here, summarize, and wait for me to confirm both collaborators can run it in Cloud Shell.

## Phase 1: proof-of-concept loop

Goal: a person with an empty profile can be interviewed, have a rich profile saved, paste a job description, and receive a useful fit report. Everything lands as readable JSON in `data/`.

### Interviewer agent

- Sub-agent of Head Hunter. Prompt in `agents/interviewer/prompt.md`.
- Behaves like a sharp recruiter doing a deep intake: chronological walk through roles, then for each role digs for specific accomplishments in situation / action / result form, pushing for numbers, tools, team size, scope, and what the person would do differently. Asks one or two questions at a time, not a questionnaire.
- Tools: `load_profile`, `save_profile`, `add_accomplishment`, `add_skill`, `add_open_question`. Every saved accomplishment and skill must carry `evidence_id` and the user's own `source_text` (their words, lightly cleaned). Inferences go into `open_questions`, not into facts.
- Before ending a session it lists the gaps it noticed (roles without metrics, skills without evidence) and saves them as `open_questions` so the next session can resume.
- Persist across `adk web` sessions via the repository, keyed by `HH_USER_ID`.

### Intake agent

- Sub-agent. Accepts pasted JD text (file upload can wait). Deterministic pre-processing where possible (strip boilerplate, split into lines), then an LLM pass that produces a `JobPosting` with structured `requirements[]`, each tagged required/preferred and categorized (skill, experience, credential, location, other). Saves via repository and returns the `job_id`.

### Fit Analyst agent

- Sub-agent. Given a `job_id`, loads profile and posting and produces a `FitReport` following AGENTS.md rule 3: met requirements cite `evidence_ids`; unmet are `stretch` or `blocker` with a one-line reason. Score is computed by a deterministic Python function from the met/unmet lists (weight required over preferred, blockers heavily), not chosen by the model. Saves the report and presents a readable summary.

### Head Hunter coordinator

- Routes between the three sub-agents. If the profile is empty or thin, steers toward the Interviewer before allowing a fit analysis, and says why.

### Tests and evals

- Unit tests for fit scoring and for schema validation.
- One ADK eval set: a fixture profile and a fixture JD where the profile clearly lacks one required credential; the expected report marks it `blocker`.

### Done means

- `adk web` → interview yourself for ten minutes → `data/profile.json` is rich and readable → paste a JD → `data/jobs/*.json` and `data/fit_reports/*.json` exist and the chat shows a sensible report.
- `docs/PLAN.md` updated with what shipped and what's deferred to Phase 2.
- Plain-language summary and try-it steps for my collaborator.
