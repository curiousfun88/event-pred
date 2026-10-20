# Script index

Every runnable script: first a map grouped by research phase (see
[`RESEARCH_LOG.md`](RESEARCH_LOG.md)), then the investigation notes for each
thread in the order it actually happened, with superseded scripts marked and
the **CURRENT** version named for each mechanism. Each script's module
docstring states the question it answers and why it exists.

Run everything from the **repository root**, e.g. `python stg_infra/score_forecast.py`.
Paths below are relative to `stg_infra/` unless they start with `scripts/`.

**Where to start:**
[`3-economics/spread-artefact-finding.md`](3-economics/spread-artefact-finding.md)
(the central finding), [`planning/four-week-plan-and-reframe.md`](planning/four-week-plan-and-reframe.md)
(current status) and [`2-model/architecture-map.md`](2-model/architecture-map.md)
(how the pipeline works, with verify-it-yourself commands).

Every PnL figure below is computed from **last trade prints**, which sit at the
bid or the ask and never at mid. `spread-artefact-finding.md` measured that
92.5% of baskets sum above $1 at last prints (the overround pattern); with
quotes, the print side carries 54% of the deviation pooled and 87% in two-sided
baskets, one-sided books most of the rest (RESEARCH_LOG §7). **Read every dollar
figure below as a backtest artefact, not as realisable profit.**

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

---

## Investigation notes by thread

### Ladder monotonicity thread (chronological)

- `pairwise_monotonicity_taker_side_check.py` — SUPERSEDED. Original ladder monotonicity +
  taker-side same-side-only test + spread-ratio flag. Superseded by `pairwise_monotonicity_taker_side_check_v2.py` (the
  regex ticker-suffix pairing was found unreliable for weather — see the funnel diagnostic
  below).
- `pairwise_monotonicity_more_checks.py` — follow-up on the ORIGINAL (superseded)
  results: well-sampled-only violation rates, spread-ratio bucket breakdown, magnitude vs.
  spread. **Its weather headline (~50% violation rate, 5.4× gap/spread) does not survive
  the sub_title correction** — those pairs are not a validated monotone chain. See
  `taker-side-investigation-notes.md`.
- `pairwise_monotonicity_title_lookup.py` — one-off ticker/title lookup used to sanity-check
  a specific T/B-suffix direction-mismatch hypothesis.
- `pairwise_monotonicity_subtitle_check.py` — direct eyeball check: does
  `yes_sub_title`/`no_sub_title` reliably distinguish bracket vs. threshold markets for
  weather? (Yes, and cleaner than parsing title text.) **This is the script that
  invalidated the weather ladder result.**
- `pairwise_monotonicity_weather_pair_type_composition.py` *(not in this repository)* — v2, classifies pairs by
  `yes_sub_title` instead of the ticker-suffix letter (the letter-only version wrongly
  treated both tails of a "T" suffix as one direction).
- `pairwise_monotonicity_ladder_identification_crosscheck.py` — cross-checks the regex
  ticker-based pairing method against the original, validated title-template-homogeneity
  method. Found the regex method produces ZERO weather/climate pairs when the two methods
  agree — see next script.
- `pairwise_monotonicity_weather_ladder_funnel_diagnostic.py` *(not in this repository)* — direct follow-up: why does
  regex-vs-validated agreement include zero weather pairs? (Root-caused to the sub_title
  bracket/threshold distinction above.)
- `pairwise_monotonicity_taker_side_check_v2.py` — **CURRENT** ladder pair-builder +
  monotonicity test. Uses `yes_sub_title` classification (bracket/upper_tail/lower_tail),
  combines Oct+Nov trades. Result: 464,709 valid pairs, ~14-15% raw violation rate, ~9-10%
  for crypto after liquidity filtering. **The validated pool is crypto/financials only** —
  narrower in category coverage than MECE.
- `pairwise_monotonicity_subtitle_check_crypto_financials.py` — extends the subtitle check to
  crypto/financials, revealing each category runs TWO distinct market designs
  (threshold-ladder "D"-series vs. bracket-basket non-"D" series).
- `pairwise_monotonicity_pair_type_composition_by_category.py` — confirms 100%
  correctly-classified pair types (all upper_tail-upper_tail) across every category on the
  corrected pairs.
- `pairwise_monotonicity_category_magnitude.py` / `_wellsampled.py` — gap/spread ratio
  analysis; liquidity-threshold sweep (crypto robust ~9-10%, financials collapses to 0% at
  strict liquidity).
- `pairwise_monotonicity_family_breakdown.py` — per-family breakdown of the corrected
  violation results.
- `pairwise_monotonicity_recategorize_check.py` *(not in this repository)* — sanity check applying the real
  Kalshi-category lookup (`fetch_kalshi_categories_series.py`) to already-computed pair
  results before a full rerun.
- `fetch_kalshi_categories_series.py` — builds a series_ticker -> category lookup from
  Kalshi's own API category field (replaces the keyword-guessing `classify_ticker()`
  fallback). **Use this, not keywords, for anything load-bearing:** in 2025-03 a keyword
  sweep saw sports at 0.7% of notional where this lookup correctly reports 86.9%. It maps
  13,738 series at ~1.00 coverage in all 54 months and is not time-bounded to
  currently-listed series.
- `pairwise_monotonicity_pnl_backtest.py` — **CURRENT** for the ladder. Idealized/fees-only/
  realistic PnL on the corrected results: idealized +$5,213.10, fees-only +$2,683.43,
  realistic −$9,221.66 (9.2% win rate). The realistic figure is the honest one and it is
  negative; the two positive figures are what the mechanism looks like before execution
  cost, not what it pays.
- `pairwise_monotonicity_pnl_sensitivity.py` — sweeps the spread-haircut fraction (0-100% of
  measured spread). Breakeven ~20-23% for both crypto and financials — i.e. the strategy
  needs to pay under a quarter of the measured spread to break even, which no taker does.
- `pairwise_monotonicity_OOT.py` — NOT updated to the corrected pipeline;
  deliberately deprioritized (rebuilds its own weather-specific ladder pairs from scratch,
  predates the sub_title correction). **Do not run it** — its weather pairs are the
  invalidated population. Would need corrected-pair treatment plus rescoping to
  crypto/financials if ever revisited, and the ladder line is closed
  (`ladder-conclusion-overturned.md`), so it will not be.

### MECE sum-to-$1 thread (chronological)

- `mece_sum_to_one_check.py` — **CURRENT**. Full-basket sum-to-$1 test using
  resolved-outcome + family-consistency validation (self-rejects ladders/combo-props).
  Persists `mece_sum_to_one_results.parquet` + `mece_sum_to_one_leg_prices.parquet` for
  downstream scripts. **Figures in this index are stale:** it originally reported 618
  full-basket snapshots from 2,354 candidates over two months, with "14+ leg families never
  achieve full coverage". After the `FAMILY_RE` fix and `MAX_LEGS` 60→100, and over a wider
  month range, it reports **4,891** full-basket (event, day) snapshots for 2025-02…2025-11,
  and 14+ leg families **do** achieve coverage (`KXF1RACE` 20 legs, `KXNASCARRACE` 41 legs —
  see `mece-population-composition.md` §2). Pooled over all 54 months there are **86**
  qualifying families and **7,581** covered basket-days across 44 months.
- `mece_family_key_diagnostic.py` — diagnostic proving the `FAMILY_RE` digit-truncation bug
  (fixed in `mece_sum_to_one_check.py`): recovered 58 candidate events, 0 regressions.
- `mece_family_audit.py` — funnel-accounting + per-family eyeball audit of the N-way cluster
  identification pipeline. Found the `MAX_LEGS=60` cutoff was excluding 2,989 events (mostly
  `KXDOGE`) — raised to 100. The "not yet rerun at MAX_LEGS=100, low priority" note is
  **obsolete**: it has been rerun, and the 14+ leg conclusion changed as a result.
- `mece_sum_to_one_pnl_backtest.py` — idealized/fees-only/realistic PnL on full-basket
  snapshots: idealized +$2,609.00, fees-only +$1,662.42, realistic +$84.42 (38.6% win rate,
  **negative median**). Superseded by `evaluate_mece_settlement_pnl.py`, which evaluates the
  correct structure (hold-to-settlement, one-way costs) rather than a round trip. Note the
  negative median against a positive total even here — the total was carried by a tail.
- `mece_sum_to_one_pnl_sensitivity.py` — sweeps the per-leg execution haircut (0-10
  cents/leg). Zero-crossing between 1-2 cents/leg. **This was the early warning and it was
  read too optimistically at the time:** the measured per-leg spread is 4.68¢ (windowed) to
  5.61¢ (pooled), i.e. two to five times past the zero-crossing. The sensitivity sweep
  already contained the negative answer.
- `mece_spread_artefact_check.py` — **CURRENT and decisive.** Splits each leg's prints by
  `taker_side`, reprices each basket four ways (last mixed / ask / bid / mid), tests sign
  asymmetry, four-way repricing, and executable edge on the gated tail. 27 self-tests
  including planted pure-artefact, real-mispricing and cross-leg-span cases. Use
  `--max-basket-span` for the cross-leg print span (median 406 min); `--min-side-gap`
  constrains the within-leg gap and is a different control.
- `mece_yield_by_month.py` — **CURRENT** for the data-window question. Pools basket
  identification across all 54 months, then counts full-basket coverage per trades month.
  19 self-tests.
- `sports_categorisation_check.py` — audits whether "sports first appears 2024-12" is a
  classification artefact. It is not: sports genuinely launched 2024-12 → 2025-02 as a
  regulatory matter. 21 self-tests including a `KXTRUMPWINS` decoy that must not count as
  sports.

### Evaluation and training (`stg_infra/`)

- `train_forecast.py` / `score_forecast.py` — forecasting-era training and scoring.
  `score_forecast.py` deliberately has no tuning flags.
- `evaluate_mece_settlement_pnl.py` — **CURRENT** PnL. Hold-to-settlement, one-way costs.
  `--spreads` now defaults to `results/mece/mece_leg_spreads.parquet` (it used to default to the
  *ladder* results file, which contains only crypto/financials pairs, so zero MECE legs
  matched and every leg silently fell through to a global median from another mechanism).
  `warn_spread_coverage` banners below 50% measured coverage. Three robustness filters
  default **off**.
- `evaluate_mece_forecast_pnl.py` / `evaluate_mece_maker_pnl.py` — round-trip and maker
  variants. The maker route is provisional; the fee shape was never verified.
- `build_mece_leg_spreads.py` — **run this with `--window`.** The file currently on disk is
  the *pooled* estimate (global median 5.613¢), which conflates bid-ask with price drift;
  the windowed estimate is 4.68¢. The difference is ~5.6¢ of cost on a 6-leg basket, which
  is why two otherwise identical PnL runs report +$757 and +$292.
- `verify_pipeline.py` — 13 correctness checks, each with a mutation proving it can fail.
  `--self-test` runs the lot.
- `evaluate_arbitrage*.py`, `evaluate_price_discovery.py`,
  `evaluate_violation_prediction.py`, `evaluate_baselines.py` — **reconstruction-era**.
  They read a different checkpoint format and are not interchangeable with the forecasting
  scripts; see `architecture-map.md` §5.

### Cross-mechanism

- `baselines.py` — consolidates both mechanisms' realistic-scenario PnL into one shared
  metrics interface (coverage %, win rate, cross-sectional Sharpe, max drawdown). Produces
  `baseline_results_summary.parquet`. Its saved numbers are the pre-correction ones; the
  baselines that matter for the forecasting claim are **persistence** and the **shrinkage
  oracle**, computed inside `model/forecast_objective.py`, not here.

### Reports / notes

- `direction-b-feasibility-report.md` — the semester's original feasibility report:
  motivates Direction B (N-way cluster GAT) over Direction A (unrestricted pair discovery,
  found to be spurious correlation), documents the market-structure taxonomy
  (MECE/K-of-N/ladder), and the original (pre-correction) empirical checks. Largely
  superseded; kept for the Direction A rejection, which still stands and is the reason not
  to pivot to cointegration.
- `taker-side-investigation-notes.md` — working notes on whether `taker_side` can address
  bid-ask bounce. **Contains a corrected conclusion**: its direction finding (that `"no"`
  prints higher) was drawn from three tickers and is wrong. `"yes"` = lifted the ask;
  median per-ticker gap **+3.82¢**. The correction is load-bearing for the overround
  finding.
- `superseded-findings-summary.md` — **stale, do not cite.** Its 267-snapshot figure
  predates the `FAMILY_RE` fix and `MAX_LEGS` raise and covers two months; its "14+ leg
  families never" claim is false on the May–Sep 2025 window; its PnL figures are
  pre-spread-decomposition. Superseded by `RESEARCH_LOG.md` and the documents listed at the
  top of this file.

### Not included

Left out as scratch/test noise, not project content: `mini_test.md`, `mini_test2.md`,
`mini_test3.md`, `test_min.md` (LaTeX-rendering smoke tests), `report_latexfonts.md`
(LaTeX-escaped duplicate of `direction-b-feasibility-report.md`, identical content
otherwise). `build_report.py` (an unrelated `stg_infra` import-path bugfix report) was
also left out.

### Convention worth preserving

Every script here that was added after the first month has a `--self-test` mode that
exercises planted cases with known answers before it touches real data. That convention
caught: the ablation `--drop-edges` key bug (argparse accepted two names that do not
exist in the cache), the category keyword matcher finding "ETH" inside `SOMETHINGNEW`,
three separate bugs in `mece_spread_artefact_check.py`, and the `FAMILY_RE`
digit-truncation bug. Keep it for anything new.
