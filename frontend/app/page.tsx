"use client";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

type Msg = { role: "user" | "assistant"; content: string };

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// LLMs occasionally emit HTML inside Markdown; convert the common cases to
// real Markdown so they don't render as literal tags.
function cleanMarkdown(text: string): string {
  return text
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/?b>/gi, "**")
    .replace(/<\/?i>/gi, "*")
    .replace(/&nbsp;/gi, " ");
}

const SUGGESTIONS = [
  "Summarize my unread emails",
  "Any urgent emails today?",
  "Search for emails about meetings",
  "Draft a reply to the latest GitHub alert",
];

export default function Chat() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const lastMsg = messages[messages.length - 1];
  const needsApproval =
    !loading && lastMsg?.role === "assistant" && lastMsg.content.includes("⏸");

  async function call(path: string, message: string) {
    setLoading(true);
    try {
      const res = await fetch(`${API}${path}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, thread_id: "default" }),
      });
      if (!res.ok) {
        const body = await res.text();
        setMessages((m) => [
          ...m,
          { role: "assistant", content: `⚠️ Backend error (${res.status}): ${body.slice(0, 300)}` },
        ]);
        return;
      }
      const data = await res.json();
      setMessages((m) => [
        ...m,
        { role: "assistant", content: data.reply || "(empty reply)" },
      ]);
    } catch {
      setMessages((m) => [
        ...m,
        { role: "assistant", content: "⚠️ Could not reach the backend on port 8000." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  function send(text?: string) {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    setMessages((m) => [...m, { role: "user", content: msg }]);
    setInput("");
    call("/chat", msg);
  }

  function approve() {
    if (loading) return;
    setMessages((m) => [...m, { role: "user", content: "✅ Approved" }]);
    call("/chat/approve", "");
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-cyan-50 text-gray-900">
      <main className="max-w-3xl mx-auto flex flex-col h-screen px-4">
        {/* Header */}
        <header className="flex items-center justify-between py-4 border-b border-gray-200/70">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-white text-xl shadow-md">
              📬
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight">Inbox Assistant</h1>
              <p className="text-xs text-gray-500 flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-green-500 inline-block" />
                Outlook connected · GPT-OSS 120B
              </p>
            </div>
          </div>
          <a
            href={`${API}/auth/login`}
            target="_blank"
            className="text-xs font-medium text-indigo-600 bg-indigo-50 hover:bg-indigo-100 px-3 py-1.5 rounded-full transition"
          >
            Reconnect Outlook
          </a>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto py-6 space-y-4">
          {messages.length === 0 && (
            <div className="text-center mt-16 space-y-6">
              <div className="text-5xl">✉️</div>
              <div>
                <p className="text-lg font-semibold">What&apos;s in your inbox?</p>
                <p className="text-sm text-gray-500">
                  Ask me to triage, search, summarize, or draft replies.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => send(s)}
                    className="text-sm bg-white border border-gray-200 hover:border-indigo-300 hover:bg-indigo-50 px-4 py-2 rounded-full shadow-sm transition"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) => (
            <div
              key={i}
              className={`flex gap-2.5 ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              {m.role === "assistant" && (
                <div className="w-8 h-8 shrink-0 rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-sm text-white shadow">
                  🤖
                </div>
              )}
              <div
                className={`max-w-[85%] px-4 py-3 rounded-2xl shadow-sm ${
                  m.role === "user"
                    ? "bg-indigo-600 text-white rounded-br-md"
                    : "bg-white border border-gray-100 rounded-bl-md"
                }`}
              >
                {m.role === "assistant" ? (
                  <div className="prose prose-sm max-w-none prose-table:text-xs prose-th:px-2 prose-td:px-2 prose-td:py-1 prose-th:py-1 prose-headings:mt-3 prose-headings:mb-2 prose-p:my-2 prose-li:my-0.5 overflow-x-auto">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {cleanMarkdown(m.content)}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <span className="whitespace-pre-wrap">{m.content}</span>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex gap-2.5">
              <div className="w-8 h-8 shrink-0 rounded-xl bg-gradient-to-br from-indigo-500 to-cyan-500 flex items-center justify-center text-sm text-white shadow">
                🤖
              </div>
              <div className="bg-white border border-gray-100 px-4 py-3 rounded-2xl rounded-bl-md shadow-sm flex items-center gap-1.5">
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-2 h-2 bg-indigo-400 rounded-full animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          )}

          {needsApproval && (
            <div className="flex justify-center">
              <button
                onClick={approve}
                className="bg-green-600 hover:bg-green-700 text-white font-medium px-6 py-2.5 rounded-full shadow-md transition animate-pulse"
              >
                ✅ Approve &amp; continue
              </button>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Composer */}
        <div className="pb-5 pt-2">
          <div className="flex gap-2 bg-white border border-gray-200 rounded-2xl p-2 shadow-lg">
            <input
              className="flex-1 px-3 py-2 outline-none bg-transparent placeholder:text-gray-400"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Ask about your inbox…"
            />
            <button
              onClick={() => send()}
              disabled={loading || !input.trim()}
              className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 text-white px-5 py-2 rounded-xl font-medium transition"
            >
              Send
            </button>
          </div>
          <p className="text-center text-[11px] text-gray-400 mt-2">
            The agent pauses for your approval before touching your mailbox.
          </p>
        </div>
      </main>
    </div>
  );
}
