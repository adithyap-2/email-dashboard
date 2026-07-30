# n8n Automation — Setup Guide (Phase 2)

This guide wires up the **foundation pipeline**: n8n reads the team's Outlook mail
+ calendar and the SharePoint engagement sheet on a schedule, normalises it, and
pushes it into the dashboard's database via `POST /ingest/*`. The dashboard then
reads that stored data instead of hitting Microsoft live.

```
                 (scheduled, app-only)                    X-Ingest-Key
 Microsoft Graph ─────────────────────▶  n8n  ──────────────────────▶  POST /ingest/*  ─▶  app DB
  users' mail + calendar                 │ normalise (owner, external, dates)              │
 SharePoint engagement sheet ────────────┘                                                 ▼
                                                                        Dashboard (DASHBOARD_SOURCE=db)
```

Everything the backend needs is already built:
`/ingest/emails`, `/ingest/meetings`, `/ingest/engagements` (all require the
`X-Ingest-Key` header), plus a `DASHBOARD_SOURCE=db` switch.

---

> **Setting up from scratch?** Use **[SETUP.md](SETUP.md)** instead — it covers
> the whole project end to end (Entra, Docker, sign-in, these workflows, HTTPS,
> backups). This file is the deeper reference for the n8n layer specifically.

## 1. Prerequisites

- Docker (the compose stack now includes an `n8n` service).
- A Microsoft **Entra ID admin** — app-only access reads all team mailboxes, so
  it needs one-time **admin consent** (this is the same consent wall from Phase 1,
  but for *application* permissions).

## 2. Register the app-only Graph identity

You can reuse the existing app registration or create a dedicated one for
automation (cleaner — automation and interactive login stay separate). In
[entra.microsoft.com](https://entra.microsoft.com) → **App registrations**:

1. **API permissions → Add permission → Microsoft Graph → Application permissions**, add:
   - `Mail.Read` — read users' mail
   - `Calendars.Read` — read users' calendars
   - `Sites.Read.All` (or `Files.Read.All`) — read the SharePoint engagement sheet
2. Click **Grant admin consent for <tenant>**. All three should show green.
3. **Certificates & secrets → New client secret** — copy the *Value*.
4. From **Overview**, note the **Application (client) ID** and **Directory (tenant) ID**.

> ⚠️ **Scope down mailbox access (recommended).** `Mail.Read` (application) grants
> read to *every* mailbox in the tenant. To restrict it to just the team, apply an
> **Application Access Policy** in Exchange Online (`New-ApplicationAccessPolicy`)
> limited to a mail-enabled security group. Ask your Exchange admin.

## 3. Generate the ingestion key

The backend refuses ingestion unless a key is set (fail-closed). Generate one:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put it in `backend/.env`:

```ini
INGEST_API_KEY=<the-generated-key>
# leave DASHBOARD_SOURCE=graph for now; flip to db in step 7
```

## 4. Start the stack

```bash
docker compose up -d --build
```

- Dashboard: http://localhost:8000
- n8n editor: http://localhost:5678 (create your local n8n owner account on first visit)

Inside the compose network n8n reaches the backend at **`http://app:8000`** (this
is provided to n8n as `N8N_BACKEND_URL`).

> The `/ingest/*` nodes read that variable with `{{ $env.N8N_BACKEND_URL }}`.
> n8n blocks `$env` inside expressions unless `N8N_BLOCK_ENV_ACCESS_IN_NODE` is
> `false`, which compose sets for you — without it those nodes fail with
> **"access to env vars denied"**. If you run n8n outside this compose stack,
> set it there too, or hardcode the backend URL in the three ingest nodes.

## 5. Create the Graph credential in n8n

In n8n → **Credentials → New → "OAuth2 API"** (generic), set:

| Field | Value |
|---|---|
| Grant Type | **Client Credentials** |
| Access Token URL | `https://login.microsoftonline.com/<tenant-id>/oauth2/v2.0/token` |
| Client ID | your Application (client) ID |
| Client Secret | the secret Value |
| Scope | `https://graph.microsoft.com/.default` |
| Authentication | Send as Basic Auth Header |

Name it **"Graph App-Only"**. Every Microsoft HTTP Request node below uses it.

Also create a **Header Auth** credential named **"Ingest Key"** with
Name = `X-Ingest-Key`, Value = your `INGEST_API_KEY`. The `POST /ingest/*` nodes
use this.

## 6. Build the two workflows

You can import the starter JSON in [`docs/n8n/`](n8n/) (**Workflows → Import from
File**) and then fill in your tenant/site IDs and the team's mailbox list, or
build them by hand from the steps below.

### Workflow A — Engagement sheet sync (daily)

1. **Schedule Trigger** — every day, early morning.
2. **HTTP Request (Graph App-Only)** — read the sheet's used range. Address the
   file by **drive + item ID**, not by path — IDs survive the file being renamed
   or moved, and sidestep URL-encoding entirely:
   ```
   GET https://graph.microsoft.com/v1.0/drives/{drive-id}/items/{item-id}/workbook/worksheets('Updated%20Engagement%20Sheet')/usedRange
   ```
   The starter JSON already has CRID's IDs baked in. To find them for a
   different tenant or file, run these three in order (any Graph client — the
   n8n node itself works, and tests the app-only credential at the same time):
   ```
   GET /sites/{hostname}:/sites/{site-name}          → copy `id`
   GET /sites/{site-id}/drive/root/search(q='Engagement')
                                                     → copy `id` + `parentReference.driveId`
   GET /drives/{drive-id}/items/{item-id}/workbook/worksheets
                                                     → confirm the tab name
   ```
   Don't combine site-path addressing with further navigation in one URL
   (`/sites/host:/sites/name:/drive/root/children`) — Graph answers `400`.

   **Encode every space as `%20`**, including inside `worksheets('...')`. A
   literal space anywhere in the URL makes Graph return `400 Bad request`.
3. **Code node** — turn `body.values` (array of rows) into ingest records. Map the
   header row to fields; forward-fill is handled by the backend, so just pass
   `organisation` as-is (blank where the sheet is blank):
   ```js
   const rows = $json.values;
   const header = rows[0].map(h => (h||'').toString().trim().toLowerCase());
   const col = (name) => header.findIndex(h => h.startsWith(name));
   const idx = {
     organisation: col('organisation'), contact_name: col('name'),
     topic: col('topic of concern'), email: col('email'),
     last_contact_raw: col('last day of contact'),
     next_followup_raw: col('next followup'),
     summary: col('overall summary'), next_steps: col('next steps'),
   };
   const pick = (r,i) => i>=0 && r[i]!=null ? String(r[i]) : null;
   return rows.slice(1).map(r => ({ json: {
     organisation: pick(r,idx.organisation), contact_name: pick(r,idx.contact_name),
     email: pick(r,idx.email), topic: pick(r,idx.topic),
     last_contact_raw: pick(r,idx.last_contact_raw),
     next_followup_raw: pick(r,idx.next_followup_raw),
     summary: pick(r,idx.summary), next_steps: pick(r,idx.next_steps),
   }}));
   ```
4. **HTTP Request (Ingest Key)** — `POST {{$env.N8N_BACKEND_URL}}/ingest/engagements`,
   body = **all items as one JSON array** (set "Send Body" = JSON, and pass the
   array — use an Aggregate/Items-to-array step so the backend gets a single
   full-refresh batch). The backend parses dates + splits the follow-up hook.

### Workflow B — Email + calendar ingestion (every 15–30 min)

1. **Schedule Trigger**.
2. **Set / Code node** — define the team's mailboxes and the lookback window:
   ```js
   const users = ['pg@crid.org','swayam@crid.org'];      // team UPNs
   const sinceIso = new Date(Date.now()-30*864e5).toISOString().split('.')[0]+'Z';
   const internal = ['crid.org'];                          // your internal domains
   return users.map(u => ({ json: { user: u, sinceIso, internal } }));
   ```
3. **Loop over items** (Split In Batches).
4. For each user, three **HTTP Request (Graph App-Only)** calls:
   - Received: `GET /users/{{$json.user}}/mailFolders/inbox/messages?$filter=receivedDateTime ge {{$json.sinceIso}}&$select=id,subject,from,receivedDateTime,bodyPreview&$top=50`
   - Sent: `GET /users/{{$json.user}}/mailFolders/sentitems/messages?$filter=sentDateTime ge {{$json.sinceIso}}&$select=id,subject,toRecipients,sentDateTime,bodyPreview&$top=50`
   - Calendar: `GET /users/{{$json.user}}/calendarView?startDateTime=<now-7d>&endDateTime=<now+2d>&$select=id,subject,organizer,attendees,start,end,location` (header `Prefer: outlook.timezone="UTC"`)
5. **Code node** — normalise to the ingest shape, setting `owner` = the mailbox and
   computing `is_external` by domain (see the payload contract below). This is the
   same logic `graph_data.py` uses today — you're just moving it into n8n.
6. **HTTP Request (Ingest Key)** — `POST .../ingest/emails` and `.../ingest/meetings`
   with the normalised arrays.

## 7. Flip the dashboard to the database

Once data is flowing in (check `docker compose logs -f app` for `POST /ingest/...`),
set in `backend/.env`:

```ini
DASHBOARD_SOURCE=db
```
and `docker compose up -d app`. The dashboard now serves each signed-in user their
own stored rows (matched on their mailbox = `owner`) — instantly, with history, and
with n8n-computed meeting follow-up status. Follow-ups still come from the shared
engagement table. To roll back, set `DASHBOARD_SOURCE=graph`.

---

## Payload contracts (what n8n must POST)

All arrays; header `X-Ingest-Key: <key>`; idempotent upsert on `id`.

**`POST /ingest/emails`**
```json
[{
  "id": "<graph message id>",       // upsert key
  "owner": "pg@crid.org",           // the mailbox (UPN) this belongs to — REQUIRED
  "direction": "received",          // or "sent"
  "subject": "…", "preview": "…",
  "contact_name": "Rama Tentu",     // received: sender; sent: first external recipient
  "contact_email": "rama@ext.org",
  "organisation": null,             // optional; dashboard enriches from the sheet anyway
  "is_external": true,              // sender (received) / any recipient (sent) outside internal domains
  "ts": "2026-07-24T09:00:00Z"
}]
```

**`POST /ingest/meetings`**
```json
[{
  "id": "<graph event id>", "owner": "pg@crid.org",
  "subject": "…", "organisation": null,
  "contact_name": "Monali Zeya", "contact_email": "mzeya@ciff.org",
  "is_external": true,              // any attendee/organiser outside internal domains
  "start_ts": "2026-07-25T10:00:00Z", "end_ts": "2026-07-25T10:30:00Z",
  "location": "Microsoft Teams",
  "attendees": ["Monali Zeya <mzeya@ciff.org>"],
  "followup_status": "none"         // "pending" | "done" | "none" — your logic can compute this
}]
```

**`POST /ingest/engagements`** — full refresh (replaces the whole table):
```json
[{
  "organisation": "Giving Green",   // blank on continuation rows; backend forward-fills
  "contact_name": "Rama Tentu", "email": "rama@givinggreen.earth",
  "topic": "Industrial decarbonisation",
  "last_contact_raw": "20th July",
  "next_followup_raw": "22nd July - send revised budget",  // backend splits date + hook
  "summary": null, "next_steps": null
}]
```

**`is_external` rule** (mirror of the current live logic): take the counterpart's
email domain; it's external if the domain is non-empty and **not** in your internal
domain list (your own tenant domains). For sent mail, external = *any* recipient is
external; for meetings, external = *any* attendee or the organiser is external.

---

## What this unlocks next

With the foundation in place, later workflows just add nodes/flows that write to
the same DB — no dashboard changes:
- **Follow-up completion** — before posting engagements, check sent mail after each
  due date and set a "handled" flag.
- **Meeting follow-up status** — after past meetings, look for a follow-up email to
  the contact → set `followup_status`.
- **Notifications** — a daily Teams/email digest of due + overdue follow-ups.
- **AI** — summaries, meeting prep, drafted follow-ups (hand off to the LLM here).
