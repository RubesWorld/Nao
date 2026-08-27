# Nao HQ — build brief

Paste this into a **Claude Code web session** (or the Claude app) that has the
**Tana Cloud** connector attached. It cannot be built from the local CLI —
the connector is Connected there but its tools are not exposed to a local
session's registry (checked 2026-08-27, recorded in `plans/blueprint.md`
item 9).

Roadmap item 9. Read the blueprint first if you have the repo; this brief is
written to stand alone if you do not.

---

## What you are building

A private dashboard for Ruben, published as a claude.ai **Artifact** that
declares the `mcp` runtime capability and reads his Tana graph **live**
through his own Tana Cloud connector. Not a static export — the page calls
the connector with the viewer's credentials at open time.

**v1 is READ-ONLY. Deliberately.** No buttons, no writes, no capture box.
The commit-to-Tana question is still open (blueprint §8 decision log), so the
rendering layer stays substrate-agnostic and only a thin data layer speaks
Tana. Action buttons are v2, only after he has lived with v1.

## Before you write a line of page code

**Observe one real round-trip per tool you intend to call.** The artifact
capability contract forbids publishing a page that calls a connector tool
whose real request and response you have not seen in this session. Argument
names and result encoding are not documented anywhere and differ from what
you may remember.

So: call `search_nodes` and `read_node` against the connector yourself first,
look at what actually comes back, and build against that. If you cannot
observe a tool, do not call it — and say so in your reply to Ruben, not in a
note inside the page.

Do not embed any observed values in the published page as sample data. That
is his real life, and a placeholder that is secretly a real promise is worse
than an empty state.

## Workspace and IDs

Workspace `drg2JUfK3f-A`.

| Thing | Tag ID | Fields you need |
|---|---|---|
| promise | `CPJBjsqaUr6F` | What `gyC8IAnhSkk0` · Deadline `nDVo67NvPODe` · Status `R4CiFnM0eZgx` (Open `f5lm-VvlvLMt`, In Progress `_h3E6UHZQsU6`, Done, Dropped) · Person `7ZqQNhdwjfRZ` |
| Task | `2QEEKpJYzp8R` | Task status `Pd4w7S52adIs` (Backlog `X94cHklrd-fb`, In progress, Done) · Due date `nQx1UuRTM4a9` · Priority `ziKP2SPwipcw` (High `V-ojP6G_v0wE`) |
| active-project | `Wgx1yMsS_LcO` | status `_ZZ9rE87D4mz` |
| Person | `cQ7tTJTcfs72` | Next reach out `7F-NpOa3hg5j` · Last interaction `q5wo_UUohjlq` · Cadence `wVnOpgqJYQJT` · Relationship `fxpCQuDuXPd7` |
| session-digest | `4utYKeS9qOH-` | Date `dfLU4LYuFw3C` · Context `eVsM8on9Xawd` · Keywords `anTdtSkPp6wV` |
| interaction | `1y3M8tt6ahGs` | Date `qTyT3tLoop87` · Attendees `hbP83qyWMasn` |
| budget-pulse | `IRxH3qTXUQLe` | — |

NAO-INDEX dashboard node: `4FnKfPTJc-ez`. Today's briefing lands on the daily
note as a `#session-digest` with Context "Morning briefing".

## What the page shows

Roughly in this order of importance. Some of these will be empty on a given
day — design the empty states first, because most days most panels are quiet.

1. **What needs you today** — overdue promises, then promises due in the next
   2 days, then overdue tasks. This is the whole reason the page exists.
2. **Today's briefing** — the morning `#session-digest`, if one was written.
3. **Reach out** — people whose Next reach out is today or earlier, and
   Family / Close friends with no interaction in 60+ days.
4. **Projects** — `#active-project` with status Active, with next action.
   Flag any with no session-digest activity in 7+ days.
5. **Money** — the latest `#budget-pulse`. The scheduled jobs are already the
   ETL; the page needs no Monarch access.

## Design constraints — this is the part that matters

Ruben has ADHD. These are not stylistic preferences; a dashboard that ignores
them is one he will stop opening, which makes it worse than nothing.

**One answer above the fold.** The top of the page states the single most
important thing, in a sentence, in large type. Not a grid of equal panels —
a grid makes the reader do the prioritising, and that is the exact work being
offloaded. If nothing is urgent, say *that*, plainly and warmly, and let the
page be short.

**Never show a wall.** Top 3 of anything, then a count: "3 of 11 open tasks".
The other 8 are not hidden information, they are deferred information. A list
of everything reads as a list of failures and gets closed.

**Relative time first, absolute second.** "in 2 days", "3 weeks overdue",
"last seen 108 days ago" — with the date in smaller, quieter type beside it.
Time blindness is the single most useful thing this page can compensate for.
"Fri Aug 28" requires arithmetic; "in 2 days" does not.

**Colour is signal, never decoration.** Exactly one treatment for overdue,
one for due-soon, one for calm. If four things are coloured, nothing is.
Everything else is greyscale.

**No interaction required to get the answer.** No tabs, accordions, hover
states, or "click to expand" over anything that matters. Activation energy is
the tax being avoided; a page that must be operated will not be.

**Stable positions.** Same panel in the same place every day, whether or not
it has content, so it becomes scannable by muscle memory rather than re-read
each time. An empty panel that holds its position beats one that collapses
and shifts everything below it.

**No motion.** No animated counters, no fades, no auto-rotating anything.

**Finished things leave.** Nothing lingers as a completed row to scroll past.
The page should get shorter as the day goes well.

**Quiet is a valid state and must look deliberate.** "Nothing needs you today"
should look like a designed answer, not a broken query. Most days are quiet
and the page must feel good on those days or it will not survive them.

Beyond that: light and dark both, readable at arm's length on a phone, and
generous line height. Prefer one column on narrow screens over anything that
reflows into a puzzle.

## Ship notes

- Title it something short and specific — it will sit in a gallery.
- A page declaring `mcp` cannot be shared publicly. That is correct here; it
  is a personal cockpit and the manifest is a consented credential grant.
- Keep the connector manifest minimal — only the tools you actually observed
  and actually call.
- Show freshness. Every capability result carries `cache.storedAt`; a stale
  number rendered as current is the failure mode that makes a dashboard
  quietly untrustworthy.
- Handle `claude.use("mcp")` resolving `null` — render the page shell and its
  empty states rather than a blank screen.

## Data hazards, found the hard way

Real characteristics of this graph as of 2026-08-27. Ignore them and the page
will look broken through no fault of its own.

- **Querying `#Person` returns non-people.** Three old-style search nodes
  (`SEARCH WHERE Next reach out <= TODAY` and similar) carry the `#Person`
  tag, because the query lives in the node title and Tana reads the `#Person`
  in it as a real tag application. They cannot be untagged without breaking
  the searches. **Filter out any Person whose name starts with `SEARCH`**, and
  expect roughly 17 real people out of ~20 returned.
- **`Birthday` and `Important dates` both exist** and people are entered in
  either. Read both if you surface birthdays.
- **Facts go stale silently.** Nothing currently reconciles `#fact` /
  `#preference` against newer digests (roadmap item 3, unbuilt). Do not render
  facts as current truth on this page yet.
- **Interests coverage is ~9 of 17 people**, so any "who likes X" view will be
  confidently incomplete. Out of scope for v1; noted so it is not trusted.
- **Tana's search index lags a few seconds behind a write.** Something written
  moments ago may not appear yet. Do not treat an empty result as authoritative
  immediately after a change.
