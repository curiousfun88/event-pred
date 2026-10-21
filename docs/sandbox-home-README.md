# Live forward test: files on this sandbox

This folder holds the live paper-trading test of G2, a learned market-making strategy on Kalshi event contracts.
It runs every hour on Lumid sandboxes and persists across the daily sandbox handovers.

**For the result, start with the dashboard: https://curiousfun88.github.io/event-pred-live/**
It shows the main result: G2 and its baselines on the 23 series G2 was trained and backtested on, counting quoting
hours from 16 Oct 2026 17:00 UTC, settled positions only, pessimistic fills, net of Kalshi's fees.

The pre-registered verdicts are computed on settled events at the interim cut (28 Oct 2026, positions settled by
30 Oct) and the final cut (11 Nov 2026). Until then all figures are provisional.

## Where the results are

| What | Path (under /home/curiouslearner842) | Updated |
|---|---|---|
| The dashboard's data: every strategy's settled net P&L and return, and P&L over time | `live-backup/site/summary.json` | every 10 minutes |
| The hash-chained ledger, one entry per quoting hour | `event-pred/runs/live/paper/ledger/entries/<YYYYMMDDTHH>.json` | hourly |
| OpenTimestamps receipts for the hourly decisions and ledger entries | `event-pred/runs/live/stamps/`, `event-pred/runs/live/paper/ledger/stamps/` | hourly |
| Each hour's decisions: every candidate quote, its inputs and every strategy's choice | `event-pred/runs/live/scores/one_<H>.parquet`, `two_<H>.parquet` | hourly |
| One line per hour of the decision cycle (the same as the Research Fleet `fwdtest-hour` job) | `event-pred/runs/live/runs.jsonl` | hourly |
| Simulated fills per strategy, under each fill model | `event-pred/runs/live/paper/fills_primary_<strategy>.parquet` (pessimistic, the reported one), `_opt_` (optimistic), `_strict_` | each ledger round |
| Offline results fixed before going live (baselines, training-window choice, sensitivity checks) | `event-pred/results/live/*.json` | fixed |
| Cut reports (interim and final) | `results/cuts/` | added at each cut |
| Logs | `event-pred/logs/` (`sbx_keeper.log`: handovers and backups) | continuous |

In a ledger entry, `new_fills` and `settlements` are what happened in that hour, `hash` and `prev_hash` chain the
entries, and `verification` lists any mismatch found when the hour's fills were re-derived from scratch. For P&L
use `summary.json` or the dashboard: they recount the fills (amendment L20), while the entries' own running totals
undercount repeated identical fills.

## Research Fleet

The same results are posted as jobs on Research Fleet:

- `fwdtest-daily-<YYYYMMDD>`: once a day, the main result per strategy (`main_<strategy>_net_usd`,
  `main_<strategy>_ret_pct`, `main_g2_minus_rnd2_usd`). Read this one for the result.
- `fwdtest-pnl-<YYYYMMDDTHH>`: every hour, the main result's settled net P&L at that hour.
- `fwdtest-hour-<YYYYMMDDTHH>`: every hour, what was decided (markets scanned, quotes considered, share posted).
  A health check, with no P&L.

Open a job and choose Result to see its metrics. Jobs go to the home site, with office as the backup. Hourly jobs
from 18 to 21 Oct 2026 are on the office site.

## Strategy codes

| Code | Strategy |
|---|---|
| g2 | G2, the strategy under test: gradient-boosted trees, posting quotes it predicts will net more than 1 cent |
| rnd2 | Random quoting at G2's posting share, the main control |
| lin2, mlp2 | Linear model and neural network on G2's inputs |
| g | G, the original 2025 model, never retrained |
| cand | Quote every candidate |
| g2w1, g2w2 | G2 trained on the last 3 or 6 months instead of all history |
| g2p, rnd2p | Two-price variant of G2, and its random control |
| wide3, liq, liq_traded | Rules: wide spreads only, liquid markets only |
| g2_sel | G2 restricted to selected categories |

## Please do not change

Everything under `event-pred/runs/live/` and `live-backup/` is written by the running test. Read freely, but do
not edit, move or delete files there. `.lumid/` holds the account's access token and is not part of the results.

Code and rules: https://github.com/curiousfun88/event-pred (pre-registration:
`docs/planning/lumid-forward-test-preregistration.md`).
