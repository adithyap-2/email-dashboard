"""Multi-user Microsoft (Entra ID) auth.

Each teammate signs in with their own Microsoft account via the OAuth
authorization-code flow. MSAL keeps every account's refresh token in a single
serialized token cache; a browser session cookie maps to one account's
`home_account_id`, so `get_token()` only ever returns the signed-in user's own
delegated token. The dashboard then reads that user's mailbox/calendar directly
from Microsoft Graph — no shared/pre-fixed data.

The "current user" for a request is carried in a ContextVar set by the
`require_user` dependency, so existing Graph helpers (graph_tools, the agent)
keep working unchanged: they call `auth.get_token()` and transparently get the
right user's token.
"""

import contextvars
import json
import os
import secrets
import threading

import msal
from dotenv import load_dotenv

import db

load_dotenv()

SCOPES = os.environ["GRAPH_SCOPES"].split()
CACHE_PATH = os.environ.get("TOKEN_CACHE_PATH", "token_cache.bin")

# The one setting that changes between a laptop and a shared server. Everything
# user-facing (the Microsoft redirect, cookie security) is derived from it, so
# there is a single URL to keep in sync with the Entra app registration.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
REDIRECT_URI = os.environ.get("REDIRECT_URI") or f"{PUBLIC_BASE_URL}/auth/callback"

# Only these email domains may sign in. Entra already limits sign-in to the
# tenant when AUTHORITY is tenant-specific; this additionally keeps out guest
# accounts invited into the tenant. Empty = allow anyone the tenant lets in.
ALLOWED_EMAIL_DOMAINS = {
    d.strip().lower().lstrip("@")
    for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",")
    if d.strip()
}

# One serialized cache holds every signed-in account (fine for an internal tool;
# use per-user encrypted storage for anything larger). Reads and writes are
# guarded because several teammates can be refreshing tokens at the same time
# and the whole file is rewritten on each save.
cache = msal.SerializableTokenCache()
_cache_lock = threading.Lock()


def _load_cache():
    with _cache_lock:
        if os.path.exists(CACHE_PATH):
            cache.deserialize(open(CACHE_PATH).read())


def _save_cache():
    with _cache_lock:
        if cache.has_state_changed:
            # Write-then-rename so a crash mid-write can't truncate the cache
            # and sign every user out at once.
            tmp = f"{CACHE_PATH}.tmp"
            with open(tmp, "w") as f:
                f.write(cache.serialize())
            os.replace(tmp, CACHE_PATH)


def email_allowed(email: str | None) -> bool:
    """True if this account may use the dashboard."""
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    if not email or "@" not in email:
        return False
    return email.rsplit("@", 1)[1].strip().lower() in ALLOWED_EMAIL_DOMAINS


_app: msal.ConfidentialClientApplication | None = None


def get_msal_app() -> msal.ConfidentialClientApplication:
    global _app
    if _app is None:
        _load_cache()
        _app = msal.ConfidentialClientApplication(
            os.environ["CLIENT_ID"],
            client_credential=os.environ["CLIENT_SECRET"],
            authority=os.environ["AUTHORITY"],
            token_cache=cache,
        )
    return _app


# --- current-request user -------------------------------------------------
_current_hid: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_home_account_id", default=None
)


def set_current_account(home_account_id: str | None) -> None:
    _current_hid.set(home_account_id)


# --- login flow -----------------------------------------------------------
def begin_login() -> str:
    """Start an auth-code flow; return the Microsoft URL to redirect the user to."""
    flow = get_msal_app().initiate_auth_code_flow(SCOPES, redirect_uri=REDIRECT_URI)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO auth_flows (state, flow) VALUES (?, ?)",
            (flow["state"], json.dumps(flow)),
        )
    return flow["auth_uri"]


def complete_login(query_params: dict) -> dict:
    """Redeem the callback. Returns the MSAL result (with id_token_claims) or an
    {'error': ...} dict."""
    state = query_params.get("state")
    if not state:
        return {"error": "missing_state"}
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT flow FROM auth_flows WHERE state = ?", (state,)
        ).fetchone()
        if row:
            conn.execute("DELETE FROM auth_flows WHERE state = ?", (state,))
    if not row:
        return {"error": "unknown_or_expired_state"}
    flow = json.loads(row["flow"])
    result = get_msal_app().acquire_token_by_auth_code_flow(flow, dict(query_params))
    _save_cache()
    return result


# --- sessions -------------------------------------------------------------
def create_session(home_account_id: str, username: str | None, name: str | None) -> str:
    sid = secrets.token_urlsafe(32)
    with db.get_conn() as conn:
        conn.execute(
            "INSERT INTO sessions (session_id, home_account_id, username, name) "
            "VALUES (?, ?, ?, ?)",
            (sid, home_account_id, username, name),
        )
    return sid


def get_session(sid: str) -> dict | None:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (sid,)
        ).fetchone()
    return dict(row) if row else None


def delete_session(sid: str) -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))


# --- tokens ---------------------------------------------------------------
def _account_for(home_account_id: str | None):
    if not home_account_id:
        return None
    for acct in get_msal_app().get_accounts():
        if acct.get("home_account_id") == home_account_id:
            return acct
    return None


def token_for(home_account_id: str) -> str:
    """Silent token for a specific signed-in account. Raises if that account is
    no longer cached (user must re-authenticate)."""
    app = get_msal_app()
    acct = _account_for(home_account_id)
    if not acct:
        raise RuntimeError("account_not_signed_in")
    result = app.acquire_token_silent(SCOPES, account=acct)
    _save_cache()
    if not result or "access_token" not in result:
        raise RuntimeError("token_refresh_failed")
    return result["access_token"]


def get_token() -> str:
    """Token for the current request's user (set via ContextVar). Used by the
    legacy Graph helpers / agent so they need no changes."""
    return token_for(_current_hid.get())
