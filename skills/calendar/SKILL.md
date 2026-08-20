---
name: calendar
description: Put something on Ruben's Google Calendar from a one-liner, or answer what's already on it. Use when he says /calendar, "put X on my calendar", "book", "add to calendar", "am I free Thursday", "what's on Saturday", or mentions a plan with a time attached ("dinner with Chloe Saturday at 7"). Creates real events on the primary calendar after confirming the details. Not for scheduling cloud agents or cron routines — that is the built-in `schedule` skill.
---

# Schedule something on Ruben's calendar

Ruben is deliberately trying to use his calendar more. The friction he is
trying to remove is opening the app, so the win here is turning one sentence
into a real event. Be fast and decisive; do not interview him.

## Calendars

| Calendar | ID | Use |
|---|---|---|
| Primary | `nycrar@gmail.com` | Everything, unless he says otherwise |
| Family | `family13001140461417692349@group.calendar.google.com` | Only when he says it is a family thing |

Never write to `Skincare - Morning`, `Skincare - Evening`, or
`The 5 Day "$1k Savings" Challenge`. Those are habit routines he maintains
elsewhere, and the nightly calendar capture ignores them by design.

Timezone is `America/New_York` unless the event is clearly somewhere else.

## Step 1 — Parse

From his sentence, pull:

- **Title** — see the naming rule below, it matters more than it looks
- **Date** — resolve relative words against today's actual date. Run
  `date "+%Y-%m-%d %A"` rather than assuming what day it is. "Saturday" means
  the next one; "next Saturday" means the one after that if the next is within
  three days, otherwise the same one — if that is genuinely ambiguous, state
  which date you picked rather than asking.
- **Time and duration** — if he gave a start but no end, use a sensible
  default and say which you used: dinner 2h, lunch 1h, coffee 1h, drinks 2h,
  a call 30m, a party or show 3h, anything unclear 1h.
- **Location** — a venue name is enough; Google resolves it.
- **Attendees** — only if he explicitly names email addresses or says to
  invite someone. See the warning below.

### Naming rule — put the person's name in the title

`Dinner with Chloe` beats `Dinner`. `Catan at Wyatt's` beats `Catan`.

This is not style. The nightly calendar capture reads event titles to work out
who Ruben spent time with, because he creates almost all of his own events and
so the attendee list is just him. A title with a name becomes a linked
interaction in Tana and refreshes that person's Last interaction date, which
is what the Sunday relationship review runs on. A title without one becomes a
proposal that has to ask "who was there?".

So when he mentions who he is seeing, put them in the title even if he phrased
it differently. If he did not mention anyone, do not invent a name.

## Step 2 — Confirm, then create

Show the parsed event back in one or two lines and create it. Do not make him
approve a form field by field:

> Dinner with Chloe — Sat Aug 23, 7:00–9:00pm, Carbone. Creating it.

Then call `create_event` on the primary calendar.

**Two things need an explicit yes before you act, because they reach other
people or overwrite his data:**

- **Attendees.** Adding one sends a real invitation email. Never add an
  attendee he did not explicitly ask for, and confirm before creating an event
  that has any.
- **Changing or deleting an existing event.** Find it first with
  `search_events` or `list_events`, show him which one you matched, and get a
  yes before calling `update_event` or `delete_event`. Deleting an event with
  guests cancels on them too.

Creating a plain solo-calendar event needs no separate approval — he asked for
it, that is the whole point of the skill.

## Step 3 — Report

One line, with the link:

> ✅ Dinner with Chloe — Sat Aug 23, 7–9pm at Carbone. <link>

If he mentioned a person who is not yet in Tana, say so in a single clause and
move on — do not derail into creating a Person node. The nightly capture will
propose it after the event actually happens, which is the right time.

## Reading the calendar

For "am I free Thursday", "what's on this weekend", "when am I seeing Chloe":

- Use `list_events` for a time range, `search_events` for open-ended keyword
  lookups on the primary calendar.
- Answer in plain lines — day, time, title, location. No tables for fewer than
  five events.
- Include the Family calendar when the question is about his availability, not
  just when he names it. Being double-booked by a family event still counts as
  being busy.
- For "am I free", answer the actual question first ("Thursday evening is
  open") and only then list what is already there.

## What not to do

- Do not create Tana nodes here. This skill touches the calendar only; the
  nightly capture (`scripts/calendar-capture.py`) owns the Tana side and
  proposes after the fact so cancelled plans never get logged as real.
- Do not add reminders, colors, or recurrence he did not ask for.
- Do not create an event in the past to "record" something that already
  happened. Log that as an interaction instead — that is the `interaction`
  skill's job.
