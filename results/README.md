# Results

Tables written by the scripts. Several are also **inputs** to later stages:
the graph is built from the MECE basket and ladder pair tables, so regenerating
those changes every downstream number. Paths in code are relative to the repo root.

## `data_audit/` — what the data contains

| File | Written by | Read by | Contents |
|---|---|---|---|
| `kalshi_series_categories.parquet` | `examples/fetch_kalshi_categories_series.py` | `classify_ticker()` and category checks | Kalshi's own series → category map |
| `category_month_counts.parquet` | `examples/category_history_audit.py` | `exotics_category_check.py` | Markets per category per month |
| `mece_yield_by_month.parquet` | `examples/mece_yield_by_month.py` | data-window memo | Fully covered basket-days per month, 54 months |
| `sports_categorisation_check.parquet` | `examples/sports_categorisation_check.py` | data-window memo | Sports markets per (month, series) |

## `mece/` — MECE baskets

| File | Written by | Read by | Contents |
|---|---|---|---|
| `mece_sum_to_one_results.parquet` | `examples/mece_sum_to_one_check.py` | PnL backtest, liquidity check, ground-truth validation | Per basket-day deviation |
| `mece_sum_to_one_leg_prices.parquet` | `examples/mece_sum_to_one_check.py` | **Graph construction** (`run_real_training.py`), spreads, artefact check | Validated basket membership and leg prices |
| `mece_sum_to_one_pnl_results.parquet` | `examples/mece_sum_to_one_pnl_backtest.py` | `baselines.py`, sports breakdown | Naive MECE PnL, three cost scenarios |
| `mece_sum_to_one_pnl_sensitivity_results.parquet` | `examples/mece_sum_to_one_pnl_sensitivity.py` | — | PnL across execution haircuts |
| `mece_spread_artefact_check.parquet` | `examples/mece_spread_artefact_check.py` | data-window memo | Per-basket bid/ask decomposition (the overround finding) |
| `mece_leg_spreads.parquet` | `build_mece_leg_spreads.py` | `evaluate_mece_settlement_pnl.py` (default `--spreads`) | Measured per-leg spreads, pooled |
| `mece_leg_spreads_windowed.parquet`, `mece_leg_spreads_w2.parquet` | `build_mece_leg_spreads.py --window …` | — | Windowed spread variants |

## `ladder/` — threshold ladders

| File | Written by | Read by | Contents |
|---|---|---|---|
| `pairwise_monotonicity_taker_side_results.parquet` | `examples/pairwise_monotonicity_taker_side_check.py` | early ladder checks | v1 pairing (superseded, kept for comparison) |
| `pairwise_monotonicity_taker_side_results_corrected.parquet` | `examples/pairwise_monotonicity_taker_side_check_v2.py` | **Graph construction**, ladder PnL, `SpreadLookup` | Validated ladder pairs with violation stats and spreads |
| `pairwise_monotonicity_taker_side_results_corrected_smoketest.parquet` | same, smoke-test mode | — | Small-run output of the above |
| `pairwise_monotonicity_pnl_results.parquet` | `examples/pairwise_monotonicity_pnl_backtest.py` | `baselines.py` | Naive ladder PnL |
| `pairwise_monotonicity_pnl_sensitivity_results.parquet` | `examples/pairwise_monotonicity_pnl_sensitivity.py` | — | PnL across spread haircuts |
| `pairwise_monotonicity_weather_{results,pnl}_{in_sample,held_out}.parquet` | `examples/pairwise_monotonicity_OOT.py` | — | Weather out-of-time check (weather later shown to be brackets, not ladders) |

## `baselines/`

| File | Written by | Contents |
|---|---|---|
| `baseline_results_summary.parquet` | `examples/baselines.py` | Both naive strategies on one metric interface — the fixed comparison point for the STGAT |

## `pairs_trading/` — Phase 1 (abandoned direction)

Output of `examples/event_pairs_arb_baseline.py` on October 2025: equity and
drawdown, ADF p-values, pair-level metrics and turnover. Kept as the evidence
for why the unrestricted pairs approach was dropped (Week 3 report §2).
