---
name: "job-pipeline"
description: "Run the automated job-application pipeline: discover new-grad roles on a schedule, shortlist them for the user, fill applications, batch the reviews, submit on approval, and log everything to the tracker."
---

# Job Pipeline

## Purpose

An end-to-end, human-in-the-loop job application loop. Scheduled runs discover roles; the user selects; the agent fills; the user approves; the agent submits and logs. Personal data lives in `profile.yaml` and `state/` — never share those. Shareable parts: `SKILL.md`, `ONBOARDING.md`, `config.yaml` (as a template), `references/`.

## Workflow

### Stage 1 — Discover (scheduled run, or "run the pipeline now")

1. Read `config.yaml` and `state/seen_roles.json`.
2. Browse ~`discovery.browse_target` roles across all lanes, highest lane priority first. Sources: LinkedIn Jobs, Ashby / Greenhouse / Workday company boards, YC jobs, aggregators, company career pages.
3. For each candidate URL, check `state/seen_roles.json` FIRST. If seen, skip it entirely — never re-read a seen role (this is the token saver). Also skip companies in the `blacklist` in config.yaml (explicit never-apply list).
4. Filter keepers: not in the `blacklist`, not already applied (check the tracker), posted within `max_post_age_days` (use the source's date filter where available — e.g. LinkedIn's past-week — otherwise read the posting date and drop stale ones; best-effort when a board exposes no date), new-grad eligible per config grad rules, location fit (preferred locations first; `relocation: yes` means other US locations are eligible but deprioritized), sponsorship plausibility.
5. Lane-match each keeper (see Lane matching). Keep the top `discovery.shortlist_size`, ordered by lane priority then fit.
6. Write EVERY browsed role to `state/seen_roles.json`: keepers → `"decision": "shortlisted"`; the rest → `"decision": "rejected"` with a short `"reason"`.
7. Save the shortlist to `state/runs/<YYYY-MM-DD-HHMM>.json`.
8. Shortlist non-empty → report it to the user for selection. Empty → stay silent.

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
