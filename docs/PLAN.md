# Phase 0 plan

Scope of this document: **Phase 0 only** (scaffold). Phase 1 is out of scope
until Phase 0 is reviewed and confirmed.

## What is already true

Verified in this worktree before planning:

| Thing | Status |
|---|---|
| `.gitignore` | Already exists (commit `ef80894`) and already covers `.env`, `data/`, `__pycache__`, `.venv/`. Nothing is unprotected. |
| Git remote | `https://github.com/tdoolittle3/head-hunter-agent.git` |
| Branch | `claude/phase-0-planning-setup-ff5a76`, off `main`, clean |
| Python | 3.12.10 |

## ADK facts verified against the installed package

`google-adk` was not installed anywhere on this machine. A local `.venv/`
(gitignored) was created and the real package read. Everything below is read
from source, not assumed.

| Fact | Verified value | Where |
|---|---|---|
| ADK version | **2.9.1** | `pip show google-adk` |
| `google-genai` version | 2.24.0 | `pip list` |
| Agent class | `google.adk.agents.Agent` (alias of `LlmAgent`) | `agents/__init__.py` |
| Agent fields used | `name`, `model`, `description`, `instruction`, `tools`, `sub_agents` | `agents/llm_agent.py`, `agents/base_agent.py` |
| Tools accept plain callables | Yes — `ToolUnion = Union[Callable, BaseTool, BaseToolset]` | `agents/llm_agent.py:131` |
| ADK's own default model | `gemini-3.5-flash` | `agents/llm_agent.py:274` |
| Vertex env vars | `GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` — all three read as written in the kickoff prompt | `google/genai/_api_client.py:657,714,715` |
| `.env` discovery | ADK walks **up** from the agent folder to the filesystem root looking for `.env`, so a repo-root `.env` is found | `cli/utils/envs.py` |
| `adk web` agents dir | Defaults to the current working directory | `cli/cli_tools_click.py:2136` |
| Agent discovery | Each **subdirectory** of the agents dir is one agent; it must contain `agent.py` (or `__init__.py`) exposing `root_agent` | `cli/utils/agent_loader.py` |

### The one thing that does not line up

`adk web` run from the repo root treats `head_hunter/` as the agent and imports
`head_hunter.agent` looking for `root_agent`. But `AGENTS.md` says every agent
lives at `head_hunter/agents/<name>/agent.py`.

Both can be true at once: `head_hunter/agent.py` becomes a three-line file that
re-exports the coordinator from `head_hunter/agents/head_hunter/agent.py`. The
README's `adk web` instruction stays literally correct and the AGENTS.md
convention is not bent. This is **Decision D1** below.

## Files Phase 0 creates, in commit order

Each numbered group is one commit. `ruff check .` and `pytest` pass before each.

**1. Project config**

- `pyproject.toml` — project metadata, ruff config (lint + format), pytest config
- `requirements.txt` — pinned to the versions actually installed and tested
- `.env.example` — `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `HH_USER_ID=local`, `HH_DATA_DIR=./data`,
  one comment per line
- `.gitignore` — already correct; add `.adk/` only

**2. Schemas** — `head_hunter/schemas/`

- `base.py` — `StoredRecord` mixin: `user_id`, `created_at`, `updated_at`
- `evidence.py` — `Evidence` (see **Q1**)
- `profile.py` — `Role`, `Accomplishment`, `Skill`, `Education`,
  `OpenQuestion`, `Profile`
- `job.py` — `Requirement`, `JobPosting`
- `fit.py` — `MetRequirement`, `UnmetRequirement`, `FitReport`
- `resume.py` — `ResumeBullet`, `ResumeSection`, `ValidationResult`, `Resume`
- `journal.py` — `JournalEntry` (Phase 4, defined now, unused)
- `tests/test_schemas.py` — every model round-trips through
  `model_dump_json()` then `model_validate_json()` and compares equal

**3. Storage** — `head_hunter/storage/`

- `repository.py` — abstract base, exactly the seven methods the kickoff prompt
  names: `get_profile`, `save_profile`, `list_jobs`, `get_job`, `save_job`,
  `save_fit_report`, `get_fit_report`
- `json_repo.py` — JSON backend under `HH_DATA_DIR` (see **D3** for file layout)
- `head_hunter/config.py` — reads `HH_USER_ID` / `HH_DATA_DIR` at call time
- `tests/test_json_repo.py` — save/load round trip, missing-record behaviour,
  directory auto-creation, and a check that the written file is indented and
  human-readable

**4. Coordinator agent**

- `head_hunter/agents/head_hunter/prompt.md` — greeting/routing prompt, prose
- `head_hunter/agents/head_hunter/agent.py` — builds `root_agent`, loads
  `prompt.md` at import time
- `head_hunter/agent.py` — re-export shim so `adk web` from the repo root
  works (**D1**)
- `head_hunter/__init__.py`, and `__init__.py` for each subpackage
- Empty-but-real `head_hunter/tools/` and `head_hunter/evals/` packages with a
  one-line README each, so Phase 1 has somewhere to land

**5. Scripts + docs**

- Task runner for `dev` / `test` / `lint` (see **Q5**)
- `README.md` — replace `<owner>` with `tdoolittle3`
- `docs/PLAN.md` — this file, updated with what actually shipped

## Decisions I have made — say so if you disagree

**D1 — `adk web` entry point.** `head_hunter/agent.py` re-exports the
coordinator's `root_agent`. Keeps `adk web` from the repo root working exactly
as the README promises, without weakening the one-agent-per-folder convention.
Side benefit: `adk web head_hunter/agents` later gives a dropdown of every
individual agent, which is handy for testing the Interviewer on its own.

**D2 — Prompts load from disk at import time.** `prompt.md` is read with
`pathlib` next to `agent.py`. Your collaborator can edit prompt text and restart
`adk web` without touching Python.

**D3 — On-disk layout.** The kickoff prompt says "one JSON file per record
type", but its own Phase 1 done-criteria say `data/jobs/*.json` and
`data/fit_reports/*.json` — one file *per record*. I am going with per-record
files, because they stay readable as the job count grows:

```
data/
  profile.json
  jobs/<job_id>.json
  fit_reports/<job_id>.json
```

**D4 — `user_id` is a field, not a folder.** Every record carries it from day
one as AGENTS.md requires, but Phase 1 does not namespace directories by user.
Multi-user namespacing is a Firestore concern (Phase 3).

**D5 — Timestamps.** `created_at` / `updated_at` are timezone-aware UTC,
serialized as ISO-8601 strings. Readable, sortable, unambiguous.

**D6 — IDs.** Short human-readable slugs with a random suffix
(`acc-20260916-7f3a`) rather than raw UUID4. AGENTS.md rule 5 says a
non-programmer has to be able to read these files; a wall of UUIDs fails that.

**D7 — `requirements.txt` is canonical**, `pyproject.toml` mirrors it. Cloud
Shell uses pip, and the README already tells people to `pip install -r`.

## Questions that were open — answered 2026-09-16

The first three are all under AGENTS.md "Agent design rules", so none of them
were guessed. Answers are recorded inline as **Answer:** under each.

### Q1 — Is `Evidence` its own record? *(rule 1: evidence-backed profile)*

**Answer: (a) — `Evidence` is its own record type.**

AGENTS.md gives `Accomplishment` both an `evidence_id` **and** a `source_text`,
but gives `Skill` only `evidence_ids[]` with no source text of its own. That
asymmetry reads two different ways:

- **(a) Evidence is its own record type.** An `Evidence` row owns the user's
  words (`source_text`, when captured, which session). Accomplishments and
  skills point at it by id, and several can cite the same evidence.
  `Accomplishment.source_text` becomes a convenience copy.
- **(b) There is no `Evidence` model.** `Accomplishment.evidence_id` is just the
  accomplishment's own id, and `Skill.evidence_ids[]` points at accomplishments.
  Skills can only be evidenced by an accomplishment, never by a standalone thing
  the user said.

My recommendation is **(a)**. Phase 2's `validate_resume()` has to compare a
resume bullet against *the text of the cited evidence*; that only works cleanly
if evidence is a first-class thing that owns text. It is also the only way a
skill can cite the user's actual words.

### Q2 — Where does `hypothesis` live? *(rule 1: "it may record a `hypothesis` field")*

**Answer: (a) — `hypothesis` lives on `OpenQuestion`.** `accomplishments[]` and
`skills[]` therefore mean "confirmed fact", with no unconfirmed entries mixed in.

AGENTS.md says the Interviewer must not record inferences as facts, but may
record a `hypothesis` and ask about it later. It does not say where that field
sits. Options:

- **(a) On `OpenQuestion`.** An inference the agent wants to check becomes an
  open question carrying the guess: "I think you led that team — true?" One
  place for everything unconfirmed; facts stay clean.
- **(b) On `Accomplishment` / `Skill`.** The record exists but is flagged
  unconfirmed, with a `confirmed: bool`.
- **(c) Both.**

I lean **(a)** — it keeps `accomplishments[]` and `skills[]` meaning "confirmed
fact, full stop", which is what makes rule 2 (traceable resumes) enforceable.
But this is your product call.

### Q3 — What is `Skill.level`? *(feeds rule 3's stretch/blocker judgement)*

**Answer: fixed ladder — `aware` / `working` / `strong` / `expert`.**

Free text from the model, or a fixed ladder? A fixed set
(`aware` / `working` / `strong` / `expert`) is comparable across skills and lets
fit scoring stay deterministic. Free text is richer, but the Fit Analyst then
has to interpret prose. I lean fixed ladder, with `years` and `last_used`
carrying the nuance. Your call.

### Q4 — Which Gemini model, and which region?

**Answer: `gemini-3.5-flash` everywhere, `GOOGLE_CLOUD_LOCATION=us-central1`.**
The model id lives in one constant (`head_hunter/config.py`) so swapping it
later is a one-line change. Still unverified from here: that your Vertex project
has this model enabled in that region — the first `adk web` run will confirm it.

ADK 2.9.1 defaults to `gemini-3.5-flash`. Do you want that pinned everywhere, or
a stronger model for the Interviewer and Fit Analyst (they do the hardest
judgement work) with flash for the rest? I also need the
`GOOGLE_CLOUD_LOCATION` value you intend to use, and confirmation that your
Vertex project has that model enabled — I cannot check your project from here.

### Q5 — `Makefile` or `scripts/`?

**Answer: `Makefile`, with the raw commands written out in the README** so a
Windows machine without `make` can run them directly.

The kickoff prompt says either. Cloud Shell has `make`; your Windows machine
does not, by default. Options: a `Makefile` (clean, Linux-first, you would run
the raw commands on Windows), or `scripts/` with a `.sh` and `.ps1` twin for
each of dev/test/lint (six small files, works everywhere). Slight lean toward
the `Makefile` plus the raw commands written out in the README, because it is
less to keep in sync.

## What actually shipped

All of it, in five commits. `ruff check .` clean, 36 tests passing, `adk web`
verified running and the coordinator verified answering a real message.

Two things turned up during the build that the plan above did not predict.

### Surprise 1 — `adk web` from the repo root lists the same agent twice

`adk web` does not use the `AgentLoader` that the plan cites; it uses
`NestedAgentLoader`, which walks up to five directory levels deep and lists
**every** folder containing an `agent.py`. From the repo root that produced two
dropdown entries — `head_hunter` and `head_hunter.agents.head_hunter` — and
Phase 1 would have made it five.

Verified behaviour:

| Command | Dropdown shows |
|---|---|
| `adk web` (repo root) | `head_hunter`, `head_hunter.agents.head_hunter` |
| `adk web head_hunter` | `head_hunter` only |
| `adk web head_hunter/agents` | each agent separately |

So the documented command is now **`adk web head_hunter`**, and
`adk web head_hunter/agents` becomes the way to test one specialist alone in
Phase 1. D1 still holds — the shim is what makes the first two rows work.

### Surprise 2 — the chosen model is not available in the project on this machine

Q4 settled on `gemini-3.5-flash`, which is also ADK 2.9.1's own default. Against
the Google Cloud project configured on this machine
(`project-cfe4e420-...`, `us-central1`) that model returns **404 not found**.
Probing that project directly:

| Model | Result |
|---|---|
| `gemini-2.5-flash` | available |
| `gemini-2.5-pro` | available |
| `gemini-3.5-flash` | 404 |
| `gemini-3-pro-preview`, `gemini-3-flash`, `gemini-2.0-flash` | 404 |

That project is almost certainly not the one Head Hunter will run in, so the
committed default was **left at `gemini-3.5-flash` as decided**. What changed is
that the model id is now readable from `HH_MODEL`, so a project that does not
serve the default is a one-line `.env` edit rather than a code change — which
matters, because the collaborator who hits this cannot edit Python. This adds
one variable to `.env.example` beyond the list in the kickoff prompt.

The end-to-end smoke test (ADK `InMemoryRunner`, real Vertex call) was run with
`HH_MODEL=gemini-2.5-flash` and the coordinator replied correctly.

### Deviations from the plan above, in full

- `adk web` → `adk web head_hunter` (Surprise 1)
- `HH_MODEL` added to `.env.example` (Surprise 2)
- `head_hunter/prompts.py` added — a single `load_prompt()` helper rather than
  repeating the pathlib dance in every agent module
- `head_hunter/schemas/ids.py` added to hold D6's id format
- `StorageError` added, so a corrupt or mis-owned data file fails loudly with
  the path in the message (AGENTS.md rule 6)
- `tests/test_agent_loads.py` added — not in the plan, but it is the test that
  would have caught Surprise 1

## Added after Phase 0: Cloud Run deploy plumbing

Deployment is Phase 3 work. What landed here is only the plumbing, so the
container is known to build before Firestore and connectors get piled on top.
`make deploy-test` works; it is a smoke test, not a home for real data.

Three things turned up reading the ADK 2.9.1 deploy code, all verified against
the installed package rather than assumed.

**`adk deploy` copies only the agent folder.** The generated Dockerfile does
`COPY "agents/head_hunter/" "/app/agents/head_hunter/"` and installs the
`requirements.txt` it finds *inside* that folder. The repo-root one is never
seen. Hence `head_hunter/requirements.txt`, and
`tests/test_requirements_in_sync.py` to stop the two drifting — AGENTS.md
already flags duplicate dependency lists as a hazard.

Our absolute `head_hunter.*` imports do survive this, because the package lands
at `/app/agents/head_hunter/` and ADK puts `/app/agents` on the path.

**The default data directory is unwritable in the container.** The Dockerfile
runs `WORKDIR /app` as root, then switches to `USER myuser`, and only chowns
`/app/agents/head_hunter/`. So `/app` stays root-owned, and the default
`HH_DATA_DIR=./data` resolves to `/app/data`, where `config.data_dir()`'s
`mkdir` would raise `PermissionError`. Phase 0 never calls it, so nothing breaks
today — Phase 1 would have crashed on the first save. The deploy targets set
`HH_DATA_DIR=/tmp/head-hunter-data`.

That path is wiped on every container restart, which is the real point: **the
JSON store cannot back a deployed service.** Firestore is not a nice-to-have for
Phase 3, it is the thing that makes deployment meaningful.

**ADK passes nothing about authentication.** It neither adds nor blocks
`--allow-unauthenticated`; whatever follows `--` is forwarded verbatim to
`gcloud run deploy` (traced: `ctx.args` → `extra_gcloud_args` → the gcloud
argv). Left alone, `gcloud` prompts, and a careless yes would put a chat
interface holding personal career data on the public internet. Both deploy
targets pass `--no-allow-unauthenticated` explicitly, and the README routes
access through `gcloud run services proxy`.

## Explicitly not in Phase 0

Interviewer, Intake, Fit Analyst, any tools, fit scoring, the eval set, DOCX
rendering, Firestore, Gmail. Schemas for later phases (`Resume`,
`JournalEntry`) are *defined* in Phase 0 because AGENTS.md asks for that, but
nothing reads or writes them yet.

## Done means

- `ruff check .` clean, `pytest` green
- `adk web` from the repo root starts, lists `head_hunter`, and the agent greets
  you and explains what it will be able to do
- A non-programmer can follow the README from a fresh Cloud Shell to a working
  chat window
