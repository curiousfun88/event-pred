# Script index

Every runnable script, grouped by the research phase it belongs to (see
[`RESEARCH_LOG.md`](RESEARCH_LOG.md)). Each script's module docstring states
the question it answers and why it exists; this page is the map.

Run everything from the **repository root**, e.g. `python stg_infra/score_forecast.py`.
Paths below are relative to `stg_infra/` unless they start with `scripts/`.

## Data acquisition — `scripts/`

| Script | Purpose |
|---|---|
| `scripts/fetch_kalshi_data.py` | Pull historical trades and markets from the Kalshi API |
| `scripts/data_split_by_month.py` | Split raw files into `data/{kind}/{kind}_kalshi_{even,odd}/{kind}_YYYY-MM.parquet` |
| `scripts/data_split_odd_even_months.py` | Streaming odd/even-month splitter (`SplitByOddEvenMonths`), used by `kalshi_traintest.py` |
| `scripts/view_parquet.py` | Print columns and head of a markets/trades file |
| `examples/fetch_kalshi_categories_series.py` | Kalshi's own series → category lookup → `results/data_audit/kalshi_series_categories.parquet` |

## Phase 0 — `stg` library demos (Semester 1)

| Script | Purpose |
|---|---|
| `examples/kalshi_example.py` | Build a spatio-temporal graph from Kalshi data |
| `examples/kalshi_traintest.py` | Month-based train/test graph construction |
| `examples/kof_n_stg_sparsity_demo.py` | K-of-N sparsity demonstration on the semester-1 pipeline |

## Phase 1 — Pairs trading (abandoned)

| Script | Output |
|---|---|
| `examples/event_pairs_arb_baseline.py` | Direction-A pairs baseline → `results/pairs_trading/` |
| `examples/overlap_test.py` | Event-universe overlap check for the pairs selection |

## Phase 2 — Constraint detection and naive baselines

**Feasibility (markets file, then trades)**

| Script | Question |
|---|---|
| `examples/testrun.py` | How many N-way clusters exist, and how large? |
| `examples/sum_to_k_check.py` | Do large resolved events have exactly K YES legs? |
| `examples/sum_to_one_check.py` | Is sum-to-K violated in quotes? (led to the markets-file finding) |
| `examples/k_to_n_check.py` | Sum-to-K for K-of-N events ("Top 6", "finalist") from trades |

**MECE baskets**

| Script | Output / question |
|---|---|
| `examples/mece_sum_to_one_check.py` | **Basket identification** → `results/mece/mece_sum_to_one_{results,leg_prices}.parquet` |
| `examples/mece_family_audit.py` | How much of the N-way population does a known structure explain? |
| `examples/mece_family_key_diagnostic.py` | Is the family-key regex grouping the right events? |
| `examples/mece_liquidity_check.py` | Are the largest deviations just thin legs? (introduced `MIN_LEG_TRADES`) |
| `examples/mece_sum_to_one_pnl_backtest.py` | Naive MECE PnL → `results/mece/mece_sum_to_one_pnl_results.parquet` |
| `examples/mece_sum_to_one_pnl_sensitivity.py` | Haircut sensitivity → `results/mece/mece_sum_to_one_pnl_sensitivity_results.parquet` |
| `examples/mece_sports_breakdown.py` | What is inside the "sports" PnL bucket? |

**Ladders**

| Script | Output / question |
|---|---|
| `examples/pairwise_monotonicity_check.py` | Violation rate with clock-time proximity between trades |
| `examples/pairwise_monotonicity_subtitle_check.py` | Classify ladder direction from `yes_sub_title` (weather) |
| `examples/pairwise_monotonicity_subtitle_check_crypto_financials.py` | Same eyeball check for crypto/financials |
| `examples/pairwise_monotonicity_title_lookup.py` | One-off title lookup for a suspected direction mismatch |
| `examples/pairwise_monotonicity_taker_side_check.py` | Same-`taker_side` violation test → `results/ladder/pairwise_monotonicity_taker_side_results.parquet` |
| `examples/pairwise_monotonicity_taker_side_check_v2.py` | **Ladder identification (current)** → `results/ladder/pairwise_monotonicity_taker_side_results_corrected.parquet` |
| `examples/pairwise_monotonicity_more_checks.py` | Follow-ups on the v1 taker-side output |
| `examples/pairwise_monotonicity_family_breakdown.py` | Why violation rate rises with the per-side trade cutoff |
| `examples/pairwise_monotonicity_category_magnitude.py` | Why weather violates ~50% vs crypto ~10% |
| `examples/pairwise_monotonicity_category_magnitude_wellsampled.py` | Same, well-sampled pairs only |
| `examples/pairwise_monotonicity_pair_type_composition_by_category.py` | Which pair types are valid no-arbitrage comparisons, by category |
| `examples/pairwise_monotonicity_ladder_identification_crosscheck.py` | Cross-check ladder pairing against family identification |
| `examples/weather_ladder_leak_check.py` | Do weather brackets leak into the ladder population? |
| `examples/classify_subtitle_diff_check.py` | Which pairs did the compound-subtitle fix drop? |
| `examples/misc.py` | Two-line smoke test of `classify_subtitle` |
| `examples/pairwise_monotonicity_OOT.py` | Out-of-sample weather check → `results/ladder/pairwise_monotonicity_weather_*_{in_sample,held_out}.parquet` |
| `examples/pairwise_monotonicity_pnl_backtest.py` | Naive ladder PnL → `results/ladder/pairwise_monotonicity_pnl_results.parquet`; defines `classify_ticker()` |
| `examples/pairwise_monotonicity_pnl_sensitivity.py` | Spread-haircut sensitivity → `results/ladder/pairwise_monotonicity_pnl_sensitivity_results.parquet` |

**Validation, data windows and baselines**

| Script | Output / question |
|---|---|
| `examples/kalshi_ground_truth_validation.py` | Classification vs Kalshi's `strike_type` / `mutually_exclusive` (98.5% / 97.5%) |
| `examples/category_history_audit.py` | Markets per category per month → `results/data_audit/category_month_counts.parquet` |
| `examples/weather_spike_check.py` | Is the Dec 2024 – Jan 2025 weather spike a product rollout? |
| `examples/exotics_category_check.py` | What is the "exotics" category? |
| `examples/data_windows.py` | **Module, not a script:** category windows and train/val/test split boundaries |
| `examples/baselines.py` | Consolidate naive baselines → `results/baselines/baseline_results_summary.parquet` |

## Phase 3 — STGAT v1 (masked-leg reconstruction, superseded)

| Script | Purpose |
|---|---|
| `build_combined_stgat_graph.py` | **Module:** `build_combined_graph()` wires MECE hubs + ladder edges into one `GraphBuilder` |
| `verify_combined_graph.py` | Check the combined graph on one real day |
| `diagnose_timestamps.py` | Find out-of-range `created_time` rows that hang `group_by_dynamic` |
| `run_real_training.py` | Build `cache/bundle_month_*.pt` one month at a time, then train v1 → `runs/v1_reconstruction/` |
| `verify_training_loop.py` | Training loop on synthetic scenarios with known answers |
| `verify_inference.py` | `model/inference.py` masked-forward on synthetic scenarios |
| `diagnose_features.py` | Per-slot feature ranges in the cache (motivated standardisation) |
| `evaluate_baselines.py` | Model vs no-learning predictors on identical masked positions |
| `evaluate_arbitrage.py` | MECE: model vs naive rule as a strategy, held-out test |
| `evaluate_arbitrage_ladder.py` | Ladder counterpart; defines `SpreadLookup` (reused by v2) |
| `diagnose_spreads.py` | Can the measured-spread file speak to the traded markets? |
| `verify_ladder_direction.py` | Confirms the strike-ordering convention every ladder number depends on |
| `evaluate_price_discovery.py` | When a stale leg trades, does it move toward the model's fair value? |
| `diagnose_persistence.py` | Do violations persist long enough to be worth forecasting? |
| `diagnose_staleness.py` | Is the persistence real, or just prices not updating? |
| `evaluate_violation_prediction.py` | Does the model predict *confirmed* violations better than arithmetic? |

## Phase 4 — STGAT v2 (forecasting, current)

| Script | Purpose |
|---|---|
| `train_forecast.py` | **Training entry point.** Horizon forecasts, residual head, mechanism-weighted loss → `runs/v2_*/` |
| `score_forecast.py` | Score a checkpoint on a held-out split **once**, against persistence and the shrinkage oracle |
| `evaluate_mece_forecast_pnl.py` | Taker round-trip PnL with controls (random, oracle, always-revert, static arb) and participation caps |
| `evaluate_mece_maker_pnl.py` | Same signals executed as a maker, with a flow-derived fill model |
| `evaluate_mece_settlement_pnl.py` | Hold-to-settlement variant with model-timed entry |
| `diagnose_mask_semantics.py` | What `mask=True` actually means (why a liveness filter was a no-op) |
| `diagnose_ladder_reversion.py` | Ladder reversion bucketed by gap magnitude |
| `diagnose_ladder_conditional.py` | Ladder reversion conditional on a leg repricing (overturned α ≈ 0.99) |
| `diagnose_basket_coverage.py` | How much of the MECE market can a naive real-time trader see? |
| `diagnose_basket_composition.py` | What kind of market is the model actually trading? |

**Pipeline-wide:** `verify_pipeline.py` — 13 invariants (causality, residual head starts at persistence, ablation, baselines, reporting, identities, bootstrap coverage, splits); `--self-test` proves each check fails on a planted bug.

## Phase 5 — Measurement and data window

| Script | Output / question |
|---|---|
| `examples/mece_spread_artefact_check.py` | **The overround test** → `results/mece/mece_spread_artefact_check.parquet` |
| `build_mece_leg_spreads.py` | Measured MECE per-leg spreads → `results/mece/mece_leg_spreads.parquet` (`--window` variants) |
| `examples/mece_yield_by_month.py` | Usable basket-days per month, all 54 months → `results/data_audit/mece_yield_by_month.parquet` |
| `examples/sports_categorisation_check.py` | Is "sports first appears 2024-12" real? → `results/data_audit/sports_categorisation_check.parquet` |

## Library code (imported, not run)

| Path | Contents |
|---|---|
| `stg/` | Graph data model (`core.py`), builder, strategies, Kalshi nodes/edges, torch bridge |
| `stg/pairs/` | Phase-1 pairs-trading pipeline and metrics |
| `stg/events/` | Phase-0 economic-series implied means |
| `model/train.py` | `STGATBackbone`, `TrainingConfig`, v1 training loop |
| `model/spatial_attention.py` / `temporal_attention.py` | Two-channel GATv2; causal temporal attention |
| `model/output_heads.py` | v1 constrained heads (superseded) |
| `model/forecast_head.py` / `forecast_objective.py` | v2 residual head; horizon loss with persistence and oracle baselines |
| `model/training_objective.py` / `inference.py` | v1 masked-leg objective and masked forward pass |
| `model/chunking.py` / `month_store.py` | Split-safe time chunks; one cached bundle per month |
| `model/data_validation.py` | Validity filters applied before the active-node set |
| `model/run_guards.py` | Assertions that stop a run on known failure classes (split leakage, schema drift, …) |
