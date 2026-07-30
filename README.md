# Relationship Intelligence Dashboard

A single, spacious dashboard where each teammate signs in with their **own
Microsoft account** and sees **their own** external communications, meetings,
and follow-ups — without opening Outlook, Teams, or SharePoint. Not an email
client, not a CRM — an intelligence layer.

Built on the existing FastAPI + Next.js stack (the original LangGraph inbox
agent is preserved at `/chat`).

> **Running it on your machine? → [docs/SETUP.md](docs/SETUP.md)**
> Complete step-by-step: config, Docker, sign-in, n8n credentials and workflows,
> troubleshooting. ~30 minutes, and you get a full local copy with your own
> mailbox. Moving to a single shared deployment later is covered at the end.

```bash
cp backend/.env.example backend/.env   # fill in — see docs/SETUP.md step 4
docker compose up -d --build           # dashboard on :8000, n8n on :5678
```

## Single window

The Next.js frontend is built to a **static export** and served by the FastAPI
backend, so the whole app — dashboard, API, and Microsoft login — lives on **one
URL** (`http://localhost:8000`). No separate frontend port; no "start backend,
then open a different localhost" step. `./start.sh` builds the frontend and
boots the backend.

## Architecture (this phase: live per-user)

```
                      sign in (OAuth)                       enrich
 Teammate ──▶ /auth/login ──▶ Microsoft ──▶ /auth/callback ──▶ session cookie
    │                                                              │
    └───────────── GET /api/dashboard (their session) ────────────┘
                              │
             ┌────────────────┴───────────────────┐
        Microsoft Graph (that user's           Engagement sheet
        mailbox + calendar, live)              (shared, read-only, from Excel)
        → external emails & meetings           → follow-ups (common to everyone)
```

Each browser session maps to one Microsoft account (`home_account_id`); MSAL
holds every user's refresh token, and `/api/dashboard` reads **only the
signed-in user's** Graph data. "External" = anyone outside that user's own
email domain(s). Follow-ups and contact metadata come from the shared engagement
sheet, so they're identical for all users; emails and meetings vary per login.

### Phase 2 — n8n automation
The `/ingest/*` endpoints let **n8n** take over data collection: it reads
Graph/SharePoint on a schedule (app-only), normalises, and pushes into the DB.
Set `DASHBOARD_SOURCE=db` and the UI switches from live Graph to the stored data
with no code change. Full setup + importable starter workflows:
**[docs/n8n-setup.md](docs/n8n-setup.md)** and **[docs/n8n/](docs/n8n/)**.

Ingestion is secured by `INGEST_API_KEY` (sent as the `X-Ingest-Key` header);
stored emails/meetings carry an `owner` (mailbox) so each user still sees only
their own data. `docker compose up` now also starts an `n8n` service on `:5678`.

### Modules
- External emails **received** / **sent** in a configurable range (24h / 48h /
  7d / 30d / custom).
- **Today's** follow-ups and **pending** (overdue) follow-ups.
- **Upcoming** external meetings (next 2 days) and **past** meetings (previous
  week) with follow-up status.
- **Communication overview** — emails vs. meetings per organisation.

## Engagement sheet (read-only)

Relationship metadata comes from `Engagement Sheet.xlsx` → the
**"Updated Engagement Sheet"** tab. It is **input only** — the dashboard never
writes to it and never invents engagement rows. Follow-ups are derived from it:
`Next Followup date and message` is parsed into a due date + message hook, then
categorised as *today* / *pending* automatically. Free-text dates
("20th July", "Not specific") are parsed leniently; ambiguous ones are skipped.

Business users keep editing the sheet independently. Reload it after changes:
`POST /ingest/reload-engagements` (in production, n8n mirrors the SharePoint
copy into the same table).

## Backend API

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `GET`  | `/auth/login` | — | Start Microsoft sign-in (redirects to Microsoft) |
| `GET`  | `/auth/callback` | — | OAuth redirect; creates a session cookie |
| `GET`  | `/auth/me` | session | Current signed-in user (401 if not) |
| `POST` | `/auth/logout` | session | Clear the session |
| `GET`  | `/api/dashboard?range=7d` | session | The signed-in user's whole dashboard, live |
| `GET`  | `/api/engagements` | session | Full engagement directory (read-only, shared) |
| `POST` | `/ingest/emails` / `/ingest/meetings` | — | **n8n** upserts (next phase) |
| `POST` | `/ingest/reload-engagements` | — | Re-read the Excel sheet |
| `GET`  | `/health` | — | Liveness |

`range` is `24h` / `48h` / `7d` / `30d` / `custom` (applies to emails +
overview; meeting windows are fixed: next 2 days / previous 7 days).

## Microsoft app registration

Needs an Entra ID app (the one in `.env`) with **delegated** permissions:
`User.Read`, `Mail.Read`, `Calendars.Read` (+ `Mail.ReadWrite`, `Mail.Send` for
the inbox agent), and redirect URI `http://localhost:8000/auth/callback` (Web).
Each teammate consents on first sign-in. For a deployed instance, add that
host's `/auth/callback` as a redirect URI and set `REDIRECT_URI` accordingly.

## Run

```bash
./start.sh                       # builds the frontend, serves everything on :8000
```
Open **http://localhost:8000** and sign in with Microsoft. One URL, one process.
(Docker: `docker compose up -d --build`.)

Config lives in `backend/.env` (see `.env.example`): `DB_PATH`,
`ENGAGEMENT_XLSX`, `ENGAGEMENT_SHEET`, `INTERNAL_DOMAINS` (extra internal email
domains treated as non-external), and `DASHBOARD_TODAY` (pins "today" for
follow-up categorisation — defaults to the real system date).

## Original inbox agent

The LangGraph agent over Microsoft Graph is unchanged, still served at `/chat`,
now **per-user** (each session gets its own conversation thread and token).
It's the surface future AI capabilities can build on.
