// Mirrors the normalised payload from the backend /api/dashboard endpoint.
// The dashboard is source-agnostic: whether a row came from n8n or the sample
// seeder, it looks identical here.

export type RangeKey = "24h" | "48h" | "7d" | "30d" | "custom";

export interface EmailRow {
  id: string;
  direction: "received" | "sent";
  subject: string | null;
  preview: string | null;
  contact_name: string | null;
  contact_email: string | null;
  organisation: string | null;
  topic: string | null; // enriched from the engagement sheet
  ts: string;
  is_external: boolean;
}

export interface MeetingRow {
  id: string;
  subject: string | null;
  organisation: string | null;
  contact_name: string | null;
  contact_email: string | null;
  start_ts: string;
  end_ts: string | null;
  location: string | null;
  attendees: string[];
  followup_status?: "pending" | "done" | "none";
  is_external: boolean;
}

export interface FollowupRow {
  organisation: string | null;
  contact_name: string | null;
  email: string | null;
  topic: string | null;
  message_hook: string | null;
  next_followup_raw: string | null;
  next_followup_date: string | null;
  last_contact_raw: string | null;
  last_contact_date: string | null;
  days_overdue: number | null;
}

export interface OverviewRow {
  organisation: string;
  emails: number;
  meetings: number;
}

export interface DashboardData {
  meta: {
    today: string;
    range: RangeKey;
    range_start: string;
    range_end: string;
    // All three describe the same window — the selected range, applied forward
    // for upcoming meetings and backward for emails and past meetings.
    window_hours: number;
    upcoming_days: number;
    past_days: number;
    user: { name: string | null; email: string | null };
    warnings: string[];
  };
  kpis: {
    emails_received: number;
    emails_sent: number;
    followups_today: number;
    followups_pending: number;
    meetings_upcoming: number;
    meetings_past: number;
  };
  emails_received: EmailRow[];
  emails_sent: EmailRow[];
  followups_today: FollowupRow[];
  followups_pending: FollowupRow[];
  meetings_upcoming: MeetingRow[];
  meetings_past: MeetingRow[];
}

// Same-origin by default (backend serves this build). Override for split dev.
export const API = process.env.NEXT_PUBLIC_API_URL ?? "";

export interface Me {
  name: string | null;
  email: string | null;
}

/** Returns the signed-in user, or null if not authenticated (401). */
export async function fetchMe(): Promise<Me | null> {
  const res = await fetch(`${API}/auth/me`, { credentials: "include", cache: "no-store" });
  if (res.status === 401) return null;
  if (!res.ok) throw new Error(`Auth check failed (${res.status})`);
  return res.json();
}

export async function logout(): Promise<void> {
  await fetch(`${API}/auth/logout`, { method: "POST", credentials: "include" });
}

export class AuthError extends Error {}

export async function fetchDashboard(
  range: RangeKey,
  start?: string,
  end?: string
): Promise<DashboardData> {
  const params = new URLSearchParams({ range });
  if (range === "custom" && start) {
    params.set("start", start);
    if (end) params.set("end", end);
  }
  const res = await fetch(`${API}/api/dashboard?${params.toString()}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 401) throw new AuthError("not signed in");
  if (!res.ok) throw new Error(`Backend error ${res.status}`);
  return res.json();
}

export interface RefreshResult {
  source: "graph" | "db";
  stored_emails: number;
  stored_meetings: number;
  warnings: string[];
  refreshed_at: string;
}

/**
 * Pull the signed-in user's latest mail/calendar from Microsoft on demand,
 * rather than waiting for n8n's next scheduled run. A no-op in 'graph' mode,
 * where every dashboard load is already live.
 */
export async function refreshNow(hours = 24): Promise<RefreshResult> {
  const res = await fetch(`${API}/api/refresh?hours=${hours}`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
  });
  if (res.status === 401) throw new AuthError("not signed in");
  if (!res.ok) throw new Error(`Refresh failed (${res.status})`);
  return res.json();
}