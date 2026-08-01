---
name: notes
description: File a batch of notes about a specific project, person, event, or trip into Tana under the right parent node. Handles photos of handwritten pages and typed brain dumps. Use when the user says /notes, "add these notes to <thing>", "here are my notes on <project>", drops a photo of a notebook page, or pastes a messy blob tied to something specific.
---

# Notes to Tana

Take a batch of notes — handwritten photo or typed blob — that belong to **one specific thing**, and file them into Tana under that thing's node.

This is not a generic inbox capture. The defining feature is that the notes have an **anchor**: a project, person, event, or trip they're about. Find the anchor first; everything else hangs off it.

If the notes turn out to have no anchor and are just scattered unrelated thoughts, say so and suggest the user capture them individually instead. Don't force a parent that isn't real.

## Workflow

### 1. Anchor

Identify what the notes are about, then find its node.

- If the user named it ("notes on the Jeremy King parties"), `search_nodes` with `textContains` for it.
- If they didn't name it, infer from the note content — project names, people, event names.
- If exactly one plausible match, use it and say which one you picked in the proposal.
- If several plausible matches, ask which. This is the one question worth interrupting for — filing under the wrong parent is worse than a round-trip.
- If no match, propose creating it: `"No node for '<X>'. Create it as #active-project and file under that?"` Wait for approval before creating.

Read the anchor node with `read_node` (maxDepth 3) before writing. You need to know its existing structure so new items land in the right sub-branch and you don't duplicate what's already there.

### 2. Read the input

**Photo of handwriting** — use the Read tool on the image path. Transcribe it fully before classifying anything.

- Preserve the author's own structure. Arrows, boxes, indentation, and margin notes carry meaning — a boxed item is usually emphasis, an arrow usually means "leads to" or "assign to".
- Words you genuinely can't read: transcribe your best guess followed by `[?]`. Never silently guess. Surface every `[?]` in the proposal so the user can correct them in one pass.
- Struck-through text is deleted — drop it unless the user's crossing-out is ambiguous.
- Multiple pages: read all of them before proposing anything.

**Typed blob** — use it as given.

### 3. Split and route

Break the batch into discrete items. Then route each one.

#### Author-supplied sections win

Ruben often labels sections on the page — `TASKS`, `FACTS`, `IDEAS`, `DECISIONS`, `PROMISES`, or obvious shorthand (`TODO`, `T:`, `F:`). **When a section header is present, it decides the routing for everything under it.** Don't apply the conservative-tagging heuristic below to those items and don't re-litigate his call — he labelled it a task because he wants a task.

- Match headers loosely. Handwriting gets abbreviated and pluralized inconsistently.
- The header itself is not a node. Drop it; it becomes the route, not content.
- A section ends at the next header or the end of the page.
- Items still need their fields filled — a line under `TASKS` is a `#Task`, but it still needs Context, and a date in the line still becomes Due date.
- If something under a header is clearly not that type (a bare observation sitting under `TASKS`), file it as the header says anyway, but mention it in the proposal: `(under TASKS but reads like a note — confirm?)`. His structure is the default; you just flag the oddity.

Anything **outside** a labelled section falls through to the heuristic below.

#### Everything else — be conservative about tagging

Most lines in a page of notes are context, not database records. A line becomes a tagged node only if it's genuinely a standalone, retrievable thing. Everything else stays a plain child bullet under the anchor. Over-tagging is the main failure mode of this skill: fifteen `#Task` nodes from one notebook page makes the task queue useless.

| Route to | When | Required fields |
|---|---|---|
| `#Task` (`2QEEKpJYzp8R`) | A concrete action with an owner and an end state | Context (`3mm756QVdoVI`) — **always**. Plus Due date (`nQx1UuRTM4a9`) if a date appears, Category (`cx4Y5x4Xb0Er`), Related project (`378gGRJv2gEG`) → the anchor if it's an #active-project |
| `#decision` (`ubqmsjwBBw3C`) | Something was settled, and a different choice was available | Decision (`3eDuVwXPWW5b`), Rationale (`oPZyxjv6e6Tx`) — **always**, Date (`v69Jjb2LwNPz`) |
| `#promise` (`CPJBjsqaUr6F`) | A commitment to a named person | Full fielding per CLAUDE.md — What, Who, Person, Deadline, Status, Context. Also add to that Person's Related promises (`79fvxtChzi3L`) |
| `#idea` (`r4lfIKti2qS3`) | A proposal for a thing that doesn't exist yet | Summary (`u5jXKY9yU-wk`), Category (`jrQApDKMS3v1`), Status (`sPiU0uspKH1J`) = Raw, Related project (`JxSSyeEpSKz6`) |
| `#fact` (`Sk_ziuZwe1pu`) | Durable personal info that outlives this project | Fact (`Ae5CAmU-T7ov`), Category (`qGFwbeKWgWZJ`), Confidence (`asqwkE5R5jQq`), Source (`IMDSpmoZf2re`), Last confirmed (`yIQFmolSFz9q`) |
| Plain bullet | **Everything else** — observations, constraints, names, numbers, half-thoughts, vibes | None. Just a child node under the anchor, nested to match the source structure. |

Rules of thumb:
- No verb and no owner → plain bullet, not a Task.
- "Maybe we should…" → plain bullet or `#idea`, never `#decision`.
- A fact that's only true inside this project (a venue's capacity) → plain bullet. `#fact` is for things about Ruben that survive the project ending.
- Don't double-tag. Pick the one that fits.

### 4. Check for duplicates

Before proposing, scan the anchor's existing children (from step 1) plus a `search_nodes` pass for any near-identical items. Handwritten notes often restate things already captured. Flag repeats in the proposal as `(already there — skipping)` rather than writing them twice.

### 5. Propose

Show the whole batch in one compact block before writing anything:

```
Filing under: <Anchor name> (<node id>)

Tagged:
  #Task     Order wine for Wine Wednesday — due Aug 5, Personal
  #idea     Bouquet-making event — Event, Raw
  #decision Rooftop over backyard — rationale: better flow for 40+

Plain notes (12):
  Vibe should stay homegrown / Cole knows the rooftop owner / budget ~$400 …

Unclear transcription:
  "portal[?]" — line 4

Skipping (already in Tana):
  Ashni as DJ
```

Then: `Write it? (yes / adjust)`

Wait for approval. One reply from the user should be enough to fix everything — if they say "the wine one isn't a task, and portal means the invite page", apply both and write without re-proposing.

### 6. Write

One `import_tana_paste` call under the anchor node. Use tag IDs (`#[[^tagId]]`) and field IDs (`[[^fieldId]]:: value`) — never names.

Preserve the source hierarchy in the plain bullets. If the page had three sections, write three parent bullets with children, not a flat list of eighteen.

If the anchor is an `#active-project` and the notes clearly move it forward, offer to refresh its Current state / Next action fields — call `get_tag_schema` on `Wgx1yMsS_LcO` for the field IDs. Offer, don't do it silently.

### 7. Confirm

One line: `Filed <n> items under <Anchor> — <x> tagged (<breakdown>), <y> plain notes. Node: <id>`

## Rules

- **Anchor before anything else.** Never write into the Inbox as a fallback because you couldn't find the parent — ask instead.
- **Transcribe before you classify.** Don't route items while still reading a photo; you'll miss context from later lines.
- **`[?]` on anything uncertain.** A wrong transcription filed confidently is worse than an obvious gap.
- **Conservative tagging — but only where Ruben didn't label it.** Under a `TASKS` / `FACTS` header his call stands. Outside one, when torn between a tag and a plain bullet, choose the plain bullet. It's easy to promote later, tedious to clean up a polluted queue.
- **Context field on every Task**, per CLAUDE.md — the surrounding notes are the context, so there's no excuse for leaving it empty here.
- **One proposal, one approval, one write.** Don't write items incrementally as you classify them.
