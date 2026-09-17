# Plan



Phase 0 (scaffold), Phase 1 (the proof-of-concept loop) and Phase 2 (the
resume), all shipped.



The write-ups run newest last. The Phase 0 record is kept first because the

decisions it pinned still govern the code.



## Phase 0



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



---



# Phase 1: the proof-of-concept loop



Interview → Profile → paste a JD → Fit Report. Shipped and verified end to end

against a live Vertex model: a six-turn conversation built a profile, parsed a

posting, and produced a report scoring 35 with the missing security clearance

correctly marked a blocker. All three files landed in `data/`.



## What shipped



| Piece | Where | Note |

|---|---|---|

| Deterministic fit scoring | `head_hunter/scoring.py` | The model cannot pass a score |

| Deterministic JD clean-up | `head_hunter/jd_text.py` | Strips site furniture before the model reads it |

| Interviewer | `head_hunter/agents/interviewer/` | The only agent that writes career facts |

| Intake | `head_hunter/agents/intake/` | Pasted JD → structured `JobPosting` |

| Fit Analyst | `head_hunter/agents/fit_analyst/` | Cited report, stretch vs blocker |

| Coordinator | `head_hunter/agents/head_hunter/` | Routes; warns on a thin profile |

| Tools | `head_hunter/tools/` | Grouped per agent |

| Eval set | `head_hunter/evals/` | Blocker detection, with fixture profile |



88 tests, `ruff` clean.



## The rules are enforced in code, not in prompts



A prompt can be ignored by a model having an off day. These cannot:



- **Rule 1 (evidence-backed).** `add_accomplishment` and `add_skill` both

  require `source_text` of at least four words and build an `Evidence` record

  from it. There is no path to recording a career fact without the user's own

  words. The one tool that accepts a guess is `add_open_question`, which stores

  it in a `hypothesis` field that no resume can cite.

- **Rule 3 (fit reports cite).** `MetRequirement` refuses to construct with an

  empty `evidence_ids`, and `save_fit_report` rejects a met requirement with no

  citations, telling the model to move it to unmet instead. It also refuses to

  save unless *every* requirement has been judged, so nothing can be quietly

  skipped.

- **Rule 4 (deterministic where possible).** `save_fit_report` has no `score`

  parameter. A test asserts that, so nobody can add one without noticing.

- **Rule 2 (one author).** A test asserts that only the Interviewer holds the

  profile-writing tools; Intake, the Fit Analyst, and the coordinator do not.



## Three things found by testing, not by reading docs



**A raising tool killed the whole run.** AGENTS.md rule 6 says tools raise and

agents tell the user what failed. Those are two obligations and ADK only gives

the first for free: without an `on_tool_error_callback`, a raised exception

escapes the invocation and the user sees a stack trace, not an explanation. Ran

both cases to confirm. With the callback attached the model says "I was not able

to ... the error message was ...", which is what the rule actually asks for.

Every agent now has it.



**`adk eval` could not load the package at all.** It imports

`head_hunter/__init__.py` and looks for an `agent` attribute on it — a different

path from `adk web`, which imports `head_hunter.agent` directly. Our `__init__`

did not re-export it, so `adk eval` failed with "Agent module should have either

`root_agent` or `get_agent_async`". ADK's own `adk create` template has

`from . import agent`; Phase 0 noted the template and did not copy that line.



It has to be the *relative* form: `adk eval` loads the file under a synthetic

module name, so `head_hunter` is not importable by name at that moment. And

`adk eval` does not put the repo root on `sys.path` the way `adk web` does,

which is why `make eval` sets `PYTHONPATH=.`.



**Every agent transfer was re-sending the whole prompt uncached.** ADK warns

about this at startup and this system transfers constantly. Fixed by exposing an

`App` with `context_cache_config` from `head_hunter/agent.py` — the loader

prefers `app` over `root_agent`, and both are exported so nothing else breaks.

`min_tokens` is set to 2048 because Gemini rejects caches below its own floor;

the eval run confirmed it, skipping a 1992-token prefix and then caching

successfully.



## The eval was passing for the wrong reason



Worth recording, because it nearly shipped. The first `adk eval` run reported

"Tests passed: 1" — and it was reading a fit report left on disk by an earlier

manual run, which had been committed as if it were a fixture. The Fit Analyst

has a `get_fit_report` tool, so the model could answer from the cached report

without ever comparing the profile to the posting.



It surfaced only because that file looked out of place in the commit diff.

Deleting it turned the eval red, which is what a real failure looks like.



Two more things then had to be fixed before it passed honestly:



- **`include_intermediate_responses_in_final: true`** in `test_config.json`.

  The Fit Analyst answers *after* a transfer from the coordinator, so without

  the flag ADK records the root agent's `final_response` as `null` and the case

  scores 0.0 however good the answer was.

- **The fixture profile was thin** (one accomplishment), so the coordinator

  could stop and ask "shall I run it anyway?" instead of running — an

  intermittent failure waiting to happen. It now carries three accomplishments,

  and a test asserts `not profile.is_thin()`.



`make eval` now deletes `fixture_data/fit_reports/` before running, the

directory is gitignored, and a test fails if one is ever committed again.



## Decisions taken in Phase 1



**P1 — Tools, not `output_schema`, for this phase.** Every Phase 1 step has to

persist something, and a tool does the judgment-to-storage handoff in one call

while still leaving a readable reply in the chat. `output_schema` earns its

place in Phase 2, where the Resume Tailor produces a typed artefact for a

validator rather than prose for a human.



**P2 — `add_role` added to the tool list.** The kickoff prompt names five

Interviewer tools; accomplishments need a `role_id`, so there has to be a sixth.



**P3 — A four-word floor on `source_text`.** A one-word quote is not evidence

and could not support a resume bullet later. The tool refuses and tells the

Interviewer to go back and ask.



**P4 — A required blocker caps the score at 35; a preferred blocker does not.**

Being unable to hold a job is categorically different from missing a

nice-to-have. The constants are named and tested in `head_hunter/scoring.py`.



**P5 — Ambiguous requirements are tagged `required`.** Over-stating the bar

produces a cautious report; under-stating it produces a confident wrong one.



## Deferred to Phase 2 and beyond



- **Resume Tailor and `validate_resume()`.** The schemas exist and are unused.

  This is where `output_schema` and a generator-critic loop belong.

- **DOCX rendering.** `python-docx` is a dependency and nothing imports it yet.

- **File upload for job descriptions.** Paste only for now.

- **A stronger eval metric.** `response_match_score` is ROUGE similarity,

  not an assertion. A custom metric asserting `unmet[].gap == "blocker"`

  on the stored report would be far better than comparing prose.

- **Richer evals.** One case ships. The README in `head_hunter/evals/` lists the

  next three worth writing, including a posting the profile genuinely fits, so

  the analyst is not merely pessimistic.

- **`google-adk[eval]` is not in `requirements.txt`.** Running `adk eval` needs

  it, and it pulls in pandas, scikit-learn, nltk, rouge_score and tabulate.

  That is a large addition for a dev-only tool, and the kickoff prompt says not

  to add dependencies without asking — so it is documented, not added.

- **Cloud Run deploy.** On its own branch, unmerged, and blocked on Firestore

  regardless: the JSON store cannot survive a container restart.



## The default model was changed, reversing Q4

Q4 settled on `gemini-3.5-flash`, which is ADK 2.9.1's own default. It returns
**404 NOT_FOUND** on Vertex in both projects it has been tried in, including
`head-hunter-agent` in us-central1. Confirmed against that project's REST
endpoint:

| Model | us-central1 |
|---|---|
| `gemini-2.5-flash` | serves |
| `gemini-2.5-pro` | serves |
| `gemini-2.5-flash-lite` | serves |
| `gemini-3.5-flash` | 404 |
| `gemini-3-flash` | 404 |
| `gemini-2.0-flash` | 404 |

`DEFAULT_MODEL` is now `gemini-2.5-flash`. It honours the intent of Q4 -- cheap
flash-tier in us-central1 -- and it is what every end-to-end run and the eval
were actually verified against. `HH_MODEL` still overrides it.

This reverses a decision that was explicitly asked and answered, on evidence
gathered afterwards. Say the word and it goes back.

## Known rough edges



- The coordinator sometimes repeats a sub-agent's closing line after a handoff,

  so the user reads the same sentence twice. Cosmetic.

- `response_match_score` is a ROUGE similarity, not an assertion. It catches an

  answer that misses the blocker entirely but is not proof. The hard guarantees

  are in the Python tests.

- The profile grows without bound in one JSON file. Fine for one person and a

  few dozen accomplishments; it is a Firestore problem, not a Phase 1 one.


---



# Phase 2: the resume



Profile + posting + fit report -> a tailored resume whose every bullet traces

back to something the user said, rendered to Markdown and Word. The loop the

README promised in its diagram now exists in code.



## What shipped



| Piece | Where | Note |

|---|---|---|

| Traceability validator | `head_hunter/resume_validation.py` | Plain Python. The model cannot argue with it |

| Markdown + DOCX rendering | `head_hunter/resume_render.py` | Markdown is canonical; DOCX is rendered from it |

| Resume Tailor | `head_hunter/agents/resume_tailor/` | Generator; the validator is the critic |

| Resume storage | `head_hunter/storage/` | Record, `.md` and `.docx` per posting |

| Tools | `head_hunter/tools/resume_tools.py` | Context, save-and-validate, render |

| Eval set | `head_hunter/evals/no_invented_experience.evalset.json` | The profile lacks a credential; the resume omits it |



140 tests, `ruff` clean. 48 of those are new.



## The guarantee, and where it actually lives



Rule 2 is a product promise: the resume can only say what the profile says.

Three things enforce it, none of them a prompt.



- **The schema.** `ResumeBullet` has `min_length=1` on `evidence_ids`, so a

  bullet with no citation cannot be constructed at all.

- **`validate_resume()`.** Deterministic Python, run inside `save_resume`. It

  fails a bullet that uses a number, tool, company, or title not present in the

  evidence that bullet cites.

- **`render_resume()` is a separate call, and it refuses.** A resume whose

  validation did not pass cannot produce a `.docx`. This is the one that

  matters, because the `.docx` is the artefact that reaches an employer. A test

  asserts the two tools stay separate, so nobody merges them for convenience.



## Two decisions inside the validator



**P5 — "The cited evidence" means the records anchored to it, not only

`source_text`.** A bullet citing `ev-1234` may draw on the accomplishment built

from that evidence (situation, action, result, metrics, tools), that

accomplishment's role (company, title), and any skill citing it.



The alternative — `source_text` alone — fails honest bullets. The fixture

profile has a user who said "nine days to two" and an accomplishment whose

`metrics` field records "9 days to 2 days". A resume saying "cut close from 9

days to 2" is good writing about a true thing, and a strict validator would

reject it.



Widening this far and no further is what keeps the interesting failure

reachable: a bullet citing the Acme evidence while naming Northwind as the

employer still fails, because Northwind's role is anchored to different

evidence. There is a test for exactly that.



**P6 — It fails closed.** Term checking is heuristic: a capitalized word

mid-sentence that is not in the stop-list is treated as a name that has to

trace. An unusual verb can therefore be flagged wrongly.



That is the error to make. The failure names the exact word, the Tailor rewords

the bullet, and the reworded bullet is usually shorter. The opposite error ships

a resume claiming something the user never said, which is the single thing this

system exists not to do. The prompt tells the Tailor this outright so it does

not waste turns arguing.



## Things found by running it, not by reading docs



**`$2M` passed the number check on evidence that said "two days".** The first

version emitted both the bare value and the scaled value as acceptable forms of

a magnitude, so `$2M` matched a corpus containing `2`. A magnitude now replaces

the bare value rather than joining it: `$2M`, `2M`, `2 million` and `2000000`

all reduce to one string, and none of them matches a bare `2`.



**`S3` was being read as the number 3.** Any digit in a token made it a

quantity, so "migrated to S3" passed against evidence mentioning "three". A

token is now a quantity only when nothing alphabetic precedes its digits, which

keeps `$2M` and `40%` as numbers while sending `S3`, `k8s` and `Python3` to the

name check, where they belong.



Both were found by running candidate bullets against the fixture profile before

writing a single test. Neither would have been caught by reading the code.



## The DOCX is deliberately boring



No tables, no columns, no text boxes, no headers or footers, no images —

`tests/test_resume_render.py` asserts their absence. An applicant tracking

system reads this before a person does, and it parses a single column of styled

paragraphs reliably and everything else badly.



`render_docx` raises on Markdown it does not understand rather than skipping

the line. A resume quietly missing a bullet is a worse failure than a render

that refuses to run (rule 6).



## Known rough edges



- **The stop-list is a list of English words in a Python file.** It works, and

  it is the least elegant thing in the repo. A dictionary lookup would be

  better; it would also be a new dependency, which the kickoff prompt says not

  to add without asking.

- **`validate_resume()` checks vocabulary, not semantics.** A bullet that

  reuses only words from its cited evidence but rearranges them into a claim

  the user never made would pass. Closing that needs entailment checking, which

  is a model call, which is the thing this function deliberately is not.

- **One resume per posting.** Writing a second overwrites the first. Versioning

  wants a real store, so it waits for Phase 3.

- **Education sections carry no evidence.** `Education` has no `evidence_ids`

  field, so a bullet about a degree has to cite something else. Worth revisiting

  when the Interviewer starts collecting degrees properly.



## Deferred



- **`output_schema` for the Tailor.** Phase 1 decision P1 said this was where

  it would earn its place. It did not: the generator-critic loop needs the

  model to *re-*submit a corrected draft after reading structured failures, and

  a tool round-trip does that while `output_schema` ends the turn. Tools again,

  for the same reason as Phase 1.

- **A cover letter.** Same evidence, same validator, different shape. Cheap to

  add once someone wants it.

- **PDF output.** `.docx` is what applicant tracking systems ask for. PDF needs

  another dependency and has no clear demand yet.

