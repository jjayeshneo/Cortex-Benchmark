#!/usr/bin/env python3
"""Build the Cortex-Bench leaderboard: results/*.json -> docs/index.html.

The JSON files in results/ are the source of truth; this page is a disposable artifact. Losing
the site loses nothing, and every row's provenance is `git log results/<entry-id>.json`.

Design direction: a measurement instrument, not a dashboard. Ink on warm paper, serif headings,
monospace for every figure so numbers align like a financial tape, and one teal accent used only
to mark a leading value. The page is generated whole from Python -- the only JavaScript is the
theme toggle, so the numbers are in the HTML and remain readable with scripting off.

Four display rules, each a defence against a way leaderboards mislead:

  1. Rank by mean over N runs and always print the spread. Two identical runs of the same agent at
     temperature 0 disagreed on 21% of this benchmark's tasks; one number implies a precision that
     does not exist.
  2. One denominator for the whole board. A system that skips tasks is scored on all of them, and
     the coverage column shows what it skipped. Skipping must never raise a score.
  3. Snapshots never mix in a ranking. Gold answers are snapshot-bound, so a row measured against
     an older snapshot is shown, marked, and left unranked.
  4. Unmeasured is not zero. A metric with no measurement renders as a dash carrying its reason.

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

# The only absolute URL the generated page emits. Pages serves from docs/, so a relative link to a
# file at the repo root would 404 for every visitor.
REPO_URL = "https://github.com/jjayeshneo/Cortex-Benchmark"

TIER_NAMES = {
    1: "Schema linking", 2: "Single-table filter", 3: "Joins", 4: "Aggregation",
    5: "Window / ranking", 6: "Domain computation", 7: "Unanswerable / null-result",
    8: "Open analysis (rubric)", 9: "Multi-turn session",
}

BANDS = {
    "measured":  ("Measured",  "Organizer-run against the current snapshot, and ranked."),
    "reference": ("Reference", "A control, not a competitor. Pinned above the ranking."),
    "legacy":    ("Legacy",    "Measured against an older snapshot. Shown, not ranked."),
}


# ----------------------------------------------------------------------------- data

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


def current_snapshot(entries: list) -> str:
    """The snapshot the board ranks on: the highest snapshot id present.

    Snapshot ids sort chronologically by construction (wm_synthetic_v1.3_2026_09_01), so this needs
    no separate config that could drift out of date.
    """
    return max(e["protocol"]["data_snapshot_id"] for e in entries)


def band_of(entry: dict, snap: str) -> str:
    if entry["system"].get("kind") == "reference":
        return "reference"
    return "measured" if entry["protocol"]["data_snapshot_id"] == snap else "legacy"


def ex(entry: dict) -> float:
    return entry["results"]["execution_accuracy"].get("mean") or 0.0


def passn(entry: dict) -> float:
    """pass^N -- solved on EVERY run. The board's headline, and what it ranks on.

    Ranking on the mean would reward a system that is right often but never twice in a row.
    pass^N asks the question a buyer actually asks: can I rely on it?
    """
    m = entry["results"].get("pass_all") or {}
    return m.get("mean") if m.get("mean") is not None else -1.0


def dollars_per_correct(entry: dict):
    """Cost per task divided by the pass^N rate: what you pay per task that actually passes."""
    c = (entry["results"].get("cost_usd_per_task") or {}).get("mean")
    r = passn(entry)
    return None if c is None or r <= 0 else c / r


# ----------------------------------------------------------------------------- formatting

def pct(m, digits: int = 1, dash: str = "&mdash;") -> str:
    if not m or m.get("mean") is None:
        reason = (m or {}).get("unavailable_reason") or "not measured"
        return f'<span class="na" title="{html.escape(reason)}">{dash}</span>'
    s = f'{100 * m["mean"]:.{digits}f}%'
    if m.get("std") is not None:
        s += f'<span class="pm"> &plusmn;{100 * m["std"]:.1f}</span>'
    return s


def num(m, fmt: str, prefix: str = "", suffix: str = "") -> str:
    if not m or m.get("mean") is None:
        reason = (m or {}).get("unavailable_reason") or "not measured"
        return f'<span class="na" title="{html.escape(reason)}">&mdash;</span>'
    return f'{prefix}{format(m["mean"], fmt)}{suffix}'


def count(m) -> str:
    if not m or m.get("n") is None:
        reason = (m or {}).get("unavailable_reason") or "not measured"
        return f'<span class="na" title="{html.escape(reason)}">&mdash;</span>'
    return str(m["n"])


# ----------------------------------------------------------------------------- sections

def board_rows(entries: list, snap: str) -> str:
    refs = [e for e in entries if band_of(e, snap) == "reference"]
    ranked = sorted([e for e in entries if band_of(e, snap) == "measured"], key=passn, reverse=True)
    legacy = sorted([e for e in entries if band_of(e, snap) == "legacy"], key=passn, reverse=True)
    best = max([passn(e) for e in ranked], default=0.0)
    scale = max([passn(e) for e in entries] + [0.01])

    rows = []
    for e in refs + ranked + legacy:
        band = band_of(e, snap)
        rank = str(ranked.index(e) + 1) if band == "measured" else "&mdash;"
        s_, p, r = e["system"], e["protocol"], e["results"]
        lead = band == "measured" and abs(passn(e) - best) < 1e-9
        width = 100 * max(passn(e), 0) / scale
        n = p["runs"]
        att, den = p.get("attempted"), p["denominator"]
        cov = (f'<span class="warn" title="Did not attempt {den - att} of {den} tasks; '
               f'they are scored as failures.">{att}/{den} attempted</span>'
               if att is not None and att < den else f'{den}/{den} attempted')

        # The sub-line describes what the row IS. A bare version string like "1.0" tells a reader
        # nothing, so it is only shown when it is descriptive.
        ver = (s_.get("version") or "").strip()
        descriptive = ver and not ver.replace(".", "").isdigit()
        if e["model"].get("name"):
            model = html.escape(e["model"]["name"]) + (f' &middot; {html.escape(ver)}' if descriptive else "")
            # A differing model configuration is disclosed on the row itself, not only in the
            # entry JSON: two rows sharing a model name but not its settings are not a
            # scaffold-only comparison, and the numbers alone do not reveal that.
            _cn = (e["model"] or {}).get("config_note")
            cfg = f' <span class="cfg-note">&middot; {_cn}</span>' if _cn else ""
        elif descriptive:
            model = html.escape(ver)
        else:
            model = "no model &middot; no data read" if band == "reference" else "model not recorded"

        pill = BANDS[band][0]
        if band == "legacy":
            pill += " &middot; " + html.escape(p["data_snapshot_id"].split("_")[2])
        runs_l = r["execution_accuracy"].get("runs")
        title = ("runs: " + ", ".join(f"{100*v:.1f}%" for v in runs_l)) if runs_l else "single run"
        dpc = dollars_per_correct(e)
        dpc_cell = (f'${dpc:.4f}' if dpc is not None else
                    '<span class="na" title="Needs both a cost per task and a pass^N rate.">'
                    '&mdash;</span>')

        rows.append(f"""        <tr class="{band}">
          <td class="rank{' top' if lead else ''}">{rank}</td>
          <td>
            <div class="agent-cell">
              <span class="band-tick {band}"></span>
              <div>
                <div class="agent-name">{html.escape(s_['name'])}</div>
                <div class="agent-arch">{model}{cfg}</div>
                <div class="agent-arch">{cov} &middot; {n} run{'s' if n != 1 else ''}</div>
              </div>
            </div>
          </td>
          <td><span class="band-pill {band}">{pill}</span></td>
          <td class="num" title="{title}">
            <div class="score-cell">
              <span class="bar"><span class="{'lead' if lead else ''}" style="width:{width:.1f}%"></span></span>
              <span class="score-num{' lead' if lead else ''}">{pct(r.get('pass_all'))}</span>
            </div>
            <div class="score-sub">EX {pct(r['execution_accuracy'])}</div>
          </td>
          <td class="num sub-num">{pct(r.get('pass_any'))}</td>
          <td class="num sub-num">{num(r.get('median_latency_s'), '.1f', suffix='s')}</td>
          <td class="num sub-num">{num(r.get('tokens_per_task'), ',.0f')}</td>
          <td class="num sub-num">{num(r.get('cost_usd_per_task'), '.4f', prefix='$')}</td>
          <td class="num sub-num">{dpc_cell}</td>
        </tr>""")
    return "\n".join(rows)


def tier_table(entries: list, snap: str) -> str:
    order = ({"reference": 0, "measured": 1, "legacy": 2})
    ents = sorted(entries, key=lambda e: (order[band_of(e, snap)], -passn(e)))
    tiers = sorted({int(t) for e in ents for t in (e["results"].get("by_tier") or {})})
    head = "".join(
        f'<th class="num" title="{html.escape(TIER_NAMES.get(t, ""))}">T{t}</th>' for t in tiers)
    rows = []
    for e in ents:
        bt = e["results"].get("by_tier") or {}
        cells = []
        for t in tiers:
            v = bt.get(str(t))
            if v is None:
                cells.append('<td class="num na">&mdash;</td>')
                continue
            # heat is a tint of the accent, proportional to the value -- readable in both themes
            cells.append(f'<td class="num"><span class="heat" style="background:'
                         f'color-mix(in srgb, var(--accent) {6 + 34 * v:.0f}%, transparent)">'
                         f'{100 * v:.0f}</span></td>')
        rows.append(f'        <tr><td>{html.escape(e["system"]["name"])}</td>'
                    + "".join(cells) + "</tr>")
    legend = " &middot; ".join(f"<b>T{t}</b> {html.escape(TIER_NAMES.get(t, '?'))}" for t in tiers)
    return f"""      <table class="breakdown">
        <thead><tr><th>System</th>{head}</tr></thead>
        <tbody>
{chr(10).join(rows)}
        </tbody>
      </table>
      <p class="note">{legend}. Values are Pass^N: % of the tier solved on every run.</p>"""


def scatter(entries: list, snap: str, metric: str, y_title: str, fmt: str) -> str:
    """Accuracy against cost or latency. Bottom-right is best."""
    pts = [(e, e["results"].get(metric, {}).get("mean")) for e in entries]
    pts = [(e, y) for e, y in pts if y is not None and passn(e) > 0]
    if not pts:
        return ('<p class="note">No system has published this metric yet, so there is nothing to '
                'plot. An unmeasured metric is left blank rather than drawn as a zero.</p>')
    W, H, L, R, T, B = 760, 400, 62, 24, 20, 52
    ymax = max(y for _, y in pts) * 1.25 or 1.0
    xmax = max(passn(e) for e, _ in pts) * 1.20 or 1.0

    def sx(v): return L + (W - L - R) * (v / xmax)
    def sy(v): return H - B - (H - T - B) * (v / ymax)

    g = [f'<line class="axis-line" x1="{L}" y1="{H-B}" x2="{W-R}" y2="{H-B}"/>',
         f'<line class="axis-line" x1="{L}" y1="{T}" x2="{L}" y2="{H-B}"/>']
    for i in range(5):
        yv = ymax * i / 4
        y = sy(yv)
        if i:
            g.append(f'<line class="grid-line" x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}"/>')
        g.append(f'<text class="axis-label" x="{L-10}" y="{y+4:.1f}" text-anchor="end">'
                 f'{format(yv, fmt)}</text>')
    for i in range(5):
        xv = xmax * i / 4
        x = sx(xv)
        g.append(f'<text class="axis-label" x="{x:.1f}" y="{H-B+18}" text-anchor="middle">'
                 f'{100*xv:.0f}%</text>')
    g.append(f'<text class="axis-title" x="{(L+W-R)/2:.0f}" y="{H-B+40}" text-anchor="middle">'
             f'Pass^N</text>')
    g.append(f'<text class="axis-title" x="-{(T+H-B)/2:.0f}" y="16" transform="rotate(-90)" '
             f'text-anchor="middle">{html.escape(y_title)}</text>')
    for e, y in sorted(pts, key=lambda p: -p[1]):
        band = band_of(e, snap)
        cx, cy = sx(passn(e)), sy(y)
        g.append(f'<circle class="pt {band}" cx="{cx:.1f}" cy="{cy:.1f}" r="6.5"/>')
        anchor = "end" if cx > (W - R) * 0.72 else "start"
        dx = -11 if anchor == "end" else 11
        g.append(f'<text class="pt-label" x="{cx+dx:.1f}" y="{cy-2:.1f}" text-anchor="{anchor}">'
                 f'{html.escape(e["system"]["name"])}</text>')
        g.append(f'<text class="pt-sub" x="{cx+dx:.1f}" y="{cy+11:.1f}" text-anchor="{anchor}">'
                 f'{100*passn(e):.1f}% &middot; {format(y, fmt)}</text>')
    return (f'<div class="scatter-box"><svg viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{html.escape(y_title)} against Pass^N">'
            + "".join(g) + "</svg></div>")


CSS = """
  :root{
    --paper:#FBFAF7; --paper-2:#F3F1EB; --ink:#1A1D1A; --ink-soft:#5A5F57; --ink-faint:#8A8F84;
    --rule:#DAD7CD; --rule-strong:#B9B5A8; --accent:#0F6E63; --accent-soft:#0F6E6318;
    --measured:#2B4C6F; --reference:#8A5A2B; --legacy:#7A7468; --warn:#9A5B12;
    --bar-track:#E4E1D8;
    --serif:"Iowan Old Style","Palatino Linotype","Book Antiqua",Palatino,Georgia,serif;
    --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;
    --mono:"SFMono-Regular",ui-monospace,"JetBrains Mono","Menlo",Consolas,monospace;
  }
  [data-theme="dark"]{
    --paper:#14150F; --paper-2:#1D1F17; --ink:#EDEBE1; --ink-soft:#A9A99C; --ink-faint:#74766A;
    --rule:#2C2E23; --rule-strong:#3D4030; --accent:#4FBFAF; --accent-soft:#4FBFAF1F;
    --measured:#7FA8CE; --reference:#C99A5F; --legacy:#8E8878; --warn:#E0A33E;
    --bar-track:#26281D;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html{scroll-behavior:smooth}
  body{background:var(--paper);color:var(--ink);font-family:var(--sans);line-height:1.5;
       -webkit-font-smoothing:antialiased;transition:background .3s ease,color .3s ease}
  .wrap{max-width:1120px;margin:0 auto;padding:0 32px}
  a{color:var(--accent)}

  .topbar{border-bottom:1px solid var(--rule);position:sticky;top:0;z-index:50;
          background:color-mix(in srgb,var(--paper) 88%,transparent);backdrop-filter:blur(8px)}
  .topbar-inner{display:flex;align-items:center;justify-content:space-between;height:60px}
  .brand{display:flex;align-items:baseline;gap:10px;font-family:var(--serif)}
  .brand .mark{font-size:20px;font-weight:600;letter-spacing:-.01em}
  .brand .sub{font-size:12px;color:var(--ink-faint);font-family:var(--mono);
              text-transform:uppercase;letter-spacing:.08em}
  .nav{display:flex;gap:26px;align-items:center}
  .nav a{color:var(--ink-soft);text-decoration:none;font-size:13.5px}
  .nav a:hover{color:var(--ink)}
  .theme-btn{font-family:var(--mono);font-size:11px;letter-spacing:.06em;background:none;
             border:1px solid var(--rule-strong);color:var(--ink-soft);padding:6px 11px;
             border-radius:2px;cursor:pointer;text-transform:uppercase}
  .theme-btn:hover{border-color:var(--ink-soft);color:var(--ink)}

  .hero{padding:64px 0 40px;border-bottom:1px solid var(--rule)}
  .eyebrow{font-family:var(--mono);font-size:12px;letter-spacing:.14em;text-transform:uppercase;
           color:var(--accent);margin-bottom:20px}
  .hero h1{font-family:var(--serif);font-weight:600;font-size:clamp(30px,5vw,50px);line-height:1.06;
           letter-spacing:-.02em;max-width:17ch;margin-bottom:20px}
  .hero p{font-size:16.5px;color:var(--ink-soft);max-width:64ch}
  .hero-meta{display:flex;flex-wrap:wrap;gap:28px;margin-top:34px}
  .hero-stat .n{font-family:var(--mono);font-size:26px;font-weight:600;letter-spacing:-.02em}
  .hero-stat .l{font-size:12px;color:var(--ink-faint);text-transform:uppercase;
                letter-spacing:.06em;margin-top:2px}

  section{padding:52px 0;border-bottom:1px solid var(--rule)}
  .sec-head{display:flex;align-items:baseline;gap:14px;margin-bottom:8px}
  .sec-num{font-family:var(--mono);font-size:12px;color:var(--ink-faint)}
  .sec-head h2{font-family:var(--serif);font-weight:600;font-size:26px;letter-spacing:-.01em}
  .sec-desc{color:var(--ink-soft);font-size:15px;max-width:70ch;margin-bottom:26px}

  .controls{display:flex;flex-wrap:wrap;gap:20px;align-items:center;margin-bottom:22px}
  .legend{display:flex;flex-wrap:wrap;gap:18px;font-size:12.5px;color:var(--ink-soft)}
  .legend .k{display:inline-flex;align-items:center;gap:6px}
  .dot{width:9px;height:9px;border-radius:50%;display:inline-block}

  .board-scroll{overflow-x:auto}
  .board{width:100%;border-collapse:collapse;font-size:14.5px;min-width:900px}
  .board thead th{text-align:left;font-family:var(--mono);font-size:11px;letter-spacing:.07em;
                  text-transform:uppercase;color:var(--ink-faint);font-weight:500;
                  padding:0 16px 12px;border-bottom:1px solid var(--rule-strong);white-space:nowrap}
  .board thead th.num,.board tbody td.num{text-align:right;font-variant-numeric:tabular-nums}
  .board tbody tr{border-bottom:1px solid var(--rule);transition:background .12s}
  .board tbody tr:hover{background:var(--paper-2)}
  .board tbody td{padding:15px 16px;vertical-align:middle}
  .board tbody tr.legacy .agent-name,.board tbody tr.reference .agent-name{font-weight:500}
  .rank{font-family:var(--mono);font-size:15px;color:var(--ink-faint);width:34px}
  .rank.top{color:var(--accent);font-weight:600}
  .agent-cell{display:flex;align-items:center;gap:12px}
  .band-tick{width:3px;height:32px;border-radius:2px;flex:none;background:var(--measured)}
  .band-tick.reference{background:var(--reference)}
  .band-tick.legacy{background:var(--legacy)}
  .agent-name{font-weight:600;font-size:15px}
  .cfg-note{color:#b45309;font-weight:600}
.agent-arch{font-size:12px;color:var(--ink-faint);font-family:var(--mono);margin-top:1px}
  .score-cell{display:flex;align-items:center;gap:12px;justify-content:flex-end}
  .score-num{font-family:var(--mono);font-weight:600;font-size:16px;min-width:86px;text-align:right}
  .score-num.lead{color:var(--accent)}
  .pm{color:var(--ink-faint);font-weight:400;font-size:13px}
  .score-sub{font-family:var(--mono);font-size:11.5px;color:var(--ink-faint);text-align:right;
             margin-top:3px;letter-spacing:.02em}
  .bar{width:110px;height:7px;background:var(--bar-track);border-radius:4px;overflow:hidden;flex:none}
  .bar>span{display:block;height:100%;background:var(--ink-soft);border-radius:4px}
  .bar>span.lead{background:var(--accent)}
  .sub-num{font-family:var(--mono);font-size:13.5px;color:var(--ink-soft);white-space:nowrap}
  .band-pill{font-family:var(--mono);font-size:10px;letter-spacing:.05em;text-transform:uppercase;
             padding:3px 7px;border-radius:2px;white-space:nowrap;color:var(--measured);
             background:color-mix(in srgb,var(--measured) 12%,transparent)}
  .band-pill.reference{color:var(--reference);
             background:color-mix(in srgb,var(--reference) 12%,transparent)}
  .band-pill.legacy{color:var(--legacy);
             background:color-mix(in srgb,var(--legacy) 14%,transparent)}
  .na{color:var(--ink-faint);cursor:help}
  .warn{color:var(--warn);cursor:help}

  .note{font-size:12.5px;color:var(--ink-faint);margin-top:16px;line-height:1.65;max-width:82ch}
  .note strong,.note b{color:var(--ink-soft);font-weight:600}
  .note+.note{margin-top:9px}

  .grid-scroll{overflow-x:auto}
  .breakdown{width:100%;border-collapse:collapse;font-size:13.5px;min-width:660px}
  .breakdown th,.breakdown td{padding:11px 14px;text-align:right;font-variant-numeric:tabular-nums}
  .breakdown th:first-child,.breakdown td:first-child{text-align:left}
  .breakdown thead th{font-family:var(--mono);font-size:11px;letter-spacing:.05em;
       text-transform:uppercase;color:var(--ink-faint);font-weight:500;
       border-bottom:1px solid var(--rule-strong)}
  .breakdown tbody tr{border-bottom:1px solid var(--rule)}
  .breakdown tbody td:first-child{font-family:var(--sans);font-size:14px;color:var(--ink);
       font-weight:600}
  .heat{font-family:var(--mono);padding:4px 9px;border-radius:3px;display:inline-block;min-width:44px}

  .scatter-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}
  .scatter-box{border:1px solid var(--rule);border-radius:4px;background:var(--paper-2);
               padding:18px 18px 10px}
  svg{display:block;width:100%;height:auto;overflow:visible}
  .axis-line{stroke:var(--rule-strong);stroke-width:1}
  .grid-line{stroke:var(--rule);stroke-width:1;stroke-dasharray:2 4}
  .axis-label{font-family:var(--mono);font-size:10px;fill:var(--ink-faint)}
  .axis-title{font-family:var(--mono);font-size:11px;letter-spacing:.05em;fill:var(--ink-soft);
              text-transform:uppercase}
  .pt{fill:var(--measured)}
  .pt.reference{fill:var(--reference)}
  .pt.legacy{fill:var(--legacy)}
  .pt-label{font-family:var(--mono);font-size:11px;fill:var(--ink);font-weight:600}
  .pt-sub{font-family:var(--mono);font-size:9.5px;fill:var(--ink-faint)}

  footer{padding:44px 0 68px}
  footer .cols{display:flex;flex-wrap:wrap;gap:44px;justify-content:space-between}
  footer p{font-size:13px;color:var(--ink-faint);max-width:54ch}
  footer .method{font-family:var(--mono);font-size:11.5px;color:var(--ink-soft);line-height:1.95}
  footer code{font-family:var(--mono);font-size:11.5px}

  @media (max-width:860px){.scatter-grid{grid-template-columns:1fr}}
  @media (max-width:720px){.wrap{padding:0 20px}.nav{display:none}.hero-meta{gap:20px}}
"""

JS = """
function toggleTheme(){
  var r=document.documentElement, d=r.getAttribute('data-theme')==='dark';
  r.setAttribute('data-theme', d?'light':'dark');
  document.getElementById('themeBtn').textContent = d?'Dark':'Light';
  try{localStorage.setItem('cb-theme', d?'light':'dark')}catch(e){}
}
(function(){
  var t=null; try{t=localStorage.getItem('cb-theme')}catch(e){}
  if(!t && window.matchMedia && matchMedia('(prefers-color-scheme: dark)').matches) t='dark';
  if(t==='dark'){document.documentElement.setAttribute('data-theme','dark');
    document.addEventListener('DOMContentLoaded',function(){
      document.getElementById('themeBtn').textContent='Light';});}
})();
"""


def build(entries: list) -> str:
    snap = current_snapshot(entries)
    ranked = [e for e in entries if band_of(e, snap) == "measured"]
    legacy = [e for e in entries if band_of(e, snap) == "legacy"]
    floor = next((e for e in entries if band_of(e, snap) == "reference"), None)
    den = max(e["protocol"]["denominator"] for e in entries)
    atts = {e["protocol"].get("attempted") for e in entries if e["protocol"].get("attempted")}
    att = next(iter(atts)) if len(atts) == 1 else den
    runs = max((e["protocol"]["runs"] for e in ranked), default=1)
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    present = []
    for b, label in (("measured", "ranked, current snapshot"),
                     ("reference", "control, not a competitor"),
                     ("legacy", "older snapshot, unranked")):
        if any(band_of(e, snap) == b for e in entries):
            present.append(f'<span class="k"><span class="dot" style="background:var(--{b})">'
                           f'</span>{BANDS[b][0]} &mdash; {label}</span>')
    legend_keys = "".join(present)

    legacy_note = ""
    if legacy:
        names = ", ".join(html.escape(e["system"]["name"]) for e in legacy)
        legacy_note = (
            f'      <p class="note"><strong>{names}</strong> carries a <b>Legacy</b> pill because it '
            f'was measured against an earlier data snapshot. Gold answers are bound to the snapshot '
            f'they were compiled from, so that figure is real but not comparable with the ranked '
            f'rows, and it takes no rank. Its captured SQL cannot be re-executed either &mdash; the '
            f'agent emitted parameterised SQL whose bound values were never recorded &mdash; so a '
            f'comparable number needs the agent re-run, not the capture re-scored.</p>')

    floor_note = ""
    if floor:
        floor_note = (
            f'      <p class="note"><strong>{html.escape(floor["system"]["name"])}</strong> is a '
            f'control, not a competitor: it returns the empty set for every task, reads no data and '
            f'calls no model. It scores {100*ex(floor):.1f}% because some questions in this benchmark '
            f'genuinely have no rows to return. Read every other score against it.</p>')

    return f"""<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Cortex-Bench &mdash; Wealth-Management Text-to-SQL Leaderboard</title>
<style>{CSS}</style>
<script>{JS}</script>
</head>
<body>

<div class="topbar">
  <div class="wrap topbar-inner">
    <div class="brand"><span class="mark">Cortex&#8209;Bench</span><span class="sub">Neosapients</span></div>
    <nav class="nav">
      <a href="#leaderboard">Leaderboard</a>
      <a href="#breakdown">By tier</a>
      <a href="#efficiency">Cost &amp; latency</a>
      <a href="#method">Method</a>
      <a href="{REPO_URL}">Repository</a>
    </nav>
    <button class="theme-btn" onclick="toggleTheme()" id="themeBtn">Dark</button>
  </div>
</div>

<header class="hero">
  <div class="wrap">
    <div class="eyebrow">Enterprise text-to-SQL &middot; snapshot {html.escape(snap)}</div>
    <h1>How accurately do data agents answer real wealth-management questions?</h1>
    <p>Cortex-Bench scores agents on {den} questions against a 22-table, 58-million-row synthetic
       Indian wealth-management warehouse. Nine tiers, from schema linking to multi-turn sessions,
       including a tier whose correct answer is that the question cannot be answered from the data.
       Every row below was executed by the organizers, and every score is a mean over repeated runs.</p>
    <div class="hero-meta">
      <div class="hero-stat"><div class="n">{den}</div><div class="l">Scored tasks</div></div>
      <div class="hero-stat"><div class="n">{runs}&times;</div><div class="l">Runs per task</div></div>
      <div class="hero-stat"><div class="n">22</div><div class="l">Tables &middot; 58.5M rows</div></div>
      <div class="hero-stat"><div class="n">9</div><div class="l">Difficulty tiers</div></div>
    </div>
  </div>
</header>

<section id="leaderboard">
  <div class="wrap">
    <div class="sec-head"><span class="sec-num">01</span><h2>Leaderboard</h2></div>
    <p class="sec-desc">Ranked by <strong>Pass^N</strong> &mdash; a task counts only if the system
       solves it correctly on <em>every</em> run. <strong>Pass@N</strong> (solved at least once) sits
       beside it. Both are measured over the tasks a system actually attempted, so they answer
       &ldquo;when it answers, can you rely on it?&rdquo;. Underneath each sits <strong>EX</strong>,
       execution accuracy over the full {den}-task set, where anything unattempted counts as a
       failure &mdash; so skipping still costs you there. Every system on this board attempted the
       same {att} single-turn tasks, which makes the reliability figures directly comparable.</p>

    <div class="controls">
      <div class="legend">{legend_keys}</div>
    </div>

    <div class="board-scroll">
    <table class="board">
      <thead>
        <tr>
          <th style="width:34px">#</th>
          <th>System</th>
          <th>Band</th>
          <th class="num" title="Of the tasks the system attempted, the fraction solved on EVERY run. The ranking metric.">Pass^N</th>
          <th class="num" title="Of the tasks the system attempted, the fraction solved at least once.">Pass@N</th>
          <th class="num">Latency</th>
          <th class="num">Tokens/task</th>
          <th class="num">Cost/task</th>
          <th class="num" title="Cost per task divided by the pass^N rate.">$/correct</th>
        </tr>
      </thead>
      <tbody>
{board_rows(entries, snap)}
      </tbody>
    </table>
    </div>
{floor_note}
      <p class="note"><strong>Why the board ranks on Pass^N.</strong> Two identical runs of the same
      agent &mdash; same model, same questions, temperature&nbsp;0 &mdash; disagreed on 21% of tasks.
      Ranking on the average would reward a system that is often right and never reliably right, so
      the ranking metric is the one a buyer actually cares about: solved every time. The gap between
      <b>Pass@N</b> and <b>Pass^N</b> is churn, and it is large for every system measured so far.
      Every individual run's score is published in the entry file, including the bad ones.</p>
      <p class="note"><strong>Two denominators, on purpose.</strong> Pass^N and Pass@N are over the
      {att} tasks attempted, because reliability is only meaningful about work a system took on. EX
      is over all {den}, because a system must not be able to raise its headline by declining the
      hard questions. Both are shown so neither can be quoted alone.</p>
{legacy_note}
      <p class="note">A dash is not a zero. Hover it to see why the metric was not measured.</p>
  </div>
</section>

<section id="breakdown">
  <div class="wrap">
    <div class="sec-head"><span class="sec-num">02</span><h2>Accuracy by difficulty tier</h2></div>
    <p class="sec-desc">Where each system actually loses. Tiers 1&ndash;2 are lookups and filters,
       3&ndash;5 add joins, aggregation and window functions, 6 requires applying Indian market and
       taxation rules, 7 asks questions the data cannot answer, and 9 is multi-turn. Cells are
       Pass^N, the same metric the board ranks on, so a tier row and a board row mean the same
       thing. Tiers a system never attempted are left out rather than shown as zero. Darker is
       stronger.</p>
    <div class="grid-scroll">
{tier_table(entries, snap)}
    </div>
    <p class="note">Tier 8 is excluded from every figure on this page: those ten tasks are graded
       against a rubric and the judge is not implemented, so they are neither passes nor failures.</p>
  </div>
</section>

<section id="efficiency">
  <div class="wrap">
    <div class="sec-head"><span class="sec-num">03</span><h2>Cost and latency against accuracy</h2></div>
    <p class="sec-desc">What each system spends to get where it got. Accuracy runs along the
       horizontal axis (Pass^N), so <strong>bottom-right is best</strong>: reliable and cheap,
       reliable and fast. Correctness alone is not the whole picture on a 58-million-row database &mdash; a query
       that returns the right answer in six minutes is not a usable one.</p>
    <div class="scatter-grid">
{scatter(entries, snap, "cost_usd_per_task", "USD per task", ".4f")}
{scatter(entries, snap, "median_latency_s", "Median seconds", ".0f")}
    </div>
    <p class="note">Latency and cost come from the live agent runs. Neither is currently folded into
       the score: an efficiency metric in the spirit of BIRD's VES is on the roadmap, and until it
       exists a slow correct answer ranks exactly like a fast one.</p>
  </div>
</section>

<footer id="method">
  <div class="wrap">
    <div class="sec-head"><span class="sec-num">04</span><h2>Method, in brief</h2></div>
    <div class="cols">
      <p class="method">
        {den} execution-scored questions, 9 tiers, one frozen snapshot.<br>
        Gold answers compiled by executing reference SQL against that snapshot.<br>
        Synthetic data: deterministic, seed 42, FK-integrity validated, no PII.<br>
        Scored by <code>eval/score_cortex_bench.py</code>, unmodified, by the organizers.<br>
        Every run's score published, including the bad ones.
      </p>
      <p>
        Each row on this board is a JSON file in <code>results/</code>, validated in CI against
        <code>schema/leaderboard_entry.schema.json</code>. This page is regenerated from those files
        and holds no data of its own &mdash; edit the JSON, never the HTML. The provenance of any
        number is <code>git log results/&lt;entry-id&gt;.json</code>.
        <br><br>
        To submit, open a pull request adding one entry file.
        Known defects are logged in <a href="{REPO_URL}/blob/main/ERRATA.md">ERRATA.md</a>, and what
        the data does and does not model is in
        <a href="{REPO_URL}/blob/main/DATASHEET.md">DATASHEET.md</a>.
        <br><br>
        <span class="tag">Built {built} from {len(entries)} entries.</span>
      </p>
    </div>
  </div>
</footer>

</body>
</html>
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
