# Sample questions

**39 questions** from Cortex-Bench, published with their gold answers so you can
see exactly what the benchmark asks and how it is scored. The evaluation split is private.

Data snapshot: `wm_synthetic_v1.3_2026_09_01`. These answers are only correct against that snapshot —
verify your database hash before comparing.


## What is in here, and what is not

| | |
|---|---|
| Sample questions | **39** |
| Held out for evaluation | **161** |
| Tiers represented | 1–7 and 9 (tier 8 excluded, see below) |
| Multi-turn | one **complete** session, 4 turns |

Two selection rules worth knowing, because they shape what you see:

1. **Multi-turn sessions are published whole or not at all.** Releasing turn 1 without its
   follow-ups would leak the session's premise and its coreference chain.

2. **Tier 8 is not sampled.** It is rubric-scored and the judge is not released yet, so a sample
   would demonstrate a scoring path you cannot run.


## The nine tiers

| Tier | Name | What it tests | In sample |
|---|---|---|---|
| 1 | Schema linking | Find the right table and column from a question that names neither. | 5 |
| 2 | Single-table retrieval | Filter, aggregate and sort within one table. | 5 |
| 3 | Multi-table joins | Traverse two or more relationships correctly. | 5 |
| 4 | Aggregation and grouping | Group, roll up and rank across joined entities. | 5 |
| 5 | Window functions and ranking | Ordered analytics: running totals, percentiles, rank-within-group. | 5 |
| 6 | Domain reasoning | Apply Indian wealth-management rules — tax, corporate actions, fee structures. | 5 |
| 7 | Unanswerable and null-result | The correct answer is that there is no answer, or none. Guessing is penalised. | 5 |
| 8 | Open-ended analysis | Rubric-scored narrative analysis. Excluded from this sample — the judge is not released yet. | 0 |
| 9 | Multi-turn sessions | A conversation. Later turns refer to earlier ones by pronoun or ellipsis. | 4 |

## Difficulty mix — read this before comparing to the corpus

| | Sample | Full corpus |
|---|---|---|
| Simple | 33.3% | 22.0% |
| Medium | 30.8% | 41.5% |
| Advanced | 35.9% | 36.5% |

The sample is **stratified by tier** — five per tier — not by difficulty, and in this corpus
difficulty is largely a property of the tier: tier 1 is entirely `Simple`, tiers 5 and 6 are
entirely `Advanced`. An equal-per-tier sample therefore cannot reproduce the corpus difficulty
mix, which is 22% `Simple` only because tiers 1–2 are small. **The sample is not a difficulty-
representative subset and should not be used to estimate your score on the full benchmark.**


## One example per tier


### Tier 1 — Schema linking

> How many relationship managers are currently active at the firm?

**Domain evidence provided to the agent:** At this firm, 'relationship managers' refers to client-facing advisory staff in both the 'RM' and 'Junior RM' role categories. Senior titles such as MD, VP, and AVP are recorded as designations, not as a separate role_category.

`CB_T1_001_T1` · Simple · scored by **Exact** · gold is **1 row(s)**


### Tier 2 — Single-table retrieval

> How many clients were onboarded in FY2023?

**Domain evidence provided to the agent:** In India, a financial year runs from April 1 to March 31. FY2023 covers April 1, 2023 to March 31, 2024.

`CB_T2_016_T1` · Simple · scored by **Exact** · gold is **1 row(s)**


### Tier 3 — Multi-table joins

> List the top 10 advisors by number of active clients assigned to them — showing each advisor's code, name, and seniority band; where advisors are tied on active-client count, rank them by advisor code in ascending order.

`CB_T3_031_T1` · Medium · scored by **Ordered-List-Match** · gold is **10 row(s)**


### Tier 4 — Aggregation and grouping

> How many active clients have an AUM above the HNI threshold of Rs 50 lakhs?

**Domain evidence provided to the agent:** 50 lakhs = 5,000,000 in raw INR.

`CB_T4_068_T1` · Simple · scored by **Exact** · gold is **1 row(s)**


### Tier 5 — Window functions and ranking

> Show the full management chain from every advisor up to the Managing Director.

**Domain evidence provided to the agent:** Advisors are identified by advisor_code together with advisor_full_name. Include these identifier columns in the result. Report the chain as a single text value listing advisor full names from the Managing Director down to the advisor, separated by ' > ' (space, greater-than, space). An advisor with…

`CB_T5_101_T1` · Advanced · scored by **Set-Match** · gold is **117 row(s)**


### Tier 6 — Domain reasoning

> Calculate each resident investor's total LTCG tax liability on equity sold on or after July 23 2024, applying the Budget 2024 rate of 12.5% on gains above Rs 1.25 lakh exemption, and show me the 50 investors with the highest liability.

**Domain evidence provided to the agent:** Budget 2024 effective July 23 2024: LTCG rate on equity raised to 12.5% with exemption limit raised to Rs 1.25 lakh (125000). LTCG requires holding period >= 365 days. Resident investors only. Clients are identified by investor_code together with legal_name. Include these identifier columns in the r…

`CB_T6_116_T1` · Advanced · scored by **Value-Match** · gold is **50 row(s)**


### Tier 7 — Unanswerable and null-result

> List all clients who have a Rejected KYC status and also have an active investment account, showing the account type.

**Domain evidence provided to the agent:** Clients are identified by investor_code together with legal_name. Include these identifier columns in the result.

`CB_T7_141_T1` · Simple · scored by **Exact** · gold is **0 row(s)** — *the empty set is the correct answer*


### Tier 9 — Multi-turn sessions

> How many clients were onboarded in each quarter of FY2024?

**Domain evidence provided to the agent:** FY2024 runs April 1 2024 to March 31 2025. Indian fiscal quarters: Q1=Apr-Jun 2024, Q2=Jul-Sep 2024, Q3=Oct-Dec 2024, Q4=Jan-Mar 2025.

`CB_MULTI_003_T1` · Medium · scored by **Set-Match** · gold is **4 row(s)**


## Field reference

```
task_id          stable identifier
tier             1-9, see above
sql_difficulty   Simple | Medium | Advanced
primary_axis     Schema | Data
scoring_method   Set-Match | Ordered-Match | Scalar-Match | Rubric
question         the natural-language question
domain_evidence  business context given to the agent; not a hint at the SQL
gold_sql         the reference query
gold.answer      the reference answer, as the scorer compares it
gold.answer_sha256  hash of the canonical answer
```
