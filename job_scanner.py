#!/usr/bin/env python3
"""
Chicago J1 Summer Jobs Agent
------------------------------
Daily scanner for summer/seasonal jobs in the Chicago area suited to
a 20-year-old student arriving on a J1 Work & Travel visa.

API      : Adzuna (free — https://developer.adzuna.com)
           Set ADZUNA_APP_ID and ADZUNA_APP_KEY as GitHub Secrets.
Schedule : Runs daily via GitHub Actions (.github/workflows/daily_scan.yml)
Output   : jobs/YYYY-MM-DD.json  — archived daily snapshot
           jobs/latest.json      — always the most recent scan
           jobs/latest.md        — human-readable markdown report
"""

import os
import re
import json
import time
from datetime import datetime, date
from pathlib import Path

import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

ADZUNA_APP_ID  = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_BASE    = "https://api.adzuna.com/v1/api/jobs/us/search"

LOCATION     = "chicago, il"
LOCATION_LABEL = "Chicago, IL"
RADIUS_MILES = 35
SCAN_DATE    = date.today().isoformat()
DAYS_BACK    = 2          # jobs posted in last N days
RESULTS_PER_PAGE = 50

SEARCH_QUERIES = [
    "summer jobs student",
    "seasonal summer work",
    "summer hospitality",
    "hotel summer staff",
    "summer camp counselor",
    "summer retail associate",
    "summer restaurant server",
    "summer recreation tourism",
    "amusement park summer",
    "summer internship",
    "lifeguard summer",
    "front desk hotel",
    "summer warehouse",
    "summer customer service",
]

J1_POSITIVE_KEYWORDS = [
    "summer", "seasonal", "temporary", "temp", "part-time",
    "flexible", "student", "no experience", "will train",
    "training provided", "entry level", "entry-level",
    "hospitality", "hotel", "resort", "motel",
    "restaurant", "cafe", "café", "food service", "barista",
    "retail", "store associate", "sales associate",
    "camp", "counselor", "recreation", "leisure",
    "tourism", "visitor", "guest services", "front desk",
    "amusement", "theme park", "attractions",
    "customer service", "team member", "crew member",
    "lifeguard", "pool", "aquatic",
    "stadium", "events", "concert", "warehouse", "fulfillment",
]

J1_NEGATIVE_KEYWORDS = [
    "security clearance", "permanent resident", "green card",
    "us citizen only", "work authorization required",
    "senior director", "vice president", "vp ", "chief ",
    "cfo", "cto", "ceo", "attorney", "phd required", "md required",
    "full-time permanent", "relocation", "sponsorship not available",
]

# ── SCORING ───────────────────────────────────────────────────────────────────

def score_job(job: dict) -> int:
    text = (job.get("title", "") + " " + job.get("description", "")).lower()
    score = 40

    for kw in J1_POSITIVE_KEYWORDS:
        if kw in text:
            score += 4

    for kw in J1_NEGATIVE_KEYWORDS:
        if kw in text:
            score -= 15

    title = job.get("title", "").lower()
    if "summer"    in title: score += 18
    if "seasonal"  in title: score += 12
    if "intern"    in title: score += 10
    if "part-time" in title or "part time" in title: score += 8
    if "temp"      in title: score += 8

    return max(0, min(100, score))

# ── ADZUNA API ────────────────────────────────────────────────────────────────

def fetch_adzuna(query: str, page: int = 1) -> list:
    """Fetch one page of results from the Adzuna jobs API."""
    if not ADZUNA_APP_ID or not ADZUNA_APP_KEY:
        raise SystemExit(
            "\n[ERROR] ADZUNA_APP_ID and ADZUNA_APP_KEY environment variables are not set.\n"
            "  → Get a free key at https://developer.adzuna.com\n"
            "  → Add them as GitHub Secrets in your repo Settings.\n"
        )

    params = {
        "app_id":          ADZUNA_APP_ID,
        "app_key":         ADZUNA_APP_KEY,
        "what":            query,
        "where":           LOCATION,
        "distance":        RADIUS_MILES,
        "max_days_old":    DAYS_BACK,
        "results_per_page": RESULTS_PER_PAGE,
        "content-type":    "application/json",
    }

    try:
        resp = requests.get(
            f"{ADZUNA_BASE}/{page}",
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        return _parse_adzuna(resp.json())
    except requests.HTTPError as exc:
        print(f"    [WARN] Adzuna HTTP error for '{query}': {exc}")
        return []
    except Exception as exc:
        print(f"    [WARN] Adzuna error for '{query}': {exc}")
        return []


def _parse_adzuna(data: dict) -> list:
    jobs = []
    for r in data.get("results", []):
        desc = re.sub(r"<[^>]+>", " ", r.get("description", ""))
        desc = re.sub(r"\s+", " ", desc).strip()[:450]

        job = {
            "title":       r.get("title", "").strip(),
            "company":     r.get("company", {}).get("display_name", "").strip(),
            "location":    r.get("location", {}).get("display_name", LOCATION_LABEL).strip(),
            "url":         r.get("redirect_url", "").strip(),
            "description": desc,
            "date_posted": r.get("created", "")[:10],
            "salary":      _salary(r),
            "source":      "Adzuna",
        }
        if job["title"] and job["url"]:
            jobs.append(job)
    return jobs


def _salary(r: dict) -> str:
    lo = r.get("salary_min")
    hi = r.get("salary_max")
    if lo and hi:
        return f"${lo:,.0f} – ${hi:,.0f}"
    if lo:
        return f"From ${lo:,.0f}"
    return ""

# ── SCAN ─────────────────────────────────────────────────────────────────────

def run_scan() -> list:
    print(f"\n{'='*60}")
    print(f"  Chicago J1 Summer Jobs Agent")
    print(f"  Scan date : {SCAN_DATE}")
    print(f"  Location  : {LOCATION_LABEL}  (+{RADIUS_MILES} mi radius)")
    print(f"  Queries   : {len(SEARCH_QUERIES)}")
    print(f"{'='*60}\n")

    all_jobs: list = []
    seen_urls: set = set()

    for idx, query in enumerate(SEARCH_QUERIES, 1):
        print(f"  [{idx:02d}/{len(SEARCH_QUERIES)}] '{query}'")
        jobs = fetch_adzuna(query)

        new = 0
        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                job["j1_score"] = score_job(job)
                all_jobs.append(job)
                new += 1

        print(f"          → {new} new  ({len(all_jobs)} total so far)")
        time.sleep(0.8)

    all_jobs.sort(key=lambda j: j["j1_score"], reverse=True)
    print(f"\n  Scan complete — {len(all_jobs)} unique jobs found")
    return all_jobs

# ── OUTPUT ────────────────────────────────────────────────────────────────────

def save_results(jobs: list):
    jobs_dir = Path("jobs")
    jobs_dir.mkdir(exist_ok=True)

    payload = {
        "scan_date":    SCAN_DATE,
        "scanned_at":   datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "location":     LOCATION_LABEL,
        "radius_miles": RADIUS_MILES,
        "total_jobs":   len(jobs),
        "jobs":         jobs,
    }

    archive = jobs_dir / f"{SCAN_DATE}.json"
    _write_json(archive, payload)
    _write_json(jobs_dir / "latest.json", payload)
    (jobs_dir / "latest.md").write_text(_build_markdown(jobs), encoding="utf-8")

    print(f"\n  Saved → {archive}")
    print(f"  Saved → jobs/latest.json")
    print(f"  Saved → jobs/latest.md")


def _write_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _build_markdown(jobs: list) -> str:
    today_fmt  = datetime.now().strftime("%B %d, %Y")
    top_picks  = [j for j in jobs if j["j1_score"] >= 65]
    other_jobs = [j for j in jobs if j["j1_score"] <  65]

    lines = [
        "# 🏙️ Chicago J1 Summer Jobs — Daily Scan",
        "",
        f"**Date:** {today_fmt}  ",
        f"**Area:** {LOCATION_LABEL} + {RADIUS_MILES} mile radius  ",
        f"**Total listings:** {len(jobs)}  ",
        f"**Top J1 picks (score ≥ 65):** {len(top_picks)}",
        "",
        "> Automated daily scan for summer & seasonal jobs suited to a J1 Work & Travel "
        "visa holder. Jobs scored 0–100: entry-level, seasonal, hospitality roles score highest.",
        "",
        "---",
        "",
        "## ⭐ Top J1-Recommended Listings",
        "",
    ]

    if not top_picks:
        lines.append("_No high-scoring listings today — check back tomorrow._\n")
    else:
        for job in top_picks[:60]:
            badge = "🟢" if job["j1_score"] >= 80 else "🟡"
            sal   = f"  \n**Salary:** {job['salary']}" if job.get("salary") else ""
            lines += [
                f"### {job['title']}",
                f"**Company:** {job['company']}  ",
                f"**Location:** {job['location']}{sal}  ",
                f"**J1 Score:** {badge} {job['j1_score']}/100  ",
                f"**Posted:** {job['date_posted']} | **Source:** {job['source']}  ",
                f"**Apply:** [View listing]({job['url']})",
                "",
                f"> {job['description']}",
                "",
                "---",
                "",
            ]

    if other_jobs:
        lines += [
            "## Other Listings",
            "",
            "| Title | Company | Location | Score | Apply |",
            "|-------|---------|----------|-------|-------|",
        ]
        for job in other_jobs[:40]:
            t = job["title"][:45].replace("|", "-")
            c = job["company"][:28].replace("|", "-")
            l = job["location"][:22].replace("|", "-")
            lines.append(f"| {t} | {c} | {l} | {job['j1_score']} | [Apply]({job['url']}) |")
        lines.append("")

    lines += [
        "---",
        "_Scanned daily at 8 AM Chicago time. Always verify J1 work authorisation "
        "with your sponsor before applying._",
    ]

    return "\n".join(lines)

# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    found = run_scan()
    save_results(found)
