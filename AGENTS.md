# AGENTS.md

Conventions for anyone, human or AI, writing code in this repo. Read `README.md` first for what the project is; this file is how we build it. Keep it short. If something can be learned by reading the code, it does not belong here.

## Stack

- **Python 3.12**, single package `head_hunter/`. No TypeScript, no second language.
- **Google ADK** (`google-adk`) for agents. Gemini via **Vertex AI** (`GOOGLE_GENAI_USE_VERTEXAI=TRUE`), never an AI Studio API key in this repo.
- **Pydantic v2** for every schema. Agents pass Pydantic models, not dicts.
- **Storage** through `head_hunter/storage/repository.py` (abstract). Phase 1 backend: JSON files under `data/`. Phase 3: Firestore. Agents never touch a backend directly.
- **python-docx** for DOCX output. Markdown is the canonical resume format; DOCX is rendered from it.
- **pytest** for tests, **ruff** for lint + format, **uv** or pip with `requirements.txt` (keep both in sync until we pick one).
- Runtime target: `adk web` locally / Cloud Shell now, **Cloud Run** later. Nothing may depend on a persistent local disk except the Phase 1 JSON store.

## Repo conventions

- One agent per folder: `head_hunter/agents/<name>/agent.py` exposes `root_agent`; the system prompt lives in `prompt.md` beside it and is loaded at import time. Prompts are prose, not f-strings full of logic.
- Tools are plain typed Python functions in `head_hunter/tools/`, with docstrings; ADK derives the tool schema from them. Return Pydantic models or simple JSON-able types.
- Every stored record carries `user_id`, `created_at`, `updated_at`. Single user in the POC (`user_id="local"`), but the field exists from day one because this becomes a multi-user product.
- Secrets only via environment variables; `.env.example` lists every one with a comment. `.env` and `data/` are gitignored.
- Small PRs to `main` via pull request. Commit messages: imperative, one line, why not what.
- Type hints everywhere. Docstrings on public functions. No commented-out code.
- No new dependency without a one-line justification in the PR.

## Agent design rules

These are product rules, not style preferences. Do not weaken them to make a test pass.

1. **Evidence-backed profile.** Every `Accomplishment` and `Skill` in the profile has an `evidence_id` and source text captured from the user. The Interviewer must not record inferences as facts; it may record a `hypothesis` field and ask about it later.
2. **Traceable resumes.** Every `ResumeBullet` references at least one `evidence_id`. `validate_resume()` is a deterministic Python function, not an LLM call, and fails the bullet if the reference is missing or the bullet introduces a number, tool, company, or title that does not appear in the cited evidence. The Resume Tailor loops until validation passes or reports what it could not support.
3. **Fit reports cite.** Each met requirement lists the evidence that meets it. Each unmet requirement is tagged `stretch` (learnable, adjacent) or `blocker` (credential, clearance, hard years-of-experience).
4. **Deterministic where possible.** Parsing, validation, scoring math, and storage are plain Python. LLMs do judgment and language, not bookkeeping.
5. **User-readable data.** JSON on disk must be readable by a non-programmer. Prefer flat, named fields over clever nesting.
6. **No silent tool failures.** Tools raise; agents tell the user what failed.

## Schemas (source of truth: `head_hunter/schemas/`)

Define these in Phase 0 even if some are unused until later:

- `Profile`: identity, `goals`, `constraints` (location, comp floor, remote), `roles[]`, `accomplishments[]`, `skills[]`, `education[]`, `open_questions[]`.
- `Accomplishment`: `id`, `role_id`, `situation`, `action`, `result`, `metrics[]`, `tools[]`, `evidence_id`, `source_text`.
- `Skill`: `name`, `level`, `years`, `evidence_ids[]`, `last_used`.
- `JobPosting`: `id`, `source` (paste/upload/email/search), `company`, `title`, `location`, `remote`, `comp`, `requirements[]` (each `text`, `kind`: required/preferred, `category`), `raw_text`.
- `FitReport`: `job_id`, `score` 0–100, `met[]` (requirement + evidence_ids), `unmet[]` (requirement + `stretch|blocker` + note), `summary`.
- `Resume`: `job_id`, `sections[]` of `ResumeBullet` (`text`, `evidence_ids[]`), `validation` result.
- `JournalEntry` (Phase 4): application/interview events and reflections.

## Testing

- Unit tests for every deterministic function, especially `validate_resume()` and fit scoring.
- ADK eval sets in `head_hunter/evals/`: at least one case where the profile lacks a requirement and the correct resume output omits it.
- `pytest` and `ruff check .` must pass before a PR is opened.

## Working with the non-programmer collaborator

They review agent behavior, prompts, and data files, not Python. So:

- Keep prompts in `prompt.md` files they can edit directly.
- Keep `data/*.json` human-readable.
- Every PR description says what changed in plain language and how to try it in `adk web`.
