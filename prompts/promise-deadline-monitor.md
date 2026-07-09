You are running the promise deadline monitor. Follow these exact steps. Do not skip any.

# Step 1: Find all open promises

Run this search:
```
search_nodes({
  query: { and: [
    { hasType: "CPJBjsqaUr6F" },
    { field: { fieldId: "R4CiFnM0eZgx", stringValue: "Open" } }
  ]},
  workspaceIds: ["drg2JUfK3f-A"]
})
```

Also run the same search but with `stringValue: "In Progress"`. Combine both result lists.

# Step 2: Get today's date

Run `Bash` tool: `date +%Y-%m-%d`. Save this as TODAY.
Also compute TWO_DAYS_AHEAD = TODAY + 2 days.

# Step 3: Filter for urgent

For EACH promise from Step 1, call `read_node(promise_id)` and look at the Deadline field.

Keep the promise in your URGENT list if:
- Deadline is missing → DISCARD
- Deadline < TODAY → KEEP (overdue)
- Deadline == TODAY → KEEP (due today)
- Deadline ≤ TWO_DAYS_AHEAD → KEEP (due soon)
- Deadline > TWO_DAYS_AHEAD → DISCARD

# Step 4: Decision point

If URGENT list is EMPTY:
- Print absolutely nothing to stdout.
- Do not write to Tana.
- Do not call Slack.
- End the session.

If URGENT list has 1+ items, proceed to Step 5.

# Step 5: Write nudge to Tana

Get today's daily note via `get_or_create_calendar_node(today)`. Use that as parentNodeId in `import_tana_paste`:

```
- Promise deadlines — <today's date> #[[^4utYKeS9qOH-]]
  - [[^dfLU4LYuFw3C]]:: <today YYYY-MM-DD>
  - [[^eVsM8on9Xawd]]:: Promise deadline monitor
  - [[^anTdtSkPp6wV]]:: deadline-monitor
  - [[^kFem4J7oiyPH]]:: <comma-separated promise titles>
  - <one bullet per urgent promise — see format below>
```

Promise bullet format: `<What> — for <Who>, due <YYYY-MM-DD> (<status>)`. Where status is one of: "OVERDUE - X days late", "due today", "due tomorrow", "due in X days".

# Step 7: Telegram (stdout)

Print 1-3 lines. Lead with most urgent. Format examples:

```
⚠️ OVERDUE: Submit TRP info to Marty (2 days late)
⏰ Tomorrow: Submit Coachella expenses
```

```
⏰ Today: Pay back parents check-in
```

Rules: Lead with overdue → today → tomorrow → within 2 days. Max 200 chars. No prose. No headers.

# Critical reminders

- If URGENT is empty, output NOTHING. Not even "all clear".
- The runner uses empty stdout to mean "stay quiet."
- ALWAYS go through all 7 steps when URGENT has items. Don't skip the Tana write or Slack call.
