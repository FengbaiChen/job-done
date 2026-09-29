#!/usr/bin/env python3
"""
API-first Stage-1 discovery for the job-pipeline skill.

Pulls job listings from public job-board JSON APIs (Greenhouse, Ashby) plus
the LinkedIn guest search API, applies programmatic filters
(dedupe vs state/seen_roles.json FIRST, blacklist, new-grad signal,
lane keywords, recency, location), and writes a compact candidate file for
the agent to judge. The agent judges ONLY these candidates instead of
browsing ~50 pages one by one.

Non-interactive: safe to run from cron workers. Never prompts.

Usage:
    python3 discover.py [--dry-run] [--limit N] [--max-candidates N] [--li-pages N]

Outputs (real runs only; --dry-run writes nothing):
    state/discovery_candidates.json  (compact candidate list for LLM judging)
    state/discovery_watermark.json   ({"last_successful_run": ISO ts, "runs": n})
    state/job_presence.json          ({url: {"run": n, "run_id": "YYYY-MM-DD-HHMM"}})
    state/seen_roles.json            (updated in place: absent-3-runs jobs -> "closed")
    state/source_health.json         (per-source pulled history + status)
    stdout: one-line summary (boards, jobs pulled, filtered, candidates, seconds,
            watermark run counter, newly-closed count, per-source health)
"""
import argparse
import html as htmlmod
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from datetime import time as dtime

SKILL_DIR = os.environ.get("JOB_PIPELINE_DIR", "/home/hatch/workspace/skills/job-pipeline")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"}
HTTP_TIMEOUT = 20

# ---------------------------------------------------------------- config ---
def load_config():
    import yaml
    with open(f"{SKILL_DIR}/config.yaml") as f:
        return yaml.safe_load(f)

def load_boards():
    with open(f"{SKILL_DIR}/references/company_boards.json") as f:
        return json.load(f)["boards"]

def load_seen():
    try:
        with open(f"{SKILL_DIR}/state/seen_roles.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# --------------------------------------------------------------- fetchers ---
def http_get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def http_get_text(url, timeout=HTTP_TIMEOUT):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")

def fetch_greenhouse(token, limit):
    """Returns list of normalized job dicts."""
    data = http_get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs")
    out = []
    for j in data.get("jobs", [])[:limit]:
        loc = (j.get("location") or {}).get("name", "")
        depts = ", ".join(d.get("name", "") for d in (j.get("departments") or []))
        out.append({
            "company": j.get("company_name", ""),
            "title": j.get("title", "").strip(),
            "location": loc,
            "url": j.get("absolute_url", ""),
            "date": (j.get("first_published") or "")[:10],
            "snippet": depts,
            "source": "greenhouse",
        })
    return out

def fetch_ashby(token, limit):
    data = http_get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}")
    out = []
    for j in data.get("jobs", [])[:limit]:
        if not j.get("isListed", True):
            continue
        loc = j.get("location") or ""
        if j.get("isRemote"):
            loc = "Remote" + (f", {loc}" if loc else "")
        dept = j.get("department") or ""
        team = j.get("team") or ""
        snippet = " / ".join(s for s in (dept, team) if s)
        out.append({
            "company": "",
            "title": (j.get("title") or "").strip(),
            "location": loc,
            "url": j.get("jobUrl", ""),
            "date": (j.get("publishedAt") or "")[:10],
            "snippet": snippet,
            "source": "ashby",
            "board_token": token,
        })
    return out

# LinkedIn guest search: HTML cards, ~10 per page, paginate with start=.
# Parsing splits the page into per-card chunks FIRST (cheap split on the card
# urn), then applies small field regexes per chunk — this avoids catastrophic
# backtracking on large or oddly-structured pages.
_LI_URN = re.compile(r'data-entity-urn="urn:li:jobPosting:(\d+)"')
_LI_TITLE = re.compile(r'<h3 class="base-search-card__title">\s*(.*?)\s*</h3>', re.S)
_LI_COMPANY = re.compile(r'<h4 class="base-search-card__subtitle">.*?<a[^>]*>\s*(.*?)\s*</a>', re.S)
_LI_LOC = re.compile(r'<span class="job-search-card__location">\s*(.*?)\s*</span>', re.S)
_LI_TIME = re.compile(r'<time class="job-search-card__listdate"[^>]*>', re.S)
_LI_DT = re.compile(r'datetime="([^"]*)"')
_LI_REL = re.compile(r"(\d+)\s+(hour|day|week|month)s?\s+ago", re.I)
_LI_TAG = re.compile(r"<[^>]+>")

def _clean(s):
    return htmlmod.unescape(_LI_TAG.sub("", s or "")).strip()

def _li_date(dt_attr, time_inner):
    if dt_attr and re.match(r"\d{4}-\d{2}-\d{2}", dt_attr):
        return dt_attr[:10]
    m = _LI_REL.search(time_inner or "")
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"hour": 0, "day": n, "week": 7 * n, "month": 30 * n}[unit]
        return date.fromordinal(date.today().toordinal() - days).isoformat()
    return ""

def _li_age_hours(dt_attr, time_inner):
    """Age of a LinkedIn posting in hours — lenient (minimum possible age).

    Relative times ("X hours/days ago") convert directly to hours. A bare ISO
    date is day-granularity, so assume end-of-day (youngest possible posting
    time). Returns None when nothing is parseable (caller keeps the posting).
    """
    now = datetime.now()
    m = _LI_REL.search(time_inner or "")
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        return float({"hour": n, "day": n * 24, "week": n * 7 * 24,
                      "month": n * 30 * 24}[unit])
    if dt_attr and re.match(r"\d{4}-\d{2}-\d{2}", dt_attr):
        d = datetime.fromisoformat(dt_attr[:10]).date()
        return max(0.0, (now - datetime.combine(d, dtime.max)).total_seconds() / 3600)
    return None


def _job_age_hours(job):
    """Age of any normalized job dict in hours (lenient), or None if unknown.

    LinkedIn jobs carry a precise ``age_hours``; board jobs fall back to their
    ISO date assuming end-of-day (minimum possible age). Unknown -> None.
    """
    age_h = job.get("age_hours")
    if age_h is not None:
        return float(age_h)
    d = parse_date(job.get("date", ""))
    if d is None:
        return None
    now = datetime.now()
    return max(0.0, (now - datetime.combine(d, dtime.max)).total_seconds() / 3600)


def _parse_li_cards(page_html):
    """Normalized job dicts from one LinkedIn guest-search page."""
    if len(page_html) > 300_000:  # poisoned/oversize page guard
        return []
    starts = [m.start() for m in _LI_URN.finditer(page_html)]
    out = []
    for i, s in enumerate(starts):
        chunk = page_html[s:starts[i + 1] if i + 1 < len(starts) else s + 20000]
        m_id = _LI_URN.match(page_html, s)
        m_t = _LI_TITLE.search(chunk)
        m_c = _LI_COMPANY.search(chunk)
        m_l = _LI_LOC.search(chunk)
        m_tm = _LI_TIME.search(chunk)
        if not (m_id and m_t and m_c and m_l):
            continue
        dt_m = _LI_DT.search(m_tm.group(0)) if m_tm else None
        dt = dt_m.group(1) if dt_m else ""
        t_end = chunk.find("</time>", m_tm.end()) if m_tm else -1
        inner = chunk[m_tm.end():t_end] if m_tm and t_end > 0 else ""
        out.append({
            "company": _clean(m_c.group(1)),
            "title": _clean(m_t.group(1)),
            "location": _clean(m_l.group(1)),
            "url": f"https://www.linkedin.com/jobs/view/{m_id.group(1)}",
            "date": _li_date(dt, inner),
            "age_hours": _li_age_hours(dt, inner),
            "snippet": "",
            "source": "linkedin",
        })
    return out

def fetch_linkedin(query, pages):
    """Best-effort: skip the whole source on HTTP/parse trouble."""
    out = []
    for p in range(pages):
        q = urllib.parse.urlencode({
            "keywords": query, "location": "United States",
            "start": p * 10,
        })
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?{q}"
        page_html = http_get_text(url, timeout=12)  # short timeout: never let LI stall the run
        out.extend(_parse_li_cards(page_html))
    return out

# ------------------------------------------------- incremental state ---
# Watermark + presence tracking let consecutive runs act incrementally and
# detect silently-closed postings (ATS boards drop closed jobs without notice).
#   state/discovery_watermark.json : {"last_successful_run": "<ISO ts>", "runs": n}
#   state/job_presence.json        : {url: {"run": n, "run_id": "YYYY-MM-DD-HHMM"}}
# A job absent for ABSENT_RUNS_TO_CLOSE consecutive runs whose seen_roles
# decision is not applied/shortlisted is marked "closed" ("no longer listed").
ABSENT_RUNS_TO_CLOSE = 3

def load_watermark():
    try:
        with open(f"{SKILL_DIR}/state/discovery_watermark.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_successful_run": None, "runs": 0}

def load_presence():
    try:
        with open(f"{SKILL_DIR}/state/job_presence.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def last_seen_run(entry):
    """Normalize a presence entry to its run counter (supports int or dict)."""
    if isinstance(entry, dict):
        return entry.get("run", 0)
    return entry or 0

def close_absent_jobs(presence, seen, current_n):
    """Mark jobs absent for ABSENT_RUNS_TO_CLOSE consecutive runs as closed.

    Never touches 'applied' or 'shortlisted' decisions (the user may still act
    on those). Only marks URLs already present in seen_roles.json. Mutates
    `seen` in place. Returns the number of newly-closed entries.
    """
    closed = 0
    for url, entry in presence.items():
        if current_n - last_seen_run(entry) < ABSENT_RUNS_TO_CLOSE:
            continue
        rec = seen.get(url)
        if not rec:
            continue  # pulled but never surfaced to the agent; nothing to mark
        if rec.get("decision") in ("applied", "shortlisted", "closed"):
            continue
        rec["decision"] = "closed"
        rec["reason"] = "no longer listed"
        closed += 1
    return closed

# ------------------------------------------------- source health -----
# Per-source liveness monitoring: every run records, for each of the 40 ATS
# boards plus LinkedIn (aggregated), how many parseable jobs it returned and
# how fresh the newest one was. Anomalies (fetch failure, zero parseable jobs,
# volume collapse vs history, or a newest item older than STALE_WARN_HOURS)
# are reported in the one-line summary so the scheduled run can alert the user
# instead of staying silent on an empty shortlist.
HEALTH_HIST_LEN = 10   # pulled-count history kept per source
HEALTH_MIN_HIST = 3    # runs of history before volume-drop alerts fire
STALE_WARN_HOURS = 168  # newest item older than this (7d) -> stale warning

def load_health():
    try:
        with open(f"{SKILL_DIR}/state/source_health.json") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

def eval_source_health(name, pulled, newest_age_h, failed, hist):
    """(status, note); status in ok/warn/fail. Lenient by design: needs
    repeated evidence (history) before crying volume-drop. The staleness check
    applies to LinkedIn only — small ATS boards legitimately go months without
    a new posting, so "oldest newest-item" is not a breakage signal for them."""
    if failed:
        return "fail", f"fetch failed ({failed})"
    if pulled == 0:
        return "warn", "0 parseable jobs returned"
    if name == "linkedin" and newest_age_h is not None and newest_age_h > STALE_WARN_HOURS:
        return "warn", f"newest item {newest_age_h:.0f}h old — LinkedIn may be serving stale data"
    if len(hist) >= HEALTH_MIN_HIST:
        med = _median(hist)
        if med > 0 and pulled < 0.25 * med:
            return "warn", f"volume drop: {pulled} vs median {med:.0f}"
    return "ok", ""

# ---------------------------------------------------------------- filters ---
NEWGRAD = re.compile(
    r"new[\s\-]?grad|entry[\s\-]?level|university grad|early career"
    r"|\bjunior\b|\b2026\b|\b2027\b|newgrad|recent grad", re.I)

# Lane keywords derived from SKILL.md "Lane matching" + config lane queries.
LANE_KEYWORDS = {
    "agent_infra": ["agent", "agentic", "inference", "serving", "infra",
                    "kernel", "distributed", "ml system", "machine learning",
                    "llm", "foundation model", "training", "gpu", "cuda",
                    "compiler", "runtime", "orchestration"],
    "ai_cloud": ["backend", "cloud", "platform", "kubernetes", "k8s",
                 "distributed", "microservice", "devops", "sre", "network",
                 "storage", "database"],
    "genai": ["llm", "rag", "chatbot", "prompt", "copilot", "genai",
              "generative ai", "ai engineer", "ai application", "voice ai",
              "conversational"],
}

def lane_of(text, lanes_by_priority):
    for lane in lanes_by_priority:
        for kw in LANE_KEYWORDS.get(lane, []):
            if re.search(r"\b" + re.escape(kw) + r"\b", text, re.I):
                return lane
    return None

_US_STATE = re.compile(r",\s*[A-Z]{2}\b")
_US_METROS = {
    "san francisco bay area", "san francisco", "new york", "new york city",
    "seattle", "austin", "boston", "chicago", "los angeles", "san diego",
    "denver", "atlanta", "washington", "portland", "san jose", "mountain view",
    "palo alto", "sunnyvale", "santa clara", "bellevue", "redmond", "irvine",
    "santa monica", "culver city", "menlo park", "cambridge",
}

def loc_score(loc):
    """2 = remote/CA (preferred), 1 = other US, 0 = non-US (skip)."""
    l = (loc or "").lower()
    if "remote" in l:
        return 2
    if re.search(r",\s*ca\b", l) or "california" in l:
        return 2
    if "united states" in l or _US_STATE.search(loc or ""):
        return 1
    if any(m in l for m in _US_METROS):
        return 1
    return 0

def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None

# -------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="pull + filter, print summary, write nothing")
    ap.add_argument("--limit", type=int, default=10**9, help="max jobs processed per board (testing)")
    ap.add_argument("--max-candidates", type=int, default=None,
                        help="max candidates emitted (default: discovery.browse_target from config)")
    ap.add_argument("--li-pages", type=int, default=2, help="LinkedIn pages per query (10 cards each)")
    args = ap.parse_args()
    t0 = time.time()

    cfg = load_config()
    boards = load_boards()
    seen = load_seen()

    lanes_cfg = sorted(cfg.get("lanes", []), key=lambda l: l.get("priority", 99))
    lanes_by_priority = [l["name"] for l in lanes_cfg]
    queries = [q for l in lanes_cfg for q in l.get("queries", [])]
    max_age = cfg.get("max_post_age_days", 7)
    blacklist = [b.lower() for b in (cfg.get("blacklist", {}) or {}).get("companies", [])]

    stats = {"boards_ok": 0, "boards_failed": 0, "pulled": 0,
             "deduped": 0, "candidates": 0, "li_ok": 0, "li_failed": 0}
    failed_boards = []
    seen_urls = set()  # in-run dedupe: same posting can surface via multiple queries
    pulled_urls = []   # every job URL fetched this run (for presence tracking)
    pool = []
    src_stats = {}     # source name -> {"pulled", "newest_age_h", "failed"}

    def track_source(name, jobs, failed=None):
        ages = [_job_age_hours(j) for j in jobs]
        ages = [a for a in ages if a is not None]
        src_stats[name] = {"pulled": len(jobs),
                           "newest_age_h": min(ages) if ages else None,
                           "failed": failed}

    def consider(job, board_company=""):
        stats["pulled"] += 1
        url = job.get("url", "")
        if not url:
            return
        pulled_urls.append(url)  # presence: upserted even if filtered/deduped below
        # (a) dedupe FIRST — never re-read a seen URL
        if url in seen or url in seen_urls:
            stats["deduped"] += 1
            return
        seen_urls.add(url)
        company = job.get("company") or board_company
        # (b) blacklist
        if any(b in company.lower() for b in blacklist):
            return
        text = f"{job.get('title','')} {job.get('snippet','')}"
        # internships are not new-grad full-time roles
        if re.search(r"\bintern(ship)?s?\b", job.get("title", ""), re.I):
            return
        # (c) new-grad signal
        if not NEWGRAD.search(text):
            return
        # (d) lane keyword match
        lane = lane_of(text, lanes_by_priority)
        if not lane:
            return
        # (e) recency — hour precision, lenient: LinkedIn relative times are
        # exact; day-granularity dates assume end-of-day (minimum possible age);
        # unknown dates are kept (best-effort, never drop on missing data).
        max_age_hours = max_age * 24
        age_h = _job_age_hours(job)
        if age_h is not None and age_h > max_age_hours:
            return
        # (f) location
        ls = loc_score(job.get("location", ""))
        if ls == 0:
            return
        pool.append({
            "company": company, "title": job["title"],
            "location": job.get("location", ""), "url": url,
            "date": job.get("date", ""), "lane": lane,
            "snippet": (job.get("snippet") or "")[:160],
            "source": job.get("source", ""),
            "_loc": ls, "_date": job.get("date", ""),
        })

    def fetch_board(b):
        # returns (board, jobs, error) — run in worker threads, no shared mutation
        try:
            if b["platform"] == "greenhouse":
                return b, fetch_greenhouse(b["token"], args.limit), None
            return b, fetch_ashby(b["token"], args.limit), None
        except Exception as e:  # noqa: BLE001 - best-effort per board
            return b, [], e

    with ThreadPoolExecutor(max_workers=10) as ex:
        for b, jobs, err in ex.map(fetch_board, boards):
            src_name = f"board:{b['company']}"
            if err is not None:
                stats["boards_failed"] += 1
                failed_boards.append(f"{b['company']}({type(err).__name__})")
                track_source(src_name, [], failed=type(err).__name__)
                continue
            stats["boards_ok"] += 1
            track_source(src_name, jobs)
            for j in jobs:
                consider(j, board_company=b["company"])

    # LinkedIn guest API — supplemental, best-effort per query (threaded lightly;
    # any single query failing never affects the rest of the run)
    def fetch_li_query(q):
        try:
            return q, fetch_linkedin(q, args.li_pages), None
        except Exception as e:  # noqa: BLE001
            return q, [], e

    with ThreadPoolExecutor(max_workers=4) as ex:
        li_jobs_all = []
        for q, jobs, err in ex.map(fetch_li_query, queries):
            if err is not None:
                stats["li_failed"] += 1
                continue
            stats["li_ok"] += 1
            li_jobs_all.extend(jobs)
            for j in jobs:
                consider(j)
    # LinkedIn tracked as one aggregate source (per-query volumes are too small
    # for stable anomaly detection).
    li_failed = None
    if stats["li_failed"] and not li_jobs_all:
        li_failed = f"{stats['li_failed']}/{stats['li_ok']+stats['li_failed']} queries failed"
    track_source("linkedin", li_jobs_all, failed=li_failed)

    prio = {name: i for i, name in enumerate(lanes_by_priority)}

    def sort_key(c):
        d = parse_date(c["_date"])
        return (prio.get(c["lane"], 99), -c["_loc"], -(d.toordinal() if d else 0))
    pool.sort(key=sort_key)

    candidates = [{k: c[k] for k in ("company", "title", "location", "url", "date", "lane", "snippet", "source")}
                  for c in pool[:args.max_candidates or cfg.get("discovery", {}).get("browse_target", 60)]]
    stats["candidates"] = len(candidates)
    elapsed = time.time() - t0

    # Incremental state: watermark, presence upsert, absence->closed marking.
    # Written only on real runs; --dry-run touches nothing on disk.
    run_id = datetime.now().strftime("%Y-%m-%d-%H%M")
    watermark = load_watermark()
    presence = load_presence()
    run_n = watermark.get("runs", 0)
    closed_marked = 0
    if not args.dry_run:
        run_n += 1
        for u in pulled_urls:
            presence[u] = {"run": run_n, "run_id": run_id}
        closed_marked = close_absent_jobs(presence, seen, run_n)
        watermark = {"last_successful_run": datetime.now().isoformat(timespec="seconds"),
                     "runs": run_n}
        with open(f"{SKILL_DIR}/state/discovery_watermark.json", "w") as f:
            json.dump(watermark, f, indent=1)
        with open(f"{SKILL_DIR}/state/job_presence.json", "w") as f:
            json.dump(presence, f, indent=1)
        with open(f"{SKILL_DIR}/state/seen_roles.json", "w") as f:
            json.dump(seen, f, indent=1)
        with open(f"{SKILL_DIR}/state/discovery_candidates.json", "w") as f:
            json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                       "candidates": candidates}, f, indent=1)

    # Source health: evaluate every run; persist only on real runs.
    health = load_health()
    health_alerts = []
    for name, s in src_stats.items():
        entry = health.get(name, {"pulled_hist": []})
        hist = entry.get("pulled_hist", [])
        status, note = eval_source_health(name, s["pulled"], s["newest_age_h"],
                                          s["failed"], hist)
        if not args.dry_run:
            hist = (hist + [s["pulled"]])[-HEALTH_HIST_LEN:]
            health[name] = {"pulled_hist": hist, "last_pulled": s["pulled"],
                            "last_newest_age_h": s["newest_age_h"],
                            "last_run": run_id, "status": status, "note": note}
        if status != "ok":
            health_alerts.append(f"{name}: {note}")
    if not args.dry_run:
        with open(f"{SKILL_DIR}/state/source_health.json", "w") as f:
            json.dump(health, f, indent=1)
    n_src = len(src_stats)
    n_ok = n_src - len(health_alerts)
    health_tok = f"ok({n_ok}/{n_src})" if not health_alerts else f"WARN({len(health_alerts)})"

    print(f"boards_ok={stats['boards_ok']} boards_failed={stats['boards_failed']} "
          f"li_queries_ok={stats['li_ok']}/{stats['li_ok']+stats['li_failed']} "
          f"jobs_pulled={stats['pulled']} deduped_skipped={stats['deduped']} "
          f"candidates={stats['candidates']} elapsed_s={elapsed:.1f} "
          f"watermark={run_n} closed_marked={closed_marked} health={health_tok}")
    if failed_boards:
        print("failed_boards: " + ", ".join(failed_boards[:10]))
    if health_alerts:
        print("health_alerts: " + "; ".join(health_alerts[:10]))
    if args.dry_run:
        for c in candidates[:15]:
            print(f"  - [{c['lane']}] {c['company']} — {c['title']} ({c['location']}, {c['date']})")

if __name__ == "__main__":
    main()
