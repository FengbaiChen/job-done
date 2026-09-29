# Standing application answers TEMPLATE

Copy any of these into your live standing-answers file and adjust.
Apply them without asking the user. Values come from `profile.yaml`.
Anything not covered: leave blank if optional; if required and unanswerable,
surface it to the user — never invent.

- **Education (always manual, never auto-parse):** overwrite every auto-filled
  education field with the entries from `profile.yaml`.
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
- **"How did you hear about us?":** "Job board" free text, or "Other" if
  dropdown-only.
- **Cover letter:** none, unless the user says otherwise. Leave blank; if a
  form requires one, stop and report.
- **Free-text "why this company / why this role":** stop and report — the user
  approves the text first (or draft it and include it in the batch review for
  approval).
- **Preferred name:** from profile if present.
