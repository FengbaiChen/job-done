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

Outputs:
    state/discovery_candidates.json  (compact candidate list for LLM judging)
    stdout: one-line summary (boards, jobs pulled, filtered, candidates, seconds)
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
    today = date.today()

    stats = {"boards_ok": 0, "boards_failed": 0, "pulled": 0,
             "deduped": 0, "candidates": 0, "li_ok": 0, "li_failed": 0}
    failed_boards = []
    seen_urls = set()  # in-run dedupe: same posting can surface via multiple queries
    pool = []

    def consider(job, board_company=""):
        stats["pulled"] += 1
        url = job.get("url", "")
        if not url:
            return
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
        # (e) recency (best-effort: unknown date -> keep)
        d = parse_date(job.get("date", ""))
        if d and (today - d).days > max_age:
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
            if err is not None:
                stats["boards_failed"] += 1
                failed_boards.append(f"{b['company']}({type(err).__name__})")
                continue
            stats["boards_ok"] += 1
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
        for q, jobs, err in ex.map(fetch_li_query, queries):
            if err is not None:
                stats["li_failed"] += 1
                continue
            stats["li_ok"] += 1
            for j in jobs:
                consider(j)

    prio = {name: i for i, name in enumerate(lanes_by_priority)}

    def sort_key(c):
        d = parse_date(c["_date"])
        return (prio.get(c["lane"], 99), -c["_loc"], -(d.toordinal() if d else 0))
    pool.sort(key=sort_key)

    candidates = [{k: c[k] for k in ("company", "title", "location", "url", "date", "lane", "snippet", "source")}
                  for c in pool[:args.max_candidates or cfg.get("discovery", {}).get("browse_target", 60)]]
    stats["candidates"] = len(candidates)
    elapsed = time.time() - t0

    if not args.dry_run:
        with open(f"{SKILL_DIR}/state/discovery_candidates.json", "w") as f:
            json.dump({"generated_at": datetime.now().isoformat(timespec="seconds"),
                       "candidates": candidates}, f, indent=1)

    print(f"boards_ok={stats['boards_ok']} boards_failed={stats['boards_failed']} "
          f"li_queries_ok={stats['li_ok']}/{stats['li_ok']+stats['li_failed']} "
          f"jobs_pulled={stats['pulled']} deduped_skipped={stats['deduped']} "
          f"candidates={stats['candidates']} elapsed_s={elapsed:.1f}")
    if failed_boards:
        print("failed_boards: " + ", ".join(failed_boards[:10]))
    if args.dry_run:
        for c in candidates[:15]:
            print(f"  - [{c['lane']}] {c['company']} — {c['title']} ({c['location']}, {c['date']})")

if __name__ == "__main__":
    main()
