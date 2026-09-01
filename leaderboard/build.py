#!/usr/bin/env python3
"""Build the Cortex-Bench leaderboard: results/*.json -> docs/index.html.

The JSON files in results/ are the source of truth; this page is a disposable artifact. Losing
the site loses nothing, and every row's provenance is `git log results/<entry-id>.json`.

Three display rules, each one a deliberate defence against a way leaderboards mislead:

  1. Rank by mean over N runs and always print the spread. Two identical runs of the same agent
     at temperature 0 disagreed on 21% of this benchmark's tasks; a single number implies a
     precision that does not exist.
  2. One denominator for the whole board. A system that skips tasks is scored on all of them, and
     the coverage column shows what it skipped. Skipping must never raise a score.
  3. Unmeasured is not zero. A metric with no measurement renders as a dash carrying the reason.

    python3 leaderboard/build.py [--out docs/index.html] [--check]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from validate_entry import check_file  # noqa: E402

# The only absolute URL the generated page emits. The Pages site is served from docs/, so a
# relative link to a file at the repo root would 404 for every visitor.
REPO_URL = "https://github.com/jjayeshneo/Cortex-Benchmark"

TIER_NAMES = {
    1: "Schema linking", 2: "Single-table filter", 3: "Joins", 4: "Aggregation",
    5: "Window / ranking", 6: "Domain computation", 7: "Unanswerable / null-result",
    8: "Open analysis (rubric)", 9: "Multi-turn session",
}


def load_entries() -> list:
    d = os.path.join(ROOT, "results")
    schema = json.load(open(os.path.join(ROOT, "schema", "leaderboard_entry.schema.json")))
    out, bad = [], []
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        fp = os.path.join(d, fn)
        errs = check_file(fp, schema)
        if errs:
            bad += errs
            continue
        out.append(json.load(open(fp)))
    if bad:
        for e in bad:
            print(f"  INVALID {e}", file=sys.stderr)
        raise SystemExit("refusing to build a leaderboard from invalid entries")
    return out


def pct(m, digits: int = 1) -> str:
    if not m or m.get("mean") is None:
        reason = (m or {}).get("unavailable_reason") or "not measured"
        return f'<span class="na" title="{html.escape(reason)}">&mdash;</span>'
    s = f'{100 * m["mean"]:.{digits}f}%'
    if m.get("std") is not None:
        s += f' <span class="pm">&plusmn;{100 * m["std"]:.1f}</span>'
    return s


def num(m, fmt: str) -> str:
    if not m or m.get("mean") is None:
        reason = (m or {}).get("unavailable_reason") or "not measured"
        return f'<span class="na" title="{html.escape(reason)}">&mdash;</span>'
    return format(m["mean"], fmt)


def link(text: str, url) -> str:
    t = html.escape(text)
    return f'<a href="{html.escape(url)}" rel="noopener">{t}</a>' if url else t


def row_html(e: dict, rank: str) -> str:
    s, mo, p, r = e["system"], e["model"], e["protocol"], e["results"]
    ref = s.get("kind") == "reference"
    ex = r.get("execution_accuracy", {})
    runs = ex.get("runs")
    runs_title = (", ".join(f"{100*v:.1f}%" for v in runs)) if runs else "single run"
    att, den = p.get("attempted"), p["denominator"]
    if att is not None and att < den:
        cov = (f'<span class="warn" title="Did not attempt {den-att} tasks; '
               f'they are scored as failures.">{att}/{den}</span>')
    else:
        cov = f'{att if att is not None else den}/{den}'
    pa, pl = r.get("pass_any"), r.get("pass_all")
    if pa and pl and pa.get("n") is not None:
        flip = pa["n"] - pl["n"]
        stab = (f'<span title="Passed at least once: {pa["n"]}. Passed every run: {pl["n"]}. '
                f'{flip} tasks flipped verdict between identical runs.">'
                f'{pa["n"]} / {pl["n"]}</span>')
    else:
        stab = '<span class="na">&mdash;</span>'
    badge = ('<span class="v-yes" title="Executed by the organizers.">&#9679; organizer-run</span>'
             if p.get("verified_by_organizers")
             else '<span class="v-no" title="Self-reported by the submitter.">&#9675; self-reported</span>')
    model_name = html.escape(mo["name"]) if mo.get("name") else "&mdash;"
    return f"""      <tr class="{'refrow' if ref else ''}">
        <td class="rank">{rank}</td>
        <td class="sys"><strong>{link(s['name'], s.get('url'))}</strong>
            <div class="sub">{html.escape(s.get('version') or '')}</div></td>
        <td>{html.escape(s['organization'])}</td>
        <td>{model_name}<div class="sub">{html.escape(mo['access'])}</div></td>
        <td class="ex" title="{runs_title}">{pct(ex)}</td>
        <td>{stab}</td>
        <td>{cov}</td>
        <td>{pct(r.get('session_accuracy'))}</td>
        <td>{pct(r.get('multi_turn_turn_accuracy'))}</td>
        <td>{num(r.get('cost_usd_per_task'), '.4f')}</td>
        <td>{num(r.get('median_latency_s'), '.1f')}</td>
        <td>{badge}</td>
        <td class="sub">{html.escape(p['evaluated_at'][:10])}</td>
      </tr>"""


def tier_table(entries: list) -> str:
    tiers = sorted({int(t) for e in entries for t in (e["results"].get("by_tier") or {})})
    head = "".join(f'<th title="{html.escape(TIER_NAMES.get(t, ""))}">T{t}</th>' for t in tiers)
    rows = []
    for e in entries:
        bt = e["results"].get("by_tier") or {}
        cells = []
        for t in tiers:
            v = bt.get(str(t))
            cells.append('<td class="na">&mdash;</td>' if v is None
                         else f'<td class="{"hot" if v < 0.35 else ""}">{100*v:.0f}</td>')
        rows.append(f'      <tr><td class="sys">{html.escape(e["system"]["name"])}</td>'
                    + "".join(cells) + "</tr>")
    legend = " &middot; ".join(f"T{t} {html.escape(TIER_NAMES.get(t, '?'))}" for t in tiers)
    return f"""  <table class="tiers">
    <thead><tr><th>System</th>{head}</tr></thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table>
  <p class="legend">{legend}. Values are % correct, averaged over all runs.</p>"""


CSS = """
:root{--bg:#fff;--fg:#16181d;--muted:#6b7280;--line:#e5e7eb;--accent:#1d4ed8;
      --warn:#b45309;--refbg:#f8fafc;--hot:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0f1115;--fg:#e8eaed;--muted:#9aa3af;
      --line:#262b33;--accent:#7aa2ff;--warn:#e0a33e;--refbg:#161a21;--hot:#f87171}}
*{box-sizing:border-box}
body{margin:0;padding:2.2rem 1.2rem 4rem;background:var(--bg);color:var(--fg);
     font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
main{max-width:1180px;margin:0 auto}
h1{font-size:1.9rem;margin:0 0 .2rem;letter-spacing:-.02em}
h2{font-size:1.15rem;margin:2.6rem 0 .6rem;letter-spacing:-.01em}
.tagline{color:var(--muted);margin:0 0 1.6rem}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:10px}
table{border-collapse:collapse;width:100%;font-size:13.5px;min-width:960px}
th,td{padding:.6rem .7rem;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
th{font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
tbody tr:last-child td{border-bottom:none}
td.rank{color:var(--muted);font-variant-numeric:tabular-nums}
td.ex{font-weight:650;font-variant-numeric:tabular-nums}
.sub{color:var(--muted);font-size:11.5px;font-weight:400;white-space:normal}
.pm{color:var(--muted);font-weight:400}
.na{color:var(--muted);cursor:help}
.warn{color:var(--warn);cursor:help;font-weight:600}
.refrow{background:var(--refbg)}
.refrow td.sys strong{font-weight:600}
.v-yes{color:#15803d}.v-no{color:var(--muted)}
@media (prefers-color-scheme:dark){.v-yes{color:#4ade80}}
.tiers{min-width:640px;border:1px solid var(--line);border-radius:10px}
.tiers td{font-variant-numeric:tabular-nums}
.tiers td.hot{color:var(--hot);font-weight:600}
.legend{color:var(--muted);font-size:12px}
.note{border-left:3px solid var(--accent);padding:.15rem 0 .15rem 1rem;margin:1rem 0;
      color:var(--fg)}
.note strong{font-weight:650}
ul{padding-left:1.15rem}li{margin:.35rem 0}
code{font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
     background:var(--refbg);padding:.1rem .3rem;border-radius:4px}
footer{margin-top:3rem;padding-top:1rem;border-top:1px solid var(--line);
       color:var(--muted);font-size:12.5px}
a{color:var(--accent)}
"""


def build(entries: list) -> str:
    snaps = sorted({e["protocol"]["data_snapshot_id"] for e in entries})
    sections = []
    for snap in snaps:
        group = [e for e in entries if e["protocol"]["data_snapshot_id"] == snap]
        dens = sorted({e["protocol"]["denominator"] for e in group})
        systems = [e for e in group if e["system"].get("kind") != "reference"]
        refs = [e for e in group if e["system"].get("kind") == "reference"]
        systems.sort(key=lambda e: -(e["results"]["execution_accuracy"]["mean"] or 0))
        rows = [row_html(e, "&mdash;") for e in refs]
        rows += [row_html(e, str(i)) for i, e in enumerate(systems, 1)]
        den_note = (f"all rows scored over {dens[0]} gradable tasks"
                    if len(dens) == 1 else
                    f'<span class="warn">mixed denominators {dens} &mdash; rows are not comparable</span>')
        sections.append(f"""  <h2>Snapshot <code>{html.escape(snap)}</code></h2>
  <p class="legend">Gold answers are bound to the data snapshot; entries scored against different
  snapshots are listed under separate headings and must not be compared. Here, {den_note}.</p>
  <div class="wrap"><table>
    <thead><tr>
      <th>#</th><th>System</th><th>Organization</th><th>Model</th>
      <th title="Execution accuracy: mean over all runs, with standard deviation.">EX (mean &plusmn; sd)</th>
      <th title="Tasks passed at least once / tasks passed on every run.">pass@N / pass^N</th>
      <th title="Tasks attempted out of the board denominator.">Coverage</th>
      <th title="Fraction of sessions where every turn passed.">Session</th>
      <th title="Accuracy on the 41 multi-turn tier-9 turns.">Multi&#8209;turn</th>
      <th>USD/task</th><th>Median s</th><th>Verification</th><th>Evaluated</th>
    </tr></thead>
    <tbody>
{chr(10).join(rows)}
    </tbody>
  </table></div>

  <h2>By tier</h2>
{tier_table(refs + systems)}""")

    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    plural = "y" if len(entries) == 1 else "ies"
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cortex-Bench leaderboard</title>
<style>{CSS}</style>
</head><body><main>
  <h1>Cortex-Bench leaderboard</h1>
  <p class="tagline">Text-to-SQL over a 22-table, 63-million-row synthetic Indian wealth-management
  warehouse. 200 questions across 9 tiers, 190 execution-scored.</p>

  <div class="note"><strong>Every score here is a mean over repeated runs, and the spread is
  printed next to it.</strong> We measured two identical runs of the same agent &mdash; same model,
  same questions, temperature&nbsp;0 &mdash; disagreeing on 21% of tasks. A single-run leaderboard
  number implies a precision that does not exist, so three runs are mandatory and every run's score
  is published in the entry file.</div>

{chr(10).join(sections)}

  <h2>How to read this board</h2>
  <ul>
    <li><strong>The denominator never changes.</strong> A system that attempts 149 of 190 tasks is
      scored out of 190; the skipped tasks count as failures and the coverage column says so.
      Skipping work must not raise a score.</li>
    <li><strong>pass@N / pass^N</strong> is the honest measure of stability: how many tasks the
      system got right at least once, versus on every single run. The gap is churn.</li>
    <li><strong>The null floor is a row, not a footnote.</strong> It answers nothing at all. Any
      system that does not clearly beat it has told you nothing.</li>
    <li><strong>A dash is not a zero.</strong> Hover it for why the metric was not measured.</li>
  </ul>

  <h2>Not on this board yet</h2>
  <ul>
    <li><strong>Human baseline.</strong> Not yet run. Until it exists the board has no ceiling, and
      no reader can tell whether 53% is close to the limit or nowhere near it.</li>
    <li><strong>Single-call schema-only baseline.</strong> Not yet run.</li>
    <li><strong>Our own agent.</strong> Its captured runs predate the v1.2 data repair and its
      emitted SQL is not re-executable, so it has no honest score on this snapshot. It will appear
      when it has been re-run, through the same path as every other entry.</li>
  </ul>

  <h2>Submitting</h2>
  <p>Add one JSON file to <code>results/</code>, named for its <code>entry_id</code>, and open a
  pull request. CI validates it against <code>schema/leaderboard_entry.schema.json</code> and
  rebuilds this page on merge. Run
  <code>python3 leaderboard/validate_entry.py results/your-entry.json</code> first.</p>

  <footer>
    Built {built} from {len(entries)} entr{plural} in
    <code>results/</code>. This page is generated &mdash; edit the JSON, never the HTML.
    Provenance for any row: <code>git log results/&lt;entry-id&gt;.json</code>.
  </footer>
</main></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "index.html"))
    ap.add_argument("--check", action="store_true",
                    help="fail if the committed page differs from a fresh build")
    args = ap.parse_args()
    entries = load_entries()
    page = build(entries)
    if args.check:
        try:
            cur = open(args.out).read()
        except FileNotFoundError:
            print("docs/index.html is missing; run leaderboard/build.py", file=sys.stderr)
            return 1
        # the build stamp is the only line that legitimately changes on every run
        def strip(s):
            return "\n".join(l for l in s.splitlines() if "Built 20" not in l)
        if strip(cur) != strip(page):
            print("docs/index.html is stale; run leaderboard/build.py", file=sys.stderr)
            return 1
        print(f"docs/index.html is up to date ({len(entries)} entries)")
        return 0
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    open(args.out, "w").write(page)
    print(f"wrote {args.out} from {len(entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
