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
    "security", "cyber", "soc", "infosec",
    "information security", "grc", "vulnerability", "threat",
    "incident response", "blue team", "red team", "penetration test",
    "pentest", "siem", "risk analyst", "compliance analyst",
    "cloud security", "application security", "network security",
    "identity and access management", "iam", "digital forensics",
    "security engineer", "security analyst", "cyber defense",
    "cyber risk", "vulnerability management", "malware", "forensics",
]

# Word-boundary regex per keyword — avoids both false negatives (e.g. "soc"
# not matching when a title has no trailing space, like "...Analyst (SOC)")
# and false positives (e.g. "soc" incorrectly matching inside "social").
_KEYWORD_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in KEYWORDS
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

PARALAX_README_URL = (
    "https://raw.githubusercontent.com/paralax/"
    "awesome-cybersecurity-internships/master/README.md"
)

HEADERS = {"User-Agent": "cyber-internship-watcher/1.0"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def matches_keywords(text: str) -> bool:
    return any(p.search(text) for p in _KEYWORD_PATTERNS)


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
# Source 3: paralax/awesome-cybersecurity-internships (curated bullet list)
# ---------------------------------------------------------------------------

LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def fetch_paralax_postings() -> list[dict]:
    """
    This list is already cyber-only by nature, so every entry under the
    "Specific cybersecurity internships" heading counts — no keyword
    filter needed here. Format looks like:

        * Cencora
          + [Cybersecurity Engineering Intern](https://...), Conshohocken, PA
        * Comcast [Comcast Security Analyst Intern](https://...), Mount Laurel, NJ
    """
    postings = []
    try:
        resp = requests.get(PARALAX_README_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"[paralax] fetch failed: {exc}", file=sys.stderr)
        return postings

    # Isolate the "Specific cybersecurity internships" section only —
    # skip the "Tech internships but not cybersecurity specific" section.
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
            # Top-level bullet: this line names (or renames) the company.
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
            # Indented sub-bullet: inherits the company from above.
            for role, link in LINK_RE.findall(content):
                postings.append({
                    "source": "paralax cyber list",
                    "company": current_company,
                    "role": role,
                    "link": link,
                })

    return postings


# ---------------------------------------------------------------------------
# Source 4: direct Workday company sites (confirmed tenants only)
# ---------------------------------------------------------------------------
# Workday exposes a public JSON search API used internally by every Workday
# career site's own search box. Format:
#   POST https://{tenant}.{pod}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
#   body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "..."}
#
# Only companies below have been confirmed to actually run on Workday with
# these exact tenant/site values. Don't add a company here on a guess —
# a wrong tenant/site returns an HTTP error (caught below), but a *slightly*
# wrong site slug can return an empty-but-valid response, which looks like
# "no postings" instead of "this is broken." Verify before adding.

WORKDAY_COMPANIES = [
    {
        "name": "Wells Fargo",
        "pod": "wd1",
        "tenant": "wf",
        "site": "WellsFargoJobs",
    },
    {
        "name": "Intel",
        "pod": "wd1",
        "tenant": "intel",
        "site": "External",
    },
    {
        "name": "RTX",
        "pod": "wd5",
        "tenant": "globalhr",
        "site": "REC_RTX_Ext_Gateway",
    },
]

# Search terms run individually per company — Workday's search matches
# against title/description, so narrower terms surface more relevant hits
# than one broad query.
WORKDAY_SEARCH_TERMS = ["cyber", "security", "SOC"]


def fetch_workday_postings() -> list[dict]:
    postings = []
    seen_urls_this_source = set()

    for company in WORKDAY_COMPANIES:
        base = f"https://{company['tenant']}.{company['pod']}.myworkdayjobs.com"
        api_url = f"{base}/wday/cxs/{company['tenant']}/{company['site']}/jobs"

        for term in WORKDAY_SEARCH_TERMS:
            try:
                resp = requests.post(
                    api_url,
                    headers={**HEADERS, "Content-Type": "application/json"},
                    json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": term},
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[workday:{company['name']}:{term}] fetch failed: {exc}", file=sys.stderr)
                continue

            job_postings = data.get("jobPostings", [])
            for job in job_postings:
                title = job.get("title", "")
                path = job.get("externalPath", "")
                link = f"{base}/en-US/{company['site']}{path}" if path else ""

                if link in seen_urls_this_source:
                    continue  # de-dupe across the 3 search terms per company
                seen_urls_this_source.add(link)

                # Workday's search is fuzzy — re-check with our own keyword
                # list so an off-topic match for e.g. "security" (as in
                # "job security" language) doesn't slip through.
                if matches_keywords(title):
                    postings.append({
                        "source": f"{company['name']} (Workday, direct)",
                        "company": company["name"],
                        "role": title,
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

    all_postings = (
        fetch_zshah_postings()
        + fetch_vansh_postings()
        + fetch_paralax_postings()
        + fetch_workday_postings()
    )
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
