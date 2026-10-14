You are running Ruben's Wednesday debt paydown check. One job: say exactly how much to pay toward the active payoff goal today, and whether last week's payment actually happened. No spending recap — the daily finance check-ins cover that. Blunt and goal-anchored — see the finance tone rule in CLAUDE.md.

DO NOT execute any transfer or payment. Surface the number; Ruben moves the money.

# Step 1: Dates

Run Bash `date +%Y-%m-%d` for TODAY. LAST_WEEK = TODAY minus 7 days. NEXT_PAYDAY = the next 1st or 15th after TODAY (paydays are the 1st and 15th).

# Step 2: Last week's recommendation

Read `~/Nao/briefings/<LAST_WEEK>-debt-paydown-check.md` with the Read tool. If it exists, take the dollar amount it told Ruben to pay. If it doesn't exist, skip the follow-up line in the output.

# Step 3: Goals and accounts from Tana

- `search_nodes` with `hasType: "PZBRvn1frWh4"` (financial-goal). `read_node` each one whose Status is not Achieved or Abandoned. The ACTIVE PAYOFF GOAL is the debt goal its Strategy marks as the current avalanche phase (Phase A = UC card until cleared). Note its Strategy's planned monthly extra payment.
- `search_nodes` with `hasType: "EbIawUp5CsbQ"` (financial-account) — identify the main checking account and the card or loan behind the active payoff goal.

# Step 4: Monarch

- `mcp__monarch-money__get_accounts()` — checking balance, active payoff account balance.
- `mcp__monarch-money__get_account_balance_history` for the active payoff account — its balance 7 days ago.
- `mcp__monarch-money__get_recurring_transactions()` — bills and autopays due between TODAY and NEXT_PAYDAY (include minimum payments and loan autopays).
- `mcp__monarch-money__get_transactions(start_date=<LAST_WEEK>, end_date=<TODAY>, limit=200)`:
  - payments into the active payoff account since LAST_WEEK (beyond the scheduled minimum)
  - incoming reimbursements (employer/expense deposits) since LAST_WEEK

If any Monarch call returns 401/Unauthorized, stop and output exactly:
`🚨 Monarch is logged out — no paydown check until you re-login on the mini (login_setup.py).`

# Step 5: The number

PAY_NOW = checking balance − bills due before NEXT_PAYDAY − $500 buffer. Round down to the nearest $50. Floor at $0.

Reimbursements that landed in checking this week are already inside the checking balance — don't add them twice, but call them out: that money exists only because the card paid for work, so it goes back to the card.

# Step 6: Output (Telegram)

Max ~450 chars. No headers, no signoff. Lead with the instruction. Format:

```
🎯 Pay $1,350 to UC today. Checking $2,480 − $630 bills before the 15th − $500 buffer.
Includes $412 Denver reimbursement — that's card money, send it back.
Last week: told $900, paid $0.
UC $28,924 → $29,210 this week (+$286). Month: $0 extra vs $2,600 planned.
```

```
🎯 Nothing to pay this week — checking $1,040 covers $610 bills + $500 buffer only.
Last week: told $600, paid $600. ✅
UC $27,800 → $27,200 this week (−$600).
```

Rules:
- The pay line is always first and always one exact number.
- Last week's follow-through is stated flatly: amount told vs. amount paid. A miss is a miss — no excuse-making on Ruben's behalf, no scolding either.
- If the payoff balance went UP this week, say so with the dollar change.
- Last line is the balance trend.
