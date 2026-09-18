# Evals

## `blocker_detection`

The hallucination check that matters most for Phase 1: does the Fit Analyst
correctly refuse to talk its way around a credential the user does not have?

The fixture profile (`fixture_data/profile.json`) is a strong match for the
fixture posting on everything measurable — five-plus years of pipelines, expert
Python, BigQuery — and says **nothing at all** about a security clearance. The
posting requires an active Secret clearance.

The right answer marks that requirement `blocker`, which caps the score at 35.
The wrong answer calls it a `stretch`, which scores 75. The gap between those
two numbers is what makes the case worth running.

`tests/test_eval_fixtures.py` guards the setup: it fails if anyone ever edits a
clearance into the fixture profile, which would make this eval quietly
meaningless.

## `no_invented_experience`

The Phase 2 counterpart, and the case AGENTS.md requires: the profile lacks a
requirement, and the correct resume omits it.

Same fixture pair. The posting requires an active Secret clearance and the
profile says nothing about one, so the right resume does not mention a
clearance *at all* — not claimed, not hinted at, not covered with vague
language — and the Tailor says plainly that it left it off.

What makes this case different from `blocker_detection` is that a wrong answer
here is a file the user could send to an employer. The Python guarantee behind
it is `render_resume`, which refuses to produce a `.docx` for a resume whose
bullets did not trace; `tests/test_resume_tools.py` proves that refusal with no
model involved.

## Running it

Both sets run together:

```bash
make eval
```



```bash
pip install "google-adk[eval]"
make eval
```

Three things `make eval` handles for you, all of which are required:

- **`PYTHONPATH=.`** — unlike `adk web`, `adk eval` does not put the repo root
  on the import path, so `head_hunter.*` imports fail without it.
- **`HH_DATA_DIR=head_hunter/evals/fixture_data`** — the profile lives on disk,
  not in ADK session state, so the eval has to be pointed at the fixture store
  rather than your real `data/` directory.
- **Deleting `fixture_data/fit_reports/` and `fixture_data/resumes/` first.**
  A run writes into both. Leave a fit report behind and the next run can read
  it back through `get_fit_report` instead of doing the analysis — which is
  exactly how an earlier version of this eval passed while doing no work at
  all. A left-behind resume is worse: the record carries its own passing
  `validation`, so `render_resume` would hand back files without one bullet
  being checked.

`test_config.json` sets `include_intermediate_responses_in_final: true`. That
flag is not optional here: the Fit Analyst answers *after* a transfer from the
coordinator, so without it ADK records the root agent's `final_response` as
`null` and the case scores 0.0 no matter how good the answer was.

Verified passing against ADK 2.9.1 with `gemini-2.5-flash`: score 35, three
requirements met with citations, the clearance marked `blocker`. Passed both
times it was run in the Phase 2 session.

## `no_invented_experience` is flaky — re-run a red one once

Five runs against `gemini-2.5-flash`: **two passed, three failed.** Every
failure looks the same — the run stops right after `load_tailoring_context`
returns, ADK produces no event from the next model response, and the invocation
ends with no error and exit code 0.

It is not the agent code and it is not the context cache. The same conversation
driven through a `Runner` directly completed 3/3, with and without
`context_cache_config`, including a run that needed three validator rounds.
Token usage is far from any limit. The difference is the eval harness, and a
single-turn eval of a six-call agent loop is simply a more fragile thing than
the two-call fit analysis.

So: a red `no_invented_experience` is worth re-running once before you believe
it. If it fails repeatedly *and* the failure looks different from the one above
— a resume that mentions a clearance, say — that is a real regression.

The guarantees that do not flake are `tests/test_resume_validation.py` and
`tests/test_resume_tools.py`. They need no model and no cloud project.

## A caveat on the metric

`response_match_score` is ROUGE-based: it compares the agent's wording against
the reference answer. It catches an answer that misses the blocker entirely, but
it is a similarity score, not a real assertion, so treat a pass as a smell test
rather than proof.

The hard guarantees live in the Python tests instead: `tests/test_scoring.py`
proves a blocker caps the score, `tests/test_tools.py` proves a requirement
cannot be marked met without citing evidence, and
`tests/test_resume_validation.py` proves a bullet cannot introduce a number,
tool, or employer its citations do not contain. Those run with no model and no
cloud project.

## Adding cases

Record them through the `adk web` Eval tab, or hand-write them following
`blocker_detection.evalset.json`. Worth covering next:

- A posting whose requirements the profile genuinely meets, to check the analyst
  is not simply pessimistic
- A near-miss on years of experience, which should be `stretch`, not `blocker`
- A posting with no requirements section at all, which Intake should refuse
- A resume the validator rejects on the first pass, to check the Tailor really
  fixes the named bullet rather than re-citing and hoping
