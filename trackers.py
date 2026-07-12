"""
Cyber Internship Watcher — community trackers

Polls the three community-maintained internship lists, filters for
cybersecurity-flavored postings, and emails new matches. This script is
separate from workday_watcher.py so the two can be run, tested, and
maintained independently.

Sources:
  1. zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships
  2. vanshb03/Summer2027-Internships
  3. paralax/awesome-cybersecurity-internships (cyber-only list, no keyword
     filter needed — every entry already qualifies)
"""

import re
import sys
from pathlib import Path

import requests

from common import HEADERS, load_seen, make_id, matches_keywords, save_seen, send_email

SEEN_FILE = Path(__file__).parent / "seen_trackers.json"

ZSHAH_JSON_URL = (
    "https://zshah101.github.io/"
    "Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "api/jobs.json"
)

VANSH_README_URL = (
    "https://raw.githubusercontent.com/vanshb03/"
    "Summer2027-Internships/dev/README.md"
)

PARALAX_README_URL = (
    "https://raw.githubusercontent.com/paralax/"
    "awesome-cybersecurity-internships/master/README.md"
)


# ---------------------------------------------------------------------------
# Source 1: zshah101 tracker (JSON API)
# ---------------------------------------------------------------------------

def fetch_zshah_postings() -> list[dict]:
    postings = []
    try:
        resp = requests.get(ZSHAH_JSON_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[zshah101] fetch failed: {exc}", file=sys.stderr)
        return postings

    jobs = data if isinstance(data, list) else data.get("jobs", [])
    for job in jobs:
        company = job.get("company", "")
        role = job.get("role") or job.get("title", "")
        link = job.get("apply_url") or job.get("url", "")
        if matches_keywords(f"{company} {role}"):
            postings.append({
                "source": "zshah101 tracker",
                "company": company,
                "role": role,
                "link": link,
            })
    return postings


# ---------------------------------------------------------------------------
# Source 2: vanshb03 tracker (markdown table in README)
# ---------------------------------------------------------------------------

ROW_RE = re.compile(r"^\|(.+)\|$")


def fetch_vansh_postings() -> list[dict]:
    postings = []
    try:
        resp = requests.get(VANSH_README_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"[vanshb03] fetch failed: {exc}", file=sys.stderr)
        return postings

    last_company = ""
    for line in text.splitlines():
        m = ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group(1).split("|")]
        if len(cells) < 4:
            continue
        if cells[0].lower() in ("company", "") or set(cells[0]) <= {"-", ":"}:
            continue

        company, role = cells[0], cells[1]
        if company in ("↳", ""):
            company = last_company
        else:
            last_company = company

        row_text = " ".join(cells)
        href_match = re.search(r'href="(https?://[^"]+)"', row_text)
        if href_match:
            link = href_match.group(1)
        else:
            all_urls = re.findall(r"\((https?://[^\s)]+)\)", row_text)
            link = all_urls[-1] if all_urls else ""

        if matches_keywords(f"{company} {role}"):
            postings.append({
                "source": "vanshb03 tracker",
                "company": company,
                "role": role,
                "link": link,
            })
    return postings


# ---------------------------------------------------------------------------
# Source 3: paralax/awesome-cybersecurity-internships (curated bullet list)
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def fetch_paralax_postings() -> list[dict]:
    postings = []
    try:
        resp = requests.get(PARALAX_README_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"[paralax] fetch failed: {exc}", file=sys.stderr)
        return postings

    start = text.find("### Specific cybersecurity internships")
    end = text.find("### Tech internships but not cybersecurity specific")
    if start == -1:
        print("[paralax] couldn't find expected section header", file=sys.stderr)
        return postings
    section = text[start:end if end != -1 else None]

    current_company = ""
    for line in section.splitlines():
        if not line.strip():
            continue

        leading_spaces = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if not content.startswith(("*", "+", "-")):
            continue
        content = content[1:].strip()

        if leading_spaces == 0:
            bracket_idx = content.find("[")
            current_company = (
                content[:bracket_idx].strip() if bracket_idx != -1 else content
            )
            for role, link in LINK_RE.findall(content):
                postings.append({
                    "source": "paralax cyber list",
                    "company": current_company,
                    "role": role,
                    "link": link,
                })
        else:
            for role, link in LINK_RE.findall(content):
                postings.append({
                    "source": "paralax cyber list",
                    "company": current_company,
                    "role": role,
                    "link": link,
                })

    return postings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    seen = load_seen(SEEN_FILE)

    all_postings = (
        fetch_zshah_postings() + fetch_vansh_postings() + fetch_paralax_postings()
    )
    print(f"[trackers] Fetched {len(all_postings)} cyber-keyword postings total.")

    new_postings = []
    for p in all_postings:
        pid = make_id(p["company"], p["role"], p["link"])
        if pid not in seen:
            new_postings.append(p)
            seen.add(pid)

    if new_postings:
        print(f"[trackers] Found {len(new_postings)} new posting(s):")
        for p in new_postings:
            print(f"  - {p['company']}: {p['role']}")
        send_email(f"🔔 {len(new_postings)} new cyber internship posting(s) — trackers", new_postings)
    else:
        print("[trackers] No new postings this run.")

    save_seen(SEEN_FILE, seen)


if __name__ == "__main__":
    main()
