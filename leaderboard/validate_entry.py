#!/usr/bin/env python3
"""Validate leaderboard entries against schema/leaderboard_entry.schema.json.

Deliberately dependency-free. The whole repo's promise is "clone it and run it", and a CI job
that needs `pip install jsonschema` before it can check a JSON file is a job that will one day
be skipped. This implements the draft-07 subset the entry schema actually uses:
type, required, properties, additionalProperties (bool or schema), enum, pattern, minLength,
minimum/maximum, items, and local $ref into #/definitions.

Beyond the schema it enforces three cross-field rules a schema cannot express:
  R1 entry_id must equal the filename stem
  R2 a metric with runs[] must have mean equal to the mean of runs (no hand-edited headline)
  R3 mean:null requires unavailable_reason (a missing measurement is stated, never shown as zero)

    python3 leaderboard/validate_entry.py results/*.json
    python3 leaderboard/validate_entry.py --selftest
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCHEMA_PATH = os.path.join(ROOT, "schema", "leaderboard_entry.schema.json")

TYPES = {"object": dict, "array": list, "string": str, "number": (int, float),
         "integer": int, "boolean": bool, "null": type(None)}


def _is_type(v, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    return isinstance(v, TYPES[t])


def validate(value, schema: dict, root: dict, path: str, errs: list) -> None:
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            errs.append(f"{path}: unsupported $ref {ref}")
            return
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        validate(value, node, root, path, errs)
        return

    t = schema.get("type")
    if t is not None:
        opts = t if isinstance(t, list) else [t]
        if not any(_is_type(value, o) for o in opts):
            errs.append(f"{path}: expected {'/'.join(opts)}, got {type(value).__name__}")
            return

    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not one of {schema['enum']}")
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errs.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if "minLength" in schema and len(value) < schema["minLength"]:
            errs.append(f"{path}: shorter than minLength {schema['minLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errs.append(f"{path}: {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errs.append(f"{path}: {value} > maximum {schema['maximum']}")

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            validate(item, schema["items"], root, f"{path}[{i}]", errs)

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing required field {req!r}")
        addl = schema.get("additionalProperties", True)
        for k, v in value.items():
            if k in props:
                validate(v, props[k], root, f"{path}.{k}", errs)
            elif addl is False:
                errs.append(f"{path}: unexpected field {k!r}")
            elif isinstance(addl, dict):
                validate(v, addl, root, f"{path}.{k}", errs)


def cross_field_rules(entry: dict, stem: str, errs: list) -> None:
    # R1 -- the filename is the row's identity in git history; a mismatch makes provenance untraceable.
    if entry.get("entry_id") != stem:
        errs.append(f"entry_id {entry.get('entry_id')!r} != filename stem {stem!r}")

    for name, m in (entry.get("results") or {}).items():
        if not isinstance(m, dict) or name == "by_tier":
            continue
        p = f"results.{name}"
        runs = m.get("runs")
        mean = m.get("mean")
        # R2 -- the headline must be derivable from the published runs.
        if runs and mean is not None:
            vals = [r for r in runs if r is not None]
            # tolerance scales with magnitude: an accuracy is stored to 6dp, a latency in
            # seconds to 2dp, and both are legitimately rounded for display.
            tol = max(5e-4, 1e-3 * abs(mean))
            if vals and abs(sum(vals) / len(vals) - mean) > tol:
                errs.append(f"{p}: mean {mean} != mean(runs) {sum(vals)/len(vals):.6f}")
            declared = (entry.get("protocol") or {}).get("runs")
            if declared is not None and len(runs) != declared:
                errs.append(f"{p}: {len(runs)} run values but protocol.runs = {declared}")
        # R3 -- an unmeasured metric says so; it never renders as a zero.
        if mean is None and not m.get("unavailable_reason"):
            errs.append(f"{p}: mean is null without unavailable_reason")


def check_file(fp: str, schema: dict) -> list:
    errs: list = []
    try:
        entry = json.load(open(fp))
    except Exception as exc:  # noqa: BLE001
        return [f"{fp}: not valid JSON -- {exc}"]
    validate(entry, schema, schema, "$", errs)
    cross_field_rules(entry, os.path.basename(fp)[:-5], errs)
    return [f"{os.path.basename(fp)}: {e}" for e in errs]


def selftest(schema: dict) -> int:
    """Every case must FAIL validation. A validator that never rejects is decoration."""
    import copy
    import tempfile

    # Use whatever entry is actually present rather than a hardcoded filename: the selftest must
    # keep working when rows are added or retired, or it silently stops testing.
    rdir = os.path.join(ROOT, "results")
    names = sorted(f for f in os.listdir(rdir) if f.endswith(".json"))
    if not names:
        print("  no entries in results/ -- nothing to build the selftest from")
        return 1
    stem = names[0][:-5]
    base = json.load(open(os.path.join(rdir, names[0])))
    cases = []

    a = copy.deepcopy(base); a["entry_id"] = "2026-01-01-renamed"
    cases.append(("entry_id not matching filename", a))
    b = copy.deepcopy(base); del b["protocol"]["data_snapshot_id"]
    cases.append(("missing data_snapshot_id", b))
    c = copy.deepcopy(base); c["protocol"]["split"] = "holdout"
    cases.append(("split outside enum", c))
    d = copy.deepcopy(base); d["results"]["execution_accuracy"] = {"mean": 0.9, "runs": [0.1, 0.1, 0.1]}
    d["protocol"]["runs"] = 3
    cases.append(("headline mean inflated above its runs", d))
    e = copy.deepcopy(base); e["results"]["cost_usd_per_task"] = {"mean": None}
    cases.append(("null metric with no reason given", e))
    f = copy.deepcopy(base); f["declarations"]["test_data_seen"] = "no"
    cases.append(("declaration as string instead of boolean", f))
    g = copy.deepcopy(base); g["system"]["sponsor"] = "Acme"
    cases.append(("undeclared extra field", g))
    h = copy.deepcopy(base); h["results"]["by_tier"]["7"] = 1.4
    cases.append(("tier accuracy above 1.0", h))

    ok = True
    with tempfile.TemporaryDirectory() as td:
        for label, entry in cases:
            fp = os.path.join(td, f"{stem}.json")
            json.dump(entry, open(fp, "w"))
            errs = check_file(fp, schema)
            status = "REJECTED" if errs else "*** ACCEPTED ***"
            print(f"  [{status:<16}] {label}")
            if errs:
                print(f"       -> {errs[0]}")
            else:
                ok = False
        # and the real entry must still pass
        real = os.path.join(rdir, names[0])
        errs = check_file(real, schema)
        print(f"  [{'PASSED' if not errs else '*** REJECTED ***':<16}] the real entry validates")
        if errs:
            ok = False
            for e_ in errs:
                print(f"       -> {e_}")
    print("\nselftest: all checks behave correctly" if ok else "\nselftest: FAILED")
    return 0 if ok else 1


def main() -> int:
    schema = json.load(open(SCHEMA_PATH))
    args = sys.argv[1:]
    if args and args[0] == "--selftest":
        return selftest(schema)
    files = args or sorted(
        os.path.join(ROOT, "results", f)
        for f in os.listdir(os.path.join(ROOT, "results")) if f.endswith(".json"))
    all_errs = []
    for fp in files:
        errs = check_file(fp, schema)
        print(f"  [{'OK  ' if not errs else 'FAIL'}] {os.path.basename(fp)}")
        for e in errs:
            print(f"       {e}")
        all_errs += errs
    print(f"\n{len(files)} entr{'y' if len(files)==1 else 'ies'} checked, {len(all_errs)} error(s)")
    return 1 if all_errs else 0


if __name__ == "__main__":
    raise SystemExit(main())
