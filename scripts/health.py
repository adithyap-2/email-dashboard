"""Health check for the Relationship Intelligence Dashboard.

Run it after a deployment, or whenever the dashboard looks wrong:

    docker compose exec app python /app/scripts/health.py

It answers the questions that have actually gone wrong in practice, none of
which surface as errors anywhere:

  * is a mailbox silently missing (not in n8n's Config list)?
  * is a busy mailbox being truncated by the Graph page-size cap?
  * has the SharePoint engagement sheet stopped syncing?
  * is anyone's data stale because scheduled runs are failing?

Exit code is 0 if everything looks healthy, 1 if anything needs attention.
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", "/data/data.db")
# Mirrors api.SYNC_FUTURE_DAYS — how far ahead meetings are pulled.
SYNC_FUTURE_DAYS = 30
STALE_HOURS = 6        # hint threshold only; see the note in main()
PAGE_SIZE = 999        # must match the $top in the n8n Graph nodes

problems: list[str] = []
notes: list[str] = []


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    print(f"Health check — {iso(now)}\n{'=' * 62}")

    # --- engagement sheet (shared, from SharePoint) -----------------------
    n_eng = conn.execute("SELECT COUNT(*) FROM engagements").fetchone()[0]
    dated = conn.execute(
        "SELECT COUNT(*) FROM engagements WHERE next_followup_date IS NOT NULL"
    ).fetchone()[0]
    print(f"\nENGAGEMENT SHEET (shared)\n  rows: {n_eng}   with a parsed follow-up date: {dated}")
    if n_eng == 0:
        problems.append("engagements table is EMPTY — the SharePoint sync has never succeeded")
    elif dated == 0:
        problems.append("no engagement row has a usable follow-up date — check the sheet's columns")

    # --- per-mailbox coverage --------------------------------------------
    owners = [r[0] for r in conn.execute(
        "SELECT DISTINCT owner FROM emails UNION SELECT DISTINCT owner FROM meetings"
    )]
    print(f"\nMAILBOXES ({len(owners)} with data)")
    if not owners:
        problems.append("no mailbox has any data — check the n8n Config node and credentials")

    horizon = iso(now + timedelta(days=SYNC_FUTURE_DAYS - 2))
    for o in sorted(owners):
        e_n, e_max = conn.execute(
            "SELECT COUNT(*), MAX(ts) FROM emails WHERE owner = ?", (o,)
        ).fetchone()
        m_n, m_min, m_max = conn.execute(
            "SELECT COUNT(*), MIN(start_ts), MAX(start_ts) FROM meetings WHERE owner = ?", (o,)
        ).fetchone()
        future = conn.execute(
            "SELECT COUNT(*) FROM meetings WHERE owner = ? AND start_ts > ?", (o, iso(now))
        ).fetchone()[0]

        print(f"  {o}")
        print(f"     emails   {e_n:5}  latest {str(e_max)[:16]}")
        print(f"     meetings {m_n:5}  {str(m_min)[:10]} .. {str(m_max)[:10]}  ({future} upcoming)")

        # THE SILENT ONE. Graph returns pages oldest-first; when a mailbox
        # exceeds the page size the tail is dropped with no error, so its
        # meetings just stop at a date while everyone else reaches the horizon.
        # Compared against the best-covered mailbox rather than a fixed count,
        # because truncation shows up as "reaches less far than everyone else".
        if m_max and m_max < horizon and m_n >= PAGE_SIZE * 0.8:
            problems.append(
                f"{o}: {m_n} meetings but none after {str(m_max)[:10]} — "
                f"likely TRUNCATED at the {PAGE_SIZE}-item page cap. "
                f"Enable pagination on the n8n Graph nodes."
            )
        elif m_max and m_max < horizon and future == 0 and m_n > 0:
            notes.append(f"{o}: no upcoming meetings at all (may simply be an empty calendar)")

    # --- is the automation still running? ---------------------------------
    # Measured on created_at (when WE wrote the row), not ts (when the email
    # was sent). Someone simply not receiving mail for two days is not a fault;
    # n8n having stopped writing anything is.
    print("\nINGESTION FRESHNESS")
    newest = None
    for table, label in (("emails", "emails"), ("meetings", "meetings")):
        last = conn.execute(f"SELECT MAX(created_at) FROM {table}").fetchone()[0]
        if not last:
            problems.append(f"{label}: nothing has ever been ingested")
            continue
        print(f"  {label:9} newest row first seen {last[:16]}")
        newest = max(newest, last) if newest else last

    # `created_at` defaults on INSERT and the upsert's DO UPDATE leaves it
    # alone, so it marks when a row was FIRST seen — not when the sync last
    # ran. A quiet mailbox therefore looks identical to a dead one, which is
    # why this is judged across both tables together and only as a hint.
    # n8n → Executions remains the authoritative answer.
    if newest:
        age = now - datetime.strptime(newest[:19], "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc)
        hrs = age.total_seconds() / 3600
        print(f"  -> most recent new row anywhere: {hrs:.1f}h ago")
        if hrs > STALE_HOURS:
            notes.append(
                f"nothing new ingested for {hrs:.0f}h across either table. Genuinely "
                f"quiet periods look the same, so confirm in n8n → Executions before "
                f"treating this as an outage."
            )

    # --- verdict ----------------------------------------------------------
    print(f"\n{'=' * 62}")
    for n in notes:
        print(f"  NOTE     {n}")
    for p in problems:
        print(f"  PROBLEM  {p}")
    if not problems:
        print("  All checks passed." if not notes else "  No problems; see notes above.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
