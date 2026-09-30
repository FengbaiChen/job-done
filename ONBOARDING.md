# Talos（我不投简历）— Onboarding

Shareable setup script. Run it as a conversation with a new user — step by step, confirming as you go. Do not dump all questions at once. The pipeline itself is domain-agnostic (it works for any job hunt); the examples below use a software-engineering hunt for concreteness.

## Step 1 — Resumes

Ask the user to upload 1–3 resumes. Read each one and extract:

- name, email, phone, address, location
- education (school, degree, field, dates, GPA)
- work authorization + sponsorship needs (ask if unclear)
- links (LinkedIn, GitHub, personal site)
- skills and standout projects

Store the files (note their paths). Copy `templates/profile.template.yaml` → `profile.yaml` and fill it in, then copy `templates/standing-answers.template.md` → `references/standing-answers.md` and adjust the rules to the user's situation.

## Step 2 — Confirm + fill gaps

Present the extracted profile back. Ask for anything missing:

- preferred name, earliest start date
- relocation willingness
- EEO answers (gender / race / veteran / disability)
- interview recording consent
- export-control status if relevant
- transcript file, if they have one
- **date of birth (full YYYY-MM-DD; some forms require month/day only) — collect once here, never ask mid-flow**
- **work history with start/end dates (YYYY-MM) for every role — forms require these and they are never invented**
- **companies/roles already applied to** — ask outright ("any jobs you've already applied to on your own?"). Seed each into the dedupe cache so discovery never re-suggests them:
  `python3 scripts/seed_applied.py --entry "Company|Title" [--entry "Company|Title|URL"]`
  (This is the Amazon-ADC lesson: URL-only dedup can't catch "I already applied there.")
- standardized test scores only if a target form is known to require them (note "none" is fine)

The user confirms or corrects everything before moving on.

## Step 3 — Target roles

Discuss what the user is hunting for and turn it into pipeline configuration. Do not ask them to list target companies — that comes from recommendation in Step 4.

1. **Lanes.** Propose 1 lane per resume (e.g. for a SWE: backend/infra, AI platform, frontend). Each lane gets: a name, its resume, a priority, 8–15 **keywords** (plain phrases matched against title + snippet to assign the lane), and 2–3 LinkedIn **search queries**.
2. **Title filters.** Agree on `title_include` (must match at least one — e.g. a new grad's `new grad | entry level | junior`; an experienced hire's `senior | staff`) and `title_exclude` (any match drops the posting — e.g. `intern` for full-time hunts).
3. **Industry / function tags.** Note 1–3 industry tags and function tags describing the hunt (e.g. industries `ai_infra`, `fintech`; functions `swe`, `sre`). These drive the brand recommendation in Step 4. The tag vocabulary lives in `references/board_directory.json` — reuse its tags when they fit.

## Step 4 — Brand set (recommended, not interrogated)

Users rarely have a target-company list ready, so **recommend one** instead of asking. The pipeline polls company ATS boards directly (public Greenhouse/Ashby JSON APIs — complete, structured, no login), which beats keyword search on recall for the companies it covers.

1. Copy `templates/company_boards.template.json` → `references/company_boards.json` (starter set of ~10 generic companies with stable public APIs — the user has coverage from minute one).
2. From `references/board_directory.json` (49+ companies with verified public ATS APIs, tagged by industry/function), pick 15–25 whose tags overlap the Step 3 tags.
3. Propose the list to the user with a one-line rationale each ("AI infra, hires new-grad SWEs via Ashby"). They confirm, cut, or add names.
4. **Verify live** before saving: hit each confirmed company's board API (`https://boards-api.greenhouse.io/v1/boards/{token}/jobs` or `https://api.ashbyhq.com/posting-api/job-board/{token}`); drop any token that fails and tell the user.
5. Merge the verified picks into `references/company_boards.json` (dedupe by token).

`references/company_boards.json` is the user's own list — gitignored, never committed. The directory is the shared pool; runtime source-health monitoring warns if a board goes quiet (company switched ATS, token died).

## Step 5 — Curated job lists (recommended)

API polling covers companies with public ATS boards; LinkedIn covers the rest best-effort. Community-curated lists (GitHub repos updated daily with postings) fill the remaining gap — they aggregate companies with no public API at all. During this step:

1. Based on the resumes (Step 1) and target roles (Step 3), search GitHub for daily-updated job repos (e.g. "new grad positions 2026").
2. Open the top candidates and check: updated recently, has a parseable table (Company | Role | Location | Application | Age — HTML `<table>` or markdown both work), covers the user's field.
3. Propose 1–3 to the user with a one-line description each; the user confirms.
4. Note the confirmed URLs + sections to include (e.g. "Software Engineering", "Data Science") — they are written under `curated_sources:` in Step 9.

The pipeline fetches these tables every run and treats rows like any other source: dedupe, recency window, health monitoring. If a list's format drifts (0 parseable rows), the health check warns.

## Step 6 — Connect Gmail (required, not optional)

The pipeline needs mailbox access for two things — this step cannot be skipped:

(a) **Reply tracking.** Recruiter replies, interview invitations, and application confirmation emails are detected automatically (the tracker's status updates depend on it). No mailbox access → no tracking.
(b) **Verification codes.** Some application sites require an email verification code during registration or before submission. Without mailbox access those applications cannot be completed.

Which mailbox: the one the user puts on applications — usually the email already extracted in Step 1. Confirm it with them.

Follow the gmail skill's standard connect flow (`/opt/hatch/skills/gmail/SKILL.md`):

1. Run `hatch_gws_cli gmail status`.
2. If it reports not connected, it returns a `connect_url` — post it to the user exactly as `[Connect Gmail](<connect_url>)` and wait for them to finish authorizing. Never invent a URL, never send them to Settings.
3. Verify with one read-only check (e.g. reading the mailbox profile) that commands return data before moving on.

Set expectations in one or two sentences, in the user's own words: verification codes are fetched **on demand only**. The pipeline reads Gmail only when a form-fill task parks at a verification step and reports back the site URL and the masked recipient shown on the page; then it does one targeted lookup for that single freshly-arrived message, uses the code once for that step, and never stores it, never reuses it, and never sweeps the inbox for codes.

## Step 7 — LinkedIn login (recommended if LinkedIn is a discovery source)

Roles discovered from LinkedIn need one click on "Apply" — and LinkedIn gates that behind sign-in. The pipeline handles this with a **user-takeover login** (the assistant never sees the password):

1. Spawn a browser task that opens https://www.linkedin.com/login and parks, asking the user to take over.
2. The user opens the task's browser panel, takes over, and signs in with their own credentials (including any 2FA / verification challenge), then ends the takeover and confirms.
3. Verify the login (linkedin.com/feed shows a logged-in homepage, not a login wall), then close the task. The session persists in the shared browser profile, so all later fill tasks reuse it.
4. If a fill task ever reports "linkedin session expired", repeat this step.

All browser tasks share one Chromium profile — the LinkedIn session is shared across tasks. Be upfront: LinkedIn's ToS technically prohibits automated access, so there is a small account-risk tradeoff; let the user decide.

## Step 8 — Storage

Recommend: **Google Sheet** (human-facing tracker — shareable, phone-friendly) + **local `state/seen_roles.json`** (machine dedupe cache so browsed roles are never re-read). Alternative: local-only if they decline Google.

If Sheet: connect Google Sheets, create the tracker with columns:
`Date | Company | Role | Location | Lane | Link | Confirmation | App ID | Status | Notes`
Save the spreadsheet ID in `state/tracker.json`.

## Step 9 — Config

Copy `templates/config.template.yaml` → `config.yaml` and fill it in from everything agreed above (the template's comments explain every field):

- lanes (name, resume, priority, **keywords**, queries) from Step 3
- `discovery.title_include` / `title_exclude` from Step 3
- `curated_sources` from Step 5
- run frequency and times, timezone
- roles per run (`shortlist_size`), browse target (`browse_target`)
- locations: preferred, acceptable, excluded
- companies to never apply to (`blacklist` — keep small; already-applied roles are deduped via `state/seen_roles.json`, not here)
- submit review mode: `batch` (fill all → one combined review → "submit all") or `per_application` (fill → review → approve → submit, one role at a time)
- posting recency: the auto-scaling window (`window_steps_days`, `min_candidates`) is the primary control; `max_post_age_days` is a legacy fallback
- auto-select: skip the role-picking step and go straight to filling? (`auto_select` — default true; confirm at onboarding with risks explained)
- auto-submit: submit all filled applications with no review screen? (`auto_submit` — default true; confirm at onboarding with risks explained; when false, `submit_review_mode` applies)
- grad-date eligibility rules per lane if relevant

### Automation level (confirm both explicitly — explain the risks first)

The pipeline can run end-to-end with zero interruptions. Present both switches
with their risks in plain language and get an explicit yes/no for each. The
template defaults are the aggressive ones (`true`/`true`); the user may turn
either off.

- **A. Auto-fill the shortlist** (`auto_select`, default true): every role that
  passes judging goes straight to form-filling — no picking from a list.
  Risk: a misjudged role gets filled (wasted effort, but nothing is submitted
  yet — the blast radius is small).
- **B. Auto-submit after filling** (`auto_submit`, default true): once all
  forms are filled, they are submitted immediately with no review screen.
  Risks, stated plainly:
  1. A prefill error or wrong field goes out uncaught — a submitted
     application can't be taken back. (Mitigated by the pre-submit checklist
     and standing answers, not eliminated.)
  2. A misjudged role gets applied to without the user ever seeing it.
     (Mitigated by the posting-text disqualifier scan and semantic dedup.)
  3. Duplicate applications if dedup misses — dangerous where a company caps
     applications (e.g. ByteDance's 2-role limit for new grads).
  A post-submit report (confirmations, IDs, blocked/manual list) is always
  delivered either way — only the approval step is skipped, never the logging.

Record the answers in `config.yaml`. If the user turns B off, also confirm
`submit_review_mode` (batch vs per_application).

## Step 10 — Go live

Create the discovery cron(s) per the schedule (owner: the user's job-search goal or tracked item).

Reporting destination: ask whether discovery reports should go to a dedicated side chat (recommended — keeps the main chat clean) or stay in the current chat. If side chat: create it and set it as the crons' `delivery` target.

Confirm with the user:

- "run the pipeline now" — runs a discovery immediately
- "reset pipeline config" — re-runs this onboarding (confirm before wiping)
- "pause pipeline" / "resume pipeline" — toggles the schedule
