---
name: "job-pipeline"
description: "Run the automated job-application pipeline: discover new-grad roles on a schedule, shortlist them for the user, fill applications, batch the reviews, submit on approval, and log everything to the tracker."
---

# Job Pipeline

## Purpose

An end-to-end, human-in-the-loop job application loop. Scheduled runs discover roles; the user selects; the agent fills; the user approves; the agent submits and logs. Personal data lives in `profile.yaml` and `state/` — never share those. Shareable parts: `SKILL.md`, `discover.py`, `scripts/`, `ONBOARDING.md`, `config.yaml` (as a template), `references/` (including the verified board list `company_boards.json`).

## Workflow

### Stage 1 — Discover (scheduled run, or "run the pipeline now")

1. Run the API-first discovery script (non-interactive — it never prompts):
   `python3 ~/workspace/skills/job-pipeline/discover.py`
   It pulls every board in `references/company_boards.json` through their public JSON APIs (Greenhouse / Ashby — no login needed) plus the LinkedIn guest search API for each lane query in `config.yaml`, then applies programmatic filters in this order: dedupe against `state/seen_roles.json` FIRST (never re-surface a seen URL), `blacklist`, new-grad title signal, lane keywords, location fit — and recency via the **auto-scaling window** (starts 24h, expands stepwise to 30d until `discovery.min_candidates` pre-filter roles are in-window; `--max-age-days` overrides to a fixed window for one-time backfills). It writes the compact pre-filtered set to `state/discovery_candidates.json` and prints a one-line summary (boards OK, jobs pulled, window used, candidates, seconds, watermark run counter, newly-closed count). Typical runtime is 1–3 minutes at ~10x lower token cost than browsing page by page.
2. Judge `state/discovery_candidates.json` in BATCHES: one LLM call scores and ranks ~10 roles at a time from title+company+location+date+snippet (never one call per role). Decide keep/reject from the snippet alone for clear cases; open a posting page ONLY for genuinely borderline roles, capped at ~5 page opens per run. Verify new-grad eligibility, lane fit, and sponsorship plausibility per `config.yaml` and `references/standing-answers.md`.
3. Small web supplement (capped): 2–3 targeted web searches for fresh postings from companies with no public board API (YC Jobs has no stable public API; LinkedIn company pages beyond the guest search). Open at most ~10 pages total, and check `state/seen_roles.json` before opening any URL.
4. Keep the top `discovery.shortlist_size`, ordered by lane priority then fit.
5. Write EVERY judged role (candidates you evaluated + supplement pages you opened) to `state/seen_roles.json`: keepers → `"decision": "shortlisted"`; the rest → `"decision": "rejected"` with a short `"reason"`.
6. Save the shortlist to `state/runs/<YYYY-MM-DD-HHMM>.json`.
7. Shortlist non-empty → present it to the user for selection (company, role, location, lane, link, one-line fit note). Empty → stay silent.
8. Everything in this stage is non-interactive: never ask the user questions mid-run.
9. Source health (overrides the stay-silent rule): read the `health=` token of the discovery one-line summary. If any source is WARN/FAIL, tell the user which source and the symptom (e.g. "board:Acme — fetch failed (Timeout)", "linkedin — newest item 200h old") even when the shortlist is empty. In normal (non-empty) reports, append one line: `Sources: 41/41 healthy` (or list the degraded ones). The per-source history lives in `state/source_health.json`.

To cover a new company, add its board to `references/company_boards.json` (`greenhouse` token or `ashby` org slug, verified live against the public API) — the next run picks it up automatically.

### Stage 2 — Select (user, unless auto_select)

Present the shortlist: company, role, location, lane, link, one-line fit note. The user picks ("all", numbers, or names).

If `auto_select: true` in config.yaml, skip this step: proceed with all shortlisted roles straight to Stage 3. Submit approval in Stage 4 is never skipped.

### Stage 3 — Prepare (agent)

For each selected role:

1. **Form structure (cached, no LLM re-parse):** before filling, run
   `python3 ~/workspace/skills/job-pipeline/scripts/form_cache.py "<application URL>"`.
   It prints the board's cached field mapping (form labels → types/requirements), fetching the public structure only on a cache miss. Reuse that mapping to fill standard fields (name, email, phone, links, education, EEO, work authorization) from `profile.yaml` and `references/standing-answers.md` — do NOT have the LLM re-read and re-parse the entire form on every application. Only genuinely new/unknown fields get individual attention.
2. **Free-text questions via the answer bank:** for every free-text/essay question on the form:
   a. Run `python3 ~/workspace/skills/job-pipeline/scripts/qa_match.py --question "<exact question text>"` against `state/qa_bank.json`.
   b. Score ≥ 0.75 → reuse the banked answer verbatim (still show it in the user review); bump its `use_count` in `state/qa_bank.json`.
   c. No match → draft the answer with the LLM exactly ONCE and show the draft
      verbatim in the user review; only after the user approves that wording,
      append it to `state/qa_bank.json` (`question`, `answer`, `company`,
      `role`, `approved_at`, `use_count: 0`). Open-text questions
      ("why us", motivation, "most interesting paper", etc.) may be freely
      drafted and fact-based fields computed from the profile (e.g. years of
      experience from work history); hard facts (DOB, SSN, test scores,
      citizenship) are never invented.
   Rules: unapproved drafts never enter the bank; sensitive fields (CSRF tokens, tracking IDs, captcha widgets, hidden inputs) are never sent to the LLM and never banked.
3. Fill every field per `references/standing-answers.md`, upload the lane-matched resume + transcript automatically (no permission needed). STOP before Submit.
4. **Email verification codes (on demand only):** some sites require an email verification code during registration or before submission. If a browser fill task parks at such a step, it MUST report back and stop: the site URL, the exact step it is stuck at, and the masked recipient shown on the page (e.g. "code sent to x•••@ucsd.edu"). It must NOT guess the code or proceed.
   The orchestrating agent then performs ONE targeted Gmail lookup: search for the newest message (last ~15 minutes) from that site's sender address, read ONLY that single matching message, take the code, and hand it to the waiting browser task for that step only.
   Hard rules: one code per step, never reuse a code, never write codes to files / memory / state / logs, never scan the inbox for codes speculatively (no background code sweeps). If no fresh matching message exists, tell the browser task to report back (the user may need to trigger a resend). Filling in the code happens during filling; the final Submit still requires the user's explicit approval — see Stage 5.
5. **Site accounts (register; reset the password if the email is taken):** if an
   application site requires a candidate account, create one with the
   application email — the orchestrating agent sets the password and stores it
   in the tracker's `Accounts` tab (never in memory or state files). If the
   email is already registered, run the site's password-reset flow instead
   (reset link via the on-demand Gmail lookup, same one-code rules as step 4)
   and store the new password in `Accounts`. If the reset flow hits a CAPTCHA,
   skip per rule 6.
6. **CAPTCHAs / bot challenges: skip, never solve.** If a fill task hits any
   CAPTCHA, image challenge, or bot-detection wall, it MUST stop and report
   `blocked: captcha — <site URL>`. Do not attempt to solve, do not ask the
   user mid-flow. The role is marked unfillable and reported in the batch
   review with its URL and reason, for the user to apply manually later.
7. **Fill failures are batch-reported:** every role that cannot be completed
   (CAPTCHA, login wall, missing required info, site error) is recorded with
   its posting URL and the exact reason; all of them are listed together in
   the Stage 4 review under "Could not fill".

How the review works depends on `submit_review_mode` in config.yaml:

- **batch** (default): fill ALL selected roles first, then compile everything into one combined review.
- **per_application**: fill ONE role and hand its review to the user immediately (smaller turns; the user can stop early).

### Stage 4 — Approve (user)

- **batch**: the user reviews the combined batch, edits anything, and says "submit all" (or names a subset).
- **per_application**: the user approves each role's review as it arrives ("submit"), then the agent moves to the next role.

### Stage 5 — Submit & log (agent)

Submit each approved application. Capture: confirmation text, timestamp, application/reference ID if shown. Append one row per application to the tracker. Mark each URL `"decision": "applied"` in `state/seen_roles.json`.

Submission is always via the browser flow: fill per Stage 3, park at the final review screen, and click Submit only on the user's explicit "submit" / "submit all". Email verification codes encountered during filling are handled per the Stage 3 step 4 on-demand lookup — they never replace the explicit submit approval. Direct-POST submission was evaluated on 2026-09-29 and rejected — do not build or use HTTP submitters: Greenhouse's documented application POST requires an employer API key (Basic Auth); its hosted form is gated by invisible reCAPTCHA Enterprise (bot-scored submissions get HTTP 428 `captcha-failed` and a two-phase email security-code flow) and uploads resumes via presigned S3, so pure-HTTP submission cannot pass; Ashby's hosted submit needs reCAPTCHA + CSRF with v3 spam scoring; Lever/Workday expose no candidate POST path. The public `?questions=true` job endpoint remains the supported way to read a Greenhouse form's structure (used by `scripts/form_cache.py`).

### Stage 6 — Track (ongoing)

The tracker is the source of truth. Run
`python3 ~/workspace/skills/job-pipeline/scripts/gmail_scan.py`
on a schedule (every 4–6h; silent unless hits) to detect recruiter replies,
interview invitations, and application confirmations: it is watermarked and
incremental, pre-filters without any LLM, and matches senders against the
tracker's company list. Report hits to the user and update the tracker's
Status column.

## Lane matching

- **agent_infra**: agent(s), agentic, infrastructure, infra, platform, inference, serving, kernels, distributed, ML systems
- **ai_cloud**: cloud, backend, platform, kubernetes, distributed systems, microservices
- **genai**: LLM, RAG, chatbot, prompt, copilot, GenAI app (lowest priority)

A role may match multiple lanes; assign the highest-priority matching lane and upload that lane's resume.

## Commands

- "run the pipeline now" → execute Stage 1 immediately in chat.
- "reset pipeline config" → re-run `ONBOARDING.md` (confirm before wiping `profile.yaml` / `config.yaml`).
- "pause pipeline" / "resume pipeline" → disable / enable the discovery crons.

## Operating Rules

1. Never click Submit without the user's explicit "submit" / "submit all".
2. Resume and transcript uploads are routine — never ask permission.
3. Never invent: citizenship, DOB, SSN, test scores, demographic facts. For a required field with no true answer, use "N/A" only with explicit user approval.
4. Education is always entered manually; never trust a site's resume auto-parse.
5. `profile.yaml` and `state/` are personal — never include them when sharing the skill.
6. Dedupe is sacred: check `state/seen_roles.json` before reading any role URL.

## Sharing

Public repo: https://github.com/xf-mike/muse-job-pipeline

To give this to a friend, just send them the link. Their agent clones it into `~/workspace/skills/job-pipeline/` and follows `ONBOARDING.md` with them in conversation. The repo holds only the shareable playbook + templates — `profile.yaml`, `config.yaml`, and `state/` are gitignored, so personal data can never leak into it.

The repo is the source of truth for the playbook: edit `SKILL.md` / `ONBOARDING.md` / `templates/` in `~/workspace/job-pipeline/`, then `git add -A && git commit -m "..." && git push`.
