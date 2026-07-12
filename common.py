"""
Shared helpers for the cyber internship watcher scripts.

Both trackers.py and workday_watcher.py import from here so the keyword
lists, state-file handling, and email sending stay consistent and don't
get duplicated (and drift out of sync) between the two.
"""

import json
import os
import re
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

import requests

HEADERS = {"User-Agent": "cyber-internship-watcher/1.0"}

# ---------------------------------------------------------------------------
# Topic keywords — is this posting cyber-flavored at all?
# ---------------------------------------------------------------------------

KEYWORDS = [
    "security", "cyber", "infosec",
    "information security", "vulnerability", "threat",
    "incident response", "blue team", "red team", "penetration test",
    "pentest", "siem", "risk analyst", "compliance analyst",
    "cloud security", "application security", "network security",
    "identity and access management", "digital forensics",
    "security engineer", "security analyst", "cyber defense",
    "cyber risk", "vulnerability management", "malware", "forensics",
]

# These need STRICT word-boundary matching — as substrings they collide
# with common unrelated words ("soc" inside "social"/"association",
# "iam" inside "claim"/"william", "grc" is short enough to risk noise too).
BOUNDARY_ONLY_KEYWORDS = ["soc", "iam", "grc"]

# Everything else uses substring matching on purpose — compound words like
# "Cybersecurity" (no space between "cyber" and "security") or
# "InfoSec-Analyst" wouldn't match under strict \b...\b boundaries, since
# there's no boundary between the two joined roots.
_SUBSTRING_PATTERNS = [re.compile(re.escape(kw), re.IGNORECASE) for kw in KEYWORDS]
_BOUNDARY_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in BOUNDARY_ONLY_KEYWORDS
]


def matches_keywords(text: str) -> bool:
    if any(p.search(text) for p in _SUBSTRING_PATTERNS):
        return True
    return any(p.search(text) for p in _BOUNDARY_PATTERNS)


# ---------------------------------------------------------------------------
# Seniority keywords — is this actually an early-career role?
# ---------------------------------------------------------------------------
# Needed for sources that pull from a company's FULL job board (like the
# Workday direct pollers) rather than an already-internship-scoped list.
# Without this, "Lead Information Security Engineer" and "Executive
# Director - Digital Asset Security" pass the topic filter just as easily
# as "Cybersecurity Intern" does.

EARLY_CAREER_KEYWORDS = [
    "intern", "internship", "co-op", "coop", "rotational", "rotation program",
    "early career", "early careers", "new grad", "university program",
    "student program", "campus program",
]

_EARLY_CAREER_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in EARLY_CAREER_KEYWORDS
]

# Titles that LOOK entry-level by keyword but aren't — filtered out even
# if an early-career term appears elsewhere in the title.
SENIORITY_EXCLUDE_KEYWORDS = [
    "lead", "senior", "sr.", "sr ", "principal", "staff", "manager",
    "director", "vp", "vice president", "head of", "chief", "executive",
]

_SENIORITY_EXCLUDE_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in SENIORITY_EXCLUDE_KEYWORDS
]


def is_early_career(text: str) -> bool:
    if any(p.search(text) for p in _SENIORITY_EXCLUDE_PATTERNS):
        return False
    return any(p.search(text) for p in _EARLY_CAREER_PATTERNS)


# ---------------------------------------------------------------------------
# State (seen postings) — one state file per script, passed in by caller
# ---------------------------------------------------------------------------

def load_seen(path: Path) -> set:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_seen(path: Path, seen: set) -> None:
    path.write_text(json.dumps(sorted(seen), indent=2))


def make_id(company: str, role: str, link: str) -> str:
    return f"{company.strip().lower()}|{role.strip().lower()}|{link.strip()}"


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(subject: str, new_postings: list[dict]) -> None:
    gmail_user = os.environ["GMAIL_USER"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ.get("ALERT_EMAIL_TO", gmail_user)

    lines = []
    for p in new_postings:
        lines.append(f"{p['company']} — {p['role']}")
        if p.get("link"):
            lines.append(p["link"])
        lines.append(f"(via {p['source']})")
        lines.append("")

    msg = MIMEText("\n".join(lines))
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = to_addr

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [to_addr], msg.as_string())

    print(f"Sent email with {len(new_postings)} new posting(s).")
