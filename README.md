# GetaJob

An invite-only website that finds fresh analytics job postings in India, checks that each one is still live, and ranks them against **your own resume**.

Each person uploads 1–5 versions of their resume. GetaJob suggests the roles they fit and asks them to confirm. It then searches company career sites and job APIs and builds two lists:

- **Up to 50 jobs in Delhi NCR** (Gurugram, Delhi, Noida)
- **Up to 50 jobs in the other metros** (Bengaluru, Hyderabad, Mumbai, Pune)

Every posting is **30 days old or less** and passed a live check. The lists are ordered freshest first (posted within 3, 7, 15, then 30 days), and by fit score within each group. Each job card also says which resume version to send.

GetaJob never applies for anyone, never logs in to job portals, and never guesses a date: if a posting date can't be confirmed, the job goes to *Needs review* instead of the ranked lists.

---

## What's in it

| Area | What it does |
|---|---|
| **Access** | Anyone can request access. The admin (`ADMIN_EMAIL`) approves or declines requests, invites people directly, disables accounts, issues password-reset links and promotes other admins. Invite and reset links work once and expire after 7 days. |
| **Resumes** | PDF only, up to 5 per person, 5 MB each. Every upload must belong to the same person: a new file has to match an email address or the name on the resumes already uploaded. The skills from all versions are merged, and phone numbers, emails and links are kept out of the saved profile. |
| **Roles & filters** | 8–12 suggested roles, each with evidence from the resume. Also: salary range (optional hard filter), seniority band, industries, cities, excluded companies. |
| **Search** | Public job-board JSON from 67 companies (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Workday), plus the Adzuna, Jooble, JSearch and SerpAPI APIs when keys are set. Searches run for the roles people chose, site-wide, every 12 hours. |
| **Checks** | Link must load. "Position filled" wording is detected. Title and company must match. The posting date is re-read from the job page. Reposts are flagged. Scam signs (payment requests, personal email addresses) are flagged. Login-walled pages can be confirmed by the user with one click. |
| **Fit score** | Skills 40 · Title & seniority 20 · Experience 15 · Salary 10 · Industry 10 · Location 5. Every card shows the matched skills and the gaps. |
| **Per person** | Fit scores, the tracker (New → Offer, notes, follow-up dates), manual confirmations, imports and alert-email uploads are private to each account. |
| **Exports** | The top 100 and the tracker, to Excel or CSV. |

## Security

- **Passwords:** hashed with scrypt; at least 10 characters.
- **Sessions:** signed, HttpOnly, SameSite=Lax cookies, marked Secure on HTTPS. Signing in starts a new session, and changing a password or disabling an account signs that person out everywhere.
- **Forms:** a CSRF token is required on every form and every API call that changes something.
- **Sign-in protection:** sign-in is rate-limited per account and per IP. Error messages and timing are the same whether or not an email has an account, so nobody can probe which emails are registered.
- **Access-request spam:** request-access is rate-limited and has a honeypot field.
- **Data isolation:** every database query on personal data is filtered by the signed-in user's id. Tests check that one user can't read or delete another's resumes.
- **Headers:** Content-Security-Policy (no inline scripts), frame blocking, nosniff, HSTS on HTTPS, `no-store` on private pages.
- **Uploads:** PDF signature check, size limits, a parsing page cap, and a 30 MB request cap.
- **Links and docs:** no open redirects. Invite links stay out of URLs and logs. The API docs pages are switched off.
- **Secrets:** read only from environment variables. Nothing secret or personal is in this repository.

## Run it on your computer (Windows)

1. Install **Python 3.12 or 3.13** from <https://www.python.org/downloads/windows/>. Tick **"Add python.exe to PATH"**. 3.14+ is too new for some libraries; `setup.bat` picks a supported version automatically.
2. Double-click **`setup.bat`** once.
3. Double-click **`run.bat`**. On the **first start**, the black window prints an `ADMIN SETUP` link. Open it to create the admin account for `ADMIN_EMAIL`.
4. Upload your resumes, confirm your roles, and the first job update starts.

Locally, data is a SQLite file in `%LOCALAPPDATA%\GetaJob\data`. On macOS or Linux, run `./setup.sh`, then `./run.sh`.

## Put it online (Render + Neon, both free)

**1. Database (Neon).** Sign up at <https://neon.tech> and create a project. Copy the **connection string** (`postgresql://…?sslmode=require`). Render's free tier wipes local files on every restart, so accounts and resumes must live in this external database.

**2. Web service (Render).**
1. Sign up at <https://render.com> with GitHub.
2. Choose **New → Blueprint** and pick this repository. `render.yaml` sets everything up.
3. When asked, fill in:
   - `DATABASE_URL`: the Neon string.
   - `PUBLIC_URL`: your Render address, for example `https://getajob.onrender.com`. You can add it after the first deploy.
   - Any job API keys you have.
4. Deploy, then open **Logs** and find the `ADMIN SETUP` line. Open that link to create the admin account. It's valid for 48 hours and is re-issued on each restart until it's used.

**3. Scheduled updates (GitHub Actions).** The free Render instance sleeps after 15 minutes without traffic, so its in-app timer can't be relied on. In the GitHub repo, go to **Settings → Secrets and variables → Actions** and add:
- `SITE_URL`: your Render address.
- `CRON_SECRET`: copy it from Render → Environment.

`.github/workflows/refresh.yml` then wakes the site and starts an update at 06:47 and 18:47 IST.

**Optional email.** Add `SMTP_HOST=smtp.gmail.com`, `SMTP_USER`, `SMTP_PASSWORD` (a Gmail App Password) and `MAIL_FROM`. Invites, reset links and access-request alerts are then emailed automatically. Without email, the admin page shows a copy-link button instead.

## API keys (optional, more coverage)

| Variable | Where | Free tier |
|---|---|---|
| `ADZUNA_APP_ID`, `ADZUNA_APP_KEY` | <https://developer.adzuna.com/> | ~250 calls/day |
| `JOOBLE_KEY` | <https://jooble.org/api/about> | yes |
| `RAPIDAPI_KEY` (JSearch) | <https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch> | small |
| `SERPAPI_KEY` | <https://serpapi.com/> | 100 searches/month |
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com/> | pay per use |

Only role names and city names are sent to these APIs, plus the job description and skills list for the optional AI summary. No resume text, names, emails or phone numbers are ever sent. Google-Jobs APIs run once a day by default to stay within free quotas. The admin page has per-API query budgets.

## What each job portal covers

| Portal | Covered through | Limit |
|---|---|---|
| LinkedIn | Google-Jobs APIs, the user's LinkedIn alert emails, Import | Login wall and robots.txt: users confirm these jobs with one click |
| Naukri | Google-Jobs APIs, Jooble, alert emails, Import | No logged-in access or scraping |
| Indeed | Aggregator APIs, alert emails | robots.txt disallows its search pages |
| IIMJobs / Hirist | Alert emails, Import, Google-Jobs results | No public API |
| Instahyre | Alert emails, Import | Login required to view jobs |
| Foundit | Aggregator APIs, Import | Search pages not fetched |
| Company career sites | Public ATS JSON for the companies the admin lists, plus Adzuna and Jooble | Only listed companies are searched directly |

Every request respects robots.txt and is limited to 1 per second per site. A site whose robots.txt disallows automated access, such as SmartRecruiters' API, is skipped and reported on the Sources page.

## Tests

```
python -m pytest -q                                                  # SQLite
TEST_DATABASE_URL=postgresql://user:pass@host/db python -m pytest -q # Postgres
```

105 tests cover the following, and the GitHub workflow runs them against both SQLite and Postgres on every push:
- date parsing, freshness tiers, de-duplication and city mapping
- expiry and login-wall detection, salary and experience parsing
- role relevance, scoring, and choosing the 50 per list (including the under-50 case)
- alert-email and resume parsing
- a full offline update in demo mode
- sign-in, CSRF, rate limits, admin-only pages, invite single-use, upload rules and per-user isolation, account deletion

## Project layout

```
app/        FastAPI app: routes_public (landing, sign-in, request access, invites), routes_user, routes_admin,
            templates/, static/
core/       db (SQLAlchemy: Postgres/SQLite), auth, resume parsing, normalize, dedup, verify, scoring,
            select, relevance, pipeline (update + per-user scoring), export
sources/    one adapter per source (ATS boards, aggregator APIs, alert emails, manual import)
config/     employers.yaml: companies searched directly (editable on the Admin page)
fixtures/   fictional sample data for demo mode and tests
```

To add a source, subclass `sources.base.Source`, implement `fetch(ctx)` (and optionally `verify`), and add it to `ALL_SOURCES` in `sources/__init__.py`.
