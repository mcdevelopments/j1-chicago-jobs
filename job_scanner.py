#!/usr/bin/env python3
"""
Chicago J1 Summer Jobs Agent
------------------------------
Daily scanner for summer/seasonal jobs in the Chicago area suited to
a 20-year-old student arriving on a J1 Work & Travel visa.

Sources  : Indeed RSS (multiple targeted queries)
Schedule : Runs daily via GitHub Actions (.github/workflows/daily_scan.yml)
Output   : jobs/YYYY-MM-DD.json  — archived daily snapshot
           jobs/latest.json      — always the most recent scan
           jobs/latest.md        — human-readable markdown report
"""

import re
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, date
from pathlib import Path

import requests

# ── CONFIG ────────────────────────────────────────────────────────────────────

LOCATION     = "Chicago, IL"
RADIUS_MILES = 35          # covers suburbs like Evanston, Oak Park, Schaumburg
SCAN_DATE    = date.today().isoformat()
DAYS_BACK    = 2           # jobs posted in the last N days

SEARCH_QUERIES = [
    "summer jobs student",
    "seasonal summer work",
    "summer hospitality jobs",
    "hotel summer staff",
    "summer camp counselor",
    "summer retail jobs",
    "summer restaurant server",
    "tourism recreation summer",
    "amusement park summer",
    "summer internship student",
    "summer warehouse logistics",
    "front desk hotel summer",
    "J1 visa work summer",
    "lifeguard summer Chicago",
]

# Keywords that make a role more J1-friendly (positive score)
J1_POSITIVE_KEYWORDS = [
    "summer", "seasonal", "temporary", "temp", "part-time",
    "flexible hours", "flexible schedule", "student", "no experience",
    "will train", "training provided", "entry level", "entry-level",
    "hospitality", "hotel", "resort", "motel", "inn",
    "restaurant", "café", "cafe", "food service", "barista",
    "retail", "store associate", "sales associate",
    "camp", "counselor", "recreation", "leisure",
    "tourism", "visitor", "guest services", "front desk",
    "amusement", "theme park", "attractions",
    "customer service", "team member", "crew member",
    "warehouse", "logistics", "fulfillment",
    "lifeguard", "pool", "aquatic",
    "stadium", "events", "concert",
]

# Keywords that disqualify or heavily penalise a role for J1
J1_NEGATIVE_KEYWORDS = [
    "security clearance", "clearance required",
    "permanent resident required", "green card", "us citizen only",
    "work authorization", "must be authorized",
    "senior manager", "director", "vice president", "vp ",
    "chief ", "cfo", "cto", "ceo", "attorney", "lawyer",
    "phd required", "md required", "rn required",
    "full-time permanent", "benefits package", "401k",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# ── SCORING ───────────────────────────────────────────────────────────────────

def score_job(job: dict) -> int:
    """
    Score a job 0–100 for J1 Work & Travel suitability.
    Higher = better fit for a summer student on a J1 visa.
    """
    text = (
        job.get("title", "") + " " + job.get("description", "")
    ).lower()

    score = 40  # neutral baseline

    for kw in J1_POSITIVE_KEYWORDS:
        if kw in text:
            score += 4

    for kw in J1_NEGATIVE_KEYWORDS:
        if kw in text:
            score -= 15

    title_lower = job.get("title", "").lower()
    if "summer" in title_lower:
        score += 18
    if "seasonal" in title_lower:
        score += 12
    if "intern" in title_lower:
        score += 10
    if "part" in title_lower and "time" in title_lower:
        score += 8
    if "temporary" in title_lower or "temp " in title_lower:
        score += 8

    return max(0, min(100, score))


# ── INDEED RSS ────────────────────────────────────────────────────────────────

def fetch_indeed_rss(query: str) -> list:
    """Pull jobs from Indeed's RSS feed for a single query."""
    params = {
        "q":       query,
        "l":       LOCATION,
        "radius":  RADIUS_MILES,
        "sort":    "date",
        "fromage": DAYS_BACK,
    }
    try:
        resp = requests.get(
            "https://www.indeed.com/rss",
            params=params,
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        return _parse_indeed_xml(resp.text)
    except Exception as exc:
        print(f"    [WARN] Indeed RSS failed for '{query}': {exc}")
        return []


def _parse_indeed_xml(xml_text: str) -> list:
    """Parse Indeed RSS XML into a list of job dicts."""
    jobs = []
    ns = "http://indeed.com/"
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"    [WARN] XML parse error: {exc}")
        return []

    for item in root.findall(".//item"):
        raw_desc = item.findtext("description", "")
        clean_desc = re.sub(r"<[^>]+>", " ", raw_desc)
        clean_desc = re.sub(r"\s+", " ", clean_desc).strip()[:450]

        city  = item.findtext(f"{{{ns}}}city",  "")
        state = item.findtext(f"{{{ns}}}state", "")
        loc   = f"{city}, {state}".strip(", ") or LOCATION

        job = {
            "title":       item.findtext("title", "").strip(),
            "company":     (
                item.findtext(f"{{{ns}}}company", "")
                or item.findtext("source", "")
            ).strip(),
            "location":    loc,
            "url":         item.findtext("link", "").strip(),
            "description": clean_desc,
            "date_posted": item.findtext("pubDate", "").strip(),
            "source":      "Indeed",
        }

        if job["title"] and job["url"]:
            jobs.append(job)

    return jobs


# ── SCAN ─────────────────────────────────────────────────────────────────────

def run_scan() -> list:
    """Execute the full scan across all queries, deduplicate, and score."""
    print(f"\n{'='*60}")
    print(f"  Chicago J1 Summer Jobs Agent")
    print(f"  Scan date : {SCAN_DATE}")
    print(f"  Location  : {LOCATION}  (+{RADIUS_MILES} mi radius)")
    print(f"  Queries   : {len(SEARCH_QUERIES)}")
    print(f"{'='*60}\n")

    all_jobs: list  = []
    seen_urls: set  = set()

    for idx, query in enumerate(SEARCH_QUERIES, 1):
        print(f"  [{idx:02d}/{len(SEARCH_QUERIES)}] '{query}'")
        jobs = fetch_indeed_rss(query)

        new = 0
        for job in jobs:
            if job["url"] not in seen_urls:
                seen_urls.add(job["url"])
                job["j1_score"] = score_job(job)
                all_jobs.append(job)
                new += 1

        print(f"          → {new} new  ({len(all_jobs)} total so far)")
        time.sleep(1.8)   # respectful rate limit

    all_jobs.sort(key=lambda j: j["j1_score"], reverse=True)

    print(f"\n  Scan complete — {len(all_jobs)} unique jobs found")
    return all_jobs


# ── OUTPUT ────────────────────────────────────────────────────────────────────

def save_results(jobs: list):
    """Persist results as JSON (archive + latest) and a Markdown report."""
    jobs_dir = Path("jobs")
    jobs_dir.mkdir(exist_ok=True)

    payload = {
        "scan_date":   SCAN_DATE,
        "scanned_at":  datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "location":    LOCATION,
        "radius_miles": RADIUS_MILES,
        "total_jobs":  len(jobs),
        "jobs":        jobs,
    }

    # Daily archive
    archive_path = jobs_dir / f"{SCAN_DATE}.json"
    _write_json(archive_path, payload)

    # Latest snapshot (always overwritten)
    _write_json(jobs_dir / "latest.json", payload)

    # Markdown report
    md = _build_markdown(jobs)
    (jobs_dir / "latest.md").write_text(md, encoding="utf-8")

    print(f"\n  Saved → {archive_path}")
    print(f"  Saved → jobs/latest.json")
    print(f"  Saved → jobs/latest.md")


def _write_json(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)


def _build_markdown(jobs: list) -> str:
    today_fmt   = datetime.now().strftime("%B %d, %Y")
    top_picks   = [j for j in jobs if j["j1_score"] >= 65]
    other_jobs  = [j for j in jobs if j["j1_score"] < 65]

    lines = [
        "# 🏙️ Chicago J1 Summer Jobs — Daily Scan",
        "",
        f"**Date:** {today_fmt}  ",
        f"**Area:** {LOCATION} + {RADIUS_MILES} mile radius  ",
        f"**Total listings:** {len(jobs)}  ",
        f"**Top J1 picks (score ≥ 65):** {len(top_picks)}",
        "",
        (
            "> Automated daily scan for summer & seasonal jobs suited to a "
            "J1 Work & Travel visa holder. Jobs are scored 0–100 on "
            "suitability: entry-level, student-friendly, hospitality, "
            "seasonal roles score highest."
        ),
        "",
        "---",
        "",
        "## ⭐ Top J1-Recommended Listings",
        "",
    ]

    if not top_picks:
        lines.append("_No high-scoring listings found in today's scan — check back tomorrow._")
        lines.append("")
    else:
        for job in top_picks[:60]:
            badge = "🟢" if job["j1_score"] >= 80 else "🟡"
            lines += [
                f"### {job['title']}",
                f"**Company:** {job['company']}  ",
                f"**Location:** {job['location']}  ",
                f"**J1 Score:** {badge} {job['j1_score']}/100  ",
                f"**Source:** {job['source']} | **Posted:** {job['date_posted']}  ",
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
            title   = job["title"][:45].replace("|", "-")
            company = job["company"][:30].replace("|", "-")
            loc     = job["location"][:25].replace("|", "-")
            lines.append(
                f"| {title} | {company} | {loc} | {job['j1_score']} "
                f"| [Apply]({job['url']}) |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "_Scanned automatically every day at 8 AM Chicago time by "
        "[j1-chicago-jobs](https://github.com/MCDevelopments/j1-chicago-jobs). "
        "Always verify visa work authorisation with your J1 sponsor before applying._",
    ]

    return "\n".join(lines)


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    found = run_scan()
    save_results(found)
