# Job Pipeline — Onboarding

Shareable setup script. Run it as a conversation with a new user — step by step, confirming as you go. Do not dump all questions at once.

## Step 1 — Resumes

Ask the user to upload 1–3 resumes. Read each one and extract:

- name, email, phone, address, location
- education (school, degree, field, dates, GPA)
- work authorization + sponsorship needs (ask if unclear)
- links (LinkedIn, GitHub, personal site)
- skills and standout projects → propose 1 lane per resume (e.g. agent/infra, ai/cloud, genai) with 2–3 example search queries each

Store the files (note their paths). Copy `templates/profile.template.yaml` → `profile.yaml` and fill it in, then copy `templates/standing-answers.template.md` → `references/standing-answers.md` and adjust the rules to the user's situation.

## Step 2 — Confirm + fill gaps

Present the extracted profile back. Ask for anything missing:

- preferred name, earliest start date
- relocation willingness
- EEO answers (gender / race / veteran / disability)
- interview recording consent
- export-control status if relevant
- transcript file, if they have one
- standardized test scores only if a target form is known to require them (note "none" is fine)

The user confirms or corrects everything before moving on.

## Step 3 — Connect Gmail (required, not optional)

The pipeline needs mailbox access for two things — this step cannot be skipped:

(a) **Reply tracking.** Recruiter replies, interview invitations, and application confirmation emails are detected automatically (the tracker's status updates depend on it). No mailbox access → no tracking.
(b) **Verification codes.** Some application sites require an email verification code during registration or before submission. Without mailbox access those applications cannot be completed.

Which mailbox: the one the user puts on applications — usually the email already extracted in Step 1. Confirm it with them.

Follow the gmail skill's standard connect flow (`/opt/hatch/skills/gmail/SKILL.md`):

1. Run `hatch_gws_cli gmail status`.
2. If it reports not connected, it returns a `connect_url` — post it to the user exactly as `[Connect Gmail](<connect_url>)` and wait for them to finish authorizing. Never invent a URL, never send them to Settings.
3. Verify with one read-only check (e.g. reading the mailbox profile) that commands return data before moving on.

Set expectations in one or two sentences, in the user's own words: verification codes are fetched **on demand only**. The pipeline reads Gmail only when a form-fill task parks at a verification step and reports back the site URL and the masked recipient shown on the page; then it does one targeted lookup for that single freshly-arrived message, uses the code once for that step, and never stores it, never reuses it, and never sweeps the inbox for codes.

## Step 4 — Storage

Recommend: **Google Sheet** (human-facing tracker — shareable, phone-friendly) + **local `state/seen_roles.json`** (machine dedupe cache so browsed roles are never re-read). Alternative: local-only if they decline Google.

If Sheet: connect Google Sheets, create the tracker with columns:
`Date | Company | Role | Location | Lane | Link | Confirmation | App ID | Status | Notes`
Save the spreadsheet ID in `state/tracker.json`.

## Step 5 — Config

Copy `templates/config.template.yaml` → `config.yaml` and fill it in with the user
(the template's comments explain every field):

- which lane each resume targets (+ search queries)
- run frequency and times, timezone
- roles per run (`shortlist_size`), browse target (`browse_target`)
- locations: preferred, acceptable, excluded
- companies to never apply to (`blacklist` — keep small; already-applied roles are deduped via `state/seen_roles.json`, not here)
- submit review mode: `batch` (fill all → one combined review → "submit all") or `per_application` (fill → review → approve → submit, one role at a time)
- posting recency: how fresh must a role be? (`max_post_age_days` — 7 = past week, 3, 1 = past 24h, 0.5 = past 12h; best-effort per source)
- auto-select: skip the role-picking step and go straight to filling? (`auto_select` — for lazy users; submit approval is never skipped)
- grad-date eligibility rules per lane if relevant

## Step 6 — Go live

Create the discovery cron(s) per the schedule (owner: the user's job-search goal or tracked item).

Reporting destination: ask whether discovery reports should go to a dedicated
side chat (recommended — keeps the main chat clean) or stay in the current
chat. If side chat: create it and set it as the crons' `delivery` target.

Confirm with the user:

- "run the pipeline now" — runs a discovery immediately
- "reset pipeline config" — re-runs this onboarding (confirm before wiping)
- "pause pipeline" / "resume pipeline" — toggles the schedule
