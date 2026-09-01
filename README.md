# Cortex-Bench

**Enterprise-scale, single-domain text-to-SQL with domain knowledge, multi-turn sessions, and
questions whose correct answer is that there is no answer.**

Most text-to-SQL benchmarks test breadth: many small databases, one question each. Cortex-Bench
tests depth. One 58-million-row wealth-management platform, 22 tables, and questions that require
knowing how Indian securities taxation actually works — not just how to write a join.

| | Cortex-Bench | Spider | BIRD |
|---|---|---|---|
| Questions | 200 (39 public) | 10,181 | 12,751 |
| Databases | **1** | 200 | 95 |
| Rows | **58.5 M** | small | — |
| Size | **1.07 GB** compressed | small | 33 GB |
| External domain knowledge | **yes** | no | yes |
| Multi-turn sessions | **yes** | no | no |
| Unanswerable questions | **yes** | no | no |

We are smaller than Spider and BIRD on question count and do not pretend otherwise. What we have
that they do not is depth in one domain, conversations, and questions designed to be unanswerable.

---

## Leaderboard

Live board: **[jjayeshneo.github.io/Cortex-Benchmark](https://jjayeshneo.github.io/Cortex-Benchmark/)** —
generated from `results/*.json`, one committed file per row.

| | System | Model | EX (mean ± sd) | pass@3 / pass^3 | Coverage |
|---|---|---|---|---|---|
| — | *Null floor — answers nothing* | *none* | *4.7%* | — | 190/190 |
| 1 | LangChain SQL agent | gpt-5.6-luna | **53.3% ± 1.6** | 117 / 86 | 149/190 |

**Every number on this board is a mean over three runs, and the denominator is always 190.** Two
things follow that are easy to miss:

- **Skipping does not help you.** The LangChain baseline is single-turn, so it never attempts the
  41 multi-turn turns and they score as failures. On the 149 tasks it does attempt it gets
  **68.0%** — that is a legitimate figure, but it is a *subset* figure and it does not go in the
  ranking column.
- **A single run is not reproducible.** Runs of 102, 98 and 104 look like a stable system. They are
  not: **31 tasks (21%) change verdict between runs** at identical settings. `pass@3` (passed at
  least once) is 117; `pass^3` (passed every time) is 86. The 31-task gap is churn, and a
  leaderboard reporting one number per system is publishing it as signal.

**The floor row is there on purpose.** A system that returns the empty set for all 190 tasks scores
4.7% — 9 of the 10 tier-7 questions genuinely have no rows, so silence is worth something on that
tier and nothing anywhere else. Any score has to be read against that floor. It also catches
defects: in v1.2 this row scored 10.0%, and the extra ten came from tier-9 turns that had wrongly
compiled to an empty gold ([ERRATA.md](ERRATA.md), E-2026-09-01-F5).

*No human baseline yet. It is the most important missing number on the board and we will not claim
one until it is measured.*

---

## Quickstart

Five minutes. No API key, no model calls.

```bash
git clone https://github.com/jjayeshneo/Cortex-Benchmark.git && cd Cortex-Benchmark
pip install -r requirements.txt          # duckdb, pandas, numpy — the scorer's only deps

./data/download.sh                       # 1.07 GB from GitHub releases, verifies sha256

python3 eval/prepare_sample_gold.py --out .sample_eval
python3 eval/score_cortex_bench.py \
    --benchmark  .sample_eval/benchmark.json \
    --gold-dir   .sample_eval/gold_answers \
    --mode       submission \
    --submission eval/example_submission.json \
    --duckdb-path data/wealth_management.duckdb \
    --out-dir    .sample_eval/score
```

Expected: **`Tasks passed: 23/39`**. A different number means your database is not the snapshot
these answers were compiled against — check the hash before investigating anything else.

---

## The nine tiers

| Tier | Name | What it tests |
|---|---|---|
| 1 | Schema linking | Find the right table and column from a question that names neither |
| 2 | Single-table retrieval | Filter, aggregate and sort within one table |
| 3 | Multi-table joins | Traverse two or more relationships correctly |
| 4 | Aggregation and grouping | Group, roll up and rank across joined entities |
| 5 | Window functions | Running totals, percentiles, rank-within-group |
| 6 | Domain reasoning | Apply Indian wealth-management rules — tax, corporate actions, fees |
| 7 | Unanswerable / null-result | The correct answer is that there is none. Guessing is penalised |
| 8 | Open-ended analysis | Rubric-scored narrative. Judge not yet released |
| 9 | Multi-turn sessions | A conversation; later turns refer to earlier ones by pronoun or ellipsis |

Tier 7 is the one most benchmarks lack. An agent that always produces *some* SQL and *some* rows
scores zero on it, which is the point: knowing a question cannot be answered from the data is part
of the job.

`sample/` holds 39 questions with gold answers, about five per tier, plus one complete multi-turn
session. See [sample/README.md](sample/README.md) — including an honest note on why the sample's
difficulty mix is not the corpus's.

---

## Scoring

Your column names do not matter. Row order matters only where the question asks for an ordering.
Numeric precision only has to match gold's.

Rows are compared by a **name-independent value signature**, so aliasing `client_count` as
`n_clients` costs nothing. Full policy — including the three deliberate relaxations and the
`[]` vs `null` distinction that decides all of tier 7: **[eval/SCORING.md](eval/SCORING.md)**.

The scorer in `eval/` is the same file we run. There is no second, private scorer.

---

## The database

| | |
|---|---|
| Snapshot | `wm_synthetic_v1.3_2026_09_01` |
| SHA-256 | `7caa6785340cd23b4c2691df0cf8c0350718da13bba598338d10e4e8576ee8ed` |
| Tables / rows | 22 / 58,463,766 |

| Table | Rows | Columns |
|---|---|---|
| `pos_holding_daily` | 52,052,531 | 12 |
| `txn_firm_revenue` | 3,214,159 | 18 |
| `txn_cashflow` | 937,171 | 17 |
| `txn_trade` | 937,171 | 26 |
| `pos_holding_lot` | 840,592 | 12 |
| `market_price_daily` | 312,660 | 11 |
| `txn_lot_closure` | 107,071 | 14 |
| `investor_goal` | 27,244 | 10 |
| `investor_account` | 18,430 | 17 |
| `investor_profile` | 10,000 | 41 |
| `txn_sip_mandate` | 2,862 | 15 |
| `market_index_daily` | 2,310 | 9 |
| `kpi_advisor_target` | 468 | 12 |
| `instrument_detail` | 355 | 46 |
| `instrument_master` | 355 | 28 |
| `instrument_credit_rating` | 184 | 8 |
| `advisor_profile` | 117 | 26 |
| `market_corporate_action` | 35 | 11 |
| `model_portfolio_allocation` | 25 | 7 |
| `org_business_unit` | 13 | 13 |
| `rule_taxation` | 8 | 12 |
| `model_portfolio` | 5 | 8 |

Full DDL: [data/schema/wealth_management.sql](data/schema/wealth_management.sql).

---

## Known limitations

Stated by us, before anyone else states them.

- **One database, one domain.** Cross-domain generalisation is not measured here.
- **200 questions.** Small. 39 public, 161 held out.
- **No human baseline.** We do not know the ceiling.
- **No held-out test server yet.** The submission process is not live.
- **Tier 8 (10 questions) is unscored** — the rubric judge is not implemented.
- **Fixed income is incompletely modelled.** Bonds have no daily mark-to-market series, so FI
  valuation and clean/dirty price questions are out of scope.
- **Dividends are declared but never settle.** Corporate actions are reference data that never
  reach the cashflow ledger, so total-return questions would be wrong. None are asked.
- **Efficiency is not measured.** No VES-equivalent metric yet.

Every one of these, plus each correction we have made and each one still open, is tracked in
[ERRATA.md](ERRATA.md). A benchmark with no errata log is one whose defects nobody has looked for.

---

## Licence and citation

Database: CC BY-SA 4.0. Code: Apache-2.0. See `CITATION.cff`.
