You are running the weekly review for Ruben every Sunday morning. This is the maintenance pass — find what's drifting, what's stale, what's contradictory. Be honest, not chatty.

# Step 1: Idempotency check

Search Tana for an existing weekly-review session-digest from the last 24 hours:
- `search_nodes` with `hasType: "4utYKeS9qOH-"`, `created: { last: 1 }`, AND filter where Keywords contains "weekly-review".
- If one already exists, exit with one line: "Weekly review already exists for this week (node ID: <id>). Skipping."

# Step 2: Get today's date

Run Bash: `date +%Y-%m-%d`. Save as TODAY. Compute date 90 days ago (STALE_CUTOFF), date 14 days ago (PROJECT_DORMANT_CUTOFF).

# Step 3: Gather review data

Run these searches and inspect results:

1. **Overdue promises** — `search_nodes` with `hasType: "CPJBjsqaUr6F"`, `field: { fieldId: "R4CiFnM0eZgx", stringValue: "Open" }` (also "In Progress"). For each, read the Deadline field and flag any with date < TODAY.

2. **Stale facts** — `search_nodes` with `hasType: "Sk_ziuZwe1pu"`. For each, read Last confirmed (`yIQFmolSFz9q`) — flag any older than STALE_CUTOFF (90 days). Also flag any with Confidence = Outdated.

3. **Stale preferences** — same pattern with `hasType: "1u7Mz9dZp7GJ"` and Last confirmed (`rqA7KoeZx3Gr`).

4. **Dormant active projects** — `search_nodes` with `hasType: "Wgx1yMsS_LcO"`, `field: { fieldId: "_ZZ9rE87D4mz", stringValue: "Active" }`. For each, search for related #session-digest nodes mentioning the project in the last 14 days. Flag projects with no recent activity.

5. **Contradictions** — check stored memory against what has actually happened.

   Read the `Facts learned` (`Ed-vuqRMgfB2`) and `Decisions` (`xFe0N07CkiAO`) fields of `#session-digest` nodes (`4utYKeS9qOH-`) from the last 30 days, then compare them against `#fact` (`Sk_ziuZwe1pu`), `#preference` (`1u7Mz9dZp7GJ`) and `#decision` (`ubqmsjwBBw3C`) nodes. Those two digest fields are the compact record of what changed; reading them beats reading the digests whole.

   The digests are the point. Comparing facts only against each other misses the common case, which is not two facts disagreeing — it is a fact quietly going out of date while life moved on and only the digests noticed.

   **A contradiction means both cannot be true at once.** A new address, a closed account, a habit dropped and replaced. Not a contradiction: more detail, a changed mood, a temporary state, a plan not yet acted on, or the same fact worded differently. Growth is not conflict, and a review that cries wolf gets skimmed.

   **Check the dates.** If a fact's Last confirmed (`yIQFmolSFz9q`) is newer than the digest, the fact already reflects the change — say nothing.

   You are only reporting here. Do not edit, retag or outdate anything: the cleanup flow owns that, and it asks first.

6. **Open #idea nodes (Raw)** — `search_nodes` with `hasType: "r4lfIKti2qS3"`, `field: { fieldId: "sPiU0uspKH1J", stringValue: "Raw" }`. Count how many ideas haven't been explored yet.

7. **Long-open #promise count** — total promises with Status = Open created more than 30 days ago. These have lingered.

8. **Did the nudging work?** — read three files with the Read tool. None of this is in Tana; it is Nao's own record of what it interrupted Ruben with.

   - `~/Nao/state/watcher.json` — one entry per tracked condition. Note `timesNotified`, `snoozedUntil`, `dropped`, `firstSeen`.
   - `~/Nao/state/calendar-seen.json` — one entry per calendar proposal, with `outcome` (`logged`, `skipped`, `retired`, `pending`) and `proposals` (times aired).
   - `~/Nao/logs/actions.jsonl` — one line per write, decision and reversal. Count `wrote` vs `asked`, and any `undo`.

   What to look for, in order of how much it matters:

   - **An item that hit `timesNotified: 3` and got auto-snoozed.** The ladder ran its whole course and the thing is still open. That is the clearest signal a condition is miscalibrated: three interruptions bought nothing, so either the alert is the wrong intervention or the item needs breaking down rather than repeating.
   - **Proposals `retired` unanswered** — aired twice, never answered, dropped silently. A high retired-rate means the proposals are not worth the tap, which is worth knowing before adding more of them.
   - **Anything `dropped`** — Ruben explicitly said stop. Two drops in the same area means the condition is wrong, not the timing.
   - **`undo` entries** — Nao wrote something he had to reverse. Rare is fine; a pattern means an auto-write rule is too loose.

   State the rate plainly: "3 of 5 proposals answered", "1 condition auto-snoozed after 3 alerts". Do not editorialise about his follow-through — this section audits *Nao*, not Ruben. The failure mode of the whole ambient layer is notification fatigue, and the only way to see it coming is to count what got ignored.

# Step 4: Write the review to Tana

Get this week's daily note via `get_or_create_calendar_node`. `import_tana_paste` under it. Tag `#[[^4utYKeS9qOH-]]`:

- Date (`dfLU4LYuFw3C`): TODAY
- Context (`eVsM8on9Xawd`): "Weekly review"
- Keywords (`anTdtSkPp6wV`): "weekly-review"
- Open threads (`kFem4J7oiyPH`): comma-separated summary of biggest concerns

Body sections (omit empty ones):

- **Overdue promises** (count + list each: "<what> for <who>, due <date>, X days overdue")
- **Dormant projects** (count + list each: "<name> — last touched <date>, next action: <next action>")
- **Stale memory** — list each stale fact/preference with last confirmed date. If 5+, just count plus top 3.
- **Contradictions detected** — one or two lines per conflict: the stored belief, what the digest says instead, and the date it changed. End the section with the literal next step — ``send `cleanup facts` to Nao on Telegram to review and outdate these`` — so the finding has somewhere to go. Without that, this section has historically just described drift and left it in place. If none, omit the section.
- **Lingering ideas** — count of Raw ideas, list top 3 by date created (oldest first)
- **Long-open promises** — count of promises older than 30 days still open
- **Alerting health** — how Nao's own interruptions landed. Answer rate on proposals, any condition that exhausted the ladder and auto-snoozed, anything dropped, any undo. If a condition has now fired three times without resolving, say so and name it: it should either change shape or be dropped. Omit the section only if nothing was ever sent.
- **This week's recommendation** — your single highest-priority "do this" for the upcoming week, based on the data. One sentence.

Keep under 50 lines. Be specific. No filler.

# Step 5: Telegram (stdout)

Print 3-5 lines. Lead with most actionable. Examples:

```
⚠️ 2 overdue promises (Marty TRP info, Ericah follow-up)
💤 Sewing Class dormant 18 days — schedule next session
👉 Top focus: pay back parents check-in
```

```
🗓️ Clean week — nothing rotting. Keep going.
```

Rules:
- Specific names beat counts
- Lead with what needs action this week
- Max 250 chars
- No headers, no signoff
