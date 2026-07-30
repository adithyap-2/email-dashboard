import os

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel

import api
import auth
import db
import engagement
from agent import agent
from dates import reference_today
from deps import SESSION_COOKIE, require_user

app = FastAPI(title="Relationship Intelligence Dashboard")

# Same-origin in production (frontend served by this app). CORS stays permissive
# for the localhost:3000 dev server if run separately.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api.router)


@app.on_event("startup")
def _startup():
    """Init the DB and make sure the shared engagement sheet is populated.

    The Excel file baked into the image is only a *bootstrap*. Once n8n syncs
    the live SharePoint copy it owns the table, and re-reading the image's
    snapshot on every restart would silently roll the team back to whatever the
    sheet looked like at build time — so we only load it when the table is
    empty, or when running without n8n (`DASHBOARD_SOURCE=graph`).
    """
    db.init_db()
    with db.get_conn() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM engagements").fetchone()[0]

    if api.DASHBOARD_SOURCE == "db" and existing:
        print(f"[startup] engagements: keeping {existing} n8n-synced rows "
              "(skipping the bundled Excel snapshot)")
        return

    n = engagement.load_engagements(reference_today())
    print(f"[startup] engagements: loaded {n} rows from the bundled sheet")


# ---------------------------------------------------------------- auth routes
@app.get("/auth/login")
def login():
    """Kick off Microsoft sign-in. Each teammate authenticates their own account."""
    return RedirectResponse(auth.begin_login())


@app.get("/auth/callback")
def callback(request: Request):
    result = auth.complete_login(request.query_params)
    if "access_token" not in result:
        return JSONResponse(
            {"error": result.get("error", "login_failed"),
             "detail": result.get("error_description")},
            status_code=400,
        )
    claims = result.get("id_token_claims") or {}
    username = claims.get("preferred_username")

    # Shared deployments are reachable by anyone who can hit the URL, so the
    # tenant's own check is backed up with an explicit domain allowlist.
    if not auth.email_allowed(username):
        return JSONResponse(
            {"error": "account_not_permitted",
             "detail": f"{username} is not allowed to use this dashboard."},
            status_code=403,
        )

    hid = claims.get("home_account_id") or (
        f"{claims.get('oid')}.{claims.get('tid')}" if claims.get("oid") else None
    )
    # Prefer the authoritative id from the freshly-cached account.
    accounts = auth.get_msal_app().get_accounts(username=username)
    if accounts:
        hid = accounts[0]["home_account_id"]
    sid = auth.create_session(hid, username, claims.get("name"))
    resp = RedirectResponse("/")  # back to the single-window dashboard
    resp.set_cookie(
        SESSION_COOKIE, sid, httponly=True, samesite="lax",
        # Required once the app is served over HTTPS; must stay off for a plain
        # http:// host or the browser silently drops the session cookie.
        secure=auth.PUBLIC_BASE_URL.startswith("https://"),
        max_age=60 * 60 * 24 * 30, path="/",
    )
    return resp


@app.get("/auth/me")
def whoami(user: dict = Depends(require_user)):
    s = user["session"]
    return {"name": s.get("name"), "email": s.get("username")}


@app.post("/auth/logout")
def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    if sid:
        auth.delete_session(sid)
    resp = JSONResponse({"status": "signed_out"})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------ legacy inbox agent (per-user)
class ChatIn(BaseModel):
    message: str
    thread_id: str = "default"


def _reply_from(result: dict) -> str:
    last = result["messages"][-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    pending = getattr(last, "tool_calls", None) or []
    if pending:
        calls = "\n".join(f"• {c['name']}({c['args']})" for c in pending)
        note = f"⏸ I want to run:\n{calls}\n\nClick Approve to continue."
        return f"{text}\n\n{note}".strip() if text else note
    return text


def _cancel_pending_tools(config: dict) -> None:
    state = agent.get_state(config)
    if not state.next:
        return
    last = state.values["messages"][-1]
    pending = getattr(last, "tool_calls", None) or []
    if pending:
        cancels = [
            ToolMessage(
                content="Tool call not executed — the user sent a new message instead of approving.",
                tool_call_id=c["id"],
            )
            for c in pending
        ]
        agent.update_state(config, {"messages": cancels}, as_node="tools")


@app.post("/chat")
def chat(inp: ChatIn, user: dict = Depends(require_user)):
    # Thread is namespaced per user so teammates don't share conversation state.
    thread = f"{user['session']['home_account_id']}:{inp.thread_id}"
    config = {"configurable": {"thread_id": thread}}
    _cancel_pending_tools(config)
    try:
        result = agent.invoke({"messages": [HumanMessage(inp.message)]}, config)
    except ValueError:
        try:
            agent.checkpointer.delete_thread(thread)
        except Exception:
            pass
        result = agent.invoke({"messages": [HumanMessage(inp.message)]}, config)
        return {"reply": "_(previous conversation was reset)_\n\n" + _reply_from(result)}
    return {"reply": _reply_from(result)}


@app.post("/chat/approve")
def approve(inp: ChatIn, user: dict = Depends(require_user)):
    thread = f"{user['session']['home_account_id']}:{inp.thread_id}"
    config = {"configurable": {"thread_id": thread}}
    if not agent.get_state(config).next:
        return {"reply": "Nothing is waiting for approval right now."}
    result = agent.invoke(None, config)
    return {"reply": _reply_from(result)}


# ----------------------------------------------- single-window static frontend
# Serve the built Next.js export so the whole app lives on one URL (this port).
# Mounted LAST so it never shadows the API/auth routes above.
_FRONTEND_DIR = os.environ.get(
    "FRONTEND_DIR",
    os.path.join(os.path.dirname(__file__), "..", "frontend", "out"),
)
if os.path.isdir(_FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
