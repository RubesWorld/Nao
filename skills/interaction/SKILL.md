---
name: interaction
description: Log a hangout, call, text exchange, or meeting with one or more people in Tana as an #interaction node. Updates each person's Last interaction date so the Sunday Relationship Review uses real recency data. Use when the user says /interaction, "log hangout", "log interaction", "I just hung out with X", "had coffee with Y and Z", or describes a recent meeting/conversation/event with people.
---

# Log an Interaction in Tana

When invoked, parse the input as a description of an event with one or more people, then write a structured `#interaction` node to Tana and update each attendee's Last interaction date.

## Interaction tag schema (workspace `drg2JUfK3f-A`)

Tag ID: `1y3M8tt6ahGs` (interaction)

Fields:

| Field | ID | Type / Options |
|---|---|---|
| Attendees | `hbP83qyWMasn` | Instance multi → Person (`cQ7tTJTcfs72`) — **USE THIS for all people, 1 or many** |
| Person | `JeLUQyEyYfvJ` | Instance → Person (legacy single-value, leave empty) |
| Date | `qTyT3tLoop87` | Date |
| Type | `iLX3-nJYCpCO` | Options: In-person, Call, Text, Email, Social media, Group event |
| Context | `lLH1xFj1NRFv` | Plain text — what happened, where, vibe |
| Their updates | `S6Z5fhP-nUx0` | Plain text — per-person notes ("Mitch: heading to RI; Tim: golfing more") |
| Promises made | `hZZSWiuUxHvQ` | Plain text — anything Ruben committed to |
| Follow-up needed | `di4bTV_n-4Su` | Plain text |
| Vibe | `hW50yE34rJje` | Options: Great, Good, Neutral, Off, Concerning |

Person tag fields used:
- Last interaction (`q5wo_UUohjlq`) — date — **MUST update on every attendee**

## Workflow

### Step 1: Parse the input

Extract:
- **Names of attendees** — pull all proper names mentioned
- **Type** — infer from text:
  - "coffee", "lunch", "dinner", "hung out", "saw" → In-person
  - "called", "phone" → Call
  - "texted", "DMed" → Text
  - "emailed" → Email
  - 3+ people → Group event
  - Default to In-person if ambiguous
- **Vibe** — infer from sentiment language. Default Neutral if not mentioned.
  - "great", "amazing", "best", "love" → Great
  - "good", "nice", "fun" → Good
  - "weird", "off", "strange" → Off
  - "worried", "concerning", "rough" → Concerning
- **Date** — default to today unless user mentions otherwise ("yesterday", "last Tuesday")
- **Per-person updates** — extract specific tidbits about individuals (Mitch heading to RI, Lindsay's birthday, etc.)
- **Promises** — anything the user said they'd do for someone

### Step 2: Find each Person in Tana

For each name, run `search_nodes` with `hasType: "cQ7tTJTcfs72"` and `textContains: <name>`. 

Handle results:
- **Exact 1 match** → use that nodeId
- **Multiple matches** (e.g., two people named "Chris") → list them with breadcrumb context, ask the user which one
- **Zero matches** → ask: "<Name> isn't in Tana yet. Skip, or add as new Person? (skip / add)"

Build a list of `{name, nodeId}` for confirmed attendees.

### Step 3: Create the interaction node

Use `import_tana_paste` with parentNodeId set to today's daily note (get via `get_or_create_calendar_node`). Format:

```
- <Title> #[[^1y3M8tt6ahGs]]
  - [[^hbP83qyWMasn]]:: [[Name1^nodeId1]]
  - [[^hbP83qyWMasn]]:: [[Name2^nodeId2]]
  - [[^qTyT3tLoop87]]:: <YYYY-MM-DD>
  - [[^iLX3-nJYCpCO]]:: <Type>
  - [[^hW50yE34rJje]]:: <Vibe>
  - [[^lLH1xFj1NRFv]]:: <What happened, where>
  - [[^S6Z5fhP-nUx0]]:: <Per-person updates if any>
  - [[^hZZSWiuUxHvQ]]:: <Promises if any>
```

Title format:
- 1-on-1: "Coffee with Tim — May 7"
- Group: "Knicks game with 8 friends — May 6"

Note: For multi-value Attendees, repeat the field syntax with `:: append` mode if needed, or just list them as separate lines like above.

Each Attendee reference uses `[[Name^nodeId]]` format.

### Step 4: Update Last interaction on every attendee

For each Person nodeId, call `set_field_content` with:
- nodeId: <PersonNodeId>
- attributeId: `q5wo_UUohjlq` (Last interaction)
- content: <today's date YYYY-MM-DD>

Don't skip this. The Sunday Relationship Review depends on Last interaction being current.

### Step 5: Create linked promises if any were made

If the user mentioned promises ("told Tim I'd send the recipe", "owe Mitch a call"), create one #promise node per promise:

```
- <What> #[[^CPJBjsqaUr6F]]
  - [[^gyC8IAnhSkk0]]:: <What was promised>
  - [[^4je8YrsC3pgW]]:: <Person name>
  - [[^R4CiFnM0eZgx]]:: Open
  - [[^ZaOH2CrBY9o8]]:: From interaction with <name> on <date>
```

Set Deadline if mentioned, otherwise leave it.

### Step 6: Confirm

Reply with one line: `Logged <type> with <names> (#interaction <nodeId>). Updated Last interaction on <count> people.<+N promises if any>`

## Examples

**Input:** `had coffee with Tim, great vibe, he's golfing more lately and going to Hawaii in July`

**Result:** 
- 1 #interaction (Type: In-person, Vibe: Great, Attendees: Tim, Their updates: "Tim: golfing more, Hawaii in July")
- Updates Tim's Last interaction to today

**Input:** `Knicks game last night with Mitch, Wyatt, Tim, Christopher, Hussain, Rishi, Nico, Lindsay at Jack Demsey's. Mitch heading to RI next week. Great night.`

**Result:**
- 1 #interaction (Type: Group event, Vibe: Great, Attendees: 8 people, Context: "Knicks game at Jack Demsey's", Their updates: "Mitch: heading to RI next week", Date: yesterday)
- Updates Last interaction = yesterday on all 8 people

**Input:** `texted Ericah, told her I'd call her this weekend, she's still adjusting`

**Result:**
- 1 #interaction (Type: Text, Vibe: Good, Attendees: Ericah, Promises made: "Call this weekend", Context: "Ericah still adjusting to husband in Alaska")
- Updates Ericah's Last interaction to today
- Creates 1 #promise: "Call Ericah this weekend"

## Rules

- Make Last interaction update non-negotiable. The whole Relationship Review system depends on it.
- For unknown names, ask before silently skipping or creating.
- If the user doesn't mention vibe, default to Neutral — don't infer "Great" without signal.
- Per-person updates go in "Their updates" as a structured list, not free prose.
- Don't over-explain in the confirmation reply. One line.
