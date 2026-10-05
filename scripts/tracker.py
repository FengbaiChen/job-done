#!/usr/bin/env python3
"""tracker.py — dual-backend application tracker (Google Sheets + Notion).

Zero-LLM logging for the job-pipeline skill: the agent calls this script
instead of hand-editing tracker rows, so tracker writes cost no tokens.

Backends are configured in state/tracker.json (gitignored, never committed):
    {"spreadsheet_id": "<sheets id>", "notion_data_source_id": "collection://..."}

Usage:
  tracker.py init [--sheet-title "Job Applications"]
      --notion-data-source collection://...
    Creates the Sheets spreadsheet on first run (skipped if an id is already
    stored); records both backend ids in state/tracker.json. Notion reuses an
    existing database — pass its collection:// URL (find it on the Notion page).

  tracker.py append --company "Acme" --role "SWE New Grad" [--location ...]
      [--url ...] [--status Applied] [--resume "..."] [--notes "..."]
      [--date 2026-10-05]
    Appends one row to Sheets and one page to Notion (whichever backends are
    configured). Prints a JSON summary; exit code is always 0 so a tracker
    hiccup never breaks a submission run.

  tracker.py update-status --company "Acme" --status Rejected [--role ...]
    Sets Status on the matching row/page in both backends. Used by
    gmail_scan.py — the agent never hand-edits statuses.

Conventions match scripts/gmail_scan.py: subprocess calls to hatch_gws_cli
and notion-cli, stdlib only, never raises on backend errors (reports them in
the JSON output instead).
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import date

SKILL_DIR = os.environ.get(
    "JOB_PIPELINE_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
TRACKER_PATH = os.path.join(SKILL_DIR, "state", "tracker.json")

SHEET_TAB = "Applications"
SHEET_HEADERS = ["Date", "Company", "Role", "Location", "URL",
                 "Status", "Resume", "Notes"]

# Notion status options are fixed on the database; map free text onto them.
NOTION_STATUS_MAP = {
    "applied": "Applied",
    "rejected": "Rejected",
    "interview": "Interviewed",
    "interviewing": "Interviewed",
    "interviewed": "Interviewed",
    "offer": "Offer",
    "accepted": "Accepted",
}


def run_cli(cmd):
    """Run one CLI command; return parsed JSON, raw text, or None. Never raises."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        return {"_error": f"{cmd[0]} failed: {e}"}
    out = (p.stdout or "").strip()
    if not out:
        return {"_error": f"{cmd[0]} empty output",
                "_stderr": (p.stderr or "").strip()[-300:]}
    try:
        return json.loads(out)
    except ValueError:
        return {"_raw": out}


def load_state():
    try:
        with open(TRACKER_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    os.makedirs(os.path.dirname(TRACKER_PATH), exist_ok=True)
    with open(TRACKER_PATH, "w") as f:
        json.dump(st, f, indent=2)


def sheets(params_cmd):
    return run_cli(["hatch_gws_cli", "sheets"] + params_cmd)


def notion(tool, args):
    return run_cli(["notion-cli", "call-tool", "--name", tool,
                    "--arguments-json", json.dumps(args)])


def notion_ok(res):
    """True unless the MCP call clearly errored."""
    if not isinstance(res, dict):
        return False
    if res.get("_error") or res.get("_raw"):
        return False
    inner = res.get("result", {})
    content = (inner.get("content") or [{}])[0].get("text", "")
    return "Input validation error" not in content and not inner.get("isError")


# ---------------------------------------------------------------- init

def cmd_init(args):
    st = load_state()
    out = {}
    if not st.get("spreadsheet_id"):
        res = sheets(["spreadsheets", "create", "--params",
                      json.dumps({"properties": {"title": args.sheet_title}})])
        sid = (res or {}).get("spreadsheetId")
        if sid:
            st["spreadsheet_id"] = sid
            sheets(["spreadsheets", "values", "update", "--params",
                    json.dumps({"spreadsheetId": sid,
                                "range": f"{SHEET_TAB}!A1:H1",
                                "valueInputOption": "USER_ENTERED",
                                "values": [SHEET_HEADERS]})])
            out["sheets"] = {"spreadsheet_id": sid}
        else:
            out["sheets"] = {"error": res}
    else:
        out["sheets"] = {"spreadsheet_id": st["spreadsheet_id"],
                         "note": "already configured"}
    if args.notion_data_source:
        st["notion_data_source_id"] = args.notion_data_source
    out["notion"] = ({"data_source": st["notion_data_source_id"]}
                     if st.get("notion_data_source_id")
                     else {"note": "not configured; pass --notion-data-source"})
    save_state(st)
    print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- append

def notion_props(a):
    # SQLite-values format (see notion-create-pages schema): plain strings,
    # dates split into date:<name>:start / :is_datetime, selects as arrays.
    props = {"Company": a.company}
    if a.role:
        props["Position"] = a.role
    props["date:Application Date:start"] = a.date
    props["date:Application Date:is_datetime"] = 0
    if a.url:
        props["Reference Link"] = a.url
    status = NOTION_STATUS_MAP.get((a.status or "").lower(), "Applied")
    props["Status"] = [status]
    return props


def notion_body(a):
    bits = []
    if a.location:
        bits.append(f"Location: {a.location}")
    if a.resume:
        bits.append(f"Resume: {a.resume}")
    if a.notes:
        bits.append(a.notes)
    return "\n".join(bits)


def cmd_append(args):
    st = load_state()
    out = {}
    row = [args.date, args.company, args.role or "", args.location or "",
           args.url or "", args.status or "Applied", args.resume or "",
           args.notes or ""]
    sid = st.get("spreadsheet_id")
    if sid:
        res = sheets(["spreadsheets", "values", "append", "--params",
                      json.dumps({"spreadsheetId": sid,
                                  "range": f"{SHEET_TAB}!A:H",
                                  "valueInputOption": "USER_ENTERED",
                                  "values": [row]})])
        out["sheets"] = "ok" if not (res or {}).get("_error") else {"error": res}
    else:
        out["sheets"] = {"error": "no spreadsheet_id; run init first"}
    ds = st.get("notion_data_source_id")
    if ds:
        page = {"properties": notion_props(args)}
        body = notion_body(args)
        if body:
            page["content"] = body
        res = notion("notion-create-pages",
                     {"parent": {"data_source_id": ds}, "pages": [page]})
        out["notion"] = "ok" if notion_ok(res) else {"error": res}
    else:
        out["notion"] = {"note": "not configured"}
    print(json.dumps(out, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- update-status

def norm(text):
    return "".join(c for c in (text or "").lower() if c.isalnum())


def cmd_update_status(args):
    st = load_state()
    out = {}
    sid = st.get("spreadsheet_id")
    if sid:
        res = sheets(["spreadsheets", "values", "get", "--params",
                      json.dumps({"spreadsheetId": sid,
                                  "range": f"{SHEET_TAB}!A2:H"})])
        rows = (res or {}).get("values", []) if isinstance(res, dict) else []
        target = None
        want_c, want_r = norm(args.company), norm(args.role)
        for i, r in enumerate(rows):
            if len(r) < 2:
                continue
            if want_c and want_c not in norm(r[1]):
                continue
            if want_r and want_r not in norm(r[2] if len(r) > 2 else ""):
                continue
            target = i + 2  # 1-based + header row
            break
        if target:
            res2 = sheets(["spreadsheets", "values", "update", "--params",
                           json.dumps({"spreadsheetId": sid,
                                       "range": f"{SHEET_TAB}!F{target}",
                                       "valueInputOption": "USER_ENTERED",
                                       "values": [[args.status]]})])
            out["sheets"] = ("ok" if not (res2 or {}).get("_error")
                             else {"error": res2})
        else:
            out["sheets"] = {"note": "no matching row"}
    else:
        out["sheets"] = {"error": "no spreadsheet_id; run init first"}
    ds = st.get("notion_data_source_id")
    if ds:
        q = (f"SELECT id, Company, Position FROM \"{ds}\" "
             f"WHERE Company LIKE ? LIMIT 5")
        res = notion("notion-query-data-sources",
                     {"data": {"data_source_urls": [ds], "query": q,
                               "params": [f"%{args.company}%"]}})
        page_id = None
        try:
            rows = json.loads(
                res["result"]["content"][0]["text"])["results"]
            want_r = norm(args.role)
            for r in rows:
                if want_r and want_r not in norm(r.get("Position")):
                    continue
                page_id = r["id"]
                break
        except (KeyError, ValueError, TypeError):
            rows = []
        if page_id:
            status = NOTION_STATUS_MAP.get(args.status.lower(), args.status)
            res2 = notion("notion-update-page",
                          {"command": "update_properties",
                           "page_id": page_id,
                           "properties": {"Status": [status]}})
            out["notion"] = "ok" if notion_ok(res2) else {"error": res2}
        else:
            out["notion"] = {"note": "no matching page"}
    else:
        out["notion"] = {"note": "not configured"}
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="Dual-backend application tracker.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init")
    p.add_argument("--sheet-title", default="Job Applications")
    p.add_argument("--notion-data-source", default="")

    p = sub.add_parser("append")
    p.add_argument("--company", required=True)
    p.add_argument("--role", default="")
    p.add_argument("--location", default="")
    p.add_argument("--url", default="")
    p.add_argument("--status", default="Applied")
    p.add_argument("--resume", default="")
    p.add_argument("--notes", default="")
    p.add_argument("--date", default=str(date.today()))

    p = sub.add_parser("update-status")
    p.add_argument("--company", required=True)
    p.add_argument("--role", default="")
    p.add_argument("--status", required=True)

    args = ap.parse_args()
    try:
        if args.cmd == "init":
            return cmd_init(args)
        if args.cmd == "append":
            return cmd_append(args)
        return cmd_update_status(args)
    except Exception as e:  # never break the pipeline run
        print(json.dumps({"error": f"{type(e).__name__}: {e}"}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
