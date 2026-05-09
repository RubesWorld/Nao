---
name: person
description: Quickly add or update a Person node in Tana from a one-liner description. Use when the user wants to capture someone (e.g., "add Lindsay — architect, lives in Bushwick, birthday May 1") or updates context about an existing person. Parses natural-language details into the structured Person supertag fields.
---

# Add or Update a Person in Tana

When this skill is invoked, you'll receive a free-form description of a person. Your job is to parse it and write a properly-structured `#Person` node to Tana via the `tana-local` MCP.

## Person tag schema (workspace `drg2JUfK3f-A`)

Tag ID: `cQ7tTJTcfs72` (Person)

Fields (use IDs in Tana paste):

| Field | ID | Type |
|---|---|---|
| Relationship | `fxpCQuDuXPd7` | Options: Family, Close friend, Friend, Acquaintance, Professional, Mentor, Romantic |
| Context | `G0JyrqEiSl3q` | Plain text — running notes about who they are |
| Location | `NcIOJEIxEhW3` | Plain text |
| Cadence | `wVnOpgqJYQJT` | Options: Weekly, Monthly, Quarterly, BiWeekly, Twice a year, Yearly, As-needed |
| Interests | `nB-gMHdXZA5j` | Options multi: Travel, Fitness, Music, Finance, Spirituality, Food, Wine, Tech, Sports, Art, Reading |
| Last interaction | `q5wo_UUohjlq` | Date |
| Next reach out | `7F-NpOa3hg5j` | Date |
| Important dates | `3AemJsZ4ADDe` | Date (multi) — birthdays, anniversaries |
| Notes | `QUwmlIpeAfCm` | Plain text |
| Role | `O4oU8Du1jxea` | Options |
| Email | `63VLgPp4MT-M` | Instance of E-Mail |
| Phone | `bWsGN0FM5vTE` | Number |
| LinkedIn | `LiQeZYIJ2PL7` | URL |
| Company | `XLYCyW7wW2U7` | Instance of Company |

## Workflow

1. **Check for duplicates** — Use `search_nodes` with `textContains: "<name>"` and `hasType: "cQ7tTJTcfs72"` to see if this person already exists. If they do, ask the user whether to update the existing node or create a new one.

2. **Parse the input** — Extract:
   - **Name** (becomes the node title)
   - **Relationship** — match to one of the option values
   - **Location** — city, state, country
   - **Important dates** — convert birthdays like "May 1st" or "Nov 15, 1995" to ISO format YYYY-MM-DD. If only month/day given, use the most recent or upcoming year.
   - **Interests** — match keywords to the options multi-value field
   - **Context** — everything else that doesn't fit a structured field goes here as a freeform paragraph
   - **Cadence** — only set if the user explicitly mentions communication frequency

3. **Write the node** — Use `import_tana_paste` under the workspace home node (`xAJR7-Msy1YZ`) with this format:

```
- <Name> #[[^cQ7tTJTcfs72]]
  - [[^fxpCQuDuXPd7]]:: <Relationship>
  - [[^G0JyrqEiSl3q]]:: <Context paragraph>
  - [[^NcIOJEIxEhW3]]:: <Location>
  - [[^nB-gMHdXZA5j]]:: <Interest>
  - [[^3AemJsZ4ADDe]]:: <YYYY-MM-DD>
  - [[^QUwmlIpeAfCm]]:: <Notes>
```

Only include fields that have actual values. Don't invent data.

4. **Confirm** — Reply with a single line: `Added <Name> as #Person (node ID: <id>). Fields: <comma-separated list of fields populated>.`

## Examples

**Input:** `add Lindsay Barranco — architect, lives in Bushwick, born NJ raised Houston, birthday May 1, very solutions oriented, has a boyfriend Ryan`

**Output:**
```
- Lindsay Barranco #[[^cQ7tTJTcfs72]]
  - [[^fxpCQuDuXPd7]]:: Friend
  - [[^G0JyrqEiSl3q]]:: Architect. Born in NJ, raised in Houston. Very solutions-oriented. Has a boyfriend named Ryan.
  - [[^NcIOJEIxEhW3]]:: Bushwick, Brooklyn
  - [[^3AemJsZ4ADDe]]:: 2026-05-01
```

Then confirm: `Added Lindsay Barranco as #Person (node ID: <id>). Fields: Relationship, Context, Location, Important dates.`

## Rules

- Don't ask clarifying questions unless the input is genuinely ambiguous (e.g., two people with the same name). Default to making reasonable inferences.
- Default Relationship to "Friend" if not specified.
- Convert dates to ISO format. If a year isn't given for a birthday, use the current year.
- Keep the Context field readable as a paragraph, not a bulleted list.
- After writing, the user can see the new node in Tana — no need to dump full output.
