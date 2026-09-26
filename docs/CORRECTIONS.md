# Corrections

Every claim this project made and later withdrew, with the evidence that
overturned it. Kept because a result that was never wrong was probably never
tested hard enough, and because the reasoning that caught each error is part
of the method.

Ordered by severity, not by date.

---

## 1. The profitability claim (withdrawn 2026-09-26)

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

→ `docs/3-economics/spread-artefact-finding.md`

## 2. The ladder conclusion, overturned then closed (2026-09-19)

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

→ `docs/1-detection/ladder-conclusion-overturned.md`

## 3. The split design was backwards for a forecasting task (2026-09-26)

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

→ `docs/2-model/split-design-correction.md`

## 4. The cost model was silently the wrong one (2026-09-26)

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

→ `docs/3-economics/settlement-pnl-robustness.md`

## 5. A filter that constrained the wrong quantity (2026-09-26)

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

## 6. Smaller corrections

| claim | correction |
|---|---|
| Sports markets would extend the MECE window backwards | Sports first appears 2024-12, *later* than weather, so it cannot. Kalshi could not list sporting event contracts until the regulatory position shifted in late 2024 |
| 267 fully-covered basket snapshots on 2025-10/11 | Stale. Predates the `FAMILY_RE` fix and the `MAX_LEGS` 60→100 change. The current figure is ~618 for that window |
| The hourly snapshot grid means ~8x more effective data than basket-days suggest | Wrong in the sense that matters. Consecutive hourly snapshots of one basket are overwhelmingly frozen; the effective independent sample is near the basket-day count |
| `--min-ttc 24` would exclude the last 24 hours | `TIME_TO_CLOSE` is in **seconds**. It was a 24-second bar. It nonetheless revealed that 15.9% of the evaluated population sat at `ttc == 0` — markets already past their close, which cannot be traded at all |
| Per-leg costing would improve measured PnL | It reduced it, twice. Both times the error was reasoning from a *median* spread where basket cost is a *sum* over legs, so the mean governs and the distribution is right-skewed |
| `14+ leg families never achieve full coverage` | Holds only for the original two-month window. `KXF1RACE` (20 legs) and `KXNASCARRACE` (41 legs) achieve it on May–Sep |

## 7. Still open

- The primary forecasting result (0.851x against the shrinkage oracle) is on
  the **basket aggregate** metric, which is the quantity now known to be
  ~92.5% overround. The node-level figure is 0.991x. Re-scoring against
  bid-side basket sums will determine whether the economic label survives.
  Until then the result is stated as forecasting accuracy, not as arbitrage
  detection.
- `KXCLUBWCGAME` may not be a genuine partition: one snapshot shows sum $1.89
  with 369 trades on the thinnest leg at a 0.02h gap, which is not credible
  as a standing arbitrage. Knockout ties plausibly resolve "tie" and "winner"
  on different bases. Not present in the validation split, so it has not
  affected any reported figure, but the leg rules need checking.
- Kalshi's maker fee shape (flat per contract versus the taker's `p(1-p)`
  form at a quarter rate) has not been verified against the published
  schedule. All maker results are marked provisional.
