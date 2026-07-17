# Outlook AI Email Assistant

Chat frontend + LangGraph agent over Microsoft Graph. Built from
`outlook-ai-email-assistant-guide.md`.

## Status

Everything is scaffolded and installed. **Blocked on credentials** — fill in
`backend/.env`:

1. **Entra ID app registration** (guide Phase 1, portal.azure.com):
   - `CLIENT_ID` — Application (client) ID from the app's Overview page
   - `CLIENT_SECRET` — client secret *Value* (Certificates & secrets)
   - Redirect URI must be `http://localhost:8000/auth/callback` (platform: Web)
   - Delegated permissions: `User.Read`, `Mail.Read`, `Mail.ReadWrite`,
     `Mail.Send`, `offline_access`
2. `ZAI_API_KEY` — your Z.ai API key (the agent uses GLM via Z.ai's
   OpenAI-compatible endpoint; model/endpoint are configurable via
   `ZAI_MODEL` / `ZAI_BASE_URL`)

## Run (Docker — recommended)

```bash
docker compose up -d
```

Backend on :8000, frontend on :3000. `restart: unless-stopped` means the
containers auto-start whenever Docker Desktop is running and auto-restart on
crash. The Outlook login lives in the `token-cache` volume, so it survives
rebuilds. After code changes: `docker compose up -d --build`.
Logs: `docker compose logs -f backend` (or `frontend`).

## Run (without Docker)

```bash
./start.sh
```

Starts both servers in the background; skips whatever is already running.
They stop on reboot/logout — just run it again.
Logs: `backend/backend.log`, `frontend/frontend.log`.

Then:

1. Open http://localhost:8000/auth/login (or the "Connect Outlook" link in the
   UI), sign in, consent. You should get `{"status": "connected"}` and a
   `token_cache.bin` file appears in `backend/`.
2. Sanity-check Graph access: http://localhost:8000/debug/unread
3. Open http://localhost:3000 and chat ("Summarize my unread emails").

## Notes

- The agent pauses **before every tool call** (`interrupt_before=["tools"]`).
  Click **Approve** in the UI (or `POST /chat/approve`) to resume. Refine to a
  send-only approval gate in v2.
- `backend/.env` and `backend/token_cache.bin` are gitignored — never commit
  them.
- `/debug/unread` is a dev-only endpoint; remove before deploying.
