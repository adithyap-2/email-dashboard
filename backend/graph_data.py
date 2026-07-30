"""Live Microsoft Graph queries for the dashboard, per signed-in user.

Everything here takes an explicit access token and returns rows already
normalised into the shape the frontend expects (see api.py / frontend types).
"External" is decided relative to the signed-in user's own domain(s): mail from
or to anyone outside those domains. This is the live source used *now*; the
n8n-fed DB path (ingest/*) is the next phase.
"""

from __future__ import annotations

import time
from datetime import datetime

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"


def _request(method: str, url: str, token: str, *, max_retries: int = 3, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    for attempt in range(max_retries + 1):
        r = httpx.request(method, url, headers=headers, timeout=30, **kwargs)
        if r.status_code != 429 or attempt == max_retries:
            r.raise_for_status()
            return r
        time.sleep(int(r.headers.get("Retry-After", "2")))
    raise RuntimeError("unreachable")


def _domain(email: str | None) -> str:
    return email.split("@", 1)[1].lower() if email and "@" in email else ""


def me(token: str) -> dict:
    """Signed-in user's profile — used to derive their internal domain."""
    r = _request(
        "GET",
        f"{GRAPH}/me",
        token,
        params={"$select": "displayName,mail,userPrincipalName"},
    )
    d = r.json()
    return {
        "name": d.get("displayName"),
        "email": d.get("mail") or d.get("userPrincipalName"),
    }


def _addr(recipient: dict | None) -> tuple[str | None, str | None]:
    ea = (recipient or {}).get("emailAddress", {}) if recipient else {}
    return ea.get("name"), ea.get("address")


def _iso(graph_dt: dict | None) -> str | None:
    """Graph datetime {dateTime, timeZone} (requested in UTC) -> ISO Z string."""
    if not graph_dt:
        return None
    raw = graph_dt.get("dateTime")
    if not raw:
        return None
    return raw.split(".")[0] + "Z"


def _is_external(email: str | None, internal: set[str]) -> bool:
    dom = _domain(email)
    return bool(dom) and dom not in internal


def received_emails(token: str, start_iso: str, end_iso: str,
                    internal: set[str], top: int = 50) -> list[dict]:
    """Emails the user received in the window, each tagged internal/external so
    the UI can filter. External = the sender is outside the user's domain(s)."""
    r = _request(
        "GET",
        f"{GRAPH}/me/mailFolders/inbox/messages",
        token,
        params={
            "$filter": f"receivedDateTime ge {start_iso} and receivedDateTime le {end_iso}",
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
            "$orderby": "receivedDateTime desc",
            "$top": top,
        },
        headers={"Prefer": 'outlook.body-content-type="text"'},
    )
    out = []
    for m in r.json().get("value", []):
        name, email = _addr(m.get("from"))
        out.append({
            "id": m["id"],
            "direction": "received",
            "subject": m.get("subject"),
            "preview": (m.get("bodyPreview") or "")[:160],
            "contact_name": name,
            "contact_email": email,
            "organisation": None,
            "topic": None,
            "ts": m.get("receivedDateTime"),
            "is_external": _is_external(email, internal),
        })
    return out


def sent_emails(token: str, start_iso: str, end_iso: str,
                internal: set[str], top: int = 50) -> list[dict]:
    """Emails the user sent in the window, tagged internal/external. External =
    at least one recipient is outside the user's domain(s)."""
    r = _request(
        "GET",
        f"{GRAPH}/me/mailFolders/sentitems/messages",
        token,
        params={
            "$filter": f"sentDateTime ge {start_iso} and sentDateTime le {end_iso}",
            "$select": "id,subject,toRecipients,sentDateTime,bodyPreview",
            "$orderby": "sentDateTime desc",
            "$top": top,
        },
        headers={"Prefer": 'outlook.body-content-type="text"'},
    )
    out = []
    for m in r.json().get("value", []):
        recips = [_addr(rc) for rc in (m.get("toRecipients") or [])]
        external = [(n, e) for n, e in recips if _is_external(e, internal)]
        # Prefer showing the external counterpart; else the first recipient.
        name, email = external[0] if external else (recips[0] if recips else (None, None))
        out.append({
            "id": m["id"],
            "direction": "sent",
            "subject": m.get("subject"),
            "preview": (m.get("bodyPreview") or "")[:160],
            "contact_name": name,
            "contact_email": email,
            "organisation": None,
            "topic": None,
            "ts": m.get("sentDateTime"),
            "is_external": bool(external),
        })
    return out


def meetings(token: str, start_iso: str, end_iso: str,
             internal: set[str], top: int = 50) -> list[dict]:
    """Meetings/calls in the window, tagged internal/external. External = any
    attendee or the organiser is outside the user's domain(s)."""
    r = _request(
        "GET",
        f"{GRAPH}/me/calendarView",
        token,
        params={
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "$select": "id,subject,organizer,attendees,start,end,location,isAllDay",
            "$orderby": "start/dateTime",
            "$top": top,
        },
        headers={"Prefer": 'outlook.timezone="UTC"'},
    )
    out = []
    for ev in r.json().get("value", []):
        parties = [_addr(at) for at in ev.get("attendees", [])]
        org_name, org_email = _addr(ev.get("organizer"))
        external = [(n, e) for n, e in parties if _is_external(e, internal)]
        if _is_external(org_email, internal):
            external.insert(0, (org_name, org_email))
        is_ext = bool(external)
        # Contact = the external counterpart if any, else the organiser / first
        # attendee (an internal colleague).
        if external:
            cname, cemail = external[0]
        else:
            cname, cemail = (org_name, org_email) if org_email else (
                parties[0] if parties else (None, None))
        loc = (ev.get("location") or {}).get("displayName") or "—"
        out.append({
            "id": ev["id"],
            "subject": ev.get("subject"),
            "organisation": None,
            "contact_name": cname,
            "contact_email": cemail,
            "start_ts": _iso(ev.get("start")),
            "end_ts": _iso(ev.get("end")),
            "location": loc,
            "attendees": [f"{n} <{e}>" if n else e for n, e in (parties or external)],
            "followup_status": "none",
            "is_external": is_ext,
        })
    return out
