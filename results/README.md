# `results/` — the leaderboard's source of truth

One JSON file per leaderboard row, named for its `entry_id`. The published page at
`docs/index.html` is regenerated from this directory and holds no data of its own.

Keeping rows in git rather than in a database buys three things:

- **Provenance.** `git log results/<entry-id>.json` shows when a row appeared, who merged it, and
  every value it has ever held.
- **Regenerability.** Losing the site loses nothing.
- **Visible corrections.** A retracted or amended score is a commit with a diff, not a silent edit.
  That silent edit is the failure mode that has embarrassed other leaderboards.

## Adding an entry

```bash
cp results/2026-09-01-null-floor.json results/2026-10-01-my-system.json   # start from a real one
$EDITOR results/2026-10-01-my-system.json
python3 leaderboard/validate_entry.py results/2026-10-01-my-system.json
python3 leaderboard/build.py                                             # refresh docs/index.html
```

Then open a pull request. CI re-runs both commands; a failing entry cannot merge.

## The rules the schema enforces

| Rule | Why |
|---|---|
| `entry_id` equals the filename stem | the filename is the row's identity in git history |
| `runs` values are all published, and `mean` must equal their mean | a hand-edited headline, or a cherry-picked best run, is the easiest way to fake a leaderboard |
| `denominator` is the full gradable task count, not the count attempted | skipping tasks must never raise a score; `attempted` is displayed separately |
| `data_snapshot_id` is required | gold answers are snapshot-bound, and entries scored against different snapshots are grouped separately and never ranked against each other |
| a null metric requires `unavailable_reason` | an unmeasured metric renders as a dash with its reason, never as a zero |
| `verified_by_organizers` distinguishes organizer-run from self-reported | test-split rows are organizer-run only |

Run `python3 leaderboard/validate_entry.py --selftest` to see each rule reject a deliberately
broken entry. A validator that has never rejected anything is decoration.

## Reference rows

An entry with `system.kind = "reference"` is a control, not a competitor: it is pinned above the
ranking and takes no rank number. `2026-09-01-null-floor.json` is one — it answers nothing at all,
and exists so every score on the board can be read against the benchmark's floor.
