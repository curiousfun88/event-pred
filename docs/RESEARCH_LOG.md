# Research log

How the project got to its current state, in order, with a pointer to the code,
results and logs behind each step. Dates are from commits, report headers and
log timestamps. The second half lists every conclusion that was later corrected
or withdrawn — these are part of the result, not noise to hide.

For the current state and next steps, read [`CLAUDE.md`](../CLAUDE.md).

---

## Phase 0 — Graph infrastructure (Semester 1, to Apr 2026)

Built `stg`, a strategy-pattern library that turns Kalshi trades/markets into
a spatio-temporal graph (pluggable temporal slicing, node, edge, feature,
label and post-processing strategies), plus economic-series tooling
(`stg/events/`: CPI, Fed, GDP, payrolls, unemployment, recession implied means).

- Code: `stg_infra/stg/`, `stg_infra/examples/kalshi_example.py`,
  `kalshi_traintest.py`, `kof_n_stg_sparsity_demo.py`
- Last commits of this phase: 2026-04-15

## Phase 1 — Pairs trading, and why it was dropped (Aug 2026)

A statistics-only pairs-trading baseline ("Direction A": correlation and
half-life pair selection over the unrestricted universe, October 2025) gave
Sharpe 5.52 and ~46% return. The selected pairs were economically unrelated —
the result of multiple testing over tens of thousands of candidate pairs.
A graph attention model on the same universe would have more capacity to fit
the same noise, so the project moved to **Direction B**: N-way clusters with
hard structural constraints.

- Code: `stg_infra/stg/pairs/`, `stg_infra/examples/event_pairs_arb_baseline.py`,
  `examples/overlap_test.py`
- Results: [`results/pairs_trading/`](../results/pairs_trading)
- Report: [Week 3 progress report](reports/week03_progress_report.md) (26 Aug 2026)

## Phase 2 — Detection: do the constraints get violated? (Aug–Sep 2026)

1. **Markets file is unusable for this.** It holds one static row per ticker
   per month; 0.05% of N-way legs ever show a real quote. All checks moved to
   trade prints. (`examples/sum_to_one_check.py`, `testrun.py`, `sum_to_k_check.py`)
2. **MECE baskets.** `mece_sum_to_one_check.py` identifies single-winner
   families (exactly one YES leg across ≥3 historical instances) and measures
   full-basket deviation from last trades. Follow-ups: `mece_family_audit.py`,
   `mece_family_key_diagnostic.py`, `mece_liquidity_check.py` (added the
   `MIN_LEG_TRADES` filter), `mece_sports_breakdown.py`.
3. **Ladders.** The pair-identification logic went through three generations:
   ticker-suffix guessing → `yes_sub_title` parsing (`pairwise_monotonicity_subtitle_check*.py`)
   → contract-type-aware pairing (`pairwise_monotonicity_taker_side_check_v2.py`),
   with same-`taker_side` comparisons to remove bid/ask bounce. Weather was
   found to be almost entirely brackets, not ladders
   (`pairwise_monotonicity_pair_type_composition_by_category.py`,
   `weather_ladder_leak_check.py`).
4. **Classification validated against Kalshi's own fields** (`strike_type`,
   `mutually_exclusive`) on 200-item random samples: 98.5% (MECE) and 97.5%
   (ladder) precision. (`kalshi_ground_truth_validation.py`)
5. **Data windows by category.** Financials and crypto have step changes in
   listing volume (Apr 2024, Dec 2024); weather stabilises Feb 2025.
   Encoded once in `examples/data_windows.py`.
   (`category_history_audit.py`, `weather_spike_check.py`, `exotics_category_check.py`)
6. **Naive rule-based baselines** for both mechanisms, consolidated into one
   file as the fixed comparison point: `examples/baselines.py` →
   `results/baselines/baseline_results_summary.parquet`.

- Results: [`results/mece/`](../results/mece), [`results/ladder/`](../results/ladder),
  [`results/data_audit/`](../results/data_audit)
- Report: [Week 5 consult](reports/week05_consult_progress_update.docx)
  (classification method, data windows, precision-only validation)
- Commit: `1d19474` "arbitrage checks 050926" (5 Sep 2026)

## Phase 3 — STGAT v1: masked-leg reconstruction (17–19 Sep 2026)

One graph carrying both mechanisms: ticker nodes, one hub node per MECE basket
(leg ↔ hub hyperedges) and directed ladder edges. Backbone:
type-specific projection → two-channel GATv2 → causal temporal attention.
Heads were **constrained by construction** (grouped softmax so MECE legs sum
to $1; softplus gap so ladder legs stay ordered). Objective: mask a leg and
reconstruct its current price from the graph.

Engineering found along the way: the dense (T,N,N) adjacency OOM-killed a
5-month run (→ sparse per-snapshot edges, `stg/bridge.py`); dense (T,N,F)
grows with the square of the range (→ per-month cache, `model/month_store.py`);
raw feature scales spanned 7 orders of magnitude (→ train-only standardisation).

Evaluation showed the constrained heads could not work: a head whose legs sum
to $1 makes the model's basket deviation *identical* to the naive rule's, and
98.3% of naive ladder violations were two stale prints compared with each other
(`diagnose_staleness.py`).

- Code: `run_real_training.py`, `model/train.py`, `model/output_heads.py`,
  `model/training_objective.py`, `evaluate_arbitrage*.py`, `evaluate_baselines.py`,
  `evaluate_violation_prediction.py`, `evaluate_price_discovery.py`,
  `diagnose_persistence.py`, `diagnose_staleness.py`, `diagnose_spreads.py`
- Run: [`runs/v1_reconstruction`](../runs/README.md) · Logs: [`logs/v1_reconstruction/`](../logs/README.md)

## Phase 4 — STGAT v2: forecasting (19–20 Sep 2026)

Target changed from "price now" to "price at t+h"; the constrained heads were
replaced by one unconstrained `ResidualForecastHead` (p̂ = p_now + Δ, final
layer zero-initialised so training starts exactly at persistence). The
constraint now lives only in the graph.

Results on the 5-month pilot:
- **MECE:** 0.851× (val) / **0.853× (test, scored once)** the shrinkage oracle.
  Graph ablation: no-graph run loses ~92% of the margin. Ladder-edge ablation:
  no detectable effect.
- **Ladder:** all-pairs ratio is best at initialisation under every mover
  weighting (all / weighted / W=2 / moved-only). Violations revert sharply
  *when a leg reprices*, but repricing timing is not in the features.
- **Trading:** model beats a coin-flip control on identical events and costs;
  every strategy — including idealised static arbitrage — loses net of fees.
  Maker execution helps by ~$29/trade and still loses.

- Code: `train_forecast.py`, `model/forecast_head.py`, `model/forecast_objective.py`,
  `score_forecast.py`, `evaluate_mece_forecast_pnl.py`, `evaluate_mece_maker_pnl.py`,
  `evaluate_mece_settlement_pnl.py`, `diagnose_ladder_*.py`, `diagnose_mask_semantics.py`,
  `diagnose_basket_coverage.py`, `diagnose_basket_composition.py`
- Runs: [`runs/v2_*`](../runs/README.md) · Logs: [`logs/v2_forecast/`](../logs/README.md)
- Report: [Recess Week consult](reports/recess_week_consult.pdf) (24 Sep 2026)

## Phase 5 — Measurement check and data window (24–26 Sep 2026)

- **Overround.** Last trade prints are 68.7% ask-side; with a 2.8¢ half-spread
  that *predicts* a +6.3¢ signed mean deviation on a 6-leg basket before any
  mispricing. Measured: +5.25¢, with 92.5% of baskets above $1. At executable
  prices, selling an "overpriced" basket nets −0.07¢ before fees.
  (`examples/mece_spread_artefact_check.py` → `results/mece/mece_spread_artefact_check.parquet`)
- **Usable data window.** Measured fully covered basket-days per month across
  all 54 months: proposes 2024-11..2025-11 with 7 expanding walk-forward folds;
  2022-04..2022-11 as a labelled backcast only.
  (`examples/mece_yield_by_month.py`, `examples/sports_categorisation_check.py`)
- **Measured MECE spreads** replace the ones borrowed from the ladder file
  (`build_mece_leg_spreads.py` → `results/mece/mece_leg_spreads*.parquet`).

- Report: [data-window memo](reports/data_window_memo.tex) (26 Sep 2026)
- Commit: `65a6063` "STGAT Implementation and Methodology Checks 260926"

**Now:** awaiting supervisor response to the Recess consult and the memo.
Open items are listed in priority order in [`CLAUDE.md`](../CLAUDE.md).

---

## Corrections and retractions

Each entry: what was believed, what overturned it, and where the evidence is.

| # | Earlier conclusion | Correction | Evidence |
|---|---|---|---|
| 1 | Pairs trading works (Sharpe 5.52) | Spurious pairs from multiple testing; direction abandoned | Week 3 report §2 |
| 2 | Markets-file quotes can test the basket constraint | File is one static row per ticker; switched to trade prints | Week 3 report §4.1 |
| 3 | Constrained output heads enforce no-arbitrage usefully | They make a predicted dislocation impossible and equal the naive rule by arithmetic | `model/forecast_head.py` docstring; `evaluate_arbitrage.py` docstring |
| 4 | Naive ladder violations are opportunities | 98.3% are two stale last-trade prints | `diagnose_staleness.py`, `logs/v1_reconstruction/staleness.log` |
| 5 | v1 ladder error was 0.208 against the baselines | Protocol masked both legs of a pair while giving the `partner_price` baseline the true partner price (training's own val pass: 0.026); rewritten to score identical random-subset positions | `evaluate_baselines.py` docstring; `logs/v1_reconstruction/eval_val*.log` → `baselines_*_v2.log` |
| 6 | Ladder gap is a random walk (pooled α ≈ 0.99) | α is dominated by pairs where neither leg trades (gap identical by arithmetic); conditional on a reprice the gap collapses | `diagnose_ladder_conditional.py`, Recess consult §6.2 |
| 7 | MECE PnL used "measured" spreads | Every lookup fell through to a global median from the ladder file; MECE spreads now measured directly | `build_mece_leg_spreads.py` docstring; Recess consult §8 item 2 |
| 8 | `--min-ttc 24` filters markets closing within 24 h | `time_to_close` is in **seconds**; 15.9% of the population was already closed | `CLAUDE.md` gotchas |
| 9 | Model forecasts are worth money (MECE PnL) | **Withdrawn.** 92.5% of apparent deviation is the overround; executable edge is negative before fees | Data-window memo §5; `mece_spread_artefact_check.py` |
