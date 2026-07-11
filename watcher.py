"""
Cyber Internship Watcher
-------------------------
Pulls two community-maintained internship trackers, filters for
cybersecurity-flavored postings, and emails you when something new shows up.

Sources:
  1. zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships
     -> has a real JSON API, easiest to parse
  2. vanshb03/Summer2027-Internships
     -> no API, so we pull the raw README.md and parse the markdown table

State (which postings we've already alerted on) is kept in seen.json,
which the GitHub Action commits back to the repo after each run.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

KEYWORDS = [
    "security", "cyber", "soc analyst", "soc ", "infosec",
    "information security", "grc", "vulnerability", "threat",
    "incident response", "blue team", "red team", "penetration test",
    "pentest", "siem", "risk analyst", "compliance analyst",
]

SEEN_FILE = Path(__file__).parent / "seen.json"

ZSHAH_JSON_URL = (
    "https://zshah101.github.io/"
    "Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships/"
    "api/jobs.json"
)

VANSH_README_URL = (
    "https://raw.githubusercontent.com/vanshb03/"
    "Summer2027-Internships/dev/README.md"
)

HEADERS = {"User-Agent": "cyber-internship-watcher/1.0"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def matches_keywords(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in KEYWORDS)


def load_seen() -> set:
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()


def save_seen(seen: set) -> None:
    SEEN_FILE.write_text(json.dumps(sorted(seen), indent=2))


def make_id(company: str, role: str, link: str) -> str:
    # Stable-ish identifier for a posting so we don't re-alert on it
    return f"{company.strip().lower()}|{role.strip().lower()}|{link.strip()}"


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

    # The API is a list of job dicts; field names may shift, so we
    # defensively pull with .get() and fall back gracefully.
    jobs = data if isinstance(data, list) else data.get("jobs", [])
    for job in jobs:
        company = job.get("company", "")
        role = job.get("role") or job.get("title", "")
        link = job.get("apply_url") or job.get("url", "")
        combined_text = f"{company} {role}"
        if matches_keywords(combined_text):
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
        # Skip header/separator rows
        if cells[0].lower() in ("company", "") or set(cells[0]) <= {"-", ":"}:
            continue

        company, role = cells[0], cells[1]
        # "↳" rows mean "same company as the row above"
        if company in ("↳", ""):
            company = last_company
        else:
            last_company = company

        # The Apply cell is usually raw HTML: <a href="real_url"><img .../></a>
        # Fall back to markdown-style [text](url) if href isn't present.
        row_text = " ".join(cells)
        href_match = re.search(r'href="(https?://[^"]+)"', row_text)
        if href_match:
            link = href_match.group(1)
        else:
            all_urls = re.findall(r"\((https?://[^\s)]+)\)", row_text)
            link = all_urls[-1] if all_urls else ""

        combined_text = f"{company} {role}"
        if matches_keywords(combined_text):
            postings.append({
                "source": "vanshb03 tracker",
                "company": company,
                "role": role,
                "link": link,
            })
    return postings


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(new_postings: list[dict]) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ.get("ALERT_EMAIL_TO", gmail_user)

    lines = []
    for p in new_postings:
        lines.append(f"{p['company']} — {p['role']}")
        if p["link"]:
            lines.append(p["link"])
        lines.append(f"(via {p['source']})")
        lines.append("")

    body = "\n".join(lines)
    subject = f"🔔 {len(new_postings)} new cyber internship posting(s)"

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [to_addr], msg.as_string())

    print(f"Sent email with {len(new_postings)} new posting(s).")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    seen = load_seen()

    all_postings = fetch_zshah_postings() + fetch_vansh_postings()
    print(f"Fetched {len(all_postings)} cyber-keyword postings total.")

    new_postings = []
    for p in all_postings:
        pid = make_id(p["company"], p["role"], p["link"])
        if pid not in seen:
            new_postings.append(p)
            seen.add(pid)

    if new_postings:
        print(f"Found {len(new_postings)} new posting(s):")
        for p in new_postings:
            print(f"  - {p['company']}: {p['role']}")
        send_email(new_postings)
    else:
        print("No new postings this run.")

    save_seen(seen)


if __name__ == "__main__":
    main()
