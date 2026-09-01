#!/usr/bin/env python3
"""
check_no_gold_leak.py — refuse to publish anything that leaks the private evaluation set.

This is the only irreversible risk in the project. A leaked gold answer cannot be un-leaked:
the moment the private questions or their answers are public, the benchmark stops measuring
anything and no amount of later cleanup restores it.

Design note — the check works from a POSITIVE allowlist, never from a list of private ids.
Shipping "here are the 161 ids you must not mention" to a public repo is itself a disclosure,
and it fails open: a new private task added later would not be covered. Instead, any
Cortex-Bench task id that is not one of the published sample ids is treated as a leak, and any
gold-bearing field outside the one file allowed to carry gold is treated as a leak.

Usage:
    python3 tools/check_no_gold_leak.py <tree>            # scan a directory
    python3 tools/check_no_gold_leak.py <tree> --selftest # prove the check can actually fail
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# The single file permitted to contain gold answers and sample task ids.
GOLD_BEARING_ALLOWLIST = {"sample/sample_questions.json"}


# Paths that must never appear in a public tree, matched anywhere in the relative path.
FORBIDDEN_PATH_PARTS = (
    "gold_answers", "input_tasks", "compiled_201_review", "compiled_v1_2",
    "projection_review", "public_split", "answer_key",
)
FORBIDDEN_NAME_RE = re.compile(
    r"(questions_answers|answer[_-]?key|_submission\.json$|task_scores\.json$"
    r"|compile_manifest\.json$|cortex_bench_v1.*\.json$)", re.I)

# Content signatures of gold material. `predicted_answer` is deliberately NOT here: it is a
# submitter's own output, not gold, and flagging it would ban every example submission. What
# protects a submission file is the task-id rule, which is the check that actually matters.
GOLD_FIELD_RE = re.compile(r'"(answer_sha256|gold_answer|gold_sql)"\s*:')

# Files that must MENTION gold field names to do their job -- the scorer, the adapter that
# writes gold files, this checker, and the scoring documentation -- but that carry no gold
# VALUES. Exempt from the field-name rule only; the task-id rule still applies to every one of
# them, and that is what would catch a real disclosure hiding in any of these.
CONTENT_EXEMPT = {
    "tools/check_no_gold_leak.py",      # must spell out the patterns it detects
    "eval/prepare_sample_gold.py",      # writes the gold_answers layout from the sample file
    "eval/score_cortex_bench.py",       # the scorer reads these fields
    "eval/SCORING.md",                  # documents the submission and gold formats
    "eval/example_submission.json",     # a submission over published sample tasks only
}
TASK_ID_RE = re.compile(r"\bCB_(?:T\d|DEEP|MULTI)[A-Z0-9_]*\b")

TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".py", ".txt", ".yml", ".yaml", ".csv",
                 ".html", ".sh", ".cff", ".sql"}


def load_sample_ids(root: Path) -> set[str]:
    """The published sample ids, plus the ids the compiler derives from them.

    A published task id appears in three shapes across the toolchain: the task id itself
    (CB_T1_001_T1), the session id it belongs to (CB_T1_001), and the turn id the compiler writes
    (CB_T1_001_T1_T1). All three describe the same published question, so all three are published.
    This is exact-string expansion, never prefix matching -- an unpublished turn of a published
    session is still caught, because its own id was never derived from a sample id.
    """
    f = root / "sample" / "sample_questions.json"
    if not f.exists():
        return set()
    base = {q["task_id"] for q in json.loads(f.read_text(encoding="utf-8"))["questions"]}
    derived: set[str] = set()
    for tid in base:
        m = re.fullmatch(r"(.*)_T(\d+)", tid)
        if m:
            derived.add(m.group(1))                 # session id
            derived.add(f"{tid}_T{m.group(2)}")     # compiler turn id
    return base | derived


def load_ignored(root: Path) -> list[str]:
    """Patterns from the tree's own .gitignore.

    Scratch output from the quickstart (`.sample_eval/`) legitimately contains gold answers for
    the published sample -- that is what the scorer needs to run. It is ignored, so it is never
    committed and never reaches a clone. Skipping it here keeps the local check usable; the CI
    job's history scan is what guarantees no ignored file was ever force-added.
    """
    f = root / ".gitignore"
    if not f.exists():
        return []
    return [ln.strip() for ln in f.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.startswith("#")]


def is_ignored(rel: str, patterns: list[str]) -> bool:
    from fnmatch import fnmatch
    for pat in patterns:
        if pat.endswith("/"):
            if rel.startswith(pat) or f"/{pat}" in f"/{rel}":
                return True
        elif fnmatch(rel, pat) or fnmatch(Path(rel).name, pat):
            return True
    return False


def scan(root: Path) -> list[str]:
    sample_ids = load_sample_ids(root)
    ignored_pats = load_ignored(root)
    problems: list[str] = []
    skipped = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git/" in str(path):
            continue
        rel = path.relative_to(root).as_posix()
        if is_ignored(rel, ignored_pats):
            skipped += 1
            continue

        for part in FORBIDDEN_PATH_PARTS:
            if part in rel:
                problems.append(f"{rel}: forbidden path component {part!r}")
        if FORBIDDEN_NAME_RE.search(Path(rel).name) and rel not in CONTENT_EXEMPT:
            problems.append(f"{rel}: filename matches a known answer-key pattern")

        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            problems.append(f"{rel}: unreadable ({exc})")
            continue

        allowed = rel in GOLD_BEARING_ALLOWLIST or rel in CONTENT_EXEMPT
        if not allowed and GOLD_FIELD_RE.search(text):
            field = GOLD_FIELD_RE.search(text).group(1)
            problems.append(f"{rel}: contains gold-bearing field {field!r} "
                            f"(only {sorted(GOLD_BEARING_ALLOWLIST)} may)")

        found = set(TASK_ID_RE.findall(text))
        unknown = sorted(found - sample_ids)
        if unknown:
            shown = ", ".join(unknown[:5]) + (" …" if len(unknown) > 5 else "")
            problems.append(f"{rel}: {len(unknown)} task id(s) not in the published sample: {shown}")

    if not sample_ids:
        problems.append("sample/sample_questions.json missing or empty — cannot verify ids")
    if skipped:
        # Never silent: a skip you cannot see is a hole you cannot audit.
        print(f"  (skipped {skipped} gitignored path(s) — never committed, never published)")
    return problems


def selftest(root: Path) -> int:
    """A guard that has never failed is not known to work. Plant leaks; require detection."""
    import tempfile, shutil
    print("selftest: planting deliberate leaks and requiring each to be caught\n")
    # The test id is assembled at runtime rather than written as a literal: a literal matching
    # TASK_ID_RE would make this file fail its own scan.
    fake_id = "CB_" + "T9_" + "999_T1"
    cases = [
        ("private task id in prose", "docs/NOTES.md",
         f"See {fake_id} for the effective-rate case.\n"),
        ("gold field in a NON-exempt file", "docs/dump.json",
         '{"task_id":"CB_T1_001_T1","answer_sha256":"deadbeef"}\n'),
        ("answer-key filename", "cortex_bench_190_questions_answers.md", "# key\n"),
        ("gold_answers directory", "data/gold_answers/CB_T1_001_T1.json", "{}\n"),
        # The content exemptions are the one place this check deliberately looks away. Prove
        # they do not become a hiding place: a private id inside an EXEMPT file must still fail.
        ("private id hidden inside an exempt file", "eval/SCORING.md",
         f"# scoring\n\nWorked example using {fake_id}.\n"),
        # The id expansion allows the session id and compiler turn id of a PUBLISHED task. Prove
        # it does not leak siblings: an unpublished turn of a published session shares that
        # session's prefix, and must still be caught. Prefix matching here would be a real hole.
        ("unpublished turn of a published session", "docs/turns.md",
         "Turn " + "CB_" + "MULTI_003_T7" + " needs a rerun.\n"),
        # The gitignore skip is the other place this check looks away. Prove it only excuses
        # ignored paths: the same gold file at a tracked path must still fail.
        ("gold answer at a tracked path", "sample/extra_gold.json",
         '{"task_id":"CB_T1_001_T1","gold_sql":"SELECT 1"}\n'),
    ]
    failures = 0
    for name, relpath, body in cases:
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(root, tmp / "tree", dirs_exist_ok=True)
            p = tmp / "tree" / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body, encoding="utf-8")
            found = scan(tmp / "tree")
            hit = any(relpath.split("/")[-1] in f or relpath in f for f in found)
            print(f"  [{'PASS' if hit else 'FAIL'}] {name}")
            if not hit:
                failures += 1
                print(f"         NOT DETECTED: {relpath}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    clean = scan(root)
    print(f"\n  [{'PASS' if not clean else 'FAIL'}] clean tree reports no problems")
    if clean:
        failures += 1
        for c in clean[:5]:
            print(f"         unexpected: {c}")
    print(f"\nselftest: {'all checks behave correctly' if not failures else f'{failures} BROKEN'}")
    return 1 if failures else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tree")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    root = Path(args.tree).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")
    if args.selftest:
        return selftest(root)

    problems = scan(root)
    if problems:
        print(f"GOLD LEAK CHECK FAILED — {len(problems)} problem(s) in {root}\n")
        for p in problems:
            print(f"  {p}")
        print("\nNothing may be published until every item above is resolved.")
        return 1
    print(f"gold leak check passed: {root} is safe to publish")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
