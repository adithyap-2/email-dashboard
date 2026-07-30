#!/bin/bash
# Start the Relationship Intelligence Dashboard on a SINGLE URL.
# The Next.js frontend is built to a static export and served by the FastAPI
# backend, so everything lives on http://localhost:8000 — no separate frontend
# port, no "connect backend then open frontend" dance.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

echo "▶ Building frontend (static export)…"
cd "$DIR/frontend"
if [ ! -d node_modules ]; then npm install; fi
npm run build   # -> frontend/out (served by the backend)

echo "▶ Starting backend + dashboard on :8000…"
cd "$DIR/backend"
pkill -f "uvicorn main:app" 2>/dev/null || true
sleep 1
nohup .venv/bin/python -m uvicorn main:app --port 8000 --host 0.0.0.0 > backend.log 2>&1 &

sleep 5
echo "---"
echo "Dashboard:  $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:8000/health)  →  http://localhost:8000"
echo "Open http://localhost:8000 and sign in with Microsoft."
echo "Logs: backend/backend.log"
