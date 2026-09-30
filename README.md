# Talos（我不投简历）

*The bronze automaton that applies while you sleep.*

An automated job-application pipeline that runs inside [Muse](https://muse.ai) (Meta's personal AI agent). It discovers job postings matching your profile on a schedule, shortlists the best fits, fills out applications with your standing answers, submits them automatically, and logs everything to a Google Sheet.

The automation level is your call at onboarding: by default the whole shortlist goes straight to form-filling and filled applications are submitted with no review screen — you confirm both switches explicitly after hearing the risks (a submitted application can't be taken back). Prefer a human gate? Turn either off and keep the classic review step.

It is domain-agnostic: lanes, title filters, target companies, and locations are all configuration. It was built and battle-tested on a new-grad software-engineering hunt, which is used as the worked example throughout the docs.

## Why Talos

1. **Fully automatic, by default.** Most tools stop at "here are matching jobs" or "we filled the form — you click submit." Talos goes all the way: discover → judge → fill → **submit** → log, on a schedule, with nobody in the loop. You confirm the standing authorization once at onboarding (risks stated plainly); a submit report lands afterwards, every time. A human review gate is still available — as the opt-out, not the default.
2. **Token-cheap.** Discovery sweeps ~7,000 postings via public JSON APIs with zero browser renders and zero LLM calls — a full run emits about a thousand tokens. Judging is batched 10 roles per call (~10× fewer calls than per-role scoring). Form structures are cached per ATS so a form is never re-parsed; approved answers are banked and reused. The LLM is spent only where judgment is genuinely needed — roughly two orders of magnitude cheaper per posting than render-everything, score-everything alternatives, which is what makes running it 4× a day sane.

> **If you are an AI agent** reading this repo to set this up for your user: open [`ONBOARDING.md`](ONBOARDING.md) and follow it step by step **in conversation with them**. Copy each file in `templates/` to its live filename (`config.template.yaml` → `config.yaml`, etc.) and fill it in from what the user tells you — never invent personal data. The template comments explain every field; treat them as your setup instructions.

## How it works

Six stages, running as a loop:

1. **Discover** — on a schedule (default 4× daily), `discover.py` pulls curated company ATS boards via public job-board APIs plus LinkedIn guest search and community job lists, filters programmatically (dedupe, title include/exclude, lane keywords, recency, location), and the agent judges only the pre-filtered candidates before shortlisting the top N.
2. **Select** — by default the whole judged shortlist proceeds (you confirm this at onboarding; turn `auto_select` off to pick roles yourself).
3. **Prepare** — the agent fills each application completely: standing answers, manually entered education (never trusting resume auto-parse), resume + transcript upload, drafted free-text answers. Free-text answers are reused from a Q&A answer bank when a user-approved answer matches (`scripts/qa_match.py`); the LLM drafts only genuinely new questions, once. Per-ATS form structures are cached (`scripts/form_cache.py`), so a form is never re-parsed from scratch. Email verification codes are fetched on demand only: if a fill task parks at a verification step, the agent does one targeted Gmail lookup for that single fresh message, uses the code once, and never stores it. It stops before Submit.
4. **Approve** — skipped by default (`auto_submit`, confirmed at onboarding). When off: `batch` mode gives one combined review, then "submit all"; `per_application` approves each role as it comes.
5. **Submit & log** — the agent submits per your authorization (standing `auto_submit` or explicit per-run approval), then records the confirmation, timestamp, and any application ID. A submit report is always delivered — logging is never skipped.
6. **Track** — a Google Sheet stays current: every application, its status, and a run history of every discovery run. `scripts/gmail_scan.py` watches the mailbox for recruiter replies and confirmation emails (watermarked, incremental, read-only) and feeds status updates back into the tracker.

Nothing is ever submitted without your authorization — either the standing `auto_submit` you confirmed at onboarding (risks explained), or your explicit per-run approval.

## Quickstart

**If you're the job seeker (30 seconds):** this is a robot that applies to jobs for you while you do anything else. You spend ~10 minutes chatting with your AI assistant: you give it your resumes, your basic info (name, contact, education, work dates), what kinds of roles you want, and where. Then it finds matching postings several times a day, fills out the applications, and submits them — you get a report of everything submitted, plus a Google Sheet tracking every application. Two things it will ask you to decide upfront: whether it should fill every shortlisted role without asking you to pick (default: yes), and whether it should submit without showing you a review screen first (default: yes). The honest risks of full-auto mode: a typo'd field goes out uncaught, and a submitted application can't be taken back. You can turn either switch off and keep a human review step.

**Setup (your AI agent does this with you):**

1. Clone this repo into the Muse workspace at `~/workspace/skills/job-pipeline/`:
   `git clone <this-repo-url> ~/workspace/skills/job-pipeline`
2. Ask your Muse agent to walk through `ONBOARDING.md` with you (~10 minutes, conversational).
3. You'll provide: 1–3 resumes, your profile info (including any companies you've already applied to — so it doesn't re-apply), search lanes, locations, and schedule.
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
| `scripts/gmail_scan.py` | Read-only Gmail scan — recruiter replies + confirmation emails, watermarked and incremental, matched against the tracker |
| `references/board_directory.json` | Recommendation pool: companies with verified public ATS-board APIs, tagged by industry/function — onboarding recommends a brand set from it instead of asking the user to list companies |
| `templates/company_boards.template.json` | Starter board list (~10 generic companies) → becomes the user's `references/company_boards.json` (gitignored, never committed) |
| `references/` | Live per-user files created during setup (standing answers, own board list — never committed) |
| `state/` | Runtime state: dedupe cache + run logs (never committed) |

**Design note:** the dedupe cache (`state/seen_roles.json`) holds every role ever browsed, so `config.yaml` stays small no matter how many thousands of applications you process. The `.gitignore` keeps all personal data out of the repo — what you share is always safe to share.

## Requirements

- The Muse app (the agent runs the pipeline; the repo is its playbook)
- A Google account (required): Gmail for reply tracking and on-demand verification codes, plus Sheets for the tracker (the agent sets both up with you)
- Your resumes as PDFs, and optionally a transcript

## Technical report

[TECHNICAL_REPORT.md](TECHNICAL_REPORT.md) — user guide, core architecture (sources, filtering, form filling, submission gating, email tracking), and a survey of related open-source frameworks with a borrowed-vs-invented breakdown.
