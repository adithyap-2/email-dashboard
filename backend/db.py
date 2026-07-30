"""Tiny SQLite persistence layer.

This is the application's own database — the single source the dashboard reads
from. In production, n8n workflows normalise Outlook / Teams / SharePoint data
and push it in through the /ingest/* endpoints; the dashboard never talks to
Microsoft Graph directly. SQLite keeps the whole thing file-based and
zero-config for local + Docker use; swap the DSN for Postgres later without
touching the API surface.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "data.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id            TEXT PRIMARY KEY,      -- stable id from source (Graph message id)
    owner         TEXT,                  -- mailbox this belongs to (UPN/email); per-user privacy
    direction     TEXT NOT NULL,         -- 'received' | 'sent'
    subject       TEXT,
    preview       TEXT,
    contact_name  TEXT,
    contact_email TEXT,
    organisation  TEXT,
    is_external   INTEGER NOT NULL DEFAULT 1,
    ts            TEXT NOT NULL,          -- ISO 8601 timestamp of the message
    source        TEXT DEFAULT 'n8n',    -- 'n8n' | 'sample'
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_emails_ts ON emails(ts);
CREATE INDEX IF NOT EXISTS idx_emails_owner ON emails(owner, ts);

CREATE TABLE IF NOT EXISTS meetings (
    id             TEXT PRIMARY KEY,
    owner          TEXT,                 -- mailbox this belongs to (UPN/email)
    subject        TEXT,
    organisation   TEXT,
    contact_name   TEXT,
    contact_email  TEXT,
    is_external    INTEGER NOT NULL DEFAULT 1,
    start_ts       TEXT NOT NULL,        -- ISO 8601
    end_ts         TEXT,
    location       TEXT,
    attendees      TEXT,                 -- JSON array of names/emails
    followup_status TEXT DEFAULT 'none', -- 'pending' | 'done' | 'none' (past mtgs)
    source         TEXT DEFAULT 'n8n',
    created_at     TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_meetings_start ON meetings(start_ts);
CREATE INDEX IF NOT EXISTS idx_meetings_owner ON meetings(owner, start_ts);

-- Browser sessions -> the Microsoft account that logged in. The MSAL refresh
-- tokens themselves live in the token cache (token_cache.bin); this table just
-- maps an opaque session cookie to a home_account_id so each teammate sees only
-- their own mailbox/calendar.
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    home_account_id TEXT NOT NULL,
    username        TEXT,
    name            TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- Short-lived MSAL auth-code-flow state, persisted across the OAuth redirect
-- (survives a dev auto-reload between /auth/login and /auth/callback).
CREATE TABLE IF NOT EXISTS auth_flows (
    state      TEXT PRIMARY KEY,
    flow       TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Read-only mirror of the SharePoint engagement sheet (loaded from the Excel
-- file). Business users own this sheet; the dashboard never writes to it.
CREATE TABLE IF NOT EXISTS engagements (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    organisation       TEXT,
    contact_name       TEXT,
    email              TEXT,
    topic              TEXT,
    last_contact_raw   TEXT,
    last_contact_date  TEXT,             -- parsed ISO date or NULL
    next_followup_raw  TEXT,
    next_followup_date TEXT,             -- parsed ISO date or NULL
    message_hook       TEXT,
    summary            TEXT,
    next_steps         TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]