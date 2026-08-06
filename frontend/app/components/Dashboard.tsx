"use client";

import { useCallback, useEffect, useState } from "react";
import {
  API,
  AuthError,
  DashboardData,
  EmailRow,
  FollowupRow,
  Me,
  MeetingRow,
  OverviewRow,
  RangeKey,
  fetchDashboard,
  fetchMe,
  logout as apiLogout,
  refreshNow,
} from "../lib/types";

/* ------------------------------------------------------------------ helpers */

const RANGES: { key: RangeKey; label: string }[] = [
  { key: "24h", label: "24 hours" },
  { key: "48h", label: "48 hours" },
  { key: "7d", label: "7 days" },
  { key: "30d", label: "30 days" },
  { key: "custom", label: "Custom" },
];

/** The selected range, phrased for section hints ("next 24 hours"). */
function windowLabel(range: RangeKey): string {
  if (range === "custom") return "selected range";
  return RANGES.find((r) => r.key === range)?.label ?? "7 days";
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function timeOnly(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function relative(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "";
  const diff = Date.now() - d.getTime();
  const h = Math.round(diff / 3.6e6);
  if (h < 1) return "just now";
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function initials(name: string | null): string {
  if (!name) return "?";
  return name
    .replace(/\(.*?\)/g, "")
    .split(/[\s,]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase())
    .join("");
}

/* --------------------------------------------------------------- primitives */

function Avatar({ name }: { name: string | null }) {
  return (
    <div
      className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-semibold"
      style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
    >
      {initials(name)}
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="inline-block text-[11px] leading-none px-2 py-1 rounded-md font-medium"
      style={{ background: "var(--surface-2)", color: "var(--text-muted)", border: "1px solid var(--border)" }}
    >
      {children}
    </span>
  );
}

function Section({
  title,
  hint,
  count,
  action,
  children,
}: {
  title: string;
  hint?: string;
  count?: number;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      className="rounded-2xl flex flex-col"
      style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}
    >
      <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-[13px] font-semibold tracking-tight" style={{ color: "var(--text)" }}>
            {title}
          </h2>
          {typeof count === "number" && (
            <span
              className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md tabular-nums"
              style={{ background: "var(--surface-2)", color: "var(--text-muted)", border: "1px solid var(--border)" }}
            >
              {count}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hint && (
            <span className="text-[11px] hidden sm:inline" style={{ color: "var(--text-faint)" }}>
              {hint}
            </span>
          )}
          {action}
        </div>
      </header>
      <div className="px-2 pb-2 flex-1">{children}</div>
    </section>
  );
}

/* -------------------------------------------------------- internal/external */

type CommFilter = "external" | "internal" | "all";

const COMM_OPTIONS: { key: CommFilter; label: string }[] = [
  { key: "external", label: "External" },
  { key: "internal", label: "Internal" },
  { key: "all", label: "All" },
];

function SegFilter({
  value,
  onChange,
}: {
  value: CommFilter;
  onChange: (v: CommFilter) => void;
}) {
  return (
    <div
      className="flex items-center gap-0.5 p-0.5 rounded-lg"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
    >
      {COMM_OPTIONS.map((o) => {
        const active = value === o.key;
        return (
          <button
            key={o.key}
            onClick={() => onChange(o.key)}
            className="text-[11px] font-medium px-2 py-1 rounded-md transition-colors"
            style={{
              background: active ? "var(--accent)" : "transparent",
              color: active ? "#fff" : "var(--text-muted)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

function matchesComm(isExternal: boolean, f: CommFilter): boolean {
  return f === "all" ? true : f === "external" ? isExternal : !isExternal;
}

function Empty({ label }: { label: string }) {
  return (
    <div className="px-3 py-8 text-center text-[13px]" style={{ color: "var(--text-faint)" }}>
      {label}
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex gap-3 px-3 py-2.5 rounded-xl transition-colors hover:[background:var(--surface-2)]"
    >
      {children}
    </div>
  );
}

/* ------------------------------------------------------------------- pieces */

function EmailItem({ e }: { e: EmailRow }) {
  return (
    <Row>
      <Avatar name={e.contact_name || e.organisation} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-medium truncate" style={{ color: "var(--text)" }}>
            {e.contact_name || e.contact_email || "Unknown"}
          </span>
          <span className="text-[11px] shrink-0 tabular-nums" style={{ color: "var(--text-faint)" }}>
            {relative(e.ts)}
          </span>
        </div>
        <div className="text-[13px] truncate" style={{ color: "var(--text-muted)" }}>
          {e.subject || "(no subject)"}
        </div>
        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
          {e.organisation && <Chip>{e.organisation}</Chip>}
          {e.topic && <Chip>{e.topic}</Chip>}
        </div>
      </div>
    </Row>
  );
}

function StatusBadge({ status }: { status?: string }) {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    pending: { label: "Follow-up pending", color: "var(--warn)", bg: "color-mix(in srgb, var(--warn) 14%, transparent)" },
    done: { label: "Followed up", color: "var(--good)", bg: "color-mix(in srgb, var(--good) 14%, transparent)" },
    none: { label: "No action", color: "var(--text-muted)", bg: "var(--surface-2)" },
  };
  const s = map[status || "none"] ?? map.none;
  return (
    <span
      className="inline-flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded-md whitespace-nowrap"
      style={{ color: s.color, background: s.bg }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: s.color }} />
      {s.label}
    </span>
  );
}

function MeetingItem({ m, past }: { m: MeetingRow; past?: boolean }) {
  return (
    <Row>
      <div className="shrink-0 w-11 text-center">
        <div className="text-[11px] uppercase tracking-wide" style={{ color: "var(--text-faint)" }}>
          {new Date(m.start_ts).toLocaleDateString(undefined, { weekday: "short" })}
        </div>
        <div className="text-[15px] font-semibold tabular-nums" style={{ color: "var(--text)" }}>
          {new Date(m.start_ts).getDate()}
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium truncate" style={{ color: "var(--text)" }}>
          {m.subject || m.organisation || "Meeting"}
        </div>
        <div className="text-[12px] mt-0.5" style={{ color: "var(--text-muted)" }}>
          {timeOnly(m.start_ts)}
          {m.end_ts ? `–${timeOnly(m.end_ts)}` : ""} · {m.location || "—"}
        </div>
        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
          {m.organisation && <Chip>{m.organisation}</Chip>}
          {past && <StatusBadge status={m.followup_status} />}
        </div>
      </div>
    </Row>
  );
}

function FollowupItem({ f }: { f: FollowupRow }) {
  const overdue = (f.days_overdue ?? 0) > 0;
  return (
    <Row>
      <Avatar name={f.contact_name || f.organisation} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[13px] font-medium truncate" style={{ color: "var(--text)" }}>
            {f.contact_name || "—"}
          </span>
          {overdue ? (
            <span
              className="text-[11px] font-semibold px-1.5 py-0.5 rounded-md whitespace-nowrap"
              style={{ color: "var(--danger)", background: "color-mix(in srgb, var(--danger) 12%, transparent)" }}
            >
              {f.days_overdue}d overdue
            </span>
          ) : (
            <span className="text-[11px] shrink-0" style={{ color: "var(--text-faint)" }}>
              due {fmtDate(f.next_followup_date)}
            </span>
          )}
        </div>
        {f.message_hook || f.topic ? (
          <div className="text-[13px] truncate" style={{ color: "var(--text-muted)" }}>
            {f.message_hook || f.topic}
          </div>
        ) : null}
        <div className="flex items-center gap-1.5 mt-1.5 flex-wrap">
          {f.organisation && <Chip>{f.organisation}</Chip>}
          {f.topic && f.message_hook && <Chip>{f.topic}</Chip>}
          {f.last_contact_date && <Chip>last contact {fmtDate(f.last_contact_date)}</Chip>}
        </div>
      </div>
    </Row>
  );
}

/* --------------------------------------------------- org communication chart */

function OrgOverview({ rows }: { rows: OverviewRow[] }) {
  const top = rows.slice(0, 8);
  const max = Math.max(1, ...top.map((r) => Math.max(r.emails, r.meetings)));
  if (top.length === 0) return <Empty label="No communications in this range." />;

  const Bar = ({ value, color }: { value: number; color: string }) => (
    <div className="flex items-center gap-2 h-[18px]">
      <div className="flex-1 h-[10px] rounded-[3px] overflow-hidden" style={{ background: "var(--surface-2)" }}>
        <div
          className="h-full rounded-[3px]"
          style={{ width: `${(value / max) * 100}%`, background: color, minWidth: value > 0 ? 4 : 0 }}
        />
      </div>
      <span className="text-[11px] w-4 text-right tabular-nums" style={{ color: "var(--text-muted)" }}>
        {value}
      </span>
    </div>
  );

  return (
    <div className="px-3 pt-1 pb-3">
      <div className="flex items-center gap-4 mb-3">
        <span className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-muted)" }}>
          <span className="w-2.5 h-2.5 rounded-[3px]" style={{ background: "var(--series-emails)" }} /> Emails
        </span>
        <span className="inline-flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-muted)" }}>
          <span className="w-2.5 h-2.5 rounded-[3px]" style={{ background: "var(--series-meetings)" }} /> Meetings / calls
        </span>
      </div>
      <div className="space-y-3">
        {top.map((r) => (
          <div key={r.organisation} className="grid grid-cols-[120px_1fr] gap-3 items-center">
            <div className="text-[12px] truncate" style={{ color: "var(--text)" }} title={r.organisation}>
              {r.organisation}
            </div>
            <div className="space-y-1">
              <Bar value={r.emails} color="var(--series-emails)" />
              <Bar value={r.meetings} color="var(--series-meetings)" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ KPI tile */

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "danger" | "warn" | "accent";
}) {
  const color =
    tone === "danger" ? "var(--danger)" : tone === "warn" ? "var(--warn)" : "var(--text)";
  return (
    <div
      className="rounded-xl px-4 py-3 flex flex-col gap-1"
      style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}
    >
      <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: "var(--text-faint)" }}>
        {label}
      </span>
      <span className="text-2xl font-semibold tabular-nums leading-none" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

/* ------------------------------------------------------------- sign-in gate */

function SignIn() {
  return (
    <div className="min-h-screen flex items-center justify-center px-6" style={{ background: "var(--bg)" }}>
      <div
        className="w-full max-w-sm rounded-2xl px-8 py-10 text-center"
        style={{ background: "var(--surface)", border: "1px solid var(--border)", boxShadow: "var(--shadow)" }}
      >
        <div
          className="w-12 h-12 rounded-2xl mx-auto mb-5 flex items-center justify-center text-xl font-semibold"
          style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
        >
          RI
        </div>
        <h1 className="text-lg font-semibold tracking-tight" style={{ color: "var(--text)" }}>
          Relationship Intelligence
        </h1>
        <p className="text-[13px] mt-1.5 mb-7" style={{ color: "var(--text-muted)" }}>
          Sign in with your work Microsoft account to see your own external
          communications, meetings, and follow-ups.
        </p>
        <a
          href={`${API}/auth/login`}
          className="flex items-center justify-center gap-2.5 w-full py-2.5 rounded-xl text-[14px] font-medium text-white transition-opacity hover:opacity-90"
          style={{ background: "var(--accent)" }}
        >
          <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden>
            <rect x="1" y="1" width="9" height="9" fill="#f25022" />
            <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
            <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
            <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
          </svg>
          Sign in with Microsoft
        </a>
        <p className="text-[11px] mt-6" style={{ color: "var(--text-faint)" }}>
          Each teammate sees only their own mailbox and calendar.
        </p>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- dashboard */

export default function Dashboard() {
  const [me, setMe] = useState<Me | null | undefined>(undefined); // undefined = checking
  const [range, setRange] = useState<RangeKey>("7d");
  const [custom, setCustom] = useState<{ start: string; end: string }>({ start: "", end: "" });
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Per-section internal/external filters (default to external engagement).
  const [upFilter, setUpFilter] = useState<CommFilter>("external");
  const [pastFilter, setPastFilter] = useState<CommFilter>("external");
  const [ovFilter, setOvFilter] = useState<CommFilter>("external");

  // Auth check on mount.
  useEffect(() => {
    fetchMe()
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchDashboard(
        range,
        custom.start ? new Date(custom.start).toISOString() : undefined,
        custom.end ? new Date(custom.end).toISOString() : undefined
      );
      setData(d);
    } catch (e) {
      if (e instanceof AuthError) {
        setMe(null); // session expired — drop back to sign-in
        return;
      }
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, [range, custom]);

  useEffect(() => {
    if (!me) return; // only load once signed in
    if (range === "custom" && !custom.start) return; // wait for a start date
    load();
  }, [me, load, range, custom.start]);

  // Pull anything that arrived since n8n's last scheduled run, then reload.
  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError(null);
    try {
      await refreshNow();
      await load();
      setRefreshedAt(new Date());
    } catch (e) {
      if (e instanceof AuthError) {
        setMe(null);
        return;
      }
      setError(e instanceof Error ? e.message : "Refresh failed");
    } finally {
      setRefreshing(false);
    }
  }, [load]);

  async function signOut() {
    await apiLogout();
    setMe(null);
    setData(null);
  }

  if (me === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center text-[14px]"
        style={{ background: "var(--bg)", color: "var(--text-faint)" }}>
        Loading…
      </div>
    );
  }
  if (me === null) return <SignIn />;

  const k = data?.kpis;
  const displayName = me.name || me.email || "Signed in";

  // The email sections stay external-only (as before); meetings + overview are
  // driven by their own internal/external filter.
  const receivedExt = (data?.emails_received ?? []).filter((e) => e.is_external);
  const sentExt = (data?.emails_sent ?? []).filter((e) => e.is_external);
  const upcoming = (data?.meetings_upcoming ?? []).filter((m) => matchesComm(m.is_external, upFilter));
  const past = (data?.meetings_past ?? []).filter((m) => matchesComm(m.is_external, pastFilter));

  // Communication overview — how much contact each organisation actually had
  // within the selected range.
  //
  // Only things that HAVE happened are counted: emails sent/received, and
  // meetings that already took place. Upcoming meetings are deliberately
  // excluded — a meeting scheduled for next week is not contact that occurred,
  // and counting it inflated every org with something on the calendar.
  const overview: OverviewRow[] = (() => {
    if (!data) return [];
    const map = new Map<string, OverviewRow>();
    const bump = (org: string | null, key: "emails" | "meetings") => {
      if (!org) return;
      const row = map.get(org) ?? { organisation: org, emails: 0, meetings: 0 };
      row[key] += 1;
      map.set(org, row);
    };
    [...data.emails_received, ...data.emails_sent]
      .filter((e) => matchesComm(e.is_external, ovFilter))
      .forEach((e) => bump(e.organisation, "emails"));
    data.meetings_past
      .filter((m) => matchesComm(m.is_external, ovFilter))
      .forEach((m) => bump(m.organisation, "meetings"));
    return [...map.values()].sort((a, b) => b.emails + b.meetings - (a.emails + a.meetings));
  })();

  return (
    <div className="min-h-screen" style={{ background: "var(--bg)" }}>
      <div className="max-w-6xl mx-auto px-5 sm:px-8 py-8">
        {/* Header */}
        <header className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-xl font-semibold tracking-tight" style={{ color: "var(--text)" }}>
              Relationship Intelligence
            </h1>
            <p className="text-[13px] mt-0.5" style={{ color: "var(--text-muted)" }}>
              Your external communications, meetings, and follow-ups — at a glance.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div
              className="flex items-center gap-0.5 p-1 rounded-xl"
              style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
            >
              {RANGES.map((r) => {
                const active = range === r.key;
                return (
                  <button
                    key={r.key}
                    onClick={() => setRange(r.key)}
                    className="text-[12px] font-medium px-3 py-1.5 rounded-lg transition-colors"
                    style={{
                      background: active ? "var(--accent)" : "transparent",
                      color: active ? "#fff" : "var(--text-muted)",
                    }}
                  >
                    {r.label}
                  </button>
                );
              })}
            </div>
            {/* Pull anything that landed since the last scheduled sync. */}
            <button
              onClick={refresh}
              disabled={refreshing || loading}
              title={
                refreshedAt
                  ? `Last refreshed ${refreshedAt.toLocaleTimeString([], {
                      hour: "2-digit",
                      minute: "2-digit",
                    })}`
                  : "Check Microsoft for new emails and meetings"
              }
              className="flex items-center gap-1.5 text-[12px] font-medium px-3 py-2 rounded-xl transition-colors disabled:opacity-60 disabled:cursor-not-allowed hover:[background:var(--surface-2)]"
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                color: "var(--text-muted)",
              }}
            >
              <span
                aria-hidden
                className={refreshing ? "inline-block animate-spin" : "inline-block"}
              >
                ↻
              </span>
              <span className="hidden sm:inline">
                {refreshing ? "Refreshing…" : "Refresh"}
              </span>
            </button>

            {/* User menu */}
            <div
              className="flex items-center gap-2 pl-1.5 pr-2 py-1 rounded-xl"
              style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
            >
              <div
                className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-semibold"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
                title={me.email || ""}
              >
                {initials(displayName)}
              </div>
              <div className="hidden sm:flex flex-col leading-tight max-w-[140px]">
                <span className="text-[12px] font-medium truncate" style={{ color: "var(--text)" }}>
                  {displayName}
                </span>
                {me.email && (
                  <span className="text-[10.5px] truncate" style={{ color: "var(--text-faint)" }}>
                    {me.email}
                  </span>
                )}
              </div>
              <button
                onClick={signOut}
                className="text-[11px] font-medium px-2 py-1 rounded-lg transition-colors hover:[background:var(--surface-2)]"
                style={{ color: "var(--text-muted)" }}
              >
                Sign out
              </button>
            </div>
          </div>
        </header>

        {range === "custom" && (
          <div
            className="flex flex-wrap items-center gap-3 mb-6 px-4 py-3 rounded-xl text-[13px]"
            style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
          >
            <span style={{ color: "var(--text-muted)" }}>From</span>
            <input
              type="date"
              value={custom.start}
              onChange={(e) => setCustom((c) => ({ ...c, start: e.target.value }))}
              className="px-2 py-1 rounded-md bg-transparent"
              style={{ border: "1px solid var(--border-strong)", color: "var(--text)" }}
            />
            <span style={{ color: "var(--text-muted)" }}>to</span>
            <input
              type="date"
              value={custom.end}
              onChange={(e) => setCustom((c) => ({ ...c, end: e.target.value }))}
              className="px-2 py-1 rounded-md bg-transparent"
              style={{ border: "1px solid var(--border-strong)", color: "var(--text)" }}
            />
          </div>
        )}

        {/* Live-data notice: some Graph calls failed (e.g. calendar scope not
            consented yet). Emails/meetings are the signed-in user's own. */}
        {data && data.meta.warnings.length > 0 && (
          <div
            className="flex items-center gap-2 mb-6 px-4 py-2.5 rounded-xl text-[12.5px]"
            style={{ background: "color-mix(in srgb, var(--warn) 12%, transparent)", color: "var(--warn)", border: "1px solid var(--border)" }}
          >
            <span>⚠</span>
            <span>
              Some Microsoft data couldn’t be loaded ({data.meta.warnings.join(", ")}).
              This usually means a Graph permission (e.g. Calendars.Read) hasn’t been
              consented yet.
            </span>
          </div>
        )}

        {error && (
          <div
            className="mb-6 px-4 py-3 rounded-xl text-[13px]"
            style={{ background: "color-mix(in srgb, var(--danger) 10%, transparent)", color: "var(--danger)" }}
          >
            Couldn’t reach the backend ({error}). Is it running on {API}?
          </div>
        )}

        {/* KPI row */}
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 mb-6">
          <Kpi label="Received" value={k?.emails_received ?? 0} />
          <Kpi label="Sent" value={k?.emails_sent ?? 0} />
          <Kpi label="Due today" value={k?.followups_today ?? 0} tone="warn" />
          <Kpi label="Pending" value={k?.followups_pending ?? 0} tone="danger" />
          <Kpi label="Upcoming" value={k?.meetings_upcoming ?? 0} tone="accent" />
          <Kpi label="Past" value={k?.meetings_past ?? 0} />
        </div>

        {loading && !data ? (
          <div className="text-center py-20 text-[14px]" style={{ color: "var(--text-faint)" }}>
            Loading…
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Follow-ups take priority — full attention row */}
            <Section title="Today’s follow-ups" count={data?.followups_today.length}>
              {data && data.followups_today.length ? (
                data.followups_today.map((f, i) => <FollowupItem key={i} f={f} />)
              ) : (
                <Empty label="Nothing due today. You’re all caught up." />
              )}
            </Section>

            <Section title="Pending follow-ups" hint="overdue from earlier" count={data?.followups_pending.length}>
              {data && data.followups_pending.length ? (
                data.followups_pending.map((f, i) => <FollowupItem key={i} f={f} />)
              ) : (
                <Empty label="No overdue follow-ups." />
              )}
            </Section>

            <Section title="External emails received" count={receivedExt.length}>
              {receivedExt.length ? (
                receivedExt.map((e) => <EmailItem key={e.id} e={e} />)
              ) : (
                <Empty label="No external emails received in this range." />
              )}
            </Section>

            <Section title="External emails sent" count={sentExt.length}>
              {sentExt.length ? (
                sentExt.map((e) => <EmailItem key={e.id} e={e} />)
              ) : (
                <Empty label="No external emails sent in this range." />
              )}
            </Section>

            <Section
              title="Upcoming meetings"
              hint={`next ${windowLabel(range)}`}
              count={upcoming.length}
              action={<SegFilter value={upFilter} onChange={setUpFilter} />}
            >
              {upcoming.length ? (
                upcoming.map((m) => <MeetingItem key={m.id} m={m} />)
              ) : (
                <Empty label={`No ${upFilter === "all" ? "" : upFilter + " "}meetings in the next ${windowLabel(range)}.`} />
              )}
            </Section>

            <Section
              title="Past meetings"
              hint={`previous ${windowLabel(range)}`}
              count={past.length}
              action={<SegFilter value={pastFilter} onChange={setPastFilter} />}
            >
              {past.length ? (
                past.map((m) => <MeetingItem key={m.id} m={m} past />)
              ) : (
                <Empty label={`No ${pastFilter === "all" ? "" : pastFilter + " "}meetings in the previous week.`} />
              )}
            </Section>

            {/* Communication overview spans both columns */}
            <div className="lg:col-span-2">
              <Section
                title="Communication overview"
                hint="emails vs. meetings by organisation"
                action={<SegFilter value={ovFilter} onChange={setOvFilter} />}
              >
                <OrgOverview rows={overview} />
              </Section>
            </div>
          </div>
        )}

        <footer className="mt-8 text-center text-[11px]" style={{ color: "var(--text-faint)" }}>
          Live from your Microsoft account · engagement sheet is read-only ·{" "}
          {data?.meta.today ? `as of ${fmtDate(data.meta.today)}` : ""}
        </footer>
      </div>
    </div>
  );
}