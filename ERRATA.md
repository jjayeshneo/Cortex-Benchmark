# Errata

Every correction to Cortex-Bench appears here, including the ones that make us look bad. A
benchmark with no errata log is a benchmark whose defects nobody has looked for.

Entries are dated, given a stable id, and marked **open** or **fixed**. Fixing a defect never
silently changes a published score: if a repair moves the gold answers, the affected leaderboard
rows are re-scored or retired, and that is recorded here too.

---

## E-2026-09-18-15 — Databricks Genie cost filled in, at a proxy rate

**What changed.** `results/2026-09-18-databricks-genie.json` carried `cost_usd_per_task: null` with
the reason that the conversations API returns no per-request usage. That reason was correct about
the API and wrong about the account: `system.billing.usage` meters Genie with
`usage_metadata.genie.{surface,channel,agent_id}`, which attributes consumption to this space and
this harness precisely. The field is now **$1.7265 per task**, derived the same way the Snowflake
row's $0.1629 is — account metering divided by 447 task-runs — and the derivation is in the entry's
notes.

**One assumption is load-bearing and is not hidden.** The SKU is `GENIE_FREE_USAGE` and it has no
row in `system.billing.list_prices`, because Genie was not charged for on this account during the
run. The **actual invoice for this arm was zero.** The published figure prices the measured
1,102.509 DBU at $0.70/DBU, the Premium serverless SQL compute rate this same workspace does pay,
on the basis that Databricks meters Genie consumption in serverless SQL DBUs. The DBU counts are
measured; only the multiplier is assumed, so the figure rescales linearly if Genie is priced
differently when the free tier ends.

**Why it is not comparable with the other rows, beyond the usual.** The cost column already mixes
meters — OpenAI tokens, an API-equivalent estimate, Snowflake credits, and now Databricks DBUs at a
proxy rate. This row adds a structural difference on top: it is the board's answer-track row, so
Genie executed every query itself against the full 58.5M-row dataset and that compute is inside the
number. The SQL-track rows only ever pay for inference plus a reference re-execution. Compare
within a band, and read this one as an order of magnitude rather than a price.

**Not affected.** No accuracy, latency or session figure changes. Pass^3 remains 117/190.

---

## E-2026-09-18-14 — Databricks Genie enters answer-track, and one session was re-captured

**What changed.** `results/2026-09-18-databricks-genie.json` adds Databricks Genie to the
commercial band at 117/190 Pass^3, 145/190 Pass@3, 19/41 tier-9 turns, 0/8 SSR.

**Two things about this row differ from every other row and are disclosed rather than buried.**

**1. It is scored answer-track.** Every other entry is SQL-track: the harness re-runs the SQL the
agent wrote on the single reference warehouse. This row is scored on the rows Genie's own
Databricks warehouse returned; nothing is re-executed. The organizers chose this deliberately for
this arm. It is only a measurement of the agent if the Databricks load equals the frozen snapshot,
so that was proved before any metered call: 22/22 tables, every row count exact (58,463,766 in
total), every column set matching, and 1,238 per-column aggregates (COUNT, COUNT DISTINCT, SUM,
MIN, MAX) identical on both engines. The SQL-track was then computed from the SAME captures, at no
extra cost, as a cross-check: it lands at 115/190 against answer-track's 117/190 and gives an
identical 19/41 on tier-9. A 2-task, 1.1-point difference between two independent methods is the
evidence that the load is faithful. Producing that cross-check required adding one dialect rule
(`try_divide`, which DuckDB does not have); before it, 63 statements that executed correctly on
Databricks failed on DuckDB, and the comparison would have measured the shim rather than the agent.

**2. One multi-turn session was discarded and re-captured.** In the first pass, four turns of one
9-turn conversation timed out because the capture host entered macOS Maintenance Sleep mid-call.
This was confirmed two ways: `pmset` logs the sleep/wake cycles across exactly that window, and the
rows' wall-clock elapsed exceeds their measured latency by 14 to 53 minutes, which is only possible
if `time.monotonic()` stalled while the UTC clock did not. Those were not Genie failures, but
Pass^N requires all three runs, so they were suppressing two turns the agent solved in the other
two runs. The whole session was discarded — not just the four turns, because a chained conversation
cannot be re-entered at turn 5 — and re-captured as one clean threaded conversation with sleep
inhibited. That moved Pass^3 from 115 to 117 and tier-9 from 17 to 19. No other execution in the
570 was affected, and all three final runs record 190/190 with status `ok`.

**Not affected.** No other entry, and no gold answer. The scorer, corpus and snapshot are unchanged.

## Open

### E-2026-09-01-02 — Tier 7 is 9/10 zero-row
**Severity: medium. Affects: tier 7 (10 tasks).**

Nine of the ten unanswerable / null-result questions have an empty correct answer, so "always
answer nothing" scores 90% on the tier. The tier is scheduled for rebalancing to roughly 50/50
zero-row and non-zero. Published as a floor row rather than left for a reader to discover.

### E-2026-09-01-03 — Tier 8 has no judge
**Severity: medium. Affects: all 10 tier-8 tasks.**

Open-analysis tasks are rubric-scored and the LLM-judge evaluator is not implemented. These ten
tasks are excluded from the denominator entirely (190 gradable of 200) and reported as
`rubric_pending`. They are not counted as failures and they are not counted as passes.

### E-2026-09-01-04 — Answer sets exceed a usable size
**Severity: low. Affects: 25 tasks over 100 rows, max 870.**

A 100-row cap on every answer is agreed but not yet enforced; the affected questions will be
re-scoped rather than deleted. No comparable benchmark asks for an 870-row answer.

### E-2026-09-01-05 — Two domain conventions remain undecided
**Severity: low.**

`revenue_share_pct` has two defensible readings (advisor share of firm revenue vs. firm share of
client fees), and stamp duty is excluded from `net_amount` while other statutory charges are
included. Both are documented in the datasheet and neither currently changes a gold answer; they
are listed so that a later decision is visible as a change rather than a surprise.

---

## Fixed

### E-2026-09-17-13 — Multi-turn is now measured, and the denominator changed with it
**Severity: high. Affects: every ranked row, and every percentage published before this date.**

Until now no system attempted the 41 tier-9 multi-turn turns. They counted as failures in
execution accuracy over 190, while Pass^N and Pass@N used a 149 denominator on the stated
grounds that reliability is only meaningful about work a system took on.

All six ranked systems have now run them, under a **chained** protocol: each turn is handed the
agent's own SQL from the immediately preceding turn of that session — right or wrong, never
corrected. An error on turn 2 is inherited by turn 3. Nothing gold is supplied at any point.

Two consequences, both of which change published numbers.

**Pass^N and Pass@N are now over 190, not 149.** Every system attempts every task, so the old
denominator no longer describes anything. Percentages fall accordingly — Claude Code's Pass^N
reads 70.5% here against 79.2% before, on more tasks, not fewer. A figure from before
2026-09-17 and one from after are not comparable as rates. The counts behind them are, and are
published alongside.

**Session success rate is reported for the first time.** A session counts only if every turn in
it passes on every run. Across 8 sessions and 6 systems, exactly one session has ever been
completed: LangChain took one four-turn session 4/4 on all three runs. Everything else
is 0/8. The session is identified by label on the board, not by task id, because these tasks
are held out.

An earlier plan measured these turns with an authored gold prior supplied at every turn. Those
runs were completed for all six systems and are **not** published: a turn handed a correct prior
regardless of what the agent did measures a per-turn ceiling, not whether a system can hold a
conversation. They are retained as ablation data. One finding from them is worth recording,
because it is counterintuitive: for LangChain the gold prior scored *worse* than the agent's own
prior (13/41 against 16/41). The authored prior is a deliberately minimal join key, while the
agent's own previous query is a complete statement — apparently more useful to build on, even
when wrong.

**Also added:** `results.by_session` in the entry schema, recording turns passed per session.
SSR alone cannot distinguish a system that solved 6 of 8 turns from one that solved 0 of 8;
both are a failed session, and they are not the same result.


### E-2026-09-15-12 — The LangChain row was scored against a different gold than every other row
**Severity: high. Affects: `results/2026-09-01-langchain-sql-agent.json`, and the README table.**

One gold answer, on a tier-4 task, was corrected earlier: the question attributes new clients via
the acquiring advisor, while the compiled gold had used the primary advisor. The corrected answer
returns 72 rows where the original returned 94.

The LangChain row was scored **before** that correction landed and was never re-scored. CrewAI,
nao, Vanna and Claude Code were all scored after it. Read from each row's own scored output, the
expected row count on that task is 72 for four systems and 94 for LangChain alone — so the board
was not on a single basis, and the one row that differed was the one published earliest.

All three of LangChain's published captures return 72 rows on that task, so it passes against the
corrected gold. Re-scoring the same three submissions — no new capture, no new inference — changes
exactly one task and nothing else:

    pass_all   86/149 (57.7%)  ->  87/149 (58.4%)
    pass_any  117/149 (78.5%)  -> 118/149 (79.2%)
    EX runs    0.536842, 0.515789, 0.547368  ->  0.542105, 0.521053, 0.552632
    tier 4     0.7143  ->  0.7429

**Fixed** by re-scoring and republishing the row. Every published row is now scored against the
same gold.

Two process notes, because the failure was in the checking rather than the scoring. First, an
earlier internal review concluded that no re-score was owed, on the strength of a capture file
that returned 70 rows — but that file was a pre-v1.3 capture, not the one this row is built from
and cites. A row's numbers must be checked against the artifacts the row itself names. Second,
a correction's effect on a score is to be read off the scored output, never derived by reasoning
about what the fix ought to do.


### E-2026-09-01-F5 — Ten tier-9 turns compiled to an empty gold answer
**Fixed in data snapshot `wm_synthetic_v1.3_2026_09_01`.** Two independent causes, one in the data
and one in a question.

*Cause 1 — advisor AUM targets were set roughly 4x too low.* Six of the ten turns ask which
advisors **missed** their FY2025 AUM target, and almost nobody did: 115 of 117 advisors beat
target, with a median book worth 4.0x the target assigned to them. The Senior band, which one
session filters on, had 4 advisors and 0 misses, so the turn returned nothing and every turn
chained off it inherited the empty set. The v1.2 AUM repair had lifted every advisor's book
without the targets being re-pinned. Targets are now set to each band's measured median book, so
48.9% of the 468 (advisor, period) rows miss, against 1.7% before.

*Cause 2 — one session was ill-posed.* It asked for Affluent-segment clients at or above a
threshold that is simultaneously the top of the Affluent band and the bottom of the next segment,
so no client could satisfy both halves. It had returned 9 rows in v1.1 only because the AUM
clipping defect had piled clients onto the band ceiling. The question now asks for clients
*approaching* that threshold, which is what "upgrade candidate" meant in the first place, and its
four turns return 28, 28, 27 and 27 rows.

**Blast radius, measured.** Exactly one column in one 468-row table changed; the other 21 tables
are identical row-for-row in both directions. Re-scoring the three baseline runs against the new
snapshot changed **0 of 600 task-run verdicts**, so the repair fixed the defect without moving
benchmark difficulty. The null-floor baseline fell from 19/190 to 9/190, and all 9 remaining are
tier 7, where an empty answer is genuinely correct.

### E-2026-09-01-F1 — AUM was constant within every client segment
**Fixed in data snapshot `wm_synthetic_v1.2_2026_09_01`.**

In v1.1, segment floors and caps were applied by clipping a log-normal draw, so all 298 Family
Office clients held exactly ₹10,000,000,000 and all 1,747 Ultra HNI exactly ₹500,000,000 — one
distinct value each. Every ranking, correlation and top-N question over `aum_inr` was degenerate.
Fixed by inverse-CDF sampling inside the band, so floors and caps became bounds rather than point
masses. Full list of v1.1→v1.2 repairs, with measured before/after magnitudes, is in
[DATASHEET.md](DATASHEET.md).

### E-2026-09-01-F2 — Revenue rows duplicated per trade
**Fixed in `wm_synthetic_v1.2_2026_09_01`.** 506,213 excess `txn_firm_revenue` rows were emitted;
revenue is now booked once per position. Duplicates on the full business key are now zero.

### E-2026-09-01-F3 — Securities transaction tax missing on purchases
**Fixed in `wm_synthetic_v1.2_2026_09_01`.** STT is charged on both legs of a delivery equity
trade; v1.1 charged it only on sales, understating charges on 210,866 buys.

### E-2026-09-01-F4 — Trades booked against bonds that did not exist yet
**Fixed in `wm_synthetic_v1.2_2026_09_01`.** 979,323 position-days sat outside their instrument's
issue-to-maturity life. 21 post-maturity position-days remain out of 52,052,531 and are documented
in the datasheet rather than claimed as clean.

---

## How to report a defect

Open an issue with the task id, the SQL you ran, and what you expected. A reproducible defect in a
gold answer is the most useful contribution anyone can make to this benchmark, and it will be
credited here.
