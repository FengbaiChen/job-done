# Muse Job Pipeline

An automated job-application pipeline that runs inside [Muse](https://muse.ai) (Meta's personal AI agent). It discovers new-grad software engineering roles on a schedule, shortlists the best fits, fills out applications with your standing answers, waits for your approval before anything is submitted, and logs everything to a Google Sheet.

> **If you are an AI agent** reading this repo to set this up for your user: open [`ONBOARDING.md`](ONBOARDING.md) and follow it step by step **in conversation with them**. Copy each file in `templates/` to its live filename (`config.template.yaml` → `config.yaml`, etc.) and fill it in from what the user tells you — never invent personal data. The template comments explain every field; treat them as your setup instructions.

## How it works

Six stages, running as a loop:

1. **Discover** — on a schedule (default 4× daily), `discover.py` pulls ~40 curated company boards via public job-board APIs plus LinkedIn guest search, filters programmatically (dedupe, new-grad signal, lane keywords, recency, location), and the agent judges only the pre-filtered candidates before shortlisting the top 10.
2. **Select** — you pick which roles to pursue.
3. **Prepare** — the agent fills each application completely: standing answers, manually entered education (never trusting resume auto-parse), resume + transcript upload, drafted free-text answers. Free-text answers are reused from a Q&A answer bank when a user-approved answer matches (`scripts/qa_match.py`); the LLM drafts only genuinely new questions, once. Per-ATS form structures are cached (`scripts/form_cache.py`), so a form is never re-parsed from scratch. It stops before Submit.
4. **Approve** — you review. `batch` mode: one combined review, then "submit all". `per_application` mode: approve each role as it comes.
5. **Submit & log** — the agent submits only on your explicit approval, then records the confirmation, timestamp, and any application ID.
6. **Track** — a Google Sheet stays current: every application, its status, and a run history of every discovery run.

Nothing is ever submitted without the user explicitly saying **"submit"**.

## Quickstart

1. Clone this repo into the Muse workspace at `~/workspace/skills/job-pipeline/`:
   `git clone <this-repo-url> ~/workspace/skills/job-pipeline`
2. Ask your Muse agent to walk through `ONBOARDING.md` with you (~10 minutes, conversational).
3. You'll provide: 1–3 resumes, your profile info, search lanes, locations, and schedule.
4. The agent creates your tracker sheet, activates the discovery schedule, and you're live.

## Everyday commands

Once set up, just talk to your agent:

- `"run the pipeline now"` — discovery on demand
- `"pause pipeline"` / `"resume pipeline"`
- `"reset pipeline config"` — re-do setup (confirms first)

## Repo layout

| Path | What it is |
|---|---|
| `README.md` | This file — human + agent entry point |
| `SKILL.md` | The full pipeline playbook the agent follows |
| `ONBOARDING.md` | Guided setup script (agent-led conversation) |
| `templates/config.template.yaml` | Annotated settings template → becomes `config.yaml` |
| `templates/profile.template.yaml` | Annotated personal-data template → becomes `profile.yaml` |
| `templates/standing-answers.template.md` | Form-filling rules template → becomes `references/standing-answers.md` |
| `templates/qa_bank.template.json` | Q&A answer-bank template → becomes `state/qa_bank.json` (seeded from standing answers, grows with approvals) |
| `scripts/qa_match.py` | Answer-bank matcher — reuses user-approved free-text answers, LLM drafts only new questions |
| `scripts/form_cache.py` | Per-ATS application-form structure cache — forms are never re-parsed from scratch |
| `references/` | Live standing answers (created during setup, never committed) |
| `state/` | Runtime state: dedupe cache + run logs (never committed) |

**Design note:** the dedupe cache (`state/seen_roles.json`) holds every role ever browsed, so `config.yaml` stays small no matter how many thousands of applications you process. The `.gitignore` keeps all personal data out of the repo — what you share is always safe to share.

## Requirements

- The Muse app (the agent runs the pipeline; the repo is its playbook)
- A Google account, if you want the Sheets tracker (the agent sets it up for you)
- Your resumes as PDFs, and optionally a transcript
