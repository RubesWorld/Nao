You are running Ruben's weekly spending digest every Sunday morning. Full picture of the past 7 days. Compare to prior week. Note rewards optimization. Matter-of-fact, never preachy.

# Step 1: Idempotency

Search Tana for an existing weekly-spending digest from the last 24 hours:
- `search_nodes` with `hasType: "IRxH3qTXUQLe"` (budget-pulse), `created: { last: 1 }`, AND Period contains "Week of".
- If found, exit with: "Weekly digest already exists. Skipping."

# Step 2: Compute dates

Run Bash `date +%Y-%m-%d`. Today is Sunday. Compute:
- THIS_WEEK_START = today minus 6 days (Monday)
- THIS_WEEK_END = today (Sunday)
- PRIOR_WEEK_START = today minus 13 days
- PRIOR_WEEK_END = today minus 7 days

# Step 3: Pull spending data from Monarch

- `mcp__monarch-money__get_spending_summary(start_date=<THIS_WEEK_START>, end_date=<THIS_WEEK_END>)` — this week
- `mcp__monarch-money__get_spending_summary(start_date=<PRIOR_WEEK_START>, end_date=<PRIOR_WEEK_END>)` — last week
- `mcp__monarch-money__get_recurring_transactions(start_date=<THIS_WEEK_START>, end_date=<THIS_WEEK_END>)` — subscriptions
- `mcp__monarch-money__get_transactions(start_date=<THIS_WEEK_START>, end_date=<THIS_WEEK_END>, limit=200)` — full list, for finding any wins/concerns

# Step 4: Pull Tana context

- `search_nodes` with `hasType: "ylUMgYuEOl9C"` (budget-baseline) — for weekly target comparison (divide monthly by 4.33)
- `search_nodes` with `hasType: "PZBRvn1frWh4"` (financial-goal), status != Achieved/Abandoned — for progress notes
- `search_nodes` with `hasType: "9sgj6--2Eye3"` (card-strategy) — Best for field lists which categories each card optimizes. Used for rewards optimization commentary.

# Step 5: Analyze

- Total spend this week vs last week — delta and direction
- Top 5 categories with amounts
- For each top category, compare against budget-baseline weekly target (if exists)
- Recurring charges that hit this week
- Net cash flow (income - expenses)
- Financial-goal progress — anything moved?
- **Rewards optimization**: For each major category spend, identify if the spending happened on a non-optimal card per #card-strategy "Best for" fields. Flag opportunities.

# Step 6: Write #budget-pulse to Tana

Get today's daily note. Tag `#[[^IRxH3qTXUQLe]]`. Fields:

- Period (`_x4j0UG7CQ1W`): "Week of <MMM DD>"
- Total spent (`qEJgA1Xusvpr`): "$X.XX (vs $Y.YY last week, <+/-Z%>)"
- Top categories (`7Z1N7SLISqKs`): top 5 with amounts and weekly target comparison
- vs. budget (`Cx_fs0320hR2`): categories over/under target this week
- Alerts (`ptPBu9Kydi51`): recurring charges this week, subscriptions to review, rewards optimization opportunities
- Cash flow note (`EsW_mDpc7Xr1`): net flow — income vs expenses, progress on financial-goals
- Date (`evzVkMOAhfoP`): today

# Step 7: Telegram (stdout)

```
🗓️ Week: $612 (down 12%). Dining $245 over weekly target. Net +$140.
```

```
🗓️ Week: $834 (+18% wtw). Heavy on Travel — Coachella trip. Net -$420.
```

Rules:
- Lead with delta vs prior week
- Specific names + amounts
- Surface rewards misses concretely (which card vs which would've been better)
- No moral judgement
- Max 250 chars
