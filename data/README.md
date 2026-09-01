# The database

Cortex-Bench runs against a single DuckDB file: a synthetic Indian wealth-management platform,
22 tables, 58.5 million rows, 1.07 GB.

```bash
./data/download.sh                      # writes data/wealth_management.duckdb and verifies it
```

The file is a GitHub release asset. Set `CORTEX_BENCH_DB_URL` only if you are mirroring it.

Already have the file? `./data/download.sh` verifies it in place and exits.

| | |
|---|---|
| Snapshot id | `wm_synthetic_v1.3_2026_09_01` |
| Size | 1,152,135,168 bytes (1.07 GB) |
| SHA-256 | `7caa6785340cd23b4c2691df0cf8c0350718da13bba598338d10e4e8576ee8ed` |
| Engine | DuckDB |

## The hash is not a formality

Every gold answer was produced by executing its reference SQL against **this** database. Run the
same query against a different snapshot and you get a different answer that is not wrong — it is
simply unrelated to what the benchmark recorded. The scorer refuses to run when the database does
not reproduce the gold it is about to score against, and `download.sh` exits non-zero rather than
hand you a file that will silently produce nonsense.

## Schema

- `schema/wealth_management.sql` — full DDL, generated from the live database, DuckDB dialect.

The domain is Indian wealth management: investors and their segments, advisors and their targets,
instruments across equity / mutual funds / bonds / AIFs, trades and cashflows, daily position
snapshots, tax-lot accounting, firm revenue, and reference tables for taxation and corporate
actions. Several tiers of the benchmark require applying Indian market rules — STT on both legs of
a delivery equity trade, buy-side-only stamp duty, 18% GST on brokerage, LTCG/STCG thresholds —
so the schema is not merely a shape to join, it carries domain meaning.

## Licence

The database is released under CC BY-SA 4.0. The code in this repository is Apache-2.0.
