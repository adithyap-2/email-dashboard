"""Shared FastAPI dependencies."""

import os

from fastapi import Cookie, Header, HTTPException

import auth

SESSION_COOKIE = "sid"


def require_ingest_key(x_ingest_key: str | None = Header(default=None)) -> None:
    """Guard the /ingest/* endpoints that n8n writes to. Set INGEST_API_KEY in
    the backend env and send it as the `X-Ingest-Key` header from n8n. If the
    key is unset, ingestion is refused (fail closed) rather than left open."""
    expected = os.environ.get("INGEST_API_KEY", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ingestion_disabled_no_key")
    if not x_ingest_key or x_ingest_key != expected:
        raise HTTPException(status_code=401, detail="bad_ingest_key")


def require_user(sid: str | None = Cookie(default=None, alias=SESSION_COOKIE)) -> dict:
    """Resolve the signed-in user from the session cookie, set them as the
    current request user, and hand back a live Graph token. 401 if not signed
    in or the token can no longer be refreshed (needs re-auth)."""
    if not sid:
        raise HTTPException(status_code=401, detail="not_signed_in")
    sess = auth.get_session(sid)
    if not sess:
        raise HTTPException(status_code=401, detail="session_expired")
    auth.set_current_account(sess["home_account_id"])
    try:
        token = auth.token_for(sess["home_account_id"])
    except Exception:
        raise HTTPException(status_code=401, detail="reauth_required")
    return {"session": sess, "token": token}
