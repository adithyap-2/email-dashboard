# Starter n8n workflows

Importable scaffolds for the foundation pipeline. In n8n: **Workflows → Import
from File**. Full setup (app registration, admin consent, credentials, flipping
`DASHBOARD_SOURCE=db`) is in [../n8n-setup.md](../n8n-setup.md).

| File | What it does |
|---|---|
| `engagement-sync.json` | Reads the SharePoint engagement sheet (Graph `usedRange`), normalises rows, `POST /ingest/engagements` (full refresh). |
| `email-calendar-ingest.json` | Per mailbox: reads received + sent mail and calendar (Graph, app-only), tags internal/external, `POST /ingest/emails` + `/ingest/meetings`. |

**Before running, edit these placeholders:**
- `Config` node → your team's mailbox UPNs and internal domains.
- `engagement-sync` URL → your `TODO-SITE-ID` and file path.
- Link the two credentials on the HTTP nodes: **Graph App-Only** (OAuth2 client
  credentials) and **Ingest Key** (Header Auth `X-Ingest-Key`).

These are **starting points**, not turnkey — they encode the correct endpoints,
payload shapes, and the internal/external logic, but Graph tenants differ (site
IDs, mailbox access policies), so expect to adjust and test node-by-node with
n8n's execution view.
