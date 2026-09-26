# Kalshi Arbitrage FYP — Code Index

Script history for the `stg_infra/examples/` probes, in the order the investigation
actually happened, kept for reproducibility and detail. Superseded scripts are marked —
use the CURRENT version listed for each mechanism. All scripts run via
`python -m stg_infra.examples.<script_name_without_.py>` from the repo root.

**Where to start has changed.** This index originally pointed at
`superseded-findings-summary.md` as the maintained synthesis. That document is
now stale in several places (noted inline below) and has been replaced by:

- `docs/INDEX.md` — chronology and what superseded what
- `docs/3-economics/spread-artefact-finding.md` — **the central finding; read first**
- `docs/planning/four-week-plan-and-reframe.md` — current status and priorities
- `docs/2-model/architecture-map.md` — how the pipeline works, with verify-it-yourself commands

Every PnL figure in this index is computed from **last trade prints**, which sit at the
bid or the ask and never at mid. `spread-artefact-finding.md` measured that ~92.5% of
apparent MECE basket deviation is that overround. **Read every dollar figure below as a
backtest artefact, not as realisable profit.**

## Ladder monotonicity thread (chronological)

- `pairwise_monotonicity_taker_side_check.py` — SUPERSEDED. Original ladder monotonicity +
  taker-side same-side-only test + spread-ratio flag. Superseded by `..._corrected.py` (the
  regex ticker-suffix pairing was found unreliable for weather — see the funnel diagnostic
  below).
- `pairwise_monotonicity_followup_checks.py` — follow-up on the ORIGINAL (superseded)
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
- `pairwise_monotonicity_weather_pair_type_composition.py` — v2, classifies pairs by
  `yes_sub_title` instead of the ticker-suffix letter (the letter-only version wrongly
  treated both tails of a "T" suffix as one direction).
- `pairwise_monotonicity_ladder_identification_crosscheck.py` — cross-checks the regex
  ticker-based pairing method against the original, validated title-template-homogeneity
  method. Found the regex method produces ZERO weather/climate pairs when the two methods
  agree — see next script.
- `pairwise_monotonicity_weather_ladder_funnel_diagnostic.py` — direct follow-up: why does
  regex-vs-validated agreement include zero weather pairs? (Root-caused to the sub_title
  bracket/threshold distinction above.)
- `pairwise_monotonicity_taker_side_check_corrected.py` — **CURRENT** ladder pair-builder +
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
- `pairwise_monotonicity_recategorize_check.py` — sanity check applying the real
  Kalshi-category lookup (`fetch_kalshi_series_categories.py`) to already-computed pair
  results before a full rerun.
- `fetch_kalshi_series_categories.py` — builds a series_ticker -> category lookup from
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
- `pairwise_monotonicity_pnl_out_of_sample.py` — NOT updated to the corrected pipeline;
  deliberately deprioritized (rebuilds its own weather-specific ladder pairs from scratch,
  predates the sub_title correction). **Do not run it** — its weather pairs are the
  invalidated population. Would need corrected-pair treatment plus rescoping to
  crypto/financials if ever revisited, and the ladder line is closed
  (`ladder-conclusion-overturned.md`), so it will not be.

## MECE sum-to-$1 thread (chronological)

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

## Evaluation and training (repo root)

- `train_forecast.py` / `score_forecast.py` — forecasting-era training and scoring.
  `score_forecast.py` deliberately has no tuning flags.
- `evaluate_mece_settlement_pnl.py` — **CURRENT** PnL. Hold-to-settlement, one-way costs.
  `--spreads` now defaults to `mece_leg_spreads.parquet` (it used to default to the
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

## Cross-mechanism

- `baselines.py` — consolidates both mechanisms' realistic-scenario PnL into one shared
  metrics interface (coverage %, win rate, cross-sectional Sharpe, max drawdown). Produces
  `baseline_results_summary.parquet`. Its saved numbers are the pre-correction ones; the
  baselines that matter for the forecasting claim are **persistence** and the **shrinkage
  oracle**, computed inside `model/forecast_objective.py`, not here.

## Reports / notes

- `direction_b_feasibility_report.md` — the semester's original feasibility report:
  motivates Direction B (N-way cluster GAT) over Direction A (unrestricted pair discovery,
  found to be spurious correlation), documents the market-structure taxonomy
  (MECE/K-of-N/ladder), and the original (pre-correction) empirical checks. Largely
  superseded; kept for the Direction A rejection, which still stands and is the reason not
  to pivot to cointegration.
- `taker_side_investigation_notes.md` — working notes on whether `taker_side` can address
  bid-ask bounce. **Contains a corrected conclusion**: its direction finding (that `"no"`
  prints higher) was drawn from three tickers and is wrong. `"yes"` = lifted the ask;
  median per-ticker gap **+3.82¢**. The correction is load-bearing for the overround
  finding.
- `superseded-findings-summary.md` — **stale, do not cite.** Its 267-snapshot figure
  predates the `FAMILY_RE` fix and `MAX_LEGS` raise and covers two months; its "14+ leg
  families never" claim is false on the May–Sep 2025 window; its PnL figures are
  pre-spread-decomposition. Superseded by `docs/INDEX.md` and the documents listed at the
  top of this file.

## Not included

Left out as scratch/test noise, not project content: `mini_test.md`, `mini_test2.md`,
`mini_test3.md`, `test_min.md` (LaTeX-rendering smoke tests), `report_latexfonts.md`
(LaTeX-escaped duplicate of `direction_b_feasibility_report.md`, identical content
otherwise). `build_report.py` (an unrelated `stg_infra` import-path bugfix report) was
also left out.

## Convention worth preserving

Every script here that was added after the first month has a `--self-test` mode that
exercises planted cases with known answers before it touches real data. That convention
caught: the ablation `--drop-edges` key bug (argparse accepted two names that do not
exist in the cache), the category keyword matcher finding "ETH" inside `SOMETHINGNEW`,
three separate bugs in `mece_spread_artefact_check.py`, and the `FAMILY_RE`
digit-truncation bug. Keep it for anything new.
