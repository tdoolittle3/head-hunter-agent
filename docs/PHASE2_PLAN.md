# Phase 2 plan — Resume Tailor and the traceability validator

Scope: **Phase 2 only.** Resume Tailor, `validate_resume()`, Markdown + DOCX
output, eval cases. Nothing from Phase 3.

This phase is where AGENTS.md rule 2 stops being a promise and becomes code:

> Every `ResumeBullet` references at least one `evidence_id`. `validate_resume()`
> is a deterministic Python function, not an LLM call, and fails the bullet if
> the reference is missing or the bullet introduces a number, tool, company, or
> title that does not appear in the cited evidence. The Resume Tailor loops
> until validation passes or reports what it could not support.

Rule 2 is under "Agent design rules", so the questions below were asked, not
guessed.

## What already exists

- `Resume`, `ResumeSection`, `ResumeBullet`, `ValidationResult`,
  `ValidationFailure` — defined in Phase 0, unused
- `ResumeBullet.evidence_ids` has `min_length=1`, so a bullet with no citation
  cannot construct. That is the easy half of rule 2 already done.
- `python-docx` is a pinned dependency that nothing imports yet.

## The problem in one example

From the eval fixture:

| Source | Text |
|---|---|
| `Evidence.source_text` | "...cut month-end close from **nine days to two**." |
| `Accomplishment.metrics` | `["9 days to 2 days"]` |
| `Accomplishment.tools` | `["Python", "Airflow", "BigQuery"]` |
| `Role` | Acme Foods / Staff Engineer |

A good resume bullet reads *"cut month-end close from **9 days to 2**"*. Match
that against `source_text` alone, character for character, and an honest bullet
is rejected — the user said "nine", the resume says "9".

So "appears in the cited evidence" needed defining before any code was written.
That is **Q1** and **Q2** below.

## Files this phase creates

**1. The validator (deterministic, no model)**
- `head_hunter/resume_validation.py` — `validate_resume()` and the corpus logic
- `tests/test_resume_validation.py` — the biggest test file in the repo; this
  function is the one thing standing between the profile and a fabricated resume

**2. Rendering**
- `head_hunter/resume_render.py` — `render_markdown()` and `render_docx()`
- `tests/test_resume_render.py`

**3. Storage**
- `save_resume` / `get_resume` added to `Repository` and `JsonRepository`
- Resumes land at `data/resumes/<job_id>.json`, `.md`, and `.docx`

**4. The agent**
- `head_hunter/agents/resume_tailor/{agent.py,prompt.md}`
- `head_hunter/tools/resume_tools.py`
- Wired into the coordinator as a fourth specialist

**5. Evals**
- A case where the profile lacks a requirement and the correct resume **omits**
  it, per AGENTS.md

## Decisions taken without asking

**P2-A — The validator never edits, only reports.** It returns
`ValidationResult` with a reason per failed bullet. Rewriting is the Tailor's
job; a validator that silently fixed things would hide the problem it exists to
surface.

**P2-B — DOCX renders from the same `Resume` object as the Markdown**, not by
parsing the Markdown back. AGENTS.md says "Markdown is the canonical resume
format; DOCX is rendered from it" — rendering both from one structure honours
the intent (identical content, Markdown is what you read) without a pointless
parse step. Flagged as a deviation from the literal wording.

**P2-C — ATS-friendly means boring.** No tables, no columns, no text boxes, no
headers/footers, standard heading styles. Those are what break resume parsers.

**P2-D — A bullet cites evidence, not accomplishments.** `evidence_ids` already
means evidence, consistent with `MetRequirement`.

## The four questions, answered 2026-09-17

### Q1 — What text counts as "the cited evidence"?

**ANSWER: (c) — evidence `source_text` + the citing accomplishment's fields + that accomplishment's role (`company`, `title`).**

For a bullet citing `ev-123`, which text may it draw from?

- **(a) `Evidence.source_text` only.** Strictest. Rejects "9 days" when they
  said "nine days", and rejects naming the employer, since the company lives on
  `Role` and not in the quote.
- **(b) source_text + the accomplishment that cites it** — its `situation`,
  `action`, `result`, `metrics`, `tools`.
- **(c) (b) + that accomplishment's `Role`** — `company` and `title`.

**Recommended: (c).** Everything in that set is already evidence-backed by rule
1: the Interviewer could only record it from something the user said. It makes
`metrics: ["9 days to 2 days"]` available, which is exactly the digit form a
resume needs, and it lets a bullet name the employer it belongs to.

### Q2 — How strictly are numbers matched?

**ANSWER: (a) — normalize word-numbers to digits both ways, then compare values.**

- **(a) Normalize, then compare values.** Map word-numbers to digits both ways
  ("nine" -> 9), strip separators, compare numerically. Percentages, currency
  and multiples are values too.
- **(b) Exact string match.** Simple and unforgiving; fails most real bullets.

**Recommended: (a).** Still deterministic, still catches the thing that matters
— a number in the bullet with no counterpart in the evidence at all.

### Q3 — How are invented tools, companies and titles caught?

**ANSWER: (a) — closed vocabulary drawn from the profile. Document plainly what it cannot catch.**

- **(a) Closed vocabulary from the profile.** Gather every `tools[]` entry,
  every `company` and every `title` across the whole profile. If a bullet names
  one of those and it is *not* in the cited evidence, fail. Catches the
  realistic fabrication — attributing Airflow to the role where they actually
  used something else — and needs no NLP. Cannot catch a tool the profile has
  never heard of.
- **(b) Capitalized-token heuristic.** Catches more, many false positives.
- **(c) Both**, with (b) as a warning rather than a failure.

**Recommended: (a)**, documenting plainly what it cannot catch.

### Q4 — How does the Tailor loop?

**ANSWER: (a) — tool-driven, with a hard attempt cap.**

- **(a) Tool-driven.** The Tailor calls `validate_resume`, gets structured
  failures back, rewrites, calls again. A hard attempt cap stops it spinning.
- **(b) ADK `LoopAgent`** with the validator wrapped as a sub-agent.

**Recommended: (a).** The validator is plain Python and does not need to be an
agent; a tool keeps the conversation natural and lets the Tailor explain what it
could not support, which is the half of the rule that matters most.

## Done means

- `validate_resume()` is deterministic, heavily tested, and rejects a bullet
  that borrows a number or a tool from evidence it did not cite
- The Tailor produces Markdown + DOCX for one job, every bullet traceable
- An eval case proves a missing requirement is **omitted**, not invented
- `ruff` and `pytest` green

## Note for Phase 3

Confirmed 2026-09-17: storing the profile in Firestore and reading it through
the Firestore console is acceptable. That resolves the tension with AGENTS.md
rule 5 ("user-readable data") — no JSON export command is required.
