# Cyber Internship Watcher

Polls two community internship trackers every 30 minutes, filters for
cybersecurity-flavored roles, and emails you when a new one shows up.

Sources:
- [zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships](https://github.com/zshah101/Automated-List-Of-Summer-2027-and-Fall-2026-Tech-Internships)
- [vanshb03/Summer2027-Internships](https://github.com/vanshb03/Summer2027-Internships)

## Setup

1. Push this repo to your own GitHub account.
2. Generate a Gmail **App Password**:
   Google Account → Security → 2-Step Verification (must be on) → App Passwords.
3. In this repo: **Settings → Secrets and variables → Actions → New repository secret**.
   Add:
   - `GMAIL_USER` — your Gmail address
   - `GMAIL_APP_PASSWORD` — the app password from step 2
   - `ALERT_EMAIL_TO` — where alerts should land (can be the same address)
4. Go to the **Actions** tab and confirm the workflow is enabled.
5. Click **Run workflow** to trigger it manually and confirm you get an email
   (or a "no new postings" log entry) before waiting on the schedule.

## Tuning

- Edit `KEYWORDS` in `watcher.py` to add/remove terms (e.g. "azure security",
  "cloud security", specific company names).
- Edit the cron schedule in `.github/workflows/watch.yml` to run more or
  less often. GitHub Actions free tier scheduling isn't perfectly precise
  under load, so treat 30 min as "roughly."
- `seen.json` is the script's memory. Delete it (or clear its contents to `[]`)
  if you ever want to re-alert on everything currently listed.

## Notes

- GitHub disables scheduled workflows on repos with no activity for 60 days —
  a manual "Run workflow" click resets that clock.
- If parsing breaks (e.g. a tracker changes its README table format or JSON
  schema), check the Action's run logs — the script prints fetch errors
  instead of crashing silently.
