# Standing application answers TEMPLATE

Copy any of these into your live standing-answers file and adjust.
Apply them without asking the user. Values come from `profile.yaml`.
Anything not covered: leave blank if optional; if required and unanswerable,
surface it to the user — never invent.

- **Education (always manual, never auto-parse):** overwrite every auto-filled
  education field with the entries from `profile.yaml`.
- **Work experience:** from profile `work_history` — title, company, start/end
  dates (convert YYYY-MM to the form's format). Location: fill only if known
  in profile; leave blank otherwise — never invent.
- **Date of birth:** from profile (`dob`; or `dob_month`/`dob_day` if the year
  is unknown — never invent the year). Fill month/day or full date as the form
  requires. Never ask the user mid-flow — it was collected at onboarding.
- **School name:** always the full official name from profile (e.g. "University
  of California, San Diego") — never a bare/truncated variant a dropdown suggests.
- **Earliest start date:** from profile (`earliest_start`).
- **Work authorization:** authorized to work in the US = value from profile;
  requires sponsorship now or in the future = value from profile.
- **Relocation:** from profile (`relocation`).
- **Export control / U.S.-person attestation:** pick the truthful option for the
  user's immigration status in profile. Example (F1-OPT, not a citizen/PR):
  "I am not a U.S. person, and I am NOT a current citizen or permanent
  resident of Cuba, Iran, North Korea, or Syria."
- **Interview recording consent:** from profile (`recording_consent`).
- **Graduation-date questions with only future options:** pick the closest
  available slot to the real graduation date in `profile.yaml`. Never leave a
  required one blank.
- **EEO (voluntary):** gender / race / veteran / disability from profile.
- **"How did you hear about us?":** "LinkedIn" free text, or the closest
  job-board option if dropdown-only — never leave a required one blank.
- **Salary expectations:** use the range printed on the job posting. If the
  posting lists none, look up the local median for the role + area (one quick
  search) and use that — never invent a number out of thin air, and never ask
  the user mid-flow.
- **Location fields:** fill from the JOB DESCRIPTION's location(s), not the
  config's preferred list. Willing to relocate = Yes, always. If the JD lists
  several locations and any is in the Bay Area, pick the Bay Area one
  (e.g. San Francisco); rank the rest by city size, largest first.
- **AI-use / AI-assistance disclosure** ("did you use AI to complete this
  application"): answer **No** — all information submitted is the user's own;
  the agent only operates the form, never fabricates content. Exception: if a
  question explicitly prohibits AI-generated content (e.g. "please don't use
  AI" on an essay), do NOT draft it — stop and hand it to the user to write.
- **Cover letter:** none, unless the user says otherwise. Leave blank; if a
  form requires one, stop and report.
- **Free-text "why this company / why this role":** draft from the user's real
  background (profile.yaml work history + projects) AND the job description —
  pick the 1–2 experiences that best match what the JD emphasizes, and say
  plainly why they fit. Bank company-specific drafts with
  `"scope": "company"` so they are never reused for another company. Quote the
  draft verbatim in the review for after-the-fact correction; never ask the
  user for wording mid-run.
- **Preferred name:** from profile if present.
