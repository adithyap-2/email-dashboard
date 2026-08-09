"""Dashboard read API + n8n ingestion endpoints.

The dashboard is **per-user and live**: it reads the signed-in teammate's own
mailbox and calendar from Microsoft Graph (graph_data.py) and enriches it with
the **shared, read-only engagement sheet** (loaded from Excel). Follow-ups come
from that shared sheet — common to everyone — while emails and meetings vary by
who is logged in.

The /ingest/* endpoints are the contract for the next phase (n8n), which will
normalise and push data into the DB; they are intentionally left in place.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import db
import graph_data
from dates import reference_today
from deps import require_ingest_key, require_user

router = APIRouter()

_RANGE_HOURS = {"24h": 24, "48h": 48, "7d": 24 * 7, "30d": 24 * 30}

# How wide the on-demand Refresh pulls. It must cover the largest range the UI
# can ask for (30d back, and 30d forward for upcoming meetings), otherwise
# picking "30 days" shows a window the data was never fetched for.
SYNC_PAST_DAYS = 30
SYNC_FUTURE_DAYS = 30

# Where emails/meetings come from: 'graph' (live per-user, default) or 'db'
# (n8n-populated). Follow-ups always come from the shared engagement table.
DASHBOARD_SOURCE = os.environ.get("DASHBOARD_SOURCE", "graph").strip().lower()

# Extra internal domains beyond the signed-in user's own (comma-separated).
_EXTRA_INTERNAL = {
    d.strip().lower()
    for d in os.environ.get("INTERNAL_DOMAINS", "").split(",")
    if d.strip()
}


# --- DB read path (n8n-populated data, filtered to the signed-in user) -----
def _db_emails(owner: str, direction: str, start_iso: str, end_iso: str) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, direction, subject, preview, contact_name, contact_email, "
            "organisation, is_external, ts FROM emails "
            "WHERE LOWER(owner) = ? AND direction = ? AND ts BETWEEN ? AND ? "
            "ORDER BY ts DESC",
            (owner.strip().lower(), direction, start_iso, end_iso),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_external"] = bool(d["is_external"])
        d["topic"] = None  # filled by enrichment
        out.append(d)
    return out


def _db_meetings(owner: str, start_iso: str, end_iso: str) -> list[dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, subject, organisation, contact_name, contact_email, "
            "is_external, start_ts, end_ts, location, attendees, followup_status "
            "FROM meetings WHERE LOWER(owner) = ? AND start_ts BETWEEN ? AND ? "
            "ORDER BY start_ts",
            (owner.strip().lower(), start_iso, end_iso),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["is_external"] = bool(d["is_external"])
        try:
            d["attendees"] = json.loads(d.get("attendees") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["attendees"] = []
        out.append(d)
    return out


def _graph_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- engagement-sheet enrichment ------------------------------------------
def _engagement_index(conn):
    by_email, by_org = {}, {}
    for r in conn.execute(
        "SELECT organisation, contact_name, email, topic FROM engagements"
    ):
        d = dict(r)
        if d.get("email"):
            by_email[d["email"].strip().lower()] = d
        if d.get("organisation") and d["organisation"] not in by_org:
            by_org[d["organisation"]] = d
    return by_email, by_org


def _domain_org(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    root = email.split("@", 1)[1].split(".")[0]
    return root.upper() if len(root) <= 4 else root.capitalize()


def _enrich(row: dict, by_email) -> dict:
    match = by_email.get((row.get("contact_email") or "").strip().lower())
    if match:
        row["organisation"] = match.get("organisation") or _domain_org(row.get("contact_email"))
        row["topic"] = match.get("topic")
    else:
        row["organisation"] = row.get("organisation") or _domain_org(row.get("contact_email"))
    return row


def _range_bounds(range_key, start, end, now):
    if range_key == "custom" and start:
        return start, end or _graph_iso(now)
    hours = _RANGE_HOURS.get(range_key, _RANGE_HOURS["7d"])
    return _graph_iso(now - timedelta(hours=hours)), _graph_iso(now)


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO timestamp to an aware UTC datetime, or None.

    `?start=` comes straight from the query string, so it may be anything —
    a bare date, a local time with no zone, or junk. Anything naive is treated
    as UTC; without that, subtracting it from an aware bound raises TypeError
    (not ValueError) and 500s the dashboard.
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _window_span(start_iso: str, end_iso: str) -> timedelta:
    """Length of the selected range. Upcoming meetings look this far *forward*,
    so the range selector means the same thing in every panel.

    Clamped: a custom range spanning years must not turn into a years-long
    forward calendar query.
    """
    s, e = _parse_iso(start_iso), _parse_iso(end_iso)
    if not s or not e or e <= s:
        return timedelta(days=7)
    return min(e - s, timedelta(days=SYNC_FUTURE_DAYS))


# --- the dashboard --------------------------------------------------------
@router.get("/api/dashboard")
def dashboard(
    user: dict = Depends(require_user),
    range: str = Query("7d"),
    start: str | None = None,
    end: str | None = None,
):
    warnings: list[str] = []
    now = datetime.now(timezone.utc)
    start_iso, end_iso = _range_bounds(range, start, end, now)
    # Every panel honours the range selector. Emails and past meetings look back
    # over it; upcoming meetings look the same distance forward. These windows
    # used to be fixed (+2d / -7d) no matter what the user picked, so "24 hours"
    # compared one day of email against nine days of meetings.
    span = _window_span(start_iso, end_iso)
    past_start, past_end = start_iso, end_iso
    up_start, up_end = _graph_iso(now), _graph_iso(now + span)

    if DASHBOARD_SOURCE == "db":
        # Read n8n-populated data for this user (fast, historical, status-aware).
        owner = user["session"].get("username") or ""
        profile = {"name": user["session"].get("name"), "email": owner}
        received = _db_emails(owner, "received", start_iso, end_iso)
        sent = _db_emails(owner, "sent", start_iso, end_iso)
        upcoming = _db_meetings(owner, up_start, up_end)
        past = _db_meetings(owner, past_start, past_end)
    else:
        # Live from the signed-in user's Microsoft account.
        token = user["token"]
        profile = graph_data.me(token)
        internal = set(_EXTRA_INTERNAL)
        if profile.get("email") and "@" in profile["email"]:
            internal.add(profile["email"].split("@", 1)[1].lower())

        def safe(fn, *a):
            try:
                return fn(*a)
            except Exception as e:  # a missing scope / transient Graph error
                warnings.append(f"{fn.__name__}: {type(e).__name__}")
                return []

        received = safe(graph_data.received_emails, token, start_iso, end_iso, internal)
        sent = safe(graph_data.sent_emails, token, start_iso, end_iso, internal)
        upcoming = safe(graph_data.meetings, token, up_start, up_end, internal)
        past = safe(graph_data.meetings, token, past_start, past_end, internal)

    today = reference_today()
    today_iso = today.isoformat()

    with db.get_conn() as conn:
        by_email, by_org = _engagement_index(conn)

        # enrich comms with the shared sheet
        received = [_enrich(r, by_email) for r in received]
        sent = [_enrich(r, by_email) for r in sent]
        upcoming = [_enrich(m, by_email) for m in upcoming]
        past = [_enrich(m, by_email) for m in past]

        # shared follow-ups from the engagement sheet (common to all users)
        cols = ("organisation, contact_name, email, topic, message_hook, "
                "next_followup_raw, next_followup_date, last_contact_raw, last_contact_date")
        followups_today = [dict(r) for r in conn.execute(
            f"SELECT {cols} FROM engagements WHERE next_followup_date = ? ORDER BY organisation",
            (today_iso,),
        )]
        followups_pending = [dict(r) for r in conn.execute(
            f"SELECT {cols} FROM engagements WHERE next_followup_date < ? "
            "ORDER BY next_followup_date ASC",
            (today_iso,),
        )]

    def with_overdue(f):
        if f.get("next_followup_date"):
            f["days_overdue"] = (today - date.fromisoformat(f["next_followup_date"])).days
        else:
            f["days_overdue"] = None
        return f

    followups_today = [with_overdue(f) for f in followups_today]
    followups_pending = [with_overdue(f) for f in followups_pending]

    # Headline KPIs stay focused on EXTERNAL engagement; the per-section
    # internal/external filters and the org overview are computed on the client
    # from the tagged arrays below.
    def ext(rows):
        return sum(1 for r in rows if r.get("is_external"))

    return {
        "meta": {
            "today": today_iso,
            "range": range,
            "range_start": start_iso,
            "range_end": end_iso,
            # The actual window each meeting panel used, derived from `range`.
            "window_hours": round(span.total_seconds() / 3600, 2),
            "upcoming_days": round(span.total_seconds() / 86400, 2),
            "past_days": round(span.total_seconds() / 86400, 2),
            "source": DASHBOARD_SOURCE,
            "user": {"name": profile.get("name"), "email": profile.get("email")},
            "warnings": warnings,
        },
        "kpis": {
            "emails_received": ext(received),
            "emails_sent": ext(sent),
            "followups_today": len(followups_today),
            "followups_pending": len(followups_pending),
            "meetings_upcoming": ext(upcoming),
            "meetings_past": ext(past),
        },
        "emails_received": received,
        "emails_sent": sent,
        "followups_today": followups_today,
        "followups_pending": followups_pending,
        "meetings_upcoming": upcoming,
        "meetings_past": past,
    }


@router.get("/api/engagements")
def list_engagements(user: dict = Depends(require_user)):
    """Full engagement directory (read-only, shared)."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT organisation, contact_name, email, topic, last_contact_raw, "
            "last_contact_date, next_followup_raw, next_followup_date, message_hook "
            "FROM engagements ORDER BY organisation, contact_name"
        ).fetchall()
    return db.rows_to_dicts(rows)


@router.post("/api/refresh")
def refresh(
    user: dict = Depends(require_user),
    hours: int = Query(24, ge=1, le=168),
):
    """Pull the signed-in user's newest mail and calendar straight from Graph.

    n8n polls on a timer (30 min for mail), so anything that arrived since the
    last run is invisible until it fires again. This gives the user a way to
    close that gap on demand, using their own delegated token — no dependency
    on n8n being active, and it only ever touches the caller's own mailbox.

    In 'graph' mode the dashboard already reads live on every load, so there is
    nothing to store; the client simply refetches.
    """
    now = datetime.now(timezone.utc)
    owner = (user["session"].get("username") or "").strip().lower()
    result = {
        "source": DASHBOARD_SOURCE,
        "stored_emails": 0,
        "stored_meetings": 0,
        "warnings": [],
        "refreshed_at": _graph_iso(now),
    }
    if DASHBOARD_SOURCE != "db":
        return result

    token = user["token"]
    internal = set(_EXTRA_INTERNAL)
    if "@" in owner:
        internal.add(owner.split("@", 1)[1])

    def safe(fn, *a):
        try:
            return fn(*a)
        except Exception as e:  # a missing scope / transient Graph error
            result["warnings"].append(f"{fn.__name__}: {type(e).__name__}")
            return []

    mail_start, mail_end = _graph_iso(now - timedelta(hours=hours)), _graph_iso(now)
    # Meetings are pulled wide in both directions so every selectable range —
    # including 30 days, and upcoming events well beyond this week — has data.
    mtg_start = _graph_iso(now - timedelta(days=SYNC_PAST_DAYS))
    mtg_end = _graph_iso(now + timedelta(days=SYNC_FUTURE_DAYS))

    emails = safe(graph_data.received_emails, token, mail_start, mail_end, internal)
    emails += safe(graph_data.sent_emails, token, mail_start, mail_end, internal)
    mtgs = safe(graph_data.meetings, token, mtg_start, mtg_end, internal)

    result["stored_emails"] = _store_emails(emails, owner, "graph")
    result["stored_meetings"] = _store_meetings(mtgs, owner, "graph")
    return result


# --- n8n ingestion contract -----------------------------------------------
# All /ingest/* routes require the X-Ingest-Key header (see deps.require_ingest_key).
# `owner` is the mailbox (UPN/email) the row belongs to, so the dashboard can
# show each user only their own data when reading from the DB.
class EmailIn(BaseModel):
    id: str
    owner: str                       # mailbox UPN/email this message belongs to
    direction: str = Field(pattern="^(received|sent)$")
    subject: str | None = None
    preview: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    organisation: str | None = None
    is_external: bool = True
    ts: str


class MeetingIn(BaseModel):
    id: str
    owner: str
    subject: str | None = None
    organisation: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    is_external: bool = True
    start_ts: str
    end_ts: str | None = None
    location: str | None = None
    # Nullable entries are tolerated on purpose. Graph occasionally returns an
    # attendee with no emailAddress at all (room resources, some external
    # invites), which the n8n Code node maps to null. Rejecting the value would
    # 422 the request and drop that mailbox's ENTIRE meeting batch over one
    # malformed attendee; nulls are stripped in _store_meetings instead.
    attendees: list[str | None] = []
    followup_status: str = "none"


class EngagementIn(BaseModel):
    """A raw engagement row as read from SharePoint by n8n. The backend applies
    the same normalisation (org forward-fill, follow-up split, fuzzy dates) as
    the Excel loader, so n8n just forwards the sheet's columns."""
    organisation: str | None = None
    contact_name: str | None = None
    email: str | None = None
    topic: str | None = None
    last_contact_raw: str | None = None
    next_followup_raw: str | None = None
    summary: str | None = None
    next_steps: str | None = None


# --- shared write path ----------------------------------------------------
# Both n8n (/ingest/*) and the in-app Refresh button (/api/refresh) land here,
# so a row written by either path is indistinguishable apart from `source`.
# Owner is always stored lower-cased: Entra hands back mixed-case UPNs
# ("Adithya.Prasad@…") while n8n sends whatever the mailbox list contains, and
# the dashboard's owner lookup has to match both.
def _store_emails(rows: list[dict], owner: str | None, source: str) -> int:
    if not rows:
        return 0
    params = [
        {
            "id": r["id"],
            "owner": ((r.get("owner") or owner) or "").strip().lower(),
            "direction": r.get("direction"),
            "subject": r.get("subject"),
            "preview": r.get("preview"),
            "contact_name": r.get("contact_name"),
            "contact_email": r.get("contact_email"),
            "organisation": r.get("organisation"),
            "is_external": int(bool(r.get("is_external"))),
            "ts": r.get("ts"),
            "source": source,
        }
        for r in rows
    ]
    with db.get_conn() as conn:
        conn.executemany(
            """INSERT INTO emails
               (id, owner, direction, subject, preview, contact_name,
                contact_email, organisation, is_external, ts, source)
               VALUES (:id,:owner,:direction,:subject,:preview,:contact_name,
                       :contact_email,:organisation,:is_external,:ts,:source)
               ON CONFLICT(id) DO UPDATE SET
                 owner=excluded.owner, direction=excluded.direction,
                 subject=excluded.subject, preview=excluded.preview,
                 contact_name=excluded.contact_name,
                 contact_email=excluded.contact_email,
                 organisation=excluded.organisation,
                 is_external=excluded.is_external, ts=excluded.ts,
                 source=excluded.source""",
            params,
        )
    return len(params)


def _store_meetings(rows: list[dict], owner: str | None, source: str) -> int:
    if not rows:
        return 0
    params = [
        {
            "id": r["id"],
            "owner": ((r.get("owner") or owner) or "").strip().lower(),
            "subject": r.get("subject"),
            "organisation": r.get("organisation"),
            "contact_name": r.get("contact_name"),
            "contact_email": r.get("contact_email"),
            "is_external": int(bool(r.get("is_external"))),
            "start_ts": r.get("start_ts"),
            "end_ts": r.get("end_ts"),
            "location": r.get("location"),
            "attendees": json.dumps([a for a in (r.get("attendees") or []) if a]),
            "followup_status": r.get("followup_status") or "none",
            "source": source,
        }
        for r in rows
    ]
    with db.get_conn() as conn:
        conn.executemany(
            """INSERT INTO meetings
               (id, owner, subject, organisation, contact_name, contact_email,
                is_external, start_ts, end_ts, location, attendees,
                followup_status, source)
               VALUES (:id,:owner,:subject,:organisation,:contact_name,
                       :contact_email,:is_external,:start_ts,:end_ts,:location,
                       :attendees,:followup_status,:source)
               ON CONFLICT(id) DO UPDATE SET
                 owner=excluded.owner, subject=excluded.subject,
                 organisation=excluded.organisation,
                 contact_name=excluded.contact_name,
                 contact_email=excluded.contact_email,
                 is_external=excluded.is_external, start_ts=excluded.start_ts,
                 end_ts=excluded.end_ts, location=excluded.location,
                 attendees=excluded.attendees,
                 followup_status=excluded.followup_status,
                 source=excluded.source""",
            params,
        )
    return len(params)


@router.post("/ingest/emails", dependencies=[Depends(require_ingest_key)])
def ingest_emails(items: list[EmailIn]):
    n = _store_emails([i.model_dump() for i in items], None, "n8n")
    return {"ingested": n, "type": "emails"}


@router.post("/ingest/meetings", dependencies=[Depends(require_ingest_key)])
def ingest_meetings(items: list[MeetingIn]):
    n = _store_meetings([i.model_dump() for i in items], None, "n8n")
    return {"ingested": n, "type": "meetings"}


@router.post("/ingest/engagements", dependencies=[Depends(require_ingest_key)])
def ingest_engagements(items: list[EngagementIn]):
    """Replace the engagement table from n8n's SharePoint sync. Full refresh —
    the sheet is a read-only mirror, so we never append."""
    import engagement
    records = engagement.normalize_rows([i.model_dump() for i in items], reference_today())
    n = engagement.replace_engagements(records)
    return {"ingested": n, "type": "engagements"}


@router.post("/ingest/reload-engagements", dependencies=[Depends(require_ingest_key)])
def reload_engagements():
    """Re-read the local Excel workbook (used when running without n8n)."""
    import engagement
    n = engagement.load_engagements(reference_today())
    return {"reloaded": n}
