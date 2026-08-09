# Setup Guide — Relationship Intelligence Dashboard

How to get a **complete, working copy running on your own machine**, identical to
the one it was built on. This is the testing setup: each person runs the whole
stack locally with Docker.

Follow it top to bottom. Expect 30–45 minutes, most of it waiting for the first
Docker build.

> Planning a single shared deployment the whole team logs into instead? That is
> a different setup — see [Later: one shared deployment](#later-one-shared-deployment)
> at the end.

---

## 0. What you are setting up

Everything runs on your laptop, in two Docker containers:

```
   Microsoft 365  ─────▶  n8n (timer)  ─────▶  app  ◀──── your browser
   your mailbox,          reads Graph,         FastAPI + dashboard
   calendar,              pushes data          SQLite
   SharePoint sheet                            :8000
```

- **`app`** — the dashboard. The only thing you open: <http://localhost:8000>
- **`n8n`** — background automation that pulls your mail, calendar, and the
  engagement sheet on a timer

You sign in with **your own** CRID Microsoft account and see **your own** emails
and meetings. The engagement sheet is the shared one from SharePoint, so it is
the same for everyone.

**This copy is yours alone.** Your database is on your machine — you are not
sharing data with anyone else running it. That is fine for testing.

---

## 1. Before you start

Install **Docker Desktop** ([mac](https://docs.docker.com/desktop/install/mac-install/)
· [windows](https://docs.docker.com/desktop/install/windows-install/)) and launch
it. Verify:

```bash
docker --version && docker compose version
```

Then get these five values from whoever set this up first. Four are secrets —
receive them over something private, not email or a group chat.

```
Tenant ID                  ________________________
Dashboard   client ID      ________________________
Dashboard   client secret  ________________________
Automation  client ID      ________________________
Automation  client secret  ________________________
```

You also need **`Engagement Sheet.xlsx`**.

Nothing needs to be registered in Entra ID — the two app registrations already
exist and `http://localhost:8000/auth/callback` is already an approved redirect
URI. Several people can run their own local copy against the same registrations
at the same time without interfering.

> **Handle the Automation secret carefully.** It can read *every* mailbox in the
> CRID tenant. It is on your machine only because n8n runs locally in this
> testing setup. Do not copy it anywhere else, and say so if a machine holding it
> is lost.

---

## 2. Get the code

```bash
git clone <repo-url> email-tool
cd email-tool
```

Put `Engagement Sheet.xlsx` in the folder you just cloned (the top level, next to
`docker-compose.yml`).

---

## 3. Configure

```bash
cp backend/.env.example backend/.env
```

Open `backend/.env` in any editor and set these. Leave everything else alone.

| Setting | Value |
|---|---|
| `PUBLIC_BASE_URL` | `http://localhost:8000` |
| `CLIENT_ID` | Dashboard client ID |
| `CLIENT_SECRET` | Dashboard client secret |
| `AUTHORITY` | `https://login.microsoftonline.com/6074215d-c0f6-40c3-8a60-547e474ae438` |
| `ALLOWED_EMAIL_DOMAINS` | `cridindia.com` |
| `INTERNAL_DOMAINS` | `cridindia.com` |
| `DASHBOARD_SOURCE` | `db` |

Then generate your own ingestion key and paste it in as `INGEST_API_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Keep that value handy — you will paste it into n8n in step 6.

> Two traps here. **`AUTHORITY` must not say `common`** — that would let any
> Microsoft account attempt sign-in. And make sure `AUTHORITY` appears only
> **once** in the file; if you paste a second copy, the later one silently wins.

`backend/.env` is gitignored and excluded from the Docker build. Never commit it.

---

## 4. Start it

```bash
docker compose up -d --build
```

The first build takes several minutes — it compiles the frontend. Then:

```bash
docker compose ps
```

Both services should be `Up`, with `app` eventually showing `(healthy)`.

- Dashboard → <http://localhost:8000>
- n8n editor → <http://localhost:5678>

---

## 5. Sign in

Open <http://localhost:8000> and sign in with your CRID account.

You should reach the dashboard. Follow-ups will already be populated (from the
bundled sheet), but **emails and meetings will be empty** — nothing has been
ingested for you yet. That is expected; steps 6–8 fix it.

---

## 6. Create the two n8n credentials

Open <http://localhost:5678>. On first visit it asks you to create an n8n owner
account — this is local to n8n, unrelated to Microsoft. Any email/password.

### 6a. "Graph App-Only"

**Credentials → New → OAuth2 API**:

| Field | Value |
|---|---|
| Grant Type | **Client Credentials** |
| Access Token URL | `https://login.microsoftonline.com/6074215d-c0f6-40c3-8a60-547e474ae438/oauth2/v2.0/token` |
| Client ID | **Automation** client ID |
| Client Secret | **Automation** client secret |
| Scope | `https://graph.microsoft.com/.default` |
| Authentication | Send as Basic Auth Header |

Name it exactly **`Graph App-Only`** and save.

> If saving fails with *"Client authentication failed"*: you probably pasted the
> Secret **ID** instead of the secret **Value** (the Value is not a GUID). If the
> value is definitely right, switch Authentication to **Send Client Credentials
> in Body** — n8n's Basic header does not URL-encode secrets containing
> `~`, `.`, or `+`.

### 6b. "Ingest Key"

**Credentials → New → Header Auth**:

| Field | Value |
|---|---|
| Name | `X-Ingest-Key` |
| Value | the `INGEST_API_KEY` you generated in step 3 |

Name it exactly **`Ingest Key`** and save.

---

## 7. Import the workflows

**Workflows → Import from File**, once for each file in [`n8n/`](n8n/):

- `email-calendar-ingest.json`
- `engagement-sync.json`

Open each imported workflow. Any node showing a credential warning needs the
matching credential picked from its dropdown — `Graph App-Only` on the Microsoft
nodes, `Ingest Key` on the `POST /ingest/*` nodes. Save each workflow.

### 7a. Add your own mailbox ← *don't skip this*

Open **Email + Calendar Ingest** → the **`Config`** node. Change the first line to
your own address:

```js
const users = ['your.name@cridindia.com'];
const internal = ['cridindia.com'];
```

**If your address is not here, your dashboard stays empty.** n8n only fetches the
mailboxes listed. For testing, listing just yourself is right.

Save.

---

## 8. Run both workflows once

Open each workflow and click **Execute Workflow** — the button at the bottom of
the canvas, *not* "Execute step" on an individual node.

Check the last node of each returns a non-zero count:

- **Engagement Sheet Sync** → `POST /ingest/engagements` → `{"ingested": 134}`
- **Email + Calendar Ingest** → `POST /ingest/emails` and `POST /ingest/meetings`
  → `{"ingested": N}`

> `{"ingested": 0}` almost always means you clicked **Execute step** rather than
> **Execute Workflow**, so the chain never reached the POST node.

### 8a. Publish them so they keep running

Click **Publish** in the top right of each workflow.

> In n8n 2.x this replaced the old **Inactive/Active** toggle. If you are hunting
> for a switch, this is it. Publishing is what puts a workflow on its schedule —
> saving does not, and running it manually does not.

Once published, mail syncs every 30 minutes and the sheet every 12 hours.

If the button will not cooperate, do it from the command line — n8n only applies
this on restart:

```bash
docker compose exec n8n n8n list:workflow           # get the IDs
docker compose exec n8n n8n publish:workflow --id=<id>
docker compose restart n8n
docker compose logs n8n --tail 40 | grep -i "published workflows"
# -> Processed 0 draft workflows, 2 published workflows.
```

---

## 9. Verify

```bash
docker compose exec app python -c "
import sqlite3; c=sqlite3.connect('/data/data.db')
for t in ('engagements','emails','meetings'):
    print(t, c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])"
```

All three should be non-zero. Reload <http://localhost:8000> — you should now see
your own emails and meetings alongside the shared follow-ups.

Then run the health check, which looks for the failures that produce no error
message anywhere — a mailbox missing from the `Config` list, a busy calendar
silently truncated at the Graph page cap, or a sheet that has stopped syncing:

```bash
docker compose exec app python /app/scripts/health.py
```

It prints per-mailbox coverage and exits non-zero if anything needs attention.
Worth running after any change to the workflows, and any time the dashboard
looks wrong.

That is the whole setup.

---

## 10. Using it day to day

- **Start:** `docker compose up -d` (Docker Desktop must be running)
- **Stop:** `docker compose stop`
- **Refresh now:** the **Refresh** button, top right of the dashboard. It pulls
  *your* mail and calendar immediately instead of waiting for the 30-minute
  timer — useful right after you have sent something.

You do not need to touch n8n again once it is published. Leave the editor closed.

Your data lives in Docker volumes and survives restarts and rebuilds. It does not
survive `docker compose down -v` — that flag deletes volumes, and would also wipe
n8n's saved credentials.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `AADSTS50011` redirect mismatch | `PUBLIC_BASE_URL` isn't `http://localhost:8000` | Step 3 |
| Sign-in rejected, "account not permitted" | Not a `cridindia.com` account | Use your CRID account |
| Invalid authority / sign-in fails immediately | `AUTHORITY` set twice, or still `common` | Step 3 — it must appear once, with the tenant ID |
| n8n: *Failed to acquire OAuth2 access token: Client authentication failed* | Secret ID pasted instead of Value; `common` in the token URL | Step 6a |
| n8n: *access to env vars denied* | n8n blocks `$env` in expressions | Already handled in `docker-compose.yml`; `docker compose restart n8n` |
| n8n: *Bad request - please check your parameters* | Literal spaces in a Graph URL, or unfilled `TODO-` placeholders | Encode spaces as `%20` |
| `{"ingested": 0}` | Clicked **Execute step**, not **Execute Workflow** | Step 8 |
| Dashboard has follow-ups but no emails/meetings | Your address isn't in the `Config` node | Step 7a |
| Nothing updates on its own | Workflows unpublished — runs all show `mode: manual` | Step 8a |
| Can't find the Active/Inactive toggle | n8n 2.x renamed it to **Publish** | Step 8a |
| Graph `403` after a valid token | Application permissions lack admin consent | Ask the admin who owns the Automation app |

### Useful commands

```bash
docker compose ps                     # are both services up?
docker compose logs app --tail 50     # dashboard logs
docker compose logs n8n --tail 50     # automation logs
docker compose restart app            # apply an .env change
docker compose up -d --build app      # rebuild after a code change
```

---

## Later: one shared deployment

The setup above gives every tester their own private copy — separate databases,
separate n8n, and the tenant-wide Automation secret sitting on each machine.
That is acceptable for testing and not for real use.

The eventual shape is **one deployment everyone signs into**: it runs on an
always-on host, the team opens a single HTTPS URL, n8n runs once centrally so the
Automation secret lives in exactly one place, and history is shared rather than
fragmented per laptop.

Moving there does not change the app. It needs:

1. A host that stays on — an Azure VM in the CRID tenant, or an existing internal
   server.
2. A hostname with HTTPS — a reverse proxy such as Caddy is two lines of config
   and handles certificates automatically.
3. `PUBLIC_BASE_URL=https://your-hostname` in `backend/.env`. The session
   cookie's `Secure` flag follows it automatically.
4. That same `https://your-hostname/auth/callback` added as a redirect URI on the
   **Dashboard** app registration in Entra.
5. Every teammate's address added to the `Config` node, so their history is
   ingested centrally.
6. Port **5678 left unexposed** — n8n must stay on loopback, reachable only by an
   admin over an SSH tunnel:
   `ssh -L 5678:localhost:5678 user@host`

Also back up both Docker volumes on a shared host: `app-data` holds the database
and sign-ins, `n8n-data` holds the workflows *and n8n's encryption key* — lose it
and every stored credential becomes unreadable.
