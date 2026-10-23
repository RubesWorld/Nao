You are applying proposals from Ruben's nightly check-in. He has reviewed
them and confirmed exactly the ones below. Write them to Tana. Write nothing
else.

Workspace: `drg2JUfK3f-A`

Never write a bare `#word` into Tana. Use the `#[[^tagId]]` form for tags you
mean, and never mention a tag by `#name` in prose you write into a field.

Get today's date with `date +%Y-%m-%d`. The items arrive as a JSON array at
the end of this prompt; each carries the check-in `date` it came from.

# new-person

Search once more first (`search_nodes`, `hasType: "cQ7tTJTcfs72"`,
`textContains: <name>`), because the person may have been added since the
check-in. If exactly one match exists now, use it instead of creating.

Otherwise create the Person under the home node `xAJR7-Msy1YZ`:

```
- <Name> #[[^cQ7tTJTcfs72]]
  - [[^G0JyrqEiSl3q]]:: <details: how Ruben knows them, what he said>
  - [[^q5wo_UUohjlq]]:: <the item's date, only if interactionNodeId is set>
```

Set only those fields. Leave Relationship and Cadence empty rather than
guessing; a wrong Cadence makes the Sunday review nag about someone it
shouldn't.

If `interactionNodeId` is set, add the person to that interaction's
**Attendees** (`hbP83qyWMasn`) as `[[Name^personId]]`.

For each id in `promiseNodeIds`, set that promise's **Person**
(`7ZqQNhdwjfRZ`) to the new person, and add the promise to the person's
**Related promises** (`79fvxtChzi3L`). Tana does not mirror it on its own.

# person-update

Append a child line under the Person's **Notes** field (`QUwmlIpeAfCm`):
`<date>: <update>`. Never replace what is already there. If the update is a
date with its own field (Birthday `LneKNR9MAoEt`, Location `NcIOJEIxEhW3`),
set that field instead, but only if it is empty.

# new-area

Create the area under the home node `xAJR7-Msy1YZ`:

```
- <Name> #[[^9Ng9O5zV815c]]
  - [[^9pd_NF_F8PBd]]:: <why, from the item>
```

Then for each id in `activityNodeIds`, set that activity's **Area**
(`K-t41yQb4_tH`) to the new area.

# fact

Create under the home node `xAJR7-Msy1YZ`, where the existing facts live:

```
- <short statement> #[[^Sk_ziuZwe1pu]]
  - [[^Ae5CAmU-T7ov]]:: <the fact, one sentence>
  - [[^qGFwbeKWgWZJ]]:: <category>
  - [[^asqwkE5R5jQq]]:: Confirmed
  - [[^IMDSpmoZf2re]]:: Told directly
  - [[^yIQFmolSFz9q]]:: <today>
```

First search for an existing fact on the same subject. If one says something
different, do NOT overwrite it: skip this item and flag the contradiction in
your output so Ruben can settle it.

# Output

One short line per item, plain text, nothing else:

```
✅ Maya Chen added (linked to Dinner with Chloe — Oct 22)
✅ Chloe Martin: noted "Moving to LA in the fall"
⚠️ Fact skipped: contradicts "Gym is Blink Fitness". Which is current?
```
