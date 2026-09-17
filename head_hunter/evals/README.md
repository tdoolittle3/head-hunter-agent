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

## Running it

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
- **Deleting `fixture_data/fit_reports/` first.** A run writes a report there.
  Leave it behind and the next run can read it back through `get_fit_report`
  instead of doing the analysis — which is exactly how an earlier version of
  this eval passed while doing no work at all.

`test_config.json` sets `include_intermediate_responses_in_final: true`. That
flag is not optional here: the Fit Analyst answers *after* a transfer from the
coordinator, so without it ADK records the root agent's `final_response` as
`null` and the case scores 0.0 no matter how good the answer was.

Verified passing against ADK 2.9.1 with `gemini-2.5-flash`: score 35, three
requirements met with citations, the clearance marked `blocker`.

## A caveat on the metric

`response_match_score` is ROUGE-based: it compares the agent's wording against
the reference answer. It catches an answer that misses the blocker entirely, but
it is a similarity score, not a real assertion, so treat a pass as a smell test
rather than proof.

The hard guarantees live in the Python tests instead: `tests/test_scoring.py`
proves a blocker caps the score, and `tests/test_tools.py` proves a requirement
cannot be marked met without citing evidence. Those run with no model and no
cloud project.

## Adding cases

Record them through the `adk web` Eval tab, or hand-write them following
`blocker_detection.evalset.json`. Worth covering next:

- A posting whose requirements the profile genuinely meets, to check the analyst
  is not simply pessimistic
- A near-miss on years of experience, which should be `stretch`, not `blocker`
- A posting with no requirements section at all, which Intake should refuse
