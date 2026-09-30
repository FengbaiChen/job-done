#!/usr/bin/env python3
"""Seed state/seen_roles.json with roles the user already applied to outside
the pipeline (collected at onboarding), so discovery never re-suggests them.

Usage:
    python3 scripts/seed_applied.py --entry "ByteDance|Frontend Engineer" \\
        --entry "TikTok|Backend Engineer|https://www.linkedin.com/jobs/view/123"

Format per --entry: Company|Title[|URL]. URL is optional; when omitted a
synthetic seeded: key is used. Dedup keys off the normalized (company, title)
pair (see discover.job_identity), so future discoveries of the same role are
skipped even under a different URL.
"""
import argparse
import json
import os
import sys

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_PATH = os.path.join(SKILL_DIR, "state", "seen_roles.json")
sys.path.insert(0, SKILL_DIR)
from discover import job_identity  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", action="append", required=True,
                    help='"Company|Title[|URL]" (repeatable)')
    ap.add_argument("--date", default="",
                    help="date applied, YYYY-MM-DD (default: today)")
    args = ap.parse_args()

    from datetime import date
    when = args.date or date.today().isoformat()

    try:
        with open(SEEN_PATH) as f:
            seen = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        seen = {}

    added = 0
    for raw in args.entry:
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) < 2:
            print(f"skip (need Company|Title): {raw}", file=sys.stderr)
            continue
        company, title = parts[0], parts[1]
        url = parts[2] if len(parts) > 2 and parts[2] else None
        rid, comp_norm, title_norm = job_identity(
            {"url": url or "", "company": company, "title": title})
        if url and url in seen:
            continue
        if any(job_identity({"url": u, **r})[1:] == (comp_norm, title_norm)
               for u, r in seen.items()):
            continue  # already covered by an existing entry
        key = url or f"seeded:{comp_norm}:{title_norm}"
        seen[key] = {
            "company": company,
            "title": title,
            "date": when,
            "decision": "applied",
            "note": "seeded at onboarding — user applied outside the pipeline",
        }
        added += 1

    with open(SEEN_PATH, "w") as f:
        json.dump(seen, f, indent=1)
    print(f"seeded {added} entries into state/seen_roles.json")


if __name__ == "__main__":
    main()
