---
name: "job-pipeline"
description: "Run the automated job-application pipeline: discover new-grad roles on a schedule, shortlist them for the user, fill applications, batch the reviews, submit on approval, and log everything to the tracker."
---

# Job Pipeline

## Purpose

An end-to-end, human-in-the-loop job application loop. Scheduled runs discover roles; the user selects; the agent fills; the user approves; the agent submits and logs. Personal data lives in `profile.yaml` and `state/` — never share those. Shareable parts: `SKILL.md`, `discover.py`, `ONBOARDING.md`, `config.yaml` (as a template), `references/` (including the verified board list `company_boards.json`).

## Workflow

### Stage 1 — Discover (scheduled run, or "run the pipeline now")

1. Run the API-first discovery script (non-interactive — it never prompts):
   `python3 ~/workspace/skills/job-pipeline/discover.py`
   It pulls every board in `references/company_boards.json` through their public JSON APIs (Greenhouse / Ashby — no login needed) plus the LinkedIn guest search API for each lane query in `config.yaml`, then applies programmatic filters in this order: dedupe against `state/seen_roles.json` FIRST (never re-surface a seen URL), `blacklist`, new-grad title signal, lane keywords, `max_post_age_days`, location fit. It writes the compact pre-filtered set to `state/discovery_candidates.json` and prints a one-line summary (boards OK, jobs pulled, candidates, seconds). Typical runtime is 1–3 minutes at ~10x lower token cost than browsing page by page.
2. Read `state/discovery_candidates.json` and judge ONLY those candidates: verify new-grad eligibility, lane fit, and sponsorship plausibility per `config.yaml` and `references/standing-answers.md`. Open a posting page only when a candidate row leaves genuine doubt (a handful at most) — never re-browse the full list.
3. Small web supplement (capped): 2–3 targeted web searches for fresh postings from companies with no public board API (YC Jobs has no stable public API; LinkedIn company pages beyond the guest search). Open at most ~10 pages total, and check `state/seen_roles.json` before opening any URL.
4. Keep the top `discovery.shortlist_size`, ordered by lane priority then fit.
5. Write EVERY judged role (candidates you evaluated + supplement pages you opened) to `state/seen_roles.json`: keepers → `"decision": "shortlisted"`; the rest → `"decision": "rejected"` with a short `"reason"`.
6. Save the shortlist to `state/runs/<YYYY-MM-DD-HHMM>.json`.
7. Shortlist non-empty → present it to the user for selection (company, role, location, lane, link, one-line fit note). Empty → stay silent.
8. Everything in this stage is non-interactive: never ask the user questions mid-run.

To cover a new company, add its board to `references/company_boards.json` (`greenhouse` token or `ashby` org slug, verified live against the public API) — the next run picks it up automatically.

### Stage 2 — Select (user, unless auto_select)

Present the shortlist: company, role, location, lane, link, one-line fit note. The user picks ("all", numbers, or names).

If `auto_select: true` in config.yaml, skip this step: proceed with all shortlisted roles straight to Stage 3. Submit approval in Stage 4 is never skipped.

### Stage 3 — Prepare (agent)

For each selected role: open the application page, fill every field per `references/standing-answers.md`, upload the lane-matched resume + transcript automatically (no permission needed), draft any required free-text answers. STOP before Submit.

How the review works depends on `submit_review_mode` in config.yaml:

- **batch** (default): fill ALL selected roles first, then compile everything into one combined review.
- **per_application**: fill ONE role and hand its review to the user immediately (smaller turns; the user can stop early).

### Stage 4 — Approve (user)

- **batch**: the user reviews the combined batch, edits anything, and says "submit all" (or names a subset).
- **per_application**: the user approves each role's review as it arrives ("submit"), then the agent moves to the next role.

### Stage 5 — Submit & log (agent)

Submit each approved application. Capture: confirmation text, timestamp, application/reference ID if shown. Append one row per application to the tracker. Mark each URL `"decision": "applied"` in `state/seen_roles.json`.

### Stage 6 — Track (ongoing)

The tracker is the source of truth. Optional: daily Gmail scan for recruiter replies → notify the user.

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
