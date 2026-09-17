# Head Hunter Agent

An AI agent that helps you land a job: it learns your career in depth, evaluates job postings against what you've actually done, writes tailored resumes that never invent anything, watches your inbox for recruiters, and coaches you between interviews.

Built on [Google ADK](https://google.github.io/adk-docs/) with Gemini on Google Cloud.

## How it works

Everything revolves around one thing: your **Career Profile**. It's a structured, evidence-backed record of your roles, accomplishments, skills, and goals. Every agent either adds to it or reads from it. If the profile is rich, everything downstream is good; if it's thin, nothing else can be.

```mermaid
flowchart TD
    U([You]) --> HH[Head Hunter<br/>coordinator]

    HH --> INT[Interviewer]
    HH --> IN[Intake]
    HH --> FIT[Fit Analyst]
    HH --> RES[Resume Tailor]
    HH --> COACH[Coach]

    INT -- "asks deep questions,<br/>records evidence" --> P[(Career Profile)]
    COACH -- "interview debriefs" --> P
    COACH --> J[(Journal:<br/>applications & interviews)]

    IN -- "pasted / uploaded JD" --> JOBS[(Job Postings)]
    SCOUT[Inbox Scout<br/>Gmail] -- "recruiter emails" --> IN
    SEARCH[Job Search<br/>board APIs] --> IN

    P --> FIT
    JOBS --> FIT
    FIT --> FR[Fit Report:<br/>score, met / missing reqs, gaps]

    P --> RES
    JOBS --> RES
    FR --> RES
    RES --> VAL{Traceability<br/>validator}
    VAL -- "every bullet cites<br/>profile evidence" --> OUT[/Resume<br/>Markdown + DOCX/]
    VAL -- "untraceable claim" --> RES

    style P fill:#fff3c4,stroke:#c9a400
    style VAL fill:#ffe0e0,stroke:#c00
```

### The agents

| Agent | What it does |
|---|---|
| **Head Hunter** | Front door. Figures out what you need and hands off to the right specialist. |
| **Interviewer** | Interrogates your career like a great recruiter would: what you built, for whom, what changed because of it, what you'd do differently. Records everything as evidence in the profile. Notices its own gaps and comes back to them. |
| **Intake** | Takes a job description (pasted, uploaded, forwarded from email, or found by search) and normalizes it into a structured posting. |
| **Fit Analyst** | Compares a posting to your profile. Gives a score, lists requirements you meet with the evidence, requirements you don't, and separates stretch gaps from hard blockers. |
| **Resume Tailor** | Writes an ATS-friendly resume for one specific job. Every bullet is tied to a profile entry. A separate validator rejects anything it can't trace. |
| **Inbox Scout** | Reads your Gmail, spots recruiter outreach, pulls out role/company/comp, and feeds it to Intake. |
| **Coach** | Logs applications and interviews, asks reflective questions after each one, and points out patterns over time. |

### Rules that don't bend

1. **No invented experience.** The resume can only say things the profile says. Not "similar," not "implied." If it's not there, the Interviewer asks you for it first.
2. **The profile is the source of truth.** Agents don't keep private notes about you.
3. **You can read everything.** Profile, jobs, reports, and journal are all plain data you can inspect and edit.

## Phases

| Phase | Goal | Status |
|---|---|---|
| **0 – Scaffold** | Repo, docs, ADK skeleton, schemas, hello-world agent, both collaborators running `adk web` | ✅ |
| **1 – Proof of concept** | Interviewer → Profile → paste a JD → Fit Report. The loop we iterate on. | ✅ |
| **2 – Resume** | Resume Tailor, traceability validator, Markdown + DOCX output, eval cases | |
| **3 – Connectors & deploy** | Gmail Inbox Scout, one job-board API, Firestore, Cloud Run | |
| **4 – Coach** | Application tracker, interview debriefs, pattern reflection | |
| **Later** | Auth and multi-user, billing, web UI | |

## Running it

Fastest path is Google Cloud Shell (nothing to install, already authenticated):

```bash
git clone https://github.com/tdoolittle3/head-hunter-agent.git
cd head-hunter-agent
cp .env.example .env        # fill in GOOGLE_CLOUD_PROJECT
pip install -r requirements.txt
adk web head_hunter
```

Then open Web Preview on port 8000 and talk to the Head Hunter.

### Trying the Phase 1 loop

1. Say hello. Ask it to interview you.
2. Spend ten minutes on your career. It will walk backwards through your roles
   and push for numbers. Answer as you would a recruiter.
3. Paste a job description straight into the chat.
4. Ask for a fit analysis.

Everything lands as readable JSON under `data/` -- open the files and check
them. `data/profile.json` should contain your actual words under `evidence`;
if it contains anything you did not say, that is a bug worth reporting.

Locally, do the same after `gcloud auth application-default login`.

Point `adk web` at `head_hunter` rather than at the repo root: ADK searches for
agents recursively, so from the root it lists every agent folder separately and
you have to guess which one is the front door.

If the chat window returns a 404 about the model, your Google Cloud project does
not serve `gemini-3.5-flash`. Uncomment `HH_MODEL` in `.env` and set it to a
model your project does have — no code change needed.

### Common commands

`make help` lists these. On Windows, where `make` is usually absent, run the
right-hand side directly:

| Command | What it runs |
|---|---|
| `make dev` | `adk web head_hunter` — the chat UI |
| `make agents` | `adk web head_hunter/agents` — every agent listed separately, for testing one alone |
| `make test` | `pytest` |
| `make lint` | `ruff check .` and `ruff format --check .` |
| `make format` | `ruff format .` and `ruff check --fix .` |
| `make check` | lint then test; must pass before opening a PR |
| `make eval` | run the ADK eval set (needs `pip install "google-adk[eval]"`) |

## Project layout

```
head_hunter/
  agent.py       entry point adk web loads; wraps the coordinator in an App
  agents/        one folder per agent: agent.py + prompt.md
                 head_hunter (coordinator), interviewer, intake, fit_analyst
  schemas/       Pydantic models: Profile, JobPosting, FitReport, Resume, JournalEntry
  storage/       repository interface + JSON (Phase 1) and Firestore (Phase 3) backends
  tools/         functions agents can call, grouped per agent
  scoring.py     deterministic fit score -- never the model's opinion
  jd_text.py     deterministic job-description clean-up
  evals/         ADK eval sets + fixture profile, for hallucination checks
data/            local JSON store (gitignored)
  profile.json     your career profile
  jobs/            one file per posting
  fit_reports/     one file per analysis
docs/            deeper design notes, including PLAN.md
tests/           pytest suite
AGENTS.md        conventions for AI coding agents and humans alike
CLAUDE.md        imports AGENTS.md for Claude Code
```

## For AI agents reading this

This README plus `AGENTS.md` is the intended context. The Mermaid diagram above is the authoritative logic flow; if code and diagram disagree, fix one and say which.
