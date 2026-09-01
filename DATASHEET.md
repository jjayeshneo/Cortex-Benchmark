# Datasheet — Cortex-Bench

Following the structure of *Datasheets for Datasets* (Gebru et al., 2018). Written to be read by
someone deciding whether to trust this benchmark, so the defects are here, not buried.

---

## Motivation

**Why does this dataset exist?** Text-to-SQL benchmarks are mostly broad and shallow — many small
databases, one question each, and schemas simple enough that a competent agent needs no knowledge
beyond the DDL. Real analytical work is the opposite: one large schema you must learn deeply,
business rules that live outside the database, questions asked in sequence, and questions that
cannot be answered from the data at all. Cortex-Bench measures that.

**Who created it and who funded it?** Built internally at Neosapients as an evaluation harness for
text-to-SQL agents, then released.

---

## Composition

**What do the instances represent?** Synthetic records of an Indian wealth-management platform:
clients, advisors, instruments, trades, positions, revenue.

| | |
|---|---|
| Tables | 22 |
| Rows | 58,463,766 |
| Size | 1.07 GB (DuckDB) |
| Investors | 10,000 |
| Advisors | 117 |
| Instruments | 355 (150 equity, 120 mutual funds, 30 NCDs, 25 G-Secs, 20 AIFs, 10 indices) |
| Accounts | 18,430 |
| Trades | 937,171, spanning 2022-01-17 to 2026-06-09 |
| Position snapshots | 52,052,531 across 230 weekly dates |
| Questions | 200 — 39 public, 161 held out |

**Is any of this real data?** **No.** Every row is generated. There are no real people, no real
account numbers, no real PAN identifiers, no customer records of any kind. Names, identifiers and
contact details are synthesised. **The dataset contains no personal or confidential information
and was never derived from any.**

**Is anything missing?** Yes, and it matters:

- Bonds have **no daily price series**. Fixed-income market value, clean/dirty price and
  unrealised FI P&L cannot be computed. No question asks for them.
- Corporate actions are declared but **never settle**. Twenty dividends exist as reference rows
  with per-share amounts and payment dates; not one rupee reaches the cashflow ledger, and no
  bonus or split adjusts a holding. Total-return questions would be wrong. None are asked.
- `txn_trade.other_charges` is `0.0` on every row — an unmodelled column.
- `net_amount` on a buy excludes `stamp_duty`, which is recorded but never charged to the client
  (₹3.24 crore across the corpus). The one exception is SIP installments, built by a different
  code path, which do include it. The two paths disagree.
- Monetary values are rounded with Python's banker's rounding rather than the round-half-up
  convention Indian tax uses. 3,020 of 937,171 trades (0.32%) carry a GST value that differs by
  one paisa from a half-up calculation.

**Errors, noise, redundancies?** After the v1.2 repair pass (below), `txn_firm_revenue` contains
**zero** duplicate rows on its full business key, verified across all 3,214,159 rows. One residual
remains: **21 position-days on bonds past their maturity**, out of 52,052,531 — 0.00004%. It is
recorded here rather than claimed absent.

---

## Collection process

**How was it generated?** By a deterministic Python generator seeded with `RANDOM_SEED = 42`,
producing 22 CSVs that are then materialised into DuckDB. Distributions are drawn from documented
business rules — segment AUM bands, per-segment trade frequency, statutory tax rates, SEBI minimum
commitments — not sampled from any real book.

**How were the questions written?** Authored against the schema, then **compiled**: each
question's reference SQL is executed against the frozen database and the result is stored as the
gold answer with a SHA-256. A question whose SQL fails to compile does not enter the corpus.

---

## Preprocessing and the v1.2 repair

The first release candidate (v1.1) shipped with degenerate data. A systematic audit found and
fixed the following. This is disclosed because anyone querying v1.1 would have found it in a
minute, and because it explains why published numbers are snapshot-bound.

| Defect in v1.1 | Effect | v1.2 |
|---|---|---|
| `aum_inr` clipped onto segment boundaries | Ultra HNI: 1,759 clients, **1 distinct value**. All four segments piled on their floor | Truncated log-normal within band; every client distinct |
| Trail commission emitted per tax lot | 506,213 excess revenue rows, 181,779 byte-identical | One row per position per quarter; revenue unchanged (+0.00004%) |
| `accrued_interest_inr` = 0.0 | Dead column across 53.8 M rows | Accrues on G-Sec and NCD, 30/360 semi-annual. Debt funds stay 0 by design |
| STT charged on sells only | 210,866 equity buys at zero, contradicting Indian tax law | Levied on both legs |
| Listed debt charged no brokerage | 77,718 bond trades free | 5 bps on NCD and G-Sec |
| KPI targets had no per-advisor variance | 3 distinct values across 468 rows | Independent jitter per target |
| Money targets shared one random draw | `target_aum / target_revenue` constant per band; correlating two targets returned exactly 1.0 | Independent draws |
| Only 1:1 bonuses and 2:1 splits existed | A task's evidence documented 1:2, 2:1 and 3:2 factors that never occurred | All four ratios present; splits vary 2:1 / 5:1 / 10:1 |
| Bonds held outside their lifecycle | 979,323 position-days before issue, 1,210,944 after maturity, 16,134 trades in unissued bonds | Lifecycle gate plus maturity redemption at par |
| Bond prices ignored face value | G-Sec (₹100 face) traded to ₹500; NCD (₹1,000 face) to ₹100 | Quoted as 92–108% of par |

**Verification.** Each fix was validated by replaying the *old* rule against the live database
first and confirming it reproduced the published data exactly, so every before/after comparison is
measured rather than modelled.

**Effect on difficulty.** The same agent SQL, re-executed against v1.2 and scored against
recompiled gold, changed verdict on **1 of 149 tasks** — and that one moved fail→pass because a
Gini-coefficient question had been unanswerable while AUM had only a handful of distinct values.
The repair changed the data substantially without changing what the benchmark measures.

### v1.2 → v1.3

One defect, one column.

| Defect in v1.2 | Effect | v1.3 |
|---|---|---|
| `target_aum_inr` still calibrated against v1.1 advisor books | The v1.2 AUM repair lifted every book without re-pinning targets, so 115 of 117 advisors beat target and every "which advisors missed target" question returned nothing | Targets set to each band's measured median book; 48.9% of the 468 (advisor, period) rows now miss, against 1.7% |

**Blast radius, measured.** `target_aum_inr` is the only column that changed. The other 21 tables
are identical row-for-row in both directions, and re-scoring the three baseline runs against v1.3
changed **0 of 600 task-run verdicts** — the repair removed a defect without moving difficulty. The
change alters no random draw: the generator's jitter is consumed in the same order and count, so
the new values are what a full regeneration produces.

---

## Uses

**What is it for?** Evaluating text-to-SQL and analytical agents on schema linking, joins,
window functions, domain reasoning, unanswerable questions and multi-turn dialogue.

**What should it not be used for?**

- **Training data.** The public sample is 39 questions; fine-tuning on them then reporting a
  benchmark score is meaningless.
- **Estimating your score on the full benchmark.** The sample is stratified by tier, not by
  difficulty, and difficulty in this corpus is largely a property of tier.
- **Any claim about real financial markets, clients or advisers.** It is synthetic. Nothing here
  is evidence about anything real.
- **Cross-domain generalisation.** One database, one domain.

**Could it cause harm?** The dataset models Indian securities taxation. Rates and rules are
encoded as of authoring and **must not be relied on as tax advice**; they are a fixture for
evaluating query correctness.

---

## Distribution

Database under CC BY-SA 4.0; code under Apache-2.0. Distributed as a single DuckDB file with a
published SHA-256. **Gold answers are snapshot-bound** — they were produced against
`wm_synthetic_v1.3_2026_09_01` and are meaningless against any other snapshot.

The 161 held-out questions are not distributed. Publishing them would end the benchmark's
usefulness permanently, so a CI check refuses any commit containing a held-out task id or a
gold-bearing field outside the sample file.

---

## Maintenance

**Who maintains it?** Neosapients. Errata are recorded in `docs/ERRATA.md`.

**Will it change?** Yes. Corpus and snapshot are versioned together; a data change invalidates
every gold answer, so any new snapshot ships with recompiled answers and a new id. Results are
comparable only within a snapshot, and leaderboard entries record which one they used.

**Known-broken right now:** nothing in the gold answers. The ten tier-9 turns that compiled to an
empty answer under v1.2 were repaired in v1.3 (see [ERRATA.md](ERRATA.md), E-2026-09-01-F5): advisor
AUM targets were re-pinned to each band's measured median book, and one ill-posed question was
retargeted. The remaining known imbalance is tier 7, where 9 of 10 questions have a genuinely empty
answer, so a system that answers nothing scores 4.7% overall. That is published as a baseline row
rather than left for a reader to find.
