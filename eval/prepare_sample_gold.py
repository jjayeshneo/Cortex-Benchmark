#!/usr/bin/env python3
"""
prepare_sample_gold.py — expand sample_questions.json into the layout the scorer expects.

`sample/sample_questions.json` is the single published source of truth for the sample split.
The scorer, however, takes a compiled benchmark file plus a directory of per-task gold answers.
Rather than commit that expanded layout -- which would put a `gold_answers/` directory into a
public repo and permanently weaken the one invariant that protects the private split -- this
script materialises it on demand into a working directory that is git-ignored.

    python3 eval/prepare_sample_gold.py --out .sample_eval
    python3 eval/score_cortex_bench.py \
        --benchmark .sample_eval/benchmark.json \
        --gold-dir  .sample_eval/gold_answers \
        --mode submission --submission eval/example_submission.json \
        --duckdb-path data/wealth_management.duckdb \
        --out-dir .sample_eval/score
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SAMPLE = Path("sample/sample_questions.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=str(SAMPLE))
    ap.add_argument("--out", default=".sample_eval")
    args = ap.parse_args()

    src = json.loads(Path(args.sample).read_text(encoding="utf-8"))
    snapshot = src.get("data_snapshot_id")
    out = Path(args.out)
    gold_dir = out / "gold_answers"
    gold_dir.mkdir(parents=True, exist_ok=True)

    benchmark = []
    for q in src["questions"]:
        tid = q["task_id"]
        g = q["gold"]
        (gold_dir / f"{tid}.json").write_text(json.dumps({
            "task_id": tid,
            "data_snapshot_id": snapshot,
            "schema_version": "v1.0",
            "sql_dialect": "duckdb",
            "gold_compiler_version": "cortex_gold_compiler_v1.0",
            "gold_sql": q.get("gold_sql"),
            "row_count": g.get("row_count"),
            "columns": g.get("columns"),
            "answer_sha256": g.get("answer_sha256"),
            "answer": g.get("answer"),
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        benchmark.append({
            "task_id": tid,
            "session_id": tid.rsplit("_T", 1)[0] if q.get("tier") == 9 else tid,
            "tier": q.get("tier"),
            "sql_difficulty": q.get("sql_difficulty"),
            "primary_axis": q.get("primary_axis"),
            "data_snapshot_id": snapshot,
            "schema_version": "v1.0",
            "sql_dialect": "duckdb",
            "domain": "wealth_management",
            "evaluation_mode": "execution",
            "interaction_mode": "multi_turn" if q.get("tier") == 9 else "single_turn",
            "evaluator_metadata": {},
            "turns": [{
                "turn_id": f"{tid}_T1",
                "turn_number": 1,
                "prior_turn_context_sql": None,
                "llm_inputs": {
                    "question": q.get("question"),
                    "domain_evidence": q.get("domain_evidence"),
                },
                # Field names here are the scorer's contract, not ours to choose:
                # gold_answer_path, gold_answer_type and scoring_method are read directly by
                # evaluate_tasks(). Getting one wrong fails at load time, not silently.
                "ground_truth": {
                    "gold_sql": q.get("gold_sql"),
                    "gold_answer_path": f"gold_answers/{tid}.json",
                    "gold_answer_sha256": g.get("answer_sha256"),
                    "gold_answer_type": q.get("answer_type"),
                    "scoring_method": q.get("scoring_method"),
                    "expected_output_columns": g.get("columns"),
                    "expected_row_count": g.get("row_count"),
                    "value_tolerance": q.get("value_tolerance"),
                    "rubric": None,
                },
            }],
        })

    (out / "benchmark.json").write_text(
        json.dumps(benchmark, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(benchmark)} tasks -> {out}/benchmark.json")
    print(f"wrote {len(benchmark)} gold answers -> {gold_dir}/")
    print(f"\nsnapshot: {snapshot}")
    print("These gold answers are only valid against that snapshot. Verify your database hash first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
