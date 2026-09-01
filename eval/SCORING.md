# How Cortex-Bench scores an answer

Everything here is implemented in `eval/score_cortex_bench.py`, which is the same file we run.
There is no second, private scorer.

The short version: **your column names do not matter, your row order usually does not matter,
and your numeric precision only has to match gold's.** What matters is the values.

---

## 1. What you submit

```json
{
  "predictions": [
    {"task_id": "CB_T1_001_T1", "predicted_answer": 117, "generated_sql": "SELECT ..."},
    {"task_id": "CB_MULTI_003_T2", "predicted_answer": [{"referral_source": "Banker Lead", "client_count": 200}]},
    {"task_id": "CB_T7_141_T1", "predicted_answer": []}
  ]
}
```

`predicted_answer` takes exactly three shapes:

| Your result | Submit | Notes |
|---|---|---|
| One row, one column | the bare value — `117` | not `[{"col": 117}]`, though that is also accepted |
| Any other result set | list of `{column: value}` objects | one object per row |
| Zero rows | `[]` | **a real answer** |
| Query never ran / agent declined | `null` | **not** the same as `[]` |

**`[]` and `null` are not interchangeable, and the difference decides a whole tier.** `[]` means
"the result set is empty", which is the *correct* answer for every tier-7 question. `null` means
"no prediction was produced" and always scores as a failure. Collapsing an executed-but-empty
result to `null` fails every tier-7 task while looking like a harmless bug.

`generated_sql` is optional for scoring but requested: it lets a result be reproduced and audited.
A submission whose SQL cannot be re-executed cannot be verified by anyone, including you.

---

## 2. Scoring methods

Each task declares one. It is in the sample file as `scoring_method`.

| Method | Row order | What is compared |
|---|---|---|
| `Set-Match`, `Exact-Set`, `Unordered-Set`, `Row-Set-Match`, `Exact` | ignored | multiset of rows |
| `Ordered-Match`, `Ordered-List-Match`, `List-Match` | **significant** | rows in sequence |
| `Scalar-Match`, `Exact-Scalar` | n/a | one value |
| `Rubric` | n/a | narrative, judged (tier 8; not in the sample) |

Order is only enforced where the question actually asks for an ordering.

---

## 3. Cell normalization

Applied to every value on both sides before comparison, by `normalize_value()`:

| Rule | Example |
|---|---|
| Null-like values collapse to `None` | `NaN`, `None` → `None` |
| Whitespace is collapsed and trimmed | `" HNI "` → `"HNI"` |
| Unicode is NFKC-normalized; curly quotes and dashes map to ASCII | `"don’t"` → `"don't"` |
| A midnight timestamp reduces to its date | `"2026-03-10T00:00:00"` → `"2026-03-10"` |
| Numeric types unify | `1326` and `1326.0` compare equal |
| `Decimal` and `bytes` are decoded to their canonical text | |

The date rule is deliberately narrow: **only** an ISO timestamp at exactly `00:00:00` (with an
optional all-zero fractional part) is reduced. Any real time-of-day is left untouched, so two
genuinely different instants can never be merged.

---

## 4. Row matching ignores your column names

This is the part most people do not expect.

Rows are compared by a **name-independent value signature** — the sorted multiset of the row's
cell values, plus the column count. Aliasing a column differently from gold costs you nothing.

Gold, from `CB_MULTI_003_T2`:
```json
{"referral_source": "Banker Lead", "client_count": 200}
```
Your answer, same values, different alias:
```json
{"referral_source": "Banker Lead", "n_clients": 200}
```
Naive dict equality says these differ. The scorer computes the signature
`(("num","200"), ("str","banker lead"))` for both, and they match. **This passes.**

The trade-off is explicit: a result that renamed every column *and* permuted the values into
different column meanings, yet still produced identical per-row value multisets across the whole
table, would match. That is vanishingly unlikely, and we consider it a far smaller cost than
failing correct answers over an alias.

---

## 5. Numbers

Predicted numeric values are **quantized to gold's decimal precision** before comparison, then
compared with `abs_tol = 1e-6` and `rel_tol = 1e-9`.

If gold rounds to 4 decimal places, you are compared at 4 decimal places. You are not punished for
carrying more precision, and you cannot pass by carrying less.

---

## 6. Three relaxations

Deliberate, and they only ever turn a *fail* into a *pass*:

1. **Extra columns.** Returning additional columns beyond those gold projects does not fail the
   task, provided every gold column is present and correct.
2. **Requested columns.** Where a question names the columns it wants, those are what is checked.
3. **Empty set vs count-of-zero.** For a question whose gold answer is empty, a single row
   containing only the number `0` is accepted — `SELECT COUNT(*)` returning `0` and a query
   returning no rows are the same finding.

---

## 7. Reproducing a score

```bash
python3 eval/prepare_sample_gold.py --out .sample_eval
python3 eval/score_cortex_bench.py \
    --benchmark  .sample_eval/benchmark.json \
    --gold-dir   .sample_eval/gold_answers \
    --mode       submission \
    --submission eval/example_submission.json \
    --duckdb-path data/wealth_management.duckdb \
    --out-dir    .sample_eval/score
```

The bundled `eval/example_submission.json` scores **23/39**. If you get a different number, your
database is not the snapshot these answers were compiled against — check its hash before
investigating anything else.

Outputs: `task_scores.json` (per task), `scores_summary.json`, `session_scores.json`,
`leaderboard_row.json`.

---

## 8. Gold answers are snapshot-bound

Every gold answer is compiled by executing its reference SQL against one frozen database. The
snapshot id is recorded in `sample_questions.json` and in every gold artifact. **Answers from one
snapshot are meaningless against another** — the scorer refuses to run when the database does not
reproduce the gold it is about to score against, which is a feature, not an obstacle.
