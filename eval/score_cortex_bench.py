#!/usr/bin/env python3
"""
Cortex-Bench Scorer v1.4

Fix in v1.1:
- Treat JSON null / Python None as a valid predicted_answer when the key exists.

Changes in v1.3:
- "Rubric" tasks excluded from TSR (passed=None); reported as rubric_pending_count.
- "Exact" scoring method registered explicitly in SET_MATCH_METHODS (was implicit fallthrough).
- values_equal: case-insensitive + strip comparison for free-text strings.
- Gold answer SHA256 verified at score time (abort on mismatch).
- leaderboard_row now includes is_certification and row_type fields.

Changes in v1.4 (extra-column relaxation):
- When (and ONLY when) a prediction has MORE columns than gold, pass/fail is relaxed: find an
  injective mapping gold_col -> pred_col whose per-column value multisets match (tolerance-aware),
  then verify by projecting the prediction onto the mapped columns and re-running the EXISTING
  comparison (Scalar/Set/Ordered-List, tolerance + ordering unchanged). One valid mapping -> pass;
  multiple valid mappings -> disambiguate by gold column name (case-insensitive), else FAIL with
  error_type="ambiguous_column_mapping"; no valid mapping -> fail as before.
- Equal-column and fewer-column predictions are byte-identical to v1.3 (relaxation never fires).
- Only pass/fail relaxes: precision / recall / row_f1 / column_match are still computed on the raw
  (extra-column) prediction, so the quality metrics keep penalizing the extra columns.
- Per-task flag extra_columns_relaxed=true records when the relaxed path decided the pass.

v1.6 — empty-set existence equivalence: for a task whose GOLD is the empty set (an existence /
"are there any … / show any …" check whose true answer is "none"), a prediction that is exactly
one row with one cell normalizing to numeric 0 ([[0]] / [["0"]]) is accepted as equivalent to the
empty rowset. Guarded hard: gold must be empty AND the prediction a single zero cell; a missing /
None / "" prediction stays a fail (an un-attempted task never passes), and multi-row / multi-column
/ non-zero predictions never fire. Monotonic (only flips fail->pass); per-task flag
empty_set_relaxed=true records it.

v1.6 — date-format canonicalization: an ISO datetime at exactly midnight ('2022-01-01T00:00:00',
optional all-zero fractional, 'T' or space separator) is reduced to its date ('2022-01-01') inside
normalize_value, so gold's pandas-Timestamp date form and an agent's bare-date string compare equal.
Datetimes with any real time-of-day are left untouched, so it provably merges only representations of
the same instant (loosens nothing else).

Modes:
1) gold-sql    : execute each task's gold_sql against DuckDB and compare to gold answers.
2) submission  : score an existing submission JSON against gold answers.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timezone
from types import SimpleNamespace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import duckdb
import numpy as np
import pandas as pd

SCORER_VERSION = "cortex_scorer_v1.6"
DEFAULT_NUMERIC_ABS_TOL = 1e-6
DEFAULT_NUMERIC_REL_TOL = 1e-9

# "Exact" added explicitly: 31 Scalar tasks are caught by the answer_type=="Scalar" branch;
# 9 Set tasks dispatch here. Behaviour is identical to the prior implicit fallthrough.
SET_MATCH_METHODS = {"Set-Match", "Set Match", "Exact-Set", "Unordered-Set", "Row-Set-Match", "Exact"}
ORDERED_METHODS = {"Ordered-Match", "Ordered-List-Match", "List-Match"}
SCALAR_METHODS = {"Scalar-Match", "Scalar Match", "Exact-Scalar"}
# Rubric tasks are excluded from Task Success Rate pending an LLM-judge evaluator.
RUBRIC_METHODS = {"Rubric"}

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("cortex_scorer")


def is_null_like(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
        if isinstance(result, (list, tuple, np.ndarray, pd.Series)):
            return False
        return bool(result)
    except Exception:
        return False


def normalize_value(value: Any) -> Any:
    if is_null_like(value):
        return None
    if isinstance(value, pd.Timestamp):
        return _canonical_datestr(value.isoformat())
    if isinstance(value, datetime):
        return _canonical_datestr(value.isoformat())
    if isinstance(value, date):
        return value.isoformat()  # a pure date has no time component; already 'YYYY-MM-DD'
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return _canonical_datestr(_normalize_str(value))
    return value


# Cosmetic-equivalence normalization for strings (defensive hardening; provably loosens nothing —
# it only collapses whitespace runs and maps unicode punctuation variants to their ASCII form, so
# genuinely different values still differ). Applied everywhere via normalize_value.
_WS_RE = re.compile(r"\s+")
_PUNCT_MAP = {0x2018: "'", 0x2019: "'", 0x201C: '"', 0x201D: '"',
              0x2013: "-", 0x2014: "-", 0x00A0: " "}


def _normalize_str(value: str) -> str:
    s = unicodedata.normalize("NFKC", value)
    s = s.translate(_PUNCT_MAP)
    return _WS_RE.sub(" ", s).strip()


# v1.6 date-format canonicalization (provably loosens nothing): a DATE and its MIDNIGHT-timestamp
# form denote the same day, but gold stores dates as pandas-Timestamp isoformat ('2022-01-01T00:00:00')
# while agents commonly return the bare date ('2022-01-01') — raw string compare marks them unequal.
# This reduces an ISO datetime at EXACTLY midnight (00:00:00, optional all-zero fractional, 'T' or space
# separator) to its date part, so the two representations match. A datetime with ANY real time-of-day
# (incl. non-zero fractional seconds) is left untouched — no information is discarded, so two genuinely
# different instants can never be merged.
_ISO_MIDNIGHT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]00:00:00(?:\.0+)?$")


def _canonical_datestr(s: Any) -> Any:
    if isinstance(s, str):
        m = _ISO_MIDNIGHT_RE.match(s)
        if m:
            return m.group(1)
    return s


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {str(k): normalize_value(v) for k, v in record.items()}


def normalize_records(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [normalize_record(r) for r in records]


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def canonical_sort_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(rows, key=lambda r: canonical_json(r))


def df_to_answer(df: pd.DataFrame, answer_type: str, scoring_method: str) -> Any:
    if answer_type == "Scalar" or (scoring_method in SCALAR_METHODS and df.shape == (1, 1)):
        if answer_type == "Scalar" and df.shape != (1, 1):
            raise ValueError(f"Expected scalar shape (1,1), got {df.shape}")
        return normalize_value(df.iloc[0, 0])
    records = normalize_records(df.to_dict(orient="records"))
    if scoring_method in SET_MATCH_METHODS or scoring_method == "Value-Match":
        records = canonical_sort_rows(records)
    return records


def to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _decimal_places(d: Decimal) -> int:
    """Number of decimal places a gold Decimal carries (0 for integers)."""
    exp = d.as_tuple().exponent
    return -exp if isinstance(exp, int) and exp < 0 else 0


def numeric_equal(a: Any, b: Any, abs_tol: float, rel_tol: float) -> bool:
    """Compare numbers with tolerance. ``a`` is GOLD (the reference precision), ``b`` is PREDICTED.

    Option B float handling: round the PREDICTED value to GOLD's number of decimal places before
    the tolerance check, so gold-rounded (33.33) vs full-precision predicted (33.333333) matches,
    while a genuinely different number (90.21 vs 90.22) still fails under the default tolerance.
    The existing abs_tol/rel_tol (and per-task value_tolerance override) apply on top.
    """
    da = to_decimal(a)
    db = to_decimal(b)
    if da is None or db is None:
        return False
    places = _decimal_places(da)
    try:
        db = db.quantize(Decimal(1).scaleb(-places))  # round PREDICTED to GOLD's precision
    except (InvalidOperation, ValueError):
        pass
    diff = abs(da - db)
    abs_tol_d = Decimal(str(abs_tol))
    rel_tol_d = Decimal(str(rel_tol))
    scale = max(abs(da), abs(db), Decimal("1"))
    return diff <= max(abs_tol_d, rel_tol_d * scale)


def values_equal(a: Any, b: Any, abs_tol: float, rel_tol: float) -> bool:
    a = normalize_value(a)
    b = normalize_value(b)
    if a is None or b is None:
        return a is None and b is None
    if a == b:
        return True
    # Case-insensitive comparison for free-text strings.
    # May need a case-sensitive exception list later for identifier columns (e.g. ISIN codes).
    if isinstance(a, str) and isinstance(b, str):
        return a.strip().lower() == b.strip().lower()
    return numeric_equal(a, b, abs_tol, rel_tol)


def normalize_prediction_for_task(predicted: Any, answer_type: str, scoring_method: str) -> Any:
    if answer_type == "Scalar" or scoring_method in SCALAR_METHODS:
        if not isinstance(predicted, (list, dict)):
            return normalize_value(predicted)
        if isinstance(predicted, dict):
            if len(predicted) == 1:
                return normalize_value(next(iter(predicted.values())))
            for key in ["answer", "value", "result"]:
                if key in predicted and not isinstance(predicted[key], (list, dict)):
                    return normalize_value(predicted[key])
            return normalize_record(predicted)
        if isinstance(predicted, list):
            if len(predicted) == 0:
                return None
            if len(predicted) == 1:
                item = predicted[0]
                if isinstance(item, dict):
                    if len(item) == 1:
                        return normalize_value(next(iter(item.values())))
                    return normalize_record(item)
                return normalize_value(item)
            return [normalize_value(x) for x in predicted]

    if isinstance(predicted, list):
        rows = []
        for item in predicted:
            if isinstance(item, dict):
                rows.append(normalize_record(item))
            else:
                rows.append({"value": normalize_value(item)})
        if scoring_method in SET_MATCH_METHODS or scoring_method == "Value-Match":
            return canonical_sort_rows(rows)
        return rows

    if isinstance(predicted, dict):
        for key in ["answer", "rows", "result", "data"]:
            if key in predicted and isinstance(predicted[key], list):
                return normalize_prediction_for_task(predicted[key], answer_type, scoring_method)
        return [normalize_record(predicted)]

    return predicted


def load_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_benchmark(path: str | Path) -> List[Dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        return data["tasks"]
    raise ValueError("Benchmark file must be JSON list or object with tasks list")


def load_gold_answer(gold_dir: str | Path, gold_answer_path: str) -> Dict[str, Any]:
    path = Path(gold_dir) / os.path.basename(gold_answer_path)
    if not path.exists():
        raise FileNotFoundError(f"Gold answer file not found: {path}")
    return load_json(path)


def load_submission(path: str | Path) -> Dict[str, Dict[str, Any]]:
    data = load_json(path)
    if isinstance(data, dict) and isinstance(data.get("predictions"), list):
        rows = data["predictions"]
    elif isinstance(data, list):
        rows = data
    else:
        raise ValueError("Submission must be JSON list or object with predictions list")
    by_task: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        task_id = row.get("task_id")
        if not task_id:
            raise ValueError(f"Submission row missing task_id: {row}")
        if task_id in by_task:
            raise ValueError(f"Duplicate prediction for task_id={task_id}")
        by_task[task_id] = row
    return by_task


@dataclass
class TaskScore:
    task_id: str
    session_id: Optional[str]  # multi-turn session grouping key (== task_id for single-turn tasks)
    turn_number: Optional[int]
    passed: Optional[bool]   # None means rubric_pending (excluded from TSR)
    score: Optional[float]   # None for rubric_pending tasks
    exact_match: bool
    row_f1: float
    precision: float
    recall: float
    column_match: float
    error_type: Optional[str]
    error_message: Optional[str]
    expected_row_count: Optional[int]
    predicted_row_count: Optional[int]
    answer_type: str
    scoring_method: str
    tier: Any
    sql_difficulty: Any
    primary_axis: Any
    secondary_axis: Any
    latency_seconds: Optional[float]
    cost_usd: Optional[float]
    tool_calls: Optional[int]
    generated_sql_present: bool
    sql_transpiled: bool = False  # Layer-2: scored answer came from a transpiled rewrite (native failed)
    extra_columns_relaxed: bool = False  # v1.4: pass decided by the extra-column relaxation path
    empty_set_relaxed: bool = False  # v1.6: pass decided by the empty-set count-of-zero equivalence


def row_key(row: Dict[str, Any]) -> str:
    return canonical_json(row)


def _sig_value(value: Any) -> Any:
    """Canonical, name-free token for one cell, consistent with values_equal's notions of equality:
    numbers normalized (1156 == 1156.0, trailing zeros dropped), strings stripped + lowercased,
    None distinguished. Used to build a name-independent row signature for the fast set-match path.
    """
    v = normalize_value(value)
    if v is None:
        return ("null",)
    if isinstance(v, bool):
        return ("bool", v)
    d = to_decimal(v)
    if d is not None:
        return ("num", str(d.normalize()))
    return ("str", str(v).strip().lower())


def row_value_signature(row: Dict[str, Any]) -> Tuple[Any, ...]:
    """Name- AND order-independent signature of a row: the sorted multiset of its cell values.

    Option B (signed off): rows are matched by VALUE multiset + column count, NOT by column name.
    This intentionally accepts a vanishingly unlikely false match where a result set has every
    column renamed AND its values permuted into a different column meaning yet the per-row value
    multisets still coincide across the whole table — accepted as negligible vs the benefit of not
    penalizing correct answers that merely used a different column alias.
    """
    if not isinstance(row, dict):
        return (("scalar", _sig_value(row)),)
    return tuple(sorted((_sig_value(v) for v in row.values()), key=repr))


def column_match_score(gold_rows: Any, pred_rows: Any, answer_type: str) -> float:
    if answer_type == "Scalar":
        return 1.0
    if not isinstance(gold_rows, list) or not isinstance(pred_rows, list):
        return 0.0
    if len(gold_rows) == 0 and len(pred_rows) == 0:
        return 1.0
    if len(gold_rows) == 0 or len(pred_rows) == 0:
        return 0.0
    gold_cols, pred_cols = set(), set()
    for r in gold_rows:
        if isinstance(r, dict):
            gold_cols.update(r.keys())
    for r in pred_rows:
        if isinstance(r, dict):
            pred_cols.update(r.keys())
    if not gold_cols and not pred_cols:
        return 1.0
    if not gold_cols or not pred_cols:
        return 0.0
    return len(gold_cols & pred_cols) / len(gold_cols | pred_cols)


def records_equal_with_tolerance(gold_row: Dict[str, Any], pred_row: Dict[str, Any], abs_tol: float, rel_tol: float) -> bool:
    """Option B: match two rows by VALUE multiset, ignoring column NAMES. Guardrails kept:
    equal COLUMN COUNT required, and every gold value must pair (with tolerance) to a distinct
    predicted value — so a different number or a missing/extra column still fails.
    """
    if len(gold_row) != len(pred_row):
        return False
    remaining = list(pred_row.values())
    for gv in gold_row.values():
        match_idx = next(
            (i for i, pv in enumerate(remaining) if values_equal(gv, pv, abs_tol, rel_tol)),
            None,
        )
        if match_idx is None:
            return False
        remaining.pop(match_idx)  # one-to-one: each predicted value consumed once
    return True


def set_match_metrics(gold: List[Dict[str, Any]], pred: List[Dict[str, Any]], abs_tol: float, rel_tol: float) -> Tuple[bool, float, float, float]:
    if not isinstance(gold, list) or not isinstance(pred, list):
        return False, 0.0, 0.0, 0.0
    # Fast path keyed on the name-independent value signature (no column names, no float-precision
    # bias from JSON serialization). Exact match here means same value multiset per row, any aliasing
    # / column order. Float-precision differences fall through to the tolerance-aware greedy match.
    gold_keys = {row_value_signature(r) for r in gold}
    pred_keys = {row_value_signature(r) for r in pred}
    tp = len(gold_keys & pred_keys)
    precision = tp / len(pred_keys) if pred_keys else (1.0 if not gold_keys else 0.0)
    recall = tp / len(gold_keys) if gold_keys else (1.0 if not pred_keys else 0.0)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    exact = gold_keys == pred_keys
    if exact:
        return True, 1.0, 1.0, 1.0

    if len(gold) <= 500 and len(pred) <= 500:
        unmatched = list(pred)
        matched = 0
        for g in gold:
            found_idx = None
            for idx, p in enumerate(unmatched):
                if records_equal_with_tolerance(g, p, abs_tol, rel_tol):
                    found_idx = idx
                    break
            if found_idx is not None:
                matched += 1
                unmatched.pop(found_idx)
        precision = matched / len(pred) if pred else (1.0 if not gold else 0.0)
        recall = matched / len(gold) if gold else (1.0 if not pred else 0.0)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        exact = matched == len(gold) == len(pred)
        return exact, f1, precision, recall

    return exact, f1, precision, recall


# ---------------------------------------------------------------------
# v1.4 extra-column relaxation helpers
# ---------------------------------------------------------------------

def _as_rows_cols(value: Any, cols_hint: Optional[List[str]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Coerce a gold/predicted answer into (rows, ordered-column-names).

    - list of dicts  -> the rows, columns = first row's keys
    - list of scalars-> one synthetic column
    - dict           -> a single row
    - bare scalar    -> a single 1x1 row (column name from cols_hint if given)
    - empty list     -> ([], cols_hint or [])
    """
    if isinstance(value, list):
        if value and all(isinstance(r, dict) for r in value):
            return value, list(value[0].keys())
        if not value:
            return [], (list(cols_hint) if cols_hint else [])
        return [{"__c0__": v} for v in value], ["__c0__"]
    if isinstance(value, dict):
        return [value], list(value.keys())
    col = (cols_hint[0] if cols_hint else "__scalar__")
    return [{col: value}], [col]


def _colvec(rows: List[Dict[str, Any]], col: str) -> List[Any]:
    return [r.get(col) for r in rows]


def _col_sig(rows: List[Dict[str, Any]], col: str) -> Counter:
    """Name-free value-multiset signature of one column (same canonical token as set-match)."""
    return Counter(_sig_value(v) for v in _colvec(rows, col))


# Backstop so a degenerate case (many predicted columns sharing one value-multiset) cannot make the
# injective-mapping search explode. If exceeded with >1 valid mapping still unresolved, we treat the
# case as ambiguous (many mappings reproduce the gold -> genuinely ambiguous anyway).
_MAX_MAPPING_ENUM = 4096


def _pred_has_more_columns(predicted_answer: Any, gold_answer: Any, gt: Dict[str, Any]) -> bool:
    if predicted_answer is None:
        return False
    _, gcols = _as_rows_cols(gold_answer, gt.get("expected_output_columns"))
    _, pcols = _as_rows_cols(predicted_answer, None)
    return len(pcols) > len(gcols)


def _projected_exact(answer_type: str, scoring_method: str, gold_norm: Any,
                     projected: List[Dict[str, Any]], abs_tol: float, rel_tol: float) -> bool:
    """Run the EXISTING comparison on a prediction already projected onto the gold columns."""
    pn = normalize_prediction_for_task(projected, answer_type, scoring_method)
    if answer_type == "Scalar" or scoring_method in SCALAR_METHODS:
        return values_equal(gold_norm, pn, abs_tol, rel_tol)
    if scoring_method in ORDERED_METHODS:
        if not isinstance(gold_norm, list) or not isinstance(pn, list):
            return False
        return len(gold_norm) == len(pn) and all(
            records_equal_with_tolerance(g, p, abs_tol, rel_tol) for g, p in zip(gold_norm, pn))
    if not isinstance(gold_norm, list) or not isinstance(pn, list):
        return False
    exact, _, _, _ = set_match_metrics(gold_norm, pn, abs_tol, rel_tol)
    return exact


def try_extra_column_relaxation(task: Dict[str, Any], gold_answer: Any, predicted_answer: Any,
                                abs_tol: float, rel_tol: float) -> str:
    """Decide the extra-column case. Returns 'pass' | 'ambiguous' | 'none'.

    Only reached when the prediction has strictly MORE columns than gold. Builds candidate
    gold_col -> pred_col matches by tolerance-aware per-column value-multiset equality (a NECESSARY
    condition for a whole-answer match), enumerates injective mappings, and keeps those that make
    the projected prediction pass the existing comparison. One valid mapping -> pass; several ->
    resolve by gold column name (case-insensitive), else ambiguous.
    """
    gt = task["turns"][0]["ground_truth"]
    answer_type = gt.get("gold_answer_type")
    scoring_method = gt.get("scoring_method")
    grows, gcols = _as_rows_cols(gold_answer, gt.get("expected_output_columns"))
    prows, pcols = _as_rows_cols(predicted_answer, None)
    if not grows or not prows or len(pcols) <= len(gcols) or len(prows) != len(grows):
        return "none"

    gold_norm = normalize_prediction_for_task(gold_answer, answer_type, scoring_method)
    # Candidate pruning by column value-multiset signature (O(cells), necessary condition). The final
    # decision is confirmed by projecting and re-running the real comparison (tolerance-aware).
    pred_sig = {pc: _col_sig(prows, pc) for pc in pcols}
    candidates: Dict[str, List[str]] = {}
    for gc in gcols:
        gsig = _col_sig(grows, gc)
        matches = [pc for pc in pcols if pred_sig[pc] == gsig]
        if not matches:
            return "none"  # this gold value-set appears in no predicted column
        candidates[gc] = matches

    valid: List[List[Tuple[str, str]]] = []
    enum_count = [0]
    capped = [False]

    def backtrack(i: int, chosen: List[str]) -> None:
        if capped[0] or len(valid) >= 2:
            return  # enough to know it is non-unique; stop early
        if i == len(gcols):
            enum_count[0] += 1
            if enum_count[0] > _MAX_MAPPING_ENUM:
                capped[0] = True
                return
            mapping = list(zip(gcols, chosen))
            projected = [{gc: r.get(pc) for gc, pc in mapping} for r in prows]
            if _projected_exact(answer_type, scoring_method, gold_norm, projected, abs_tol, rel_tol):
                valid.append(mapping)
            return
        for pc in candidates[gcols[i]]:
            if pc in chosen:
                continue
            backtrack(i + 1, chosen + [pc])

    backtrack(0, [])

    if not capped[0] and len(valid) == 0:
        return "none"
    # SHAPE-FIX: every mapping in `valid` is by construction a PASSING mapping (added only when
    # _projected_exact is True). So if any valid mapping exists, the answer passes regardless of
    # which one we pick — the only ambiguity is WHICH column is which, not pass/fail. This resolves
    # the degenerate duplicate-valued-column case (e.g. gold [0.0, 0.0, 0.0]) that previously
    # returned ambiguous_column_mapping. Strictness preserved: wrong values never yield a valid mapping.
    if len(valid) >= 1:
        return "pass"
    # Search capped with no valid mapping found yet: resolve only if exactly one mapping lines the gold
    # columns up to same-named predicted columns (case-insensitive) AND that mapping actually passes.
    name_map = []
    lower_to_pred = {}
    for pc in pcols:
        lower_to_pred.setdefault(str(pc).lower(), pc)
    ok = True
    used = set()
    for gc in gcols:
        pc = lower_to_pred.get(str(gc).lower())
        if pc is None or pc in used or pc not in candidates[gc]:
            ok = False
            break
        used.add(pc)
        name_map.append((gc, pc))
    if ok:
        projected = [{gc: r.get(pc) for gc, pc in name_map} for r in prows]
        if _projected_exact(answer_type, scoring_method, gold_norm, projected, abs_tol, rel_tol):
            return "pass"
    return "ambiguous"


# v1.5 requested-column-anchored relaxation ------------------------------------------------------
# Fixes the directionality asymmetry in the v1.4 extra-column relaxation: v1.4 forgives an agent for
# returning MORE columns than gold (projects pred down), but has no path to forgive GOLD carrying a
# column the question never requested and the agent omitted. This adds that path — but ONLY for tasks
# with an explicit, reviewed unrequested-column annotation (results/cortex_audit/requested_column_
# overrides.json). Gold's unrequested columns are dropped; the prediction must still reproduce every
# REQUESTED column's values. A missing/wrong requested column still fails. Non-annotated tasks are
# byte-identical to v1.4. Ripple verified zero across all single-turn tasks.
_OVERRIDES_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "results", "cortex_audit", "requested_column_overrides.json")
_UNREQUESTED_CACHE: Optional[Dict[str, List[str]]] = None


def _unrequested_cols(task: Dict[str, Any]) -> List[str]:
    global _UNREQUESTED_CACHE
    if _UNREQUESTED_CACHE is None:
        try:
            with open(_OVERRIDES_PATH) as f:
                raw = json.load(f)
            _UNREQUESTED_CACHE = {k: v for k, v in raw.items() if isinstance(v, list)}
        except Exception:
            _UNREQUESTED_CACHE = {}
    tid = task.get("task_id") or task.get("turns", [{}])[0].get("task_id")
    return _UNREQUESTED_CACHE.get(tid, [])


def _reduce_gold_answer(gold_answer: Any, unrequested: List[str]) -> Any:
    """Drop unrequested columns from a gold answer (list-of-dicts or dict). Other shapes unchanged."""
    if not unrequested:
        return gold_answer
    us = set(unrequested)
    if isinstance(gold_answer, list) and gold_answer and all(isinstance(r, dict) for r in gold_answer):
        return [{k: v for k, v in r.items() if k not in us} for r in gold_answer]
    if isinstance(gold_answer, dict):
        return {k: v for k, v in gold_answer.items() if k not in us}
    return gold_answer


def try_requested_column_match(task: Dict[str, Any], reduced_gold: Any, predicted_answer: Any,
                               abs_tol: float, rel_tol: float) -> bool:
    """Like try_extra_column_relaxation but against the REQUESTED-only gold, and fires when the
    prediction has >= (not strictly >) the reduced-gold column count. Reached ONLY for annotated tasks.
    Every reduced-gold column must map (by value-multiset signature) to a distinct predicted column
    such that the projected prediction passes the existing comparison; else fail (strictness preserved)."""
    gt = task["turns"][0]["ground_truth"]
    answer_type = gt.get("gold_answer_type")
    scoring_method = gt.get("scoring_method")
    grows, gcols = _as_rows_cols(reduced_gold, None)
    prows, pcols = _as_rows_cols(predicted_answer, None)
    if not grows or not prows or len(pcols) < len(gcols) or len(prows) != len(grows):
        return False
    gold_norm = normalize_prediction_for_task(reduced_gold, answer_type, scoring_method)
    pred_sig = {pc: _col_sig(prows, pc) for pc in pcols}
    candidates: Dict[str, List[str]] = {}
    for gc in gcols:
        gsig = _col_sig(grows, gc)
        matches = [pc for pc in pcols if pred_sig[pc] == gsig]
        if not matches:
            return False
        candidates[gc] = matches
    enum = [0]

    def backtrack(i: int, chosen: List[str]) -> bool:
        if i == len(gcols):
            enum[0] += 1
            if enum[0] > _MAX_MAPPING_ENUM:
                return False
            projected = [{gc: r.get(pc) for gc, pc in zip(gcols, chosen)} for r in prows]
            return _projected_exact(answer_type, scoring_method, gold_norm, projected, abs_tol, rel_tol)
        for pc in candidates[gcols[i]]:
            if pc in chosen:
                continue
            if backtrack(i + 1, chosen + [pc]):
                return True
        return False

    return backtrack(0, [])


def _is_zero_count_row(pred_norm: Any) -> bool:
    """True iff the prediction is EXACTLY one row with EXACTLY one cell that normalizes to
    numeric 0 (covers [[0]], [["0"]], [{"trade_count": 0}], [{"n": "0"}]). This is the
    count-of-zero shape an agent emits for an existence check ("are there any …") whose true
    answer is "none". Deliberately strict: multi-row, multi-column, non-zero, or non-numeric
    predictions all return False, so only a genuine zero-count can borrow the empty-set pass.
    Bools are rejected (False must not masquerade as the integer 0)."""
    if not isinstance(pred_norm, list) or len(pred_norm) != 1:
        return False
    row = pred_norm[0]
    if isinstance(row, dict):
        vals = list(row.values())
    elif isinstance(row, (list, tuple)):
        vals = list(row)
    else:
        vals = [row]
    if len(vals) != 1:
        return False
    # to_decimal coerces numeric strings ("0", "0.0") AND rejects bools/non-numerics (-> None),
    # so both [[0]] and [["0"]] qualify while [["no"]] / [[True]] do not.
    d = to_decimal(vals[0])
    return d is not None and d == 0


def score_answer(task: Dict[str, Any], gold_answer: Any, predicted_answer: Any, abs_tol: float, rel_tol: float):
    gt = task["turns"][0]["ground_truth"]
    answer_type = gt.get("gold_answer_type")
    scoring_method = gt.get("scoring_method")
    task_tol = gt.get("value_tolerance")
    if task_tol is not None:
        try:
            abs_tol = float(task_tol)
        except Exception:
            pass
    try:
        pred_norm = normalize_prediction_for_task(predicted_answer, answer_type, scoring_method)
        gold_norm = normalize_prediction_for_task(gold_answer, answer_type, scoring_method)
        predicted_row_count = len(pred_norm) if isinstance(pred_norm, list) else (1 if answer_type == "Scalar" else None)
        col_score = column_match_score(gold_norm, pred_norm, answer_type)

        if scoring_method in RUBRIC_METHODS:
            logger.warning(
                f"Task {task.get('task_id', '?')}: scoring_method='Rubric' — "
                "excluded from Task Success Rate (rubric_pending; LLM-judge evaluator not yet implemented)"
            )
            return None, None, False, 0.0, 0.0, 0.0, col_score, "rubric_pending", "Rubric scoring requires a judge evaluator (not yet implemented)", None, False, False

        # Diagnostics label ONLY (no scoring-outcome change): an agent that produced NOTHING
        # — raw predicted_answer None or "" (timeout / agent_error / sql_error / refusal) — is
        # distinct from a malformed non-list shape (format_error) and from a legitimate zero-row
        # answer ([], which stays a plain miss). Fires before the Scalar/Ordered/Set branches so
        # None labels as "empty_prediction" instead of "format_error". [] is intentionally NOT
        # caught here (checked on the RAW value, not the normalized one). Still scores 0/fail.
        if predicted_answer is None or predicted_answer == "":
            _empty_kind = "None" if predicted_answer is None else "empty string"
            return False, 0.0, False, 0.0, 0.0, 0.0, col_score, "empty_prediction", f"Agent produced no prediction ({_empty_kind})", None, False, False

        # Compute the base (v1.3) verdict and quality metrics via the existing per-type logic.
        if answer_type == "Scalar" or scoring_method in SCALAR_METHODS:
            exact = values_equal(gold_norm, pred_norm, abs_tol, rel_tol)
            f1 = precision = recall = 1.0 if exact else 0.0
        elif scoring_method in ORDERED_METHODS:
            if not isinstance(gold_norm, list) or not isinstance(pred_norm, list):
                return False, 0.0, False, 0.0, 0.0, 0.0, col_score, "format_error", "Ordered answer must be a list", predicted_row_count, False, False
            exact = len(gold_norm) == len(pred_norm) and all(records_equal_with_tolerance(g, p, abs_tol, rel_tol) for g, p in zip(gold_norm, pred_norm))
            _, f1, precision, recall = set_match_metrics(gold_norm, pred_norm, abs_tol, rel_tol)
        else:
            if not isinstance(gold_norm, list) or not isinstance(pred_norm, list):
                return False, 0.0, False, 0.0, 0.0, 0.0, col_score, "format_error", "Set answer must be a list", predicted_row_count, False, False
            exact, f1, precision, recall = set_match_metrics(gold_norm, pred_norm, abs_tol, rel_tol)

        # v1.6 empty-set existence equivalence — for existence/"are there any … / show any …" tasks
        # whose gold is the EMPTY SET, accept a single-row single-cell COUNT-of-zero prediction
        # ([[0]] / [["0"]]) as semantically equivalent to "no rows". Guarded hard: gold must be the
        # empty list AND the prediction must be exactly one cell normalizing to numeric 0. A missing /
        # None / "" prediction already returned above (empty_prediction) and is NOT eligible — an
        # un-attempted task stays a fail. Multi-row, multi-column, and non-zero predictions never fire.
        # Quality metrics (f1/precision/recall/col_score) are LEFT as computed (they stay 0); only the
        # pass/fail flips, and the empty_set_relaxed flag records it for audit.
        empty_set_relaxed = False
        if not exact and isinstance(gold_norm, list) and len(gold_norm) == 0 and _is_zero_count_row(pred_norm):
            exact = True
            empty_set_relaxed = True

        # v1.4 extra-column relaxation — ONLY when not already passing AND the prediction has more
        # columns than gold. Equal/fewer-column cases fall straight through, byte-identical to v1.3.
        # Quality metrics (f1/precision/recall/col_score) are LEFT as computed above so they keep
        # penalizing the extra columns; only the pass/fail (exact) can flip.
        extra_columns_relaxed = False
        if not exact and _pred_has_more_columns(predicted_answer, gold_answer, gt):
            verdict = try_extra_column_relaxation(task, gold_answer, predicted_answer, abs_tol, rel_tol)
            if verdict == "ambiguous":
                return (False, 0.0, False, f1, precision, recall, col_score,
                        "ambiguous_column_mapping",
                        "Prediction has extra columns and more than one column mapping reproduces the "
                        "gold values; gold column names do not resolve it", predicted_row_count, False, False)
            if verdict == "pass":
                exact = True
                extra_columns_relaxed = True

        # v1.5 requested-column-anchored relaxation — fires ONLY for tasks with an explicit reviewed
        # unrequested-column annotation. Drops gold's unrequested columns, then requires the prediction
        # to still reproduce every REQUESTED column correctly. Non-annotated tasks: no-op.
        if not exact:
            _unreq = _unrequested_cols(task)
            if _unreq:
                _reduced_gold = _reduce_gold_answer(gold_answer, _unreq)
                if try_requested_column_match(task, _reduced_gold, predicted_answer, abs_tol, rel_tol):
                    exact = True
                    extra_columns_relaxed = True

        score = 1.0 if exact else 0.0
        return exact, score, exact, f1, precision, recall, col_score, None, None, predicted_row_count, extra_columns_relaxed, empty_set_relaxed
    except Exception as e:
        return False, 0.0, False, 0.0, 0.0, 0.0, 0.0, "scoring_exception", str(e), None, False, False


def run_gold_sql_for_task(conn: duckdb.DuckDBPyConnection, task: Dict[str, Any]) -> Tuple[Any, float]:
    gt = task["turns"][0]["ground_truth"]
    start = time.time()
    df = conn.execute(gt["gold_sql"]).df()
    latency = time.time() - start
    return df_to_answer(df, gt.get("gold_answer_type"), gt.get("scoring_method")), latency


def evaluate_tasks(benchmark, gold_dir, mode, submission_by_task=None, duckdb_path=None, abs_tol=DEFAULT_NUMERIC_ABS_TOL, rel_tol=DEFAULT_NUMERIC_REL_TOL):
    scores: List[TaskScore] = []
    conn = None
    if mode == "gold-sql":
        if not duckdb_path:
            raise ValueError("--duckdb-path is required for gold-sql mode")
        conn = duckdb.connect(duckdb_path)
    try:
        for task in benchmark:
            task_id = task["task_id"]
            gt = task["turns"][0]["ground_truth"]
            gold_artifact = load_gold_answer(gold_dir, gt["gold_answer_path"])
            gold_answer = gold_artifact["answer"]

            # Change 4: verify gold hash at score time to catch tampered/stale gold files.
            expected_sha256 = gt.get("gold_answer_sha256")
            if expected_sha256:
                computed_sha256 = hashlib.sha256(
                    canonical_json(gold_artifact["answer"]).encode("utf-8")
                ).hexdigest()
                if computed_sha256 != expected_sha256:
                    raise RuntimeError(
                        f"Gold answer hash mismatch for task {task_id}. "
                        f"Expected {expected_sha256}, got {computed_sha256}. "
                        "The gold answer file may have been tampered with or regenerated outside the compiler."
                    )

            latency = cost = tool_calls = None
            generated_sql_present = False
            sql_transpiled = False
            predicted_answer = None
            error_type = error_message = None

            if mode == "gold-sql":
                try:
                    predicted_answer, latency = run_gold_sql_for_task(conn, task)
                    generated_sql_present = True
                    tool_calls = 1
                except Exception as e:
                    error_type = "gold_sql_execution_error"
                    error_message = str(e)
            elif mode == "submission":
                if submission_by_task is None:
                    raise ValueError("submission_by_task is required")
                pred_row = submission_by_task.get(task_id)
                if pred_row is None:
                    error_type = "missing_prediction"
                    error_message = "No prediction found for task"
                else:
                    # v1.1 fix: null is a valid answer if the key exists.
                    if "predicted_answer" in pred_row:
                        predicted_answer = pred_row["predicted_answer"]
                    elif "answer" in pred_row:
                        predicted_answer = pred_row["answer"]
                    else:
                        error_type = "missing_answer"
                        error_message = "Prediction row missing predicted_answer/answer"
                    latency = pred_row.get("latency_seconds")
                    cost = pred_row.get("cost_usd")
                    tool_calls = pred_row.get("tool_calls")
                    generated_sql_present = bool(pred_row.get("generated_sql"))
                    sql_transpiled = bool(pred_row.get("sql_transpiled"))
            else:
                raise ValueError(f"Unsupported mode: {mode}")

            # Rubric (T8) tasks are excluded from scoring (passed=None) whether or not the
            # submission contains a row for them. Clearing the error here — strictly for
            # RUBRIC_METHODS — lets score_answer's rubric branch decide, instead of a missing row
            # short-circuiting to a hard fail that inflated tasks_total to 200 and sessions_total
            # to 167 (= 157 + 10 rubric). Non-rubric tasks are untouched: a missing row still
            # falls through to the error branch below and counts as a genuine failure.
            if gt.get("scoring_method") in RUBRIC_METHODS:
                error_type = error_message = None

            if error_type is None:
                passed, score, exact, row_f1, precision, recall, col_score, s_err, s_msg, pred_rc, extra_columns_relaxed, empty_set_relaxed = score_answer(task, gold_answer, predicted_answer, abs_tol, rel_tol)
                if s_err:
                    error_type, error_message = s_err, s_msg
            else:
                passed = exact = False
                score = row_f1 = precision = recall = col_score = 0.0
                pred_rc = None
                extra_columns_relaxed = False
                empty_set_relaxed = False

            scores.append(TaskScore(
                task_id=task_id,
                session_id=task.get("session_id") or task_id,
                turn_number=task["turns"][0].get("turn_number", 1),
                passed=passed,
                score=score,
                exact_match=exact,
                row_f1=row_f1,
                precision=precision,
                recall=recall,
                column_match=col_score,
                error_type=error_type,
                error_message=error_message,
                expected_row_count=gt.get("expected_row_count"),
                predicted_row_count=pred_rc,
                answer_type=gt.get("gold_answer_type"),
                scoring_method=gt.get("scoring_method"),
                tier=task.get("tier"),
                sql_difficulty=task.get("sql_difficulty"),
                primary_axis=task.get("primary_axis"),
                secondary_axis=task.get("secondary_axis"),
                latency_seconds=latency,
                cost_usd=cost,
                tool_calls=tool_calls,
                generated_sql_present=generated_sql_present,
                sql_transpiled=sql_transpiled,
                extra_columns_relaxed=extra_columns_relaxed,
                empty_set_relaxed=empty_set_relaxed,
            ))
    finally:
        if conn is not None:
            conn.close()
    return scores


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def group_accuracy(scores: List[TaskScore], attr: str) -> Dict[str, Dict[str, Any]]:
    groups: Dict[str, List[TaskScore]] = {}
    for s in scores:
        key = getattr(s, attr)
        key = "null" if key is None else str(key)
        groups.setdefault(key, []).append(s)
    return {k: {"tasks": len(v), "passed": sum(1 for x in v if x.passed), "accuracy": mean([x.score for x in v]), "avg_row_f1": mean([x.row_f1 for x in v])} for k, v in sorted(groups.items())}


def aggregate_by_session(scores: List[TaskScore]) -> Dict[str, Any]:
    """Session-level rollup on top of per-task TSR (score_answer is untouched).

    A session passes iff ALL its scorable turns passed (rubric_pending turns are excluded from
    the all(); a session with no scorable turns is reported but excluded from the rate). Single-
    turn tasks are sessions of length 1, so multi_turn_* isolates the genuinely conversational ones.
    """
    sessions: Dict[str, List[TaskScore]] = {}
    for s in scores:
        sessions.setdefault(s.session_id or s.task_id, []).append(s)

    session_rows: List[Dict[str, Any]] = []
    for sid, turns in sorted(sessions.items()):
        turns_sorted = sorted(turns, key=lambda x: (x.turn_number or 0))
        scorable = [t for t in turns_sorted if t.passed is not None]
        turns_passed = sum(1 for t in scorable if t.passed)
        # scorable + all passed -> PASS; any scorable turn failed -> FAIL; no scorable turns -> None
        session_passed: Optional[bool] = (turns_passed == len(scorable)) if scorable else None
        session_rows.append({
            "session_id": sid,
            "turns_total": len(turns_sorted),
            "turns_scorable": len(scorable),
            "turns_passed": turns_passed,
            "session_passed": session_passed,
            "is_multi_turn": len(turns_sorted) > 1,
            "turn_task_ids": [t.task_id for t in turns_sorted],
        })

    scorable_sessions = [r for r in session_rows if r["session_passed"] is not None]
    passed_sessions = sum(1 for r in scorable_sessions if r["session_passed"])
    multi = [r for r in scorable_sessions if r["is_multi_turn"]]
    multi_passed = sum(1 for r in multi if r["session_passed"])
    # TURN-LEVEL multi-turn metric (additive; does NOT change the all-or-nothing session metric above).
    # Counts individual scorable turns inside multi-turn sessions, so partial progress is visible:
    # an agent that solves 8 of 41 multi-turn turns reads 0.195 here even though 0/8 full sessions pass.
    multi_all = [r for r in session_rows if r["is_multi_turn"]]
    mt_turns_scorable = sum(r["turns_scorable"] for r in multi_all)
    mt_turns_passed = sum(r["turns_passed"] for r in multi_all)
    return {
        "sessions_total": len(scorable_sessions),
        "sessions_passed": passed_sessions,
        "session_success_rate": passed_sessions / len(scorable_sessions) if scorable_sessions else 0.0,
        "multi_turn_sessions_total": len(multi),
        "multi_turn_sessions_passed": multi_passed,
        "multi_turn_session_success_rate": multi_passed / len(multi) if multi else 0.0,
        # Per-turn view of the same multi-turn sessions (turns passed / turns scorable).
        "multi_turn_turns_total": mt_turns_scorable,
        "multi_turn_turns_passed": mt_turns_passed,
        "multi_turn_turn_success_rate": mt_turns_passed / mt_turns_scorable if mt_turns_scorable else 0.0,
        "failed_session_ids": [r["session_id"] for r in scorable_sessions if not r["session_passed"]],
        "sessions": session_rows,
    }


def aggregate_scores(scores: List[TaskScore], mode: str) -> Dict[str, Any]:
    # Rubric tasks (passed is None) are excluded from TSR; tracked separately.
    rubric_pending = [s for s in scores if s.passed is None]
    scorable = [s for s in scores if s.passed is not None]

    session_summary = aggregate_by_session(scores)
    total = len(scorable)
    passed = sum(1 for s in scorable if s.passed)
    # Layer-2 transparency: native pass = passed WITHOUT the transpile fallback; transpiled_count =
    # tasks whose scored answer came from a transpiled rewrite. With no transpilation these equal the
    # with-fallback numbers (i.e. today).
    transpiled_count = sum(1 for s in scorable if getattr(s, "sql_transpiled", False))
    passed_native = sum(1 for s in scorable if s.passed and not getattr(s, "sql_transpiled", False))
    extra_columns_relaxed_count = sum(1 for s in scorable if getattr(s, "extra_columns_relaxed", False))
    empty_set_relaxed_count = sum(1 for s in scorable if getattr(s, "empty_set_relaxed", False))
    latencies = [s.latency_seconds for s in scorable if isinstance(s.latency_seconds, (int, float))]
    costs = [s.cost_usd for s in scorable if isinstance(s.cost_usd, (int, float))]
    error_counts: Dict[str, int] = {}
    for s in scorable:
        if s.error_type:
            error_counts[s.error_type] = error_counts.get(s.error_type, 0) + 1
        elif not s.passed:
            error_counts["answer_mismatch"] = error_counts.get("answer_mismatch", 0) + 1
    return {
        "scorer_version": SCORER_VERSION,
        "mode": mode,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "tasks_total": total,
        "tasks_passed": passed,
        "tasks_failed": total - passed,
        "task_success_rate": passed / total if total else 0.0,
        # Native (no transpile) vs the with-fallback rate above. Equal when nothing was transpiled.
        "task_success_rate_native": passed_native / total if total else 0.0,
        "tasks_passed_native": passed_native,
        "transpiled_count": transpiled_count,
        "extra_columns_relaxed_count": extra_columns_relaxed_count,
        "empty_set_relaxed_count": empty_set_relaxed_count,
        "session_success_rate": session_summary["session_success_rate"],
        "sessions_total": session_summary["sessions_total"],
        "sessions_passed": session_summary["sessions_passed"],
        "multi_turn_session_success_rate": session_summary["multi_turn_session_success_rate"],
        "multi_turn_sessions_total": session_summary["multi_turn_sessions_total"],
        "multi_turn_sessions_passed": session_summary["multi_turn_sessions_passed"],
        "multi_turn_turn_success_rate": session_summary["multi_turn_turn_success_rate"],
        "multi_turn_turns_total": session_summary["multi_turn_turns_total"],
        "multi_turn_turns_passed": session_summary["multi_turn_turns_passed"],
        "session_summary": session_summary,
        "rubric_pending_count": len(rubric_pending),
        "rubric_pending_task_ids": [s.task_id for s in rubric_pending],
        "macro_score": mean([s.score for s in scorable]),
        "avg_row_f1": mean([s.row_f1 for s in scorable]),
        "avg_precision": mean([s.precision for s in scorable]),
        "avg_recall": mean([s.recall for s in scorable]),
        "avg_column_match": mean([s.column_match for s in scorable]),
        "avg_latency_seconds": mean(latencies),
        "total_cost_usd": sum(costs),
        "avg_cost_usd": mean(costs),
        "error_counts": dict(sorted(error_counts.items())),
        "accuracy_by_tier": group_accuracy(scorable, "tier"),
        "accuracy_by_sql_difficulty": group_accuracy(scorable, "sql_difficulty"),
        "accuracy_by_primary_axis": group_accuracy(scorable, "primary_axis"),
        "accuracy_by_answer_type": group_accuracy(scorable, "answer_type"),
        "failed_task_ids": [s.task_id for s in scorable if not s.passed],
    }


def task_score_to_dict(s: TaskScore) -> Dict[str, Any]:
    return s.__dict__


def write_outputs(scores: List[TaskScore], summary: Dict[str, Any], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [task_score_to_dict(s) for s in scores]
    with open(out / "scores_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, allow_nan=False)
    with open(out / "task_scores.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False, allow_nan=False)
    if "session_summary" in summary:
        with open(out / "session_scores.json", "w", encoding="utf-8") as f:
            json.dump(summary["session_summary"], f, indent=2, ensure_ascii=False, allow_nan=False)
    if rows:
        with open(out / "task_scores.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    leaderboard_row = {
        "run_id": out.name,
        "mode": summary["mode"],
        "is_certification": summary["mode"] == "gold-sql",
        "row_type": "certification" if summary["mode"] == "gold-sql" else "agent",
        "tasks_total": summary["tasks_total"],
        "tasks_passed": summary["tasks_passed"],
        "task_success_rate": summary["task_success_rate"],
        "rubric_pending_count": summary["rubric_pending_count"],
        "macro_score": summary["macro_score"],
        "avg_row_f1": summary["avg_row_f1"],
        "avg_latency_seconds": summary["avg_latency_seconds"],
        "total_cost_usd": summary["total_cost_usd"],
        "scored_at_utc": summary["scored_at_utc"],
        "scorer_version": summary["scorer_version"],
    }
    with open(out / "leaderboard_row.json", "w", encoding="utf-8") as f:
        json.dump(leaderboard_row, f, indent=2, ensure_ascii=False, allow_nan=False)


# ---------------------------------------------------------------------
# Multi-run aggregation: Pass^N (mean consistency, ranking) + Pass@N (best-of-N)
# ---------------------------------------------------------------------

def _multirun_group_accuracy(records: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    """Sub-breakdown on the Pass^N (mean) basis: accuracy = mean pass_hat_n within the group."""
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        if r.get("pass_hat_n") is None:  # rubric_pending excluded
            continue
        k = getattr_key = r.get(key)
        k = "null" if k is None else str(k)
        groups.setdefault(k, []).append(r)
    return {
        k: {
            "tasks": len(v),
            "passed": sum(1 for x in v if x["pass_hat_n"] == 1.0),  # solved on ALL runs (consistent)
            "accuracy": mean([x["pass_hat_n"] for x in v]),         # Pass^N for the group
            "pass_at_n": mean([x["pass_at_n"] for x in v]),         # Pass@N for the group
            "avg_row_f1": mean([x["row_f1"] for x in v]),
        }
        for k, v in sorted(groups.items())
    }


def aggregate_multi_run(per_run_scores: List[List["TaskScore"]], mode: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Aggregate N independent runs' per-task scores into Pass^N / Pass@N.

    Per task: passes_out_of_n, pass_hat_n (=passes/N, CONSISTENCY = ranking metric), pass_at_n (=any).
    Headline Pass^N = mean pass_hat_n over scorable tasks; Pass@N = mean pass_at_n. Rubric tasks
    (passed is None in every run) are excluded from both, tracked as rubric_pending. Diagnostics
    (row_f1/precision/recall/column_match/latency/cost) are averaged over runs. With N==1 the numbers
    collapse to today's single-run values (pass_hat_n == pass_at_n == TSR).
    """
    n = len(per_run_scores)
    by_task = [{s.task_id: s for s in run} for run in per_run_scores]
    task_ids = [s.task_id for s in per_run_scores[0]]

    def _mean_present(vals):
        vals = [v for v in vals if isinstance(v, (int, float))]
        return (sum(vals) / len(vals)) if vals else None

    records: List[Dict[str, Any]] = []
    for tid in task_ids:
        ts_list = [bt[tid] for bt in by_task]
        base = ts_list[0]  # static task metadata is identical across runs
        passed_list = [t.passed for t in ts_list]
        rec: Dict[str, Any] = {
            "task_id": tid, "session_id": base.session_id, "turn_number": base.turn_number,
            "answer_type": base.answer_type, "scoring_method": base.scoring_method,
            "tier": base.tier, "sql_difficulty": base.sql_difficulty,
            "primary_axis": base.primary_axis, "secondary_axis": base.secondary_axis,
            "expected_row_count": base.expected_row_count, "n_runs": n,
        }
        if all(p is None for p in passed_list):  # rubric_pending in every run
            rec.update({
                "passed": None, "score": None, "exact_match": None,
                "pass_hat_n": None, "pass_at_n": None, "passes_out_of_n": None,
                "pass_hat_n_native": None, "transpiled_runs": 0,
                "run_passes": [None] * n, "row_f1": None, "precision": None, "recall": None,
                "column_match": None, "error_type": base.error_type, "error_message": base.error_message,
                "latency_seconds": None, "cost_usd": None, "generated_sql_present": None,
                "extra_columns_relaxed": False,
                "empty_set_relaxed": False,
            })
        else:
            passes = sum(1 for p in passed_list if p is True)
            pass_hat = passes / n
            # native pass = passed WITHOUT the transpile fallback; transpiled_runs = runs that used it.
            native_passes = sum(1 for t in ts_list if t.passed is True and not getattr(t, "sql_transpiled", False))
            transpiled_runs = sum(1 for t in ts_list if getattr(t, "sql_transpiled", False))
            errs = [t.error_type for t in ts_list if t.error_type]
            rep_err = Counter(errs).most_common(1)[0][0] if errs else None
            rec.update({
                "passed": (passes == n),          # consistent-all-pass
                "score": pass_hat,                # so macro/group accuracy == Pass^N
                "exact_match": all(bool(t.exact_match) for t in ts_list),
                "pass_hat_n": pass_hat,
                "pass_hat_n_native": native_passes / n,
                "transpiled_runs": transpiled_runs,
                "pass_at_n": 1.0 if passes > 0 else 0.0,
                "passes_out_of_n": passes,
                "run_passes": [bool(p) for p in passed_list],
                "row_f1": mean([t.row_f1 for t in ts_list]),
                "precision": mean([t.precision for t in ts_list]),
                "recall": mean([t.recall for t in ts_list]),
                "column_match": mean([t.column_match for t in ts_list]),
                "error_type": rep_err,
                "error_message": None,
                "latency_seconds": _mean_present([t.latency_seconds for t in ts_list]),
                "cost_usd": _mean_present([t.cost_usd for t in ts_list]),
                "generated_sql_present": any(bool(t.generated_sql_present) for t in ts_list),
                "extra_columns_relaxed": any(getattr(t, "extra_columns_relaxed", False) for t in ts_list),
                "empty_set_relaxed": any(getattr(t, "empty_set_relaxed", False) for t in ts_list),
            })
        records.append(rec)

    scorable = [r for r in records if r["pass_hat_n"] is not None]
    rubric = [r for r in records if r["pass_hat_n"] is None]
    total = len(scorable)
    pass_hat_headline = mean([r["pass_hat_n"] for r in scorable])
    pass_hat_native_headline = mean([r["pass_hat_n_native"] for r in scorable])
    pass_at_headline = mean([r["pass_at_n"] for r in scorable])
    transpiled_task_count = sum(1 for r in scorable if r.get("transpiled_runs", 0) > 0)

    # Per-run TSR (each run scored exactly as the single-run scorer would) + per-run transpile counts.
    per_run_tsr = []
    per_run_transpiled = []
    for run in per_run_scores:
        sc = [s for s in run if s.passed is not None]
        per_run_tsr.append(round(sum(1 for s in sc if s.passed) / len(sc), 6) if sc else 0.0)
        per_run_transpiled.append(sum(1 for s in sc if getattr(s, "sql_transpiled", False)))

    # error_counts summed across ALL runs (total incidence over the N passes).
    error_counts: Dict[str, int] = {}
    for run in per_run_scores:
        for s in run:
            if s.passed is None:
                continue
            if s.error_type:
                error_counts[s.error_type] = error_counts.get(s.error_type, 0) + 1
            elif not s.passed:
                error_counts["answer_mismatch"] = error_counts.get("answer_mismatch", 0) + 1

    # Session rollup on the Pass^N basis: a session "passes" iff ALL its turns are consistent-all-pass.
    sess_ns = [SimpleNamespace(session_id=r["session_id"], task_id=r["task_id"],
                               turn_number=r["turn_number"], passed=r["passed"]) for r in records]
    session_summary = aggregate_by_session(sess_ns)

    latencies = [r["latency_seconds"] for r in scorable if isinstance(r["latency_seconds"], (int, float))]
    costs = [r["cost_usd"] for r in scorable if isinstance(r["cost_usd"], (int, float))]
    summary = {
        "scorer_version": SCORER_VERSION,
        "mode": mode,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(),
        "n_runs": n,
        "tasks_total": total,
        "tasks_passed": sum(1 for r in scorable if r["passed"]),   # consistent-all-pass count
        "tasks_failed": total - sum(1 for r in scorable if r["passed"]),
        # Pass^N is the ranking metric; task_success_rate mirrors it so downstream consumers rank on it
        # (and it collapses to today's TSR when n == 1).
        "task_success_rate": pass_hat_headline,
        "pass_hat_n": pass_hat_headline,
        "pass_hat_n_native": pass_hat_native_headline,   # Pass^N on NATIVE execution (no transpile)
        "pass_at_n": pass_at_headline,
        "per_run_task_success_rate": per_run_tsr,
        "transpiled_count": transpiled_task_count,       # tasks needing transpile in >=1 run
        "per_run_transpiled": per_run_transpiled,
        "session_success_rate": session_summary["session_success_rate"],
        "sessions_total": session_summary["sessions_total"],
        "sessions_passed": session_summary["sessions_passed"],
        "multi_turn_session_success_rate": session_summary["multi_turn_session_success_rate"],
        "multi_turn_sessions_total": session_summary["multi_turn_sessions_total"],
        "multi_turn_sessions_passed": session_summary["multi_turn_sessions_passed"],
        "multi_turn_turn_success_rate": session_summary["multi_turn_turn_success_rate"],
        "multi_turn_turns_total": session_summary["multi_turn_turns_total"],
        "multi_turn_turns_passed": session_summary["multi_turn_turns_passed"],
        "session_summary": session_summary,
        "rubric_pending_count": len(rubric),
        "rubric_pending_task_ids": [r["task_id"] for r in rubric],
        "macro_score": mean([r["score"] for r in scorable]),
        "avg_row_f1": mean([r["row_f1"] for r in scorable]),
        "avg_precision": mean([r["precision"] for r in scorable]),
        "avg_recall": mean([r["recall"] for r in scorable]),
        "avg_column_match": mean([r["column_match"] for r in scorable]),
        "avg_latency_seconds": (sum(latencies) / len(latencies)) if latencies else 0.0,
        "total_cost_usd": sum(costs),
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else 0.0,
        "error_counts": dict(sorted(error_counts.items())),
        "accuracy_by_tier": _multirun_group_accuracy(records, "tier"),
        "accuracy_by_sql_difficulty": _multirun_group_accuracy(records, "sql_difficulty"),
        "accuracy_by_primary_axis": _multirun_group_accuracy(records, "primary_axis"),
        "accuracy_by_answer_type": _multirun_group_accuracy(records, "answer_type"),
        # "failed" for ranking = never solved in ANY run (Pass@N == 0); partial ones live in the CSV.
        "failed_task_ids": [r["task_id"] for r in scorable if r["pass_at_n"] == 0.0],
    }
    return records, summary


def write_multirun_outputs(records: List[Dict[str, Any]], summary: Dict[str, Any], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "scores_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, allow_nan=False)
    with open(out / "task_scores.json", "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False, allow_nan=False)
    with open(out / "session_scores.json", "w", encoding="utf-8") as f:
        json.dump(summary["session_summary"], f, indent=2, ensure_ascii=False, allow_nan=False)
    if records:
        # Flat CSV: drop the run_passes list (kept in the JSON) so columns stay scalar.
        flat = [{k: v for k, v in r.items() if k != "run_passes"} for r in records]
        with open(out / "task_scores.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(flat[0].keys()))
            writer.writeheader()
            writer.writerows(flat)
    leaderboard_row = {
        "run_id": out.name,
        "mode": summary["mode"],
        "is_certification": False,
        "row_type": "agent",
        "n_runs": summary["n_runs"],
        "tasks_total": summary["tasks_total"],
        "tasks_passed": summary["tasks_passed"],
        "task_success_rate": summary["task_success_rate"],
        "pass_hat_n": summary["pass_hat_n"],
        "pass_hat_n_native": summary["pass_hat_n_native"],
        "pass_at_n": summary["pass_at_n"],
        "transpiled_count": summary["transpiled_count"],
        "per_run_task_success_rate": summary["per_run_task_success_rate"],
        "rubric_pending_count": summary["rubric_pending_count"],
        "macro_score": summary["macro_score"],
        "avg_row_f1": summary["avg_row_f1"],
        "avg_latency_seconds": summary["avg_latency_seconds"],
        "total_cost_usd": summary["total_cost_usd"],
        "scored_at_utc": summary["scored_at_utc"],
        "scorer_version": summary["scorer_version"],
    }
    with open(out / "leaderboard_row.json", "w", encoding="utf-8") as f:
        json.dump(leaderboard_row, f, indent=2, ensure_ascii=False, allow_nan=False)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Score Cortex-Bench submissions or run Gold-SQL baseline.")
    p.add_argument("--benchmark", required=True)
    p.add_argument("--gold-dir", required=True)
    p.add_argument("--mode", choices=["gold-sql", "submission"], required=True)
    p.add_argument("--submission", default=None, help="Single submission (legacy 1x path; byte-identical output).")
    p.add_argument("--submissions", nargs="+", default=None,
                   help="N run submissions for multi-run Pass^N/Pass@N aggregation. With a single file "
                        "here, behaves exactly like --submission (1x).")
    p.add_argument("--duckdb-path", default=None)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--abs-tol", type=float, default=DEFAULT_NUMERIC_ABS_TOL)
    p.add_argument("--rel-tol", type=float, default=DEFAULT_NUMERIC_REL_TOL)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    benchmark = load_benchmark(args.benchmark)

    # MULTI-RUN: >1 submission -> Pass^N / Pass@N aggregation. A single submission (via --submissions
    # or --submission) takes the legacy path below and is byte-identical to today.
    if args.mode == "submission" and args.submissions and len(args.submissions) > 1:
        per_run_scores = [
            evaluate_tasks(benchmark, args.gold_dir, "submission",
                           load_submission(f), args.duckdb_path, args.abs_tol, args.rel_tol)
            for f in args.submissions
        ]
        records, summary = aggregate_multi_run(per_run_scores, args.mode)
        write_multirun_outputs(records, summary, args.out_dir)
        logger.info("Scoring complete (multi-run)")
        logger.info(f"n_runs: {summary['n_runs']}; per-run TSR: {summary['per_run_task_success_rate']}")
        logger.info(f"Pass^{summary['n_runs']} (mean/ranking): {summary['pass_hat_n']:.6f}")
        logger.info(f"Pass@{summary['n_runs']} (any):          {summary['pass_at_n']:.6f}")
        logger.info(
            f"Sessions passed: {summary['sessions_passed']}/{summary['sessions_total']} "
            f"(consistent-all-pass); multi-turn: "
            f"{summary['multi_turn_sessions_passed']}/{summary['multi_turn_sessions_total']}"
        )
        if summary.get("rubric_pending_count", 0) > 0:
            logger.info(f"Rubric pending (excluded): {summary['rubric_pending_count']} task(s)")
        logger.info(f"Outputs written to: {args.out_dir}")
        return

    submission_by_task = None
    if args.mode == "submission":
        # Accept a single file from either flag; keeps the 1x path unchanged.
        single = args.submission or (args.submissions[0] if args.submissions else None)
        if not single:
            raise ValueError("--submission (or --submissions) is required for submission mode")
        submission_by_task = load_submission(single)
    scores = evaluate_tasks(benchmark, args.gold_dir, args.mode, submission_by_task, args.duckdb_path, args.abs_tol, args.rel_tol)
    summary = aggregate_scores(scores, args.mode)
    write_outputs(scores, summary, args.out_dir)
    logger.info("Scoring complete")
    logger.info(f"Tasks passed: {summary['tasks_passed']}/{summary['tasks_total']}")
    logger.info(f"Task success rate: {summary['task_success_rate']:.6f}")
    logger.info(
        f"Sessions passed: {summary['sessions_passed']}/{summary['sessions_total']} "
        f"(session success rate: {summary['session_success_rate']:.6f}); "
        f"multi-turn: {summary['multi_turn_sessions_passed']}/{summary['multi_turn_sessions_total']}"
    )
    if summary.get("rubric_pending_count", 0) > 0:
        logger.info(
            f"Rubric pending (excluded from TSR): {summary['rubric_pending_count']} task(s) — "
            f"{summary['rubric_pending_task_ids']}"
        )
    logger.info(f"Outputs written to: {args.out_dir}")
    if args.mode == "gold-sql" and summary["tasks_passed"] != summary["tasks_total"]:
        logger.error("Gold-SQL baseline did not reach 100%. Inspect task_scores.json.")
        sys.exit(1)


if __name__ == "__main__":
    main()
