import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from langchain_core.messages import HumanMessage, ToolMessage
from pydantic import BaseModel

import auth
import graph_tools
from agent import agent

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/auth/login")
def login():
    return RedirectResponse(auth.get_auth_url())


@app.get("/auth/callback")
def callback(
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    if error:
        # Microsoft redirected back with an error instead of an auth code
        return JSONResponse(
            {"error": error, "error_description": error_description}, status_code=400
        )
    if not code:
        return JSONResponse(
            {"error": "missing_code", "hint": "Start the flow at /auth/login"},
            status_code=400,
        )
    result = auth.redeem_code(code)
    if "access_token" in result:
        return JSONResponse({"status": "connected"})
    return JSONResponse(result, status_code=400)


@app.get("/debug/unread")
def debug_unread():
    """Temporary endpoint to verify Graph access. Remove before deploying."""
    return graph_tools.list_unread()


class ChatIn(BaseModel):
    message: str
    thread_id: str = "default"


def _reply_from(result: dict) -> str:
    """Turn the agent result into a user-facing reply, including pending tool calls."""
    last = result["messages"][-1]
    text = last.content if isinstance(last.content, str) else str(last.content)
    pending = getattr(last, "tool_calls", None) or []
    if pending:
        calls = "\n".join(f"• {c['name']}({c['args']})" for c in pending)
        note = f"⏸ I want to run:\n{calls}\n\nClick Approve to continue."
        return f"{text}\n\n{note}".strip() if text else note
    return text


def _cancel_pending_tools(config: dict) -> None:
    """If the agent is paused on tool calls, mark them cancelled so a new
    user message doesn't corrupt the chat history."""
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
def chat(inp: ChatIn):
    config = {"configurable": {"thread_id": inp.thread_id}}
    _cancel_pending_tools(config)
    try:
        result = agent.invoke({"messages": [HumanMessage(inp.message)]}, config)
    except ValueError:
        # Corrupted thread state (e.g. from before this fix) — start it fresh
        try:
            agent.checkpointer.delete_thread(inp.thread_id)
        except Exception:
            pass
        result = agent.invoke({"messages": [HumanMessage(inp.message)]}, config)
        return {"reply": "_(previous conversation was reset)_\n\n" + _reply_from(result)}
    return {"reply": _reply_from(result)}


@app.post("/chat/approve")
def approve(inp: ChatIn):
    """Resume a paused (interrupted) run — i.e., the user approved the tool call."""
    config = {"configurable": {"thread_id": inp.thread_id}}
    if not agent.get_state(config).next:
        return {"reply": "Nothing is waiting for approval right now."}
    result = agent.invoke(None, config)  # None = resume from interrupt
    return {"reply": _reply_from(result)}
