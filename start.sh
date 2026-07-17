#!/bin/bash
# Start the email assistant (backend :8000 + frontend :3000).
# Safe to run any time — skips anything already running.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

if curl -s -o /dev/null -m 2 http://localhost:8000/openapi.json; then
  echo "backend already running on :8000"
else
  cd "$DIR/backend"
  nohup .venv/bin/python -m uvicorn main:app --reload --port 8000 > backend.log 2>&1 &
  echo "backend starting on :8000 (log: backend/backend.log)"
fi

if curl -s -o /dev/null -m 2 http://localhost:3000; then
  echo "frontend already running on :3000"
else
  cd "$DIR/frontend"
  nohup npm run dev > frontend.log 2>&1 &
  echo "frontend starting on :3000 (log: frontend/frontend.log)"
fi

sleep 5
echo "---"
echo "backend:  $(curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:8000/openapi.json)  http://localhost:8000"
echo "frontend: $(curl -s -o /dev/null -w '%{http_code}' -m 10 http://localhost:3000)  http://localhost:3000"
