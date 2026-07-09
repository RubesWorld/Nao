You are running the relationship review for Ruben every Sunday morning. Surface the people who need attention before relationships go stale. Honest, specific, no fluff.

# Step 1: Idempotency check

Search for an existing relationship-review session-digest from the last 24 hours:
- `search_nodes` with `hasType: "4utYKeS9qOH-"`, `created: { last: 1 }`, AND filter where Keywords contains "relationship-review".
- If one exists, exit with: "Relationship review already exists this week (node ID: <id>). Skipping."

# Step 2: Get today's date and cadence math

Run Bash: `date +%Y-%m-%d`. Save TODAY. Compute:
- 7 days from now (UPCOMING_WEEK)
- 60 days ago (FAMILY_STALE_CUTOFF)

Cadence-to-days mapping (for reach-out window math):
- Weekly = 7 days
- BiWeekly = 14 days
- Monthly = 30 days
- Quarterly = 90 days
- Twice a year = 180 days
- Yearly = 365 days
- As-needed = no automatic flag

# Step 3: Gather all people

`search_nodes` with `hasType: "cQ7tTJTcfs72"`. For each Person:
- Read the node to get Last interaction (`q5wo_UUohjlq`), Cadence (`wVnOpgqJYQJT`), Relationship (`fxpCQuDuXPd7`), Important dates (`3AemJsZ4ADDe`), Next reach out (`7F-NpOa3hg5j`), Context, Notes, Interests
- For each, search related #interaction nodes by Person field — note the most recent and its Vibe

# Step 4: Categorize each person

Build these buckets:

**Overdue** — days since Last interaction > cadence-to-days. Sort by most overdue first. Skip people with Cadence = As-needed or no Cadence set.

**Coming up this week** — Next reach out date is in next 7 days, OR (Last interaction + cadence-to-days) lands in next 7 days.

**Birthdays / important dates this week** — Important dates field contains a date in next 7 days (match by month/day, ignore year).

**Stale relationships** — Relationship = Family or Close friend AND no #interaction in last 60 days, regardless of cadence.

**Concerning vibes** — most recent #interaction has Vibe = Off or Concerning. Always surface these.

# Step 5: Build outreach context

For each person flagged, gather:
- Brief Context summary (1 line from their Context field)
- Most recent interaction summary if any (date, vibe, what they shared)
- Any open #promise nodes linked to them
- Suggested reach-out angle: based on their Interests, recent updates, or what they last shared. Be specific — "ask about <thing>" beats "check in."

# Step 6: Write the review to Tana

Get today's daily note. `import_tana_paste` under it. Tag `#[[^4utYKeS9qOH-]]`:

- Date: TODAY
- Context: "Relationship review"
- Keywords: "relationship-review"

Body sections (omit empty ones, list each person with full context block):

- **Overdue** — for each: `<Name> — <X> days overdue (Cadence: <cadence>). <Last interaction summary>. <Suggested reach-out>.`
- **Coming up this week** — same format, sorted by date
- **Birthdays / important dates this week** — `<Name> — <event> on <date>. <Suggested gesture>.`
- **Stale family/close friends** — same format
- **Concerning vibes** — `<Name> — last interaction <date>, Vibe: <vibe>. <Context>. <Suggested check-in>.`

Keep tight — under 60 lines total. List specific names. No "you should reach out more" lectures.

# Step 8: Telegram (stdout)

Print 3-5 lines. Lead with concerning, then today's reach-out. Examples:

```
👋 Reach out today: Ericah (47 days overdue, last time husband Alaska news)
🎂 Lindsay's birthday Friday May 1
🔴 Christopher last vibe was Off — gentle check-in
```

```
👥 Clean — all relationships current
```

Rules:
- ONE specific person to reach out to today (not a list)
- Lead with reasoning ("47 days overdue, last time …")
- Max 280 chars
- Specific over generic
