# The Pro plan: job sweep and billing

What it would take to turn Head Hunter from a tool you use into an agent that
works while you sleep — and to charge for it. This is the plan to review and
argue with before any of it is built. Numbers marked *proposal* are defaults
to react to, not decisions.

## The split

**Free is reactive. Pro is proactive.** The free tier is the honesty engine you
drive by hand; Pro is the agent acting on your behalf between visits. That is
also the cost line: proactive features burn API calls and scheduled compute per
user whether or not they open the app.

| | Free | Pro |
|---|---|---|
| Career profile & interview | Unlimited | Unlimited |
| Fit analyses | 5 per month *(proposal)* | Unlimited |
| Tailored resumes | 2 per month *(proposal)* | Unlimited |
| Application tracking & funnel | Yes | Yes |
| **Job sweep** (watchlists + board search, scored against your profile) | — | Yes |
| Inbox Scout, interview prep (later) | — | Yes |
| Price | $0 | **$12 / month** *(proposal)* |

Why $12: job-search tools cluster at $9–40/month (Teal, Huntr, LinkedIn
Premium). Job searching is episodic — people cancel when they win — so this is
monthly-only, framed as *pay while you're searching*, cancel in one click. No
annual plan. The number should be revisited after test users answer "what
would you pay?"

The free limits exist to create the upgrade moment without gutting the pitch:
the profile (the retention asset) is never limited.

## Job sweep

The agent searches for you: it reads your profile's goals and constraints,
sweeps real job sources, dedupes against what you have seen, scores each new
posting with the same deterministic fit scoring that exists today, and
surfaces "4 new matches this week, best fit 81" in the Jobs tab.

**Sources (clean APIs only — no scraping):**

1. **Greenhouse / Lever / Ashby public board APIs** — per-company, no auth.
   The user keeps a watchlist: "tell me when these 30 companies post a role
   like mine." Highest signal, costs nothing.
2. **Adzuna** (free API tier) for broad keyword/location search. One
   aggregator is enough for v1; Jooble, The Muse, USAJOBS can follow.

LinkedIn and Indeed have no public APIs and stay out until that changes.

**The pipeline (deterministic where possible, per AGENTS.md rule 4):**

```
watchlist + profile goals -> fetchers (plain Python, typed, tested)
  -> dedupe (seen-set per user: source + external id, company|title|location hash)
  -> cap: top N new postings per sweep (cost control)
  -> Intake normalizes requirements (the one LLM step)
  -> fit score (existing scoring.py) -> saved as JobPosting(source="search") + FitReport
  -> Jobs tab, newest first, badged "found for you"
```

**Trigger, in two steps:**

- *Slice 1:* a "Sweep now" button on the Jobs tab. No scheduler, no new
  infrastructure, immediately demoable, and it exercises the whole pipeline.
- *Slice 2:* Cloud Scheduler hits a worker endpoint daily per Pro user
  (OIDC service-account auth, not a user token). This is the "background
  spine" that Inbox Scout and interview prep later reuse.

**Cost control:** cap new postings scored per sweep (*proposal: 15*), sweep
daily not hourly, and skip the LLM entirely for postings whose raw text fails
cheap prefilters (wrong country, wrong seniority keywords).

## Billing

**Stripe, and as little of it as possible.** No custom payment UI:

- **Stripe Checkout** for upgrading (the Account page's Plan card gets an
  "Upgrade" button that redirects), **Customer Portal** for cancel/card
  changes. Stripe hosts both; we never touch card data.
- A **webhook** (`/api/stripe/webhook`, signature-verified) writes the plan to
  a `users/{uid}` document in Firestore: `plan`, `stripe_customer_id`,
  `current_period_end`. That document is the single source of truth.
- **Enforcement is server-side**, where the rate limiter already lives: the
  free tier's monthly fit-analysis and resume counts are checked against the
  caller's verified uid before the agent runs. The UI reads the same plan to
  show "3 of 5 analyses used" honestly, but the UI is never the gate.
- Sweep endpoints check `plan == "pro"` the same way.

Secrets via env, as always: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, one
price id. Stripe test mode until the end-to-end flow is proven.

**Deliberately not built yet:** annual plans, teams, coupons, trials
(Stripe makes a 7-day trial one checkbox later), invoicing, tax handling
beyond Stripe's defaults.

## Bring your own model (MCP)

Some people live in Claude or ChatGPT all day and will never open our web UI.
For them, Head Hunter becomes a **connector**: an MCP server on the same Cloud
Run service, so their own frontier model talks to their profile, jobs and
journal directly. The web UI stays one client among several; both doors hit
the same Firestore records and the same rules.

**Tools, at two levels:**

- *Data tools* — `get_profile`, `list_jobs`, `get_fit_report`,
  `save_job_posting`, `log_application_event`. Their model does the
  conversation; we do the bookkeeping. "Log that Acme moved me to a final
  round," said to their Claude, lands in the same journal that draws the
  funnel.
- *Agent tools* — `analyze_fit(job_id)`, `tailor_resume(job_id)` invoke our
  Gemini agents server-side and return the finished artifact. Their model
  orchestrates; our specialists execute.

**The rules survive a foreign model.** A connected Claude cannot make Head
Hunter invent experience: `tailor_resume` runs the traceability validator
server-side and returns only bullets that cite evidence. Rule 1 lives in the
tools, not in whichever model is talking.

**Auth, in two steps:** v1 uses per-user access tokens created on the Account
page (works in Claude Code and Claude Desktop immediately); the OAuth flow
that claude.ai's remote-connector directory requires comes later, once the
tools have proven themselves. MCP access is a Pro feature and reuses the same
plan check as the sweep — with the pleasant economics that a connected user
pays for their own conversation tokens, and we pay only for the agent tools.

**A2A, for later:** ADK ships Agent2Agent support (the deploy already installs
`google-adk[a2a]`), so exposing the coordinator to *other agents* is
configuration-scale work. Parked until agent ecosystems, rather than people,
are knocking.

## Build order

Each slice ships on its own and is useful without the ones after it.

1. **Sweep pipeline + "Sweep now" button** — fetchers (Greenhouse/Lever +
   Adzuna), dedupe, cap, score, Jobs-tab badge. Ungated at first so it can be
   tested; gating lands with slice 3.
2. **Scheduler** — daily background sweep per opted-in user; "found for you"
   accumulates between visits.
3. **Stripe + enforcement** — plan document, webhook, Checkout/Portal buttons
   on the Account page, free-tier counters, sweep gated to Pro.
4. **Pricing on the landing page** — only after 1–3 work and the numbers have
   survived contact with test users.
5. **MCP connector** — data tools first, then the two agent tools; per-user
   access tokens on the Account page; Pro-gated from day one (slice 3 exists
   by then). OAuth for the claude.ai connector directory only once the tools
   have earned it.

## Open questions for Thomas

1. Price point and free-tier counts (the *proposal* numbers above).
2. Watchlist seed: which companies/boards matter to your test users?
3. Does slice 2 send a weekly email digest, or is in-app enough to start?
   (Email adds a sender domain and templates — real work, real value.)
