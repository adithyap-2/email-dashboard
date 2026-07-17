import os
import time

import httpx

import auth

GRAPH = "https://graph.microsoft.com/v1.0"

# Senders the agent should never see (comma-separated in .env) — keeps
# high-volume noise like automated meeting recaps out of the LLM context.
IGNORED_SENDERS = {
    s.strip().lower()
    for s in os.environ.get("IGNORED_SENDERS", "").split(",")
    if s.strip()
}


def _is_ignored(msg: dict) -> bool:
    sender = (
        (msg.get("from") or {}).get("emailAddress", {}).get("address", "").lower()
    )
    return sender in IGNORED_SENDERS


def _headers(text_body: bool = True):
    h = {"Authorization": f"Bearer {auth.get_token()}"}
    if text_body:
        # Get plain text bodies instead of HTML -> far fewer LLM tokens
        h["Prefer"] = 'outlook.body-content-type="text"'
    return h


def _request(method: str, url: str, *, max_retries: int = 3, **kwargs) -> httpx.Response:
    """Graph call with retry on 429 honoring Retry-After."""
    for attempt in range(max_retries + 1):
        r = httpx.request(method, url, **kwargs)
        if r.status_code != 429 or attempt == max_retries:
            r.raise_for_status()
            return r
        time.sleep(int(r.headers.get("Retry-After", "2")))
    raise RuntimeError("unreachable")


def list_unread(top: int = 10) -> list[dict]:
    r = _request(
        "GET",
        f"{GRAPH}/me/messages",
        params={
            "$filter": "isRead eq false",
            # over-fetch so ignored senders don't shrink the result
            "$top": min(top * 3, 50),
            "$select": "id,subject,from,receivedDateTime,bodyPreview,importance",
            "$orderby": "receivedDateTime desc",
        },
        headers=_headers(),
    )
    msgs = [m for m in r.json()["value"] if not _is_ignored(m)]
    return msgs[:top]


def list_recent(days: int = 28, top: int = 25) -> list[dict]:
    """All mail received in the last `days` days, newest first."""
    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    r = _request(
        "GET",
        f"{GRAPH}/me/messages",
        params={
            "$filter": f"receivedDateTime ge {since}",
            "$top": min(top * 2, 50),
            "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
            "$orderby": "receivedDateTime desc",
        },
        headers=_headers(),
    )
    msgs = [m for m in r.json()["value"] if not _is_ignored(m)]
    return msgs[:top]


def search_mail(query: str, top: int = 10) -> list[dict]:
    r = _request(
        "GET",
        f"{GRAPH}/me/messages",
        params={
            "$search": f'"{query}"',
            "$top": min(top * 3, 50),
            "$select": "id,subject,from,receivedDateTime,bodyPreview",
        },
        headers=_headers(),
    )
    msgs = [m for m in r.json()["value"] if not _is_ignored(m)]
    return msgs[:top]


def read_message(message_id: str) -> dict:
    r = _request(
        "GET",
        f"{GRAPH}/me/messages/{message_id}",
        params={"$select": "id,subject,from,toRecipients,receivedDateTime,body"},
        headers=_headers(),
    )
    msg = r.json()
    if _is_ignored(msg):
        # Don't feed huge ignored-sender bodies to the LLM
        msg["body"] = {
            "contentType": "Text",
            "content": "[Body omitted — this sender is on the ignored list (IGNORED_SENDERS in .env).]",
        }
    return msg


def create_reply_draft(message_id: str, body_text: str) -> dict:
    """Create (but do NOT send) a reply draft."""
    r = _request(
        "POST",
        f"{GRAPH}/me/messages/{message_id}/createReply",
        headers=_headers(text_body=False),
    )
    draft = r.json()
    r2 = _request(
        "PATCH",
        f"{GRAPH}/me/messages/{draft['id']}",
        json={"body": {"contentType": "Text", "content": body_text}},
        headers=_headers(text_body=False),
    )
    return r2.json()


def send_draft(draft_id: str) -> bool:
    """Only call this AFTER explicit human approval."""
    _request(
        "POST",
        f"{GRAPH}/me/messages/{draft_id}/send",
        headers=_headers(text_body=False),
    )
    return True


def mark_read(message_id: str) -> bool:
    _request(
        "PATCH",
        f"{GRAPH}/me/messages/{message_id}",
        json={"isRead": True},
        headers=_headers(text_body=False),
    )
    return True
