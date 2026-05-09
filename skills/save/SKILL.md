---
name: save
description: Save the most recent substantive output (a guide, research summary, comparison, plan, recipe, itinerary, recommendation, or any reusable content) to Tana as a #resource node. Use when the user says /save, "save this", "save to Tana", "put this in Tana", or after Claude generates something the user wants to keep.
---

# Save to Tana as Resource

When invoked, take the most recent substantive content from the conversation and save it to Tana as a `#resource` node with proper structure.

## Resource tag schema (workspace `drg2JUfK3f-A`)

Tag ID: `tuCfCD4hDPPa` (resource)

Fields:

| Field | ID | Type / Options |
|---|---|---|
| Title | `-bK7vQs3A_p3` | Plain text |
| Source | `fu-cSA_gov1n` | URL |
| Type | `gwqXR25W-Czr` | Options: Article, Video, Podcast, Book, Thread, Paper |
| Domain | `otQz3obPyxrx` | Options: AI/ML, Cloud, Sales, Spirituality, Fitness, Finance, Travel, Music, Leadership |
| Key takeaways | `3qwylokdkFVS` | Plain text — short summary |
| Status | `-5fWZvOKizvS` | Options: To Review, Reviewed, Archived |
| Related projects | `PPXvRNNeYBpT` | Instance multi → active-project (`Wgx1yMsS_LcO`) |
| Related decisions | `ygmdvAa734cz` | Instance multi → decision (`ubqmsjwBBw3C`) |
| Date added | `h2omf3YXFI21` | Date |

## Workflow

1. **Identify the content** — Look at the most recent substantial output in the conversation. If the user pasted content with the /save command, use that. If there are multiple candidates, ask which one. If nothing substantive exists, reply: "Nothing to save — generate something first or paste content with /save."

2. **Classify it** — Determine:
   - **Title** — clear and searchable. Pull from the content's heading or generate a descriptive title.
   - **Type** — Article (most generated guides/summaries), Video, Podcast, Book, Thread, Paper. Default Article.
   - **Domain** — pick the closest from the options list. If none fit perfectly, use the closest. Travel for trip content, AI/ML for AI topics, etc.
   - **Status** — Reviewed (you've already engaged with the content via this session)
   - **Date added** — today in YYYY-MM-DD

3. **Check for related Tana nodes** — Use `search_nodes` to find:
   - Related #active-project (e.g., "Spain Trip" if the resource is about Spain)
   - Related #trip (same)
   - Related #person if the resource concerns someone specifically
   Use these as references in Related projects field.

4. **Write the resource node** to Tana under the workspace home node (`xAJR7-Msy1YZ`):

```
- <Title> #[[^tuCfCD4hDPPa]]
  - [[^-bK7vQs3A_p3]]:: <Title>
  - [[^gwqXR25W-Czr]]:: <Type>
  - [[^otQz3obPyxrx]]:: <Domain>
  - [[^-5fWZvOKizvS]]:: Reviewed
  - [[^h2omf3YXFI21]]:: <YYYY-MM-DD>
  - [[^3qwylokdkFVS]]:: <2-4 sentence summary of what's in it and why it's useful>
  - <full content as children — preserve structure with sub-bullets for headings>
```

For long content with sections, preserve the hierarchy as nested bullet children (use **bold** prefix for section headers).

5. **Confirm** — Reply with one line: `Saved "<Title>" as #resource in Tana (node ID: <id>). Type: <type>, Domain: <domain>.`

## Rules

- Don't ask the user to choose Type/Domain unless genuinely ambiguous — make the call.
- Preserve content fidelity. If it's a 19-section guide, save all 19 sections as children, not a summary.
- Keep Key takeaways short (2-4 sentences) — that's the at-a-glance summary, not the full content.
- If the content has source URLs (e.g., a research summary citing articles), include them in Source field if there's a primary one.
