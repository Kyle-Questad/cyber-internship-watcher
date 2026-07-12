"""
Cyber Internship Watcher — direct Workday company polling

Queries specific Fortune 500 companies' own Workday career sites directly,
using the same public JSON API their career site's search box uses. This
is the fastest-possible source since it goes straight to the company
instead of waiting on a community tracker to notice and add it.

To add a company: confirm it's actually on Workday (visit its careers
page, check the URL pattern is *.myworkdayjobs.com), find its exact
tenant/site slugs, and add an entry to WORKDAY_COMPANIES below. A wrong
tenant/site can fail silently (return 0 results instead of an error), so
verify the URL loads real job listings in a browser before adding it here.

How to find tenant/site for a new company:
  1. Go to the company's careers page, find a job listing.
  2. The URL will look like:
     https://{tenant}.{pod}.myworkdayjobs.com/en-US/{site}/job/...
  3. tenant = subdomain before .myworkdayjobs.com (e.g. "wf")
     pod    = the wdN part (e.g. "wd1", "wd5")
     site   = the segment right after the language code (e.g. "WellsFargoJobs")
"""

import sys
from pathlib import Path

import requests

from common import (
    HEADERS,
    is_early_career,
    load_seen,
    make_id,
    matches_keywords,
    save_seen,
    send_email,
)

SEEN_FILE = Path(__file__).parent / "seen_workday.json"

# ---------------------------------------------------------------------------
# Company list — add new ones here as you confirm their Workday details.
# ---------------------------------------------------------------------------

WORKDAY_COMPANIES = [
    {"name": "Wells Fargo", "pod": "wd1", "tenant": "wf", "site": "WellsFargoJobs"},
    {"name": "Intel", "pod": "wd1", "tenant": "intel", "site": "External"},
    {"name": "RTX", "pod": "wd5", "tenant": "globalhr", "site": "REC_RTX_Ext_Gateway"},
    {"name": "Boeing", "pod": "wd1", "tenant": "boeing", "site": "EXTERNAL_CAREERS"},
    {"name": "PayPal", "pod": "wd1", "tenant": "paypal", "site": "jobs"},
    {"name": "Discover", "pod": "wd5", "tenant": "discover", "site": "Discover"},
    {"name": "GoDaddy", "pod": "wd1", "tenant": "godaddy", "site": "GoDaddy_careers_events"},
    {"name": "Avnet", "pod": "wd1", "tenant": "avnet", "site": "External"},
    {"name": "Arrow Electronics", "pod": "wd1", "tenant": "arrow", "site": "AC"},
    {"name": "GDIT", "pod": "wd5", "tenant": "gdit", "site": "External_Career_Site"},
    {"name": "Visa", "pod": "wd5", "tenant": "visa", "site": "Visa_Early_Careers"},
    {"name": "USAA", "pod": "wd1", "tenant": "usaa", "site": "USAAJOBSWD"},
    {"name": "Cisco", "pod": "wd5", "tenant": "cisco", "site": "Cisco_Careers"},
]

# Search terms run individually per company — narrower terms surface more
# relevant hits than one broad combined query would.
WORKDAY_SEARCH_TERMS = ["cyber", "security", "SOC"]


def fetch_workday_postings() -> list[dict]:
    postings = []
    seen_urls_this_run = set()

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

                if link in seen_urls_this_run:
                    continue
                seen_urls_this_run.add(link)

                if matches_keywords(title) and is_early_career(title):
                    postings.append({
                        "source": f"{company['name']} (Workday, direct)",
                        "company": company["name"],
                        "role": title,
                        "link": link,
                    })

    return postings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    seen = load_seen(SEEN_FILE)

    all_postings = fetch_workday_postings()
    print(f"[workday] Fetched {len(all_postings)} matching postings across "
          f"{len(WORKDAY_COMPANIES)} companies.")

    new_postings = []
    for p in all_postings:
        pid = make_id(p["company"], p["role"], p["link"])
        if pid not in seen:
            new_postings.append(p)
            seen.add(pid)

    if new_postings:
        print(f"[workday] Found {len(new_postings)} new posting(s):")
        for p in new_postings:
            print(f"  - {p['company']}: {p['role']}")
        send_email(f"🔔 {len(new_postings)} new cyber internship posting(s) — Workday direct", new_postings)
    else:
        print("[workday] No new postings this run.")

    save_seen(SEEN_FILE, seen)


if __name__ == "__main__":
    main()
