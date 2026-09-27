# Research log

How the project got to its current state, in order: what was done in each
phase, the research documents written at the time, and the code, results and
logs behind them. Document dates are creation dates, so this reads as the
actual chronology of the investigation rather than a tidied-up narrative.

The second half, [Revisions](#revisions), records every conclusion that was
later refined or withdrawn, with the evidence that changed it. Several
documents below were superseded; the tables say so where that happened.

For current state and next steps, read [`CLAUDE.md`](../CLAUDE.md). For every
script, read [`SCRIPTS.md`](SCRIPTS.md). For where each document lives, read
[`REPO-LAYOUT.md`](REPO-LAYOUT.md).

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

## Phase 2 — Detection: does the arbitrage exist? (Aug – 5 Sep 2026)

Detection before modelling. No model is involved in any of this phase.

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

| document | what it establishes |
|---|---|
| [`superseded-findings-summary.md`](superseded-findings-summary.md) | The founding survey. Which no-arbitrage structures exist on Kalshi, how often they are violated, and at what magnitude. **Superseded**; kept as the audit trail (see [Revisions §6](#6-smaller-revisions)) |
| [`planning/direction-b-feasibility-report.md`](planning/direction-b-feasibility-report.md) | The semester's original feasibility report (same text as the [Week 3 report](reports/week03_progress_report.md)): why Direction A's pairs were spurious, the MECE / K-of-N / ladder taxonomy, and the pre-correction empirical checks. Largely superseded; kept for the Direction A rejection, which still stands |
| [`1-detection/taker-side-investigation-notes.md`](1-detection/taker-side-investigation-notes.md) | Early work on `taker_side` semantics. The same field later became the instrument that overturned the profitability claim |

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
98.3% of naive ladder violations were two stale prints compared with each other.

| document | what it establishes |
|---|---|
| [`1-detection/violation-prediction-result.md`](1-detection/violation-prediction-result.md) | Whether violations are predictable at all |
| [`1-detection/ladder-persistence-result.md`](1-detection/ladder-persistence-result.md) | **Superseded** by `ladder-conclusion-overturned.md` |
| [`1-detection/staleness-correction.md`](1-detection/staleness-correction.md) | Stale prices were inflating measured deviations. The same class of error recurs in Phase 5 at basket level |

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
  *Superseded 2026-09-27: inputs leaked. The causal rerun gives 0.909× on test (Revisions §7).*
  Graph ablation: no-graph run loses ~92% of the margin. Ladder-edge ablation:
  no detectable effect.
- **Ladder:** all-pairs ratio is best at initialisation under every mover
  weighting (all / weighted / W=2 / moved-only). Violations revert sharply
  *when a leg reprices*, but repricing timing is not in the features.
- **Trading:** model beats a coin-flip control on identical events and costs;
  every strategy — including idealised static arbitrage — loses net of fees.
  Maker execution helps by ~$29/trade and still loses.

| document | what it establishes |
|---|---|
| [`2-model/stgat-forecasting-redesign.md`](2-model/stgat-forecasting-redesign.md) | Why the task was reframed from classification to residual forecasting, and why the head is zero-initialised |
| [`2-model/architecture-map.md`](2-model/architecture-map.md) | Component-by-component map of the implementation, with a "check it yourself" command per section |
| [`1-detection/mece-test-result.md`](1-detection/mece-test-result.md) | MECE mechanism on the held-out split |
| [`1-detection/ladder-conclusion-overturned.md`](1-detection/ladder-conclusion-overturned.md) | **FINAL on the ladder.** Overturns the random-walk reading, then closes the mechanism anyway for a different and better-identified reason. Records three of its own sub-errors |
| [`2-model/stgat-results-and-limitations.md`](2-model/stgat-results-and-limitations.md) | Consolidated model results. Ladder sections superseded by the above |
| [`2-model/mece-graph-ablation-result.md`](2-model/mece-graph-ablation-result.md) | The graph supplies ~92% of the margin. The strongest architectural finding in the project |
| [`3-economics/mece-pnl-result.md`](3-economics/mece-pnl-result.md) | First round-trip PnL. Negative after costs |
| [`3-economics/pnl-scorecard.md`](3-economics/pnl-scorecard.md) | Every strategy against every baseline, in one table |
| [`3-economics/maker-execution-provisional.md`](3-economics/maker-execution-provisional.md) | Maker execution. **Provisional**: the fee shape is unverified against Kalshi's published schedule |

- Code: `train_forecast.py`, `model/forecast_head.py`, `model/forecast_objective.py`,
  `score_forecast.py`, `evaluate_mece_forecast_pnl.py`, `evaluate_mece_maker_pnl.py`,
  `diagnose_ladder_*.py`, `diagnose_mask_semantics.py`,
  `diagnose_basket_coverage.py`, `diagnose_basket_composition.py`, `verify_pipeline.py`
- Runs: [`runs/v2_*`](../runs/README.md) · Logs: [`logs/v2_forecast/`](../logs/README.md)
- Report: [Recess Week consult](reports/recess_week_consult.pdf) (24 Sep 2026)

## Phase 5 — Settlement, measurement and data window (19–26 Sep 2026)

- **Hold-to-settlement.** Legs must sum to $1 at resolution, so a held
  position captures the deviation deterministically and pays one-way costs
  (`evaluate_mece_settlement_pnl.py`). Its positive backtest did not survive
  the measurement check below.
- **Overround.** Last trade prints are 68.7% ask-side; with a 2.8¢ half-spread
  that *predicts* a +6.3¢ signed mean deviation on a 6-leg basket before any
  mispricing. Measured: +5.25¢, with 92.5% of baskets above $1. At executable
  prices, selling an "overpriced" basket nets −0.07¢ before fees.
  (`examples/mece_spread_artefact_check.py` → `results/mece/mece_spread_artefact_check.parquet`)
- **Measured MECE spreads** replace the ones borrowed from the ladder file
  (`build_mece_leg_spreads.py` → `results/mece/mece_leg_spreads*.parquet`).
- **Usable data window**, prompted by a supervisor's objection that the window
  was too short. Measured fully covered basket-days per month across all 54
  months: proposes 2024-11..2025-11 with 7 expanding walk-forward folds;
  2022-04..2022-11 as a labelled backcast only.
  (`examples/mece_yield_by_month.py`, `examples/sports_categorisation_check.py`)

| document | what it establishes |
|---|---|
| [`3-economics/settlement-arbitrage-result.md`](3-economics/settlement-arbitrage-result.md) | The hold-to-settlement reframe. Wording about "measured per-leg spreads" is corrected by the two documents below |
| [`3-economics/settlement-pnl-robustness.md`](3-economics/settlement-pnl-robustness.md) | Filter sweep, the wrong-spread-table discovery, and a retraction of "the model worsens the profitable rule" |
| [`3-economics/spread-artefact-finding.md`](3-economics/spread-artefact-finding.md) | **The central result.** 92.5% of the deviation is the overround; the executable edge is one tick; the profitability claim is withdrawn |
| [`4-data/mece-population-composition.md`](4-data/mece-population-composition.md) | The opportunity population is ~58% weather and ~24% sports above 5c, across four structurally distinct partition types. Not the 93% weather an earlier window suggested |
| [`4-data/data-window-liquidity-regime.md`](4-data/data-window-liquidity-regime.md) | Platform notional grew 369x across the archive. The binding constraint on the window is liquidity stationarity, not calendar availability |
| [`4-data/mece-yield-by-month.md`](4-data/mece-yield-by-month.md) | Usable basket-days per month across all 54 months. Two dense blocks around a 23-month trough whose apparent deviations are staleness |
| [`2-model/split-design-correction.md`](2-model/split-design-correction.md) | Corrects a proposed split that tested on data earlier than the training window |

- Report: [data-window memo](reports/data_window_memo.tex) (26 Sep 2026)
- Commit: `65a6063` "STGAT Implementation and Methodology Checks 260926"

## Phase 6 — Positioning and planning (Sep 2026)

| document | what it establishes |
|---|---|
| [`5-literature/literature-mece-positioning.md`](5-literature/literature-mece-positioning.md) | Three papers cover sum-to-one arbitrage; all are detection-only. The forecasting question appears unasked |
| [`5-literature/literature-ladder-positioning.md`](5-literature/literature-ladder-positioning.md) | Same for the ladder mechanism |
| [`5-literature/literature-sample-periods.md`](5-literature/literature-sample-periods.md) | Sample periods of the nearest work. Only one of three treats sum-to-one as a primary object; its window is 12 months |
| [`5-literature/literature-architecture-positioning.md`](5-literature/literature-architecture-positioning.md) | Where the architecture sits, and the citation licensing each departure from the paper it adapts |
| [`planning/four-week-plan-and-reframe.md`](planning/four-week-plan-and-reframe.md) | Current plan. v2; v1 was built around the withdrawn PnL headline |

**Now:** awaiting supervisor response to the Recess consult and the memo.
Open items are listed in priority order in [`CLAUDE.md`](../CLAUDE.md).

---

## Revisions

Every claim this project made and later refined or withdrew, with the
evidence that changed it. Kept because a result that was never wrong was
probably never tested hard enough, and because the reasoning that caught each
error is part of the method.

Ordered by significance, not by date.

### 1. The profitability claim (withdrawn 2026-09-26)

**Claimed:** a hold-to-settlement strategy gated on `|deviation| > cost` was
profitable, at +$292 to +$663 depending on configuration, on 4,891
fully-covered basket-days.

**Withdrawn because:** the deviation was measured from *mixed last trade
prints*. A last trade sits at the bid or the ask, never the mid. Kalshi
trades carry `taker_side`, and 68.7% of prints are ask-side. With a
half-spread near 2.8c that predicts a signed mean deviation of +6.3c on a
six-leg basket from order-flow imbalance alone.

**The prediction was recorded before the measurement. Measured: +5.25c, with
92.5% of baskets summing above $1** — the classic betting-market overround,
where a genuine mispricing population would be balanced either side of $1.

Pricing each leg on its own side, restricted to baskets whose legs printed
within an hour of each other:

| | |
|---|---|
| buy every leg at the ask | $1.1334 |
| sell every leg at the bid | $0.9993 |
| settlement pays | $1.0000 |

Selling the apparent overpricing nets −0.07c gross before fees; Kalshi's
taker fee on a six-leg basket is 1.3c to 5.8c. Restricting to the
large-deviation tail makes it worse, not better: the share of baskets with a
positive executable edge falls from 84% to 54%, because a large apparent
deviation is *produced by* a wide spread and wide-spread baskets execute
worse.

**What survives:** the forecasting results, which concern price accuracy
rather than realised trading, and the model-versus-control comparison, which
is a paired test on identical baskets and is provably invariant to the cost
model.

→ [`3-economics/spread-artefact-finding.md`](3-economics/spread-artefact-finding.md)

### 2. The ladder conclusion, overturned then closed (2026-09-19; closure stale, see §7)

**Claimed:** ladder violations follow a near-random walk (pooled alpha ~0.99),
so there is little to forecast.

**Overturned because:** the pooled alpha was measuring *untradedness*. A pair
where neither leg reprices has `gap(t+h) == gap(t)` exactly — verified, max
drift 0.000000 — and contributes alpha = 1 by arithmetic, not economics.
With 85-90% of pair-snapshots frozen, the pooled figure is dominated by
observations that contain no information.

Conditioning on a reprice: a +18.5c violation collapses to +0.07c. Eighteen
cells across two splits and three horizons agree.

**Then closed anyway, for a different reason.** The all-pairs ratio is
minimised at epoch 0 (1.0015) and rises monotonically under every mover
weight tested; as the weight goes to zero it approaches 1.0 *from above*.
There is no weight at which it crosses. Whether a pair will reprice is not
in the features, so learned reversion is applied indiscriminately and costs
~4 units of error on unmoved pairs per unit gained on moved ones.

**Three sub-errors recorded in the same document:** a constraint-geometry
argument the data contradicted; a "not deployable" claim that was right for
the wrong reason; and a weighted-reporting bug that applied the mover weight
to the reported metric as well as the loss, tripling the persistence
baseline and making a 1.070x result read as 0.996x.

→ [`1-detection/ladder-conclusion-overturned.md`](1-detection/ladder-conclusion-overturned.md)

### 3. The split design was backwards for a forecasting task (2026-09-26)

**Proposed:** train on 2024-11 to 2025-11, hold out 2022-04 to 2022-11 as a
second test set, on the grounds that it is a thinner market and an earlier
ticker generation.

**Wrong because:** the held-out period is 26 months *earlier* than the
training data. For a model whose stated task is predicting future values,
that is a backcast presented as a test set. It breaks the thing an
out-of-sample evaluation exists to establish.

**Replaced with:** expanding-window walk-forward inside a single liquidity
regime, seven folds, each training only on its own past. The 2022 block is
retained only as an explicitly labelled backcast.

→ [`2-model/split-design-correction.md`](2-model/split-design-correction.md)

### 4. The cost model was silently the wrong one (2026-09-26)

The `--spreads` argument defaulted to the *ladder* results file, whose own
docstring states it contains only crypto and financials pairs. MECE baskets
are ~58% weather and ~24% sports at a 5c threshold, so **not one leg was in
that table**. Every lookup missed on ticker and on series and fell through to
a global median borrowed from a different mechanism, while runs were
described as using "measured per-leg spreads".

The run printed `spread sources: global=27,092`, which was accurate and easy
to read past.

**Fixed, and guarded.** The sources line now carries
`[x% measured per-leg, y% fallback]` and prints a banner below 50% measured
that names the file and refuses the "measured spreads" wording. Once wired
correctly, measured spreads turned out to be ~26% *wider* than the borrowed
median, not narrower.

**Consequence for an earlier finding:** a result recorded as "the model
significantly worsens the profitable rule" (−0.27, CI excluding zero) was an
artefact of costing weather baskets with crypto spreads. With the correct
cost model it is a clean null at four settings, within ±0.03 of zero.

→ [`3-economics/settlement-pnl-robustness.md`](3-economics/settlement-pnl-robustness.md)

### 5. A filter that constrained the wrong quantity (2026-09-26)

A gap limit intended to force a basket's legs to be contemporaneous in fact
constrained each leg's *own* ask and bid prints, not the legs relative to
*each other*. The median cross-leg span is **406 minutes**, so tightening the
within-leg limit did nothing to clean the estimate, and a mid built from
whole-day means stayed larger than the last-trade figure — which no unbiased
mid can be.

Two further sub-errors in the same script: a verdict branch that could not
express "the mid estimate is worse than the last-trade one" and printed
nonsense when it happened, and a test that read a mean-based mid no span
limit can clean, because the span constrains print *times* while the mean
averages the whole day.

All three are fixed, and the fix carries a self-test that plants two legs
three hours apart and proves the old limit accepts them.

### 6. Smaller revisions

| claim | revision |
|---|---|
| Pairs trading works (Sharpe 5.52, Oct 2025) | Selected pairs were economically unrelated: multiple testing over tens of thousands of candidates. Direction A abandoned (Week 3 report §2) |
| Markets-file quotes can test the basket constraint | The file holds one static row per ticker per month; all checks moved to trade prints (Week 3 report §4.1) |
| Constrained output heads enforce no-arbitrage usefully | A head whose MECE legs sum to $1 makes the model's basket deviation equal the naive rule's by arithmetic; replaced by the residual head (`model/forecast_head.py`) |
| Naive ladder violations are opportunities | 98.3% are two stale last-trade prints compared with each other ([`staleness-correction.md`](1-detection/staleness-correction.md), `logs/v1_reconstruction/staleness.log`) |
| v1 ladder error was 0.208 against the baselines | The protocol masked both legs of a pair while giving the `partner_price` baseline the true partner price (training's own val pass: 0.026); rewritten to score identical random-subset positions (`evaluate_baselines.py`) |
| Sports markets would extend the MECE window backwards | Sports first appears 2024-12, *later* than weather, so it cannot. Kalshi could not list sporting event contracts until the regulatory position shifted in late 2024 |
| 267 fully-covered basket snapshots on 2025-10/11 | Stale. Predates the `FAMILY_RE` fix and the `MAX_LEGS` 60→100 change. The current figure is ~618 for that window |
| The hourly snapshot grid means ~8x more effective data than basket-days suggest | Wrong in the sense that matters. Consecutive hourly snapshots of one basket are overwhelmingly frozen; the effective independent sample is near the basket-day count |
| `--min-ttc 24` would exclude the last 24 hours | `TIME_TO_CLOSE` is in **seconds**. It was a 24-second bar. It nonetheless revealed that 15.9% of the evaluated population sat at `ttc == 0` — markets already past their close, which cannot be traded at all |
| Per-leg costing would improve measured PnL | It reduced it, twice. Both times the error was reasoning from a *median* spread where basket cost is a *sum* over legs, so the mean governs and the distribution is right-skewed |
| `14+ leg families never achieve full coverage` | Holds only for the original two-month window. `KXF1RACE` (20 legs) and `KXNASCARRACE` (41 legs) achieve it on May–Sep |

### 7. The headline forecast was leaky; causal rerun replaces it (2026-09-27)

The 0.851x / 0.853x came from `v2_mece`, whose inputs leaked in four ways:
- resolved markets were replayed after close;
- `time_to_close` carried after-the-fact close times;
- ladder edge features leaked;
- MECE membership was selected with hindsight, using the event's own outcome.

It was also scored on partial baskets. A first rerun (`v2_mece_clean_s*`) fixed
only the first two. It was stopped before scoring and is not cited.

The causal rerun (`v2_mece_causal_s0..s3`) was pre-registered before any result
(`runs/README.md`). It has every fix in force and uses causal membership in
val/test and the `whole_settle` scoring rule. Test was scored once per seed.

| | val | test |
|---|---|---|
| model / oracle, mean (range) | 0.823x (0.813–0.834) | **0.909x (0.883–0.941)** |
| model / persistence, mean | 0.577x | 0.613x |
| oracle alpha | 0.556 | 0.552 |

All four seeds beat the oracle, but the margin is ~9%, not ~15%. The
same checkpoints scored under the old partial-basket rule are 1.21–1.66x (not
used for any choice). The whole-basket target is far more mean-reverting
(alpha 0.55 against 0.92 before), which helps both the model and the oracle.

Figures computed on `v2_mece` are now stale: the graph ablation (~92%) and the
model-vs-control PnL (+$0.170/trade). They need re-running on the causal
checkpoints before they can be cited.

**The ladder closure (Revision 2) is stale for the same reason.** On the old
cache at h=1, 85,222 of 150,697 scored ladder pairs (57%) came from contracts
that live 1.5h or less. The 2h grid never saw them live. They appeared only as
replays after close: 583 pairs, 0% ever moved, and 66% of all scored pairs had
a leg already closed by t+h. Persistence is exact on those pairs, so the
all-pairs ratio could only be minimised by doing nothing. That is the
"minimised at epoch 0" result. On `cache_causal/` the past-close share is 0%
and the sub-1.5h class is gone. What remains (50,991 pairs) is essentially the
old live-only subset (51,278). Evidence: `logs/v2_forecast/ladder_timing.log`
vs `ladder_timing_causal.log` (train/val months only).

On test, the causal MECE checkpoints score 0.982–0.993x the ladder shrinkage
oracle (alpha 0.942, was 0.990) and 0.966–0.977x persistence, n = 99,646. They
were trained with ladder weight 0 and ladder edge features zeroed, and selected
on MECE. On moved pairs the range is 0.991–1.004x. This is **exploratory**:
not pre-registered, no val counterpart (ladder val metrics are NaN at weight
0), no CI. It retracts the negative closure; it does not establish a positive
ladder result. Reprice timing is still absent from the features (hidden
leg-age AUC 0.83 at h=1).

Forecasting ladders that live under 2h would need a sub-2h grid, a new pipeline.
It is recorded as a limitation, not pursued.

**Bid-side re-score (pre-registered, 2026-09-27).** The 0.909x does not
survive as a claim about traded-price dislocation:
- On test, all of the 0.909x comes from the 18.6% of positions whose basket
  settles by t+h, where the target is exactly $1. On unsettled positions the
  model scores 1.034x (1.006–1.057; post-hoc decomposition, disclosed), and
  every pooled test CI includes 1.0.
- On the bid-side target (unsettled, R = 1h) it scores 1.465x (1.42–1.54),
  with every CI excluding 1.0. That is on a thin sample: 117 positions, 56
  baskets, because bid prints are sparse.
- I predicted 0.97–1.03x; the result was worse.
- Headline: forecasts basket microstructure and settlement convergence.
Full tables: `runs/README.md`.

### 8. Still open

- ~~Settlement leak?~~ **Checked 2026-09-27, val s0 only: no leak found.**
  - Scrambling every snapshot after t0 leaves predictions at t <= t0
    bit-identical, and randomising slot 8 changes nothing.
  - Within a horizon, the model's pull toward $1 rises *smoothly* as close
    approaches (h=12: 0.93 within 26h, 0.88 at 26–52h where the basket does
    *not* settle, 0.52 beyond 72h). There is no jump at the settlement
    boundary.
  - The highest leg price does not explain the pull.
  - Reading: the model learned that short-lived basket families converge to
    $1, which is visible ex ante. A shrinkage oracle fitted per series x
    horizon absorbs about half the val margin (0.817x -> 0.920x; unsettled
    0.861x -> 0.929x).
  - Open: re-score test against that stronger oracle, and retrain with settled
    positions excluded from the MECE loss (both to be pre-registered).
- The graph ablation and model-vs-control result must be re-run on
  `v2_mece_causal_s*` (see revision 7).
- Ladder on the causal cache: a val figure and a bootstrap CI would be needed
  before the 0.98x is more than exploratory. `score_forecast.py` still prints
  a hardcoded "ladder alpha ~0.99" paragraph that the causal numbers contradict.
- `KXCLUBWCGAME` may not be a genuine partition: one snapshot shows sum $1.89
  with 369 trades on the thinnest leg at a 0.02h gap, which is not credible
  as a standing arbitrage. Knockout ties plausibly resolve "tie" and "winner"
  on different bases. Not present in the validation split, so it has not
  affected any reported figure, but the leg rules need checking.
- Kalshi's maker fee shape (flat per contract versus the taker's `p(1-p)`
  form at a quarter rate) has not been verified against the published
  schedule. All maker results are marked provisional.
