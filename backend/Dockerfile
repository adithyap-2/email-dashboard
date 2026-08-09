# Single-image build: compile the Next.js static export, then serve it from the
# FastAPI backend so the whole app runs on one port (8000).
# Build context is the REPO ROOT (see docker-compose.yml).

FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # -> /fe/out (static export)

FROM python:3.12-slim
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/*.py ./
COPY scripts/ ./scripts/
COPY --from=frontend /fe/out ./frontend_out
COPY ["Engagement Sheet.xlsx", "./Engagement Sheet.xlsx"]

ENV FRONTEND_DIR=/app/frontend_out
ENV ENGAGEMENT_XLSX="/app/Engagement Sheet.xlsx"

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
