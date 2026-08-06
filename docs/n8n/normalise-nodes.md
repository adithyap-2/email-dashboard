# Normalise node code (paste-ready)

The three `Normalise` nodes in **Email + Calendar Ingest** must emit **one item
per mailbox**. n8n Code nodes default to `runOnceForAllItems`, where `$json`
refers only to the *first* input item — so the original code silently dropped
every mailbox except one, no matter how many were listed in `Config`.

Symptom: only one teammate's data ever reaches the dashboard, and the others
look like the calendar or mail "isn't syncing".

Fix: iterate `$input.all()` and pair each response with its `Config` entry by
index. Re-importing the workflow JSON also applies this, but wipes your
credential selections and mailbox list — so for a running workflow, paste these
in instead.

After pasting all three: **Save**, **Execute Workflow** once, then confirm every
mailbox appears:

```bash
docker compose exec app python -c "
import sqlite3; c=sqlite3.connect('/data/data.db')
for t in ('emails','meetings'):
    print(t); [print('  ',o,n) for o,n in c.execute(f'SELECT owner,COUNT(*) FROM {t} GROUP BY owner')]"
```


---

## `Normalise received`

```js
// One Graph response per mailbox arrives here. Emit one payload per mailbox:
// reading $json would silently keep only the FIRST and drop every other user.
const cfgAll = $('Config').all();
const dom = (e) => (e && e.includes('@')) ? e.split('@')[1].toLowerCase() : '';
return $input.all().map((item, i) => {
  const cfg = (cfgAll[i] || cfgAll[0]).json;
  const owner = cfg.user;
  const internal = cfg.internal.map(d => d.toLowerCase());
  const isExt = (e) => { const d = dom(e); return !!d && !internal.includes(d); };
  const payload = (item.json.value || []).map(m => {
    const from = (m.from && m.from.emailAddress) || {};
    return { id: m.id, owner, direction: 'received', subject: m.subject || null,
      preview: (m.bodyPreview || '').slice(0, 160), contact_name: from.name || null,
      contact_email: from.address || null, organisation: null,
      is_external: isExt(from.address), ts: m.receivedDateTime };
  });
  return { json: { payload } };
});
```


---

## `Normalise sent`

```js
// One Graph response per mailbox arrives here. Emit one payload per mailbox:
// reading $json would silently keep only the FIRST and drop every other user.
const cfgAll = $('Config').all();
const dom = (e) => (e && e.includes('@')) ? e.split('@')[1].toLowerCase() : '';
return $input.all().map((item, i) => {
  const cfg = (cfgAll[i] || cfgAll[0]).json;
  const owner = cfg.user;
  const internal = cfg.internal.map(d => d.toLowerCase());
  const isExt = (e) => { const d = dom(e); return !!d && !internal.includes(d); };
  const payload = (item.json.value || []).map(m => {
    const recips = (m.toRecipients || []).map(r => r.emailAddress || {});
    const ext = recips.filter(r => isExt(r.address));
    const c = ext[0] || recips[0] || {};
    return { id: m.id, owner, direction: 'sent', subject: m.subject || null,
      preview: (m.bodyPreview || '').slice(0, 160), contact_name: c.name || null,
      contact_email: c.address || null, organisation: null,
      is_external: ext.length > 0, ts: m.sentDateTime };
  });
  return { json: { payload } };
});
```


---

## `Normalise meetings`

```js
// One Graph response per mailbox arrives here. Emit one payload per mailbox:
// reading $json would silently keep only the FIRST and drop every other user.
const cfgAll = $('Config').all();
const dom = (e) => (e && e.includes('@')) ? e.split('@')[1].toLowerCase() : '';
return $input.all().map((item, i) => {
  const cfg = (cfgAll[i] || cfgAll[0]).json;
  const owner = cfg.user;
  const internal = cfg.internal.map(d => d.toLowerCase());
  const isExt = (e) => { const d = dom(e); return !!d && !internal.includes(d); };
  const addr = (p) => (p && p.emailAddress) || {};
  const payload = (item.json.value || []).map(ev => {
    const parties = (ev.attendees || []).map(addr);
    const org = addr(ev.organizer);
    const ext = parties.filter(p => isExt(p.address));
    if (isExt(org.address)) ext.unshift(org);
    const c = ext[0] || (org.address ? org : (parties[0] || {}));
    return { id: ev.id, owner, subject: ev.subject || null, organisation: null,
      contact_name: c.name || null, contact_email: c.address || null,
      is_external: ext.length > 0,
      start_ts: (ev.start || {}).dateTime ? (ev.start.dateTime.split('.')[0] + 'Z') : null,
      end_ts: (ev.end || {}).dateTime ? (ev.end.dateTime.split('.')[0] + 'Z') : null,
      location: (ev.location || {}).displayName || null,
      attendees: parties.map(p => p.name ? (p.name + ' <' + p.address + '>') : p.address),
      followup_status: 'none' };
  });
  return { json: { payload } };
});
```
