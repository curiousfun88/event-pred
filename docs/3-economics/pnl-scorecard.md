# PnL scorecard: does the model beat predictive baselines?

Test split, h=1, 7,035 basket-snapshots, 345 baskets. Every comparison is a
**difference** with its own bootstrap interval, clustered on baskets.

> **Scope, added later.** This document evaluates the **round trip** (enter at `t`,
> exit at `t+h`), which pays fees and crosses the spread twice on every leg. That
> structure is arithmetically hopeless and was replaced by hold-to-settlement
> (`settlement-arbitrage-result.md`). Two things to carry forward from here and two
> to discard:
>
> **Carry forward:** the model-vs-random comparison, which is paired on identical
> events at identical cost and therefore survives everything found later; and the
> liquidity sweep in §2, which is a real property of the population.
>
> **Discard:** any reading of the *gross* edge as a mispricing edge. Gross is
> `|dev|`-based and ~92.5% of `|dev|` is bid/ask overround
> (`spread-artefact-finding.md`). The consolidated model-vs-control figure under the
> correct structure is **+$0.170/trade, CI [+0.107, +0.247]**.

Three sizing regimes are reported. A participation cap at X% of the
thinnest leg-side's window volume removes the thinnest baskets entirely, so
**a tighter cap leaves a more liquid surviving population**. That turns the
sensitivity check into a liquidity sweep, which is where the real finding
is.

## The three regimes

| | uncapped | cap 25% | cap 10% |
|---|---|---|---|
| events dropped below 1 contract | 0% | 24.4% | **45.7%** |
| median achievable size | 100 | 2.5 | 1.0 |
| p90 achievable size | 100 | 33.8 | 13.5 |
| reached full size | 100% | 4.7% | 2.7% |

**model − baseline, net $/trade (with 95% CI)**

| baseline | uncapped | cap 25% | cap 10% |
|---|---|---|---|
| **random** (causal control) | **+2.92** [2.27, 3.64] | **+0.75** [0.53, 1.03] | **+0.67** [0.43, 1.00] |
| **oracle_shrink** | **+1.72** [1.14, 2.37] | **−0.53** [−0.92, −0.06] | **−0.70** [−1.04, −0.35] |
| always_revert | −2.52 [−3.11, −1.89] | −1.26 [−2.00, −0.57] | −0.84 [−1.38, −0.33] |
| static_arb | −21.49 | −4.10 | −2.84 |

**Which rows are cost-invariant.** Only `random` shares the model's exact trade
set, so only that row's spread term cancels. `oracle_shrink`, `always_revert` and
`static_arb` each have their own entry gate and therefore their own baskets, sizes
and spread bills — those differences are exposed to the cost model and should be
read as conditional on it. Say which is which when reporting; this document did not
originally distinguish them.

## The finding: two monotone trends in opposite directions

Normalising to a **per-contract** edge (cost/trade is exactly linear in
size, so mean size is recoverable from the cost column):

| regime | mean size | model − random | model − oracle |
|---|---|---|---|
| uncapped | 100.0 | +0.0291 | **+0.0087** |
| cap 25% | 19.0 | +0.0395 | **+0.0009** |
| cap 10% | 13.4 | **+0.0500** | **−0.0050** |

> **vs the coin flip: +0.0291 → +0.0395 → +0.0500.** The model's
> directional edge *grows* as the population gets more liquid.
>
> **vs scalar shrinkage: +0.0087 → +0.0009 → −0.0050.** Its advantage over
> a single α *shrinks* monotonically and crosses zero at about the 25%
> threshold.

Both are true simultaneously and the combination is interpretable: **in
liquid baskets, mean reversion is the dominant dynamic.** The model
captures it, which is why it beats a coin flip by more there. But a single
α captures it too — so the model adds nothing beyond the scalar. Where
liquidity is thin, reversion is noisy, the scalar does badly, and the
model's richer signal helps. That is also where the position cannot be
filled.

The sensitivity check **confirmed** the flip rather than refuting it, and
the monotonicity across three regimes makes it a property of liquidity
rather than of a chosen threshold.

**An alternative reading of the same sweep, available only in hindsight and worth
putting in the thesis alongside the one above.** Thin baskets have wide spreads, and
wide spreads are what manufacture large apparent deviation. So "the model's edge
over the scalar lives in thin baskets" and "apparent deviation in thin baskets is
mostly overround" are the same observation from two directions. Under that reading
the oracle-crossing is not only a liquidity effect but partly a *signal-quality*
effect: where the model out-predicts the scalar, more of what it is predicting is
microstructure. The bid-side re-score is what separates the two readings; until it
is run, present the liquidity reading as primary and this one as the open
alternative.

## One caution on reading net/trade

At the 25% cap the per-contract gap versus the oracle is +0.0009 —
essentially a tie — while the net/trade gap is −$0.53. The difference is
that the model trades **larger** sizes (19.0 vs 16.6), and when
per-contract economics are negative, trading bigger simply loses more.

That is the abstention problem in another guise: among loss-making
strategies, the one that trades less looks better without being better.
**Per-contract is the cleaner measure of signal quality; net/trade is the
decision-relevant one.** Report both and say which is which.

## What survives, and what does not

**Survives — the causal claim, strengthened.** `random` uses the identical
entry rule, identical cap and identical execution, direction thrown away.
The model beats it in **all three** regimes, every CI excluding zero, and
the per-contract advantage **grows** as sizing becomes realistic.

*This is the result that survived everything. The reason is now provable rather
than just plausible: the spread cost is `sum(leg spreads) × multiplier × C`,
depending only on the tickers and the size, both fixed per event — so it cancels
**exactly** in a paired comparison. The gap is identical across three cost models.
It is the strongest number in the project.*

**Survives — the forecasting result.** 0.853× the shrinkage oracle on
held-out test MSE. Forecast accuracy; sizing does not bear on it.

*With one qualification: the metric is the basket sum of last trade prints, whose
deviation is ~92.5% overround, so what the 0.853× is a 0.853× **at** is the open
question. See `mece-graph-ablation-result.md` §5.*

**Does not survive — "beats the oracle on PnL."** At any realistic size the
model loses to simple α-shrinkage, confirmed at two thresholds.

The honest combined statement:

> The model **forecasts** basket dislocation better than an optimal
> shrinkage oracle (0.853× on held-out MSE), but does not **trade** better
> than it once execution size is constrained. Its forecasting advantage is
> concentrated in baskets too illiquid to fill, and in the liquid baskets
> where trading is possible a single mean-reversion coefficient matches it.

*Add, per the later work: and in any case neither trades profitably, because at
executable quotes the apparent dislocation is the spread.*

## An earlier claim in this doc was wrong

A previous version stated that capping size scales every dollar figure but
leaves ratios untouched, because all costs are linear in size. **True per
event, false across strategies.** The cap is computed per basket,
strategies trade different baskets, and up to 45.7% of events drop out — so
each strategy ends with a different mean size and a different surviving
population.

*This is the same distinction as the "which rows are cost-invariant" note above,
and it is worth stating once as a general rule: **a cost term cancels only between
strategies that trade the same events at the same size.** Everything else is a
comparison conditional on the cost model.*

## Caveats

- `window_volume` is a **weak proxy for depth**: two hours of turnover, not
  size resting at the touch. Likely optimistic even after capping.
- Kalshi does not retain historical order-book state, so a true depth
  analysis is impossible retrospectively (see
  `stgat-results-and-limitations.md` §8).
- **Every strategy loses money in every regime.** Ranking losers by who
  loses least is weak ground — not trading scores $0 and beats every row.
  The defensible claim is the controlled one: the model's direction beats a
  coin flip through identical machinery, at every sizing tested.
- **Print the cluster count `k` alongside every CI.** Below ~10 baskets a cluster
  bootstrap collapses rather than widening. All rows here have 345 or fewer
  baskets and the counts are healthy, but the guard belongs in the output.
- The gross-edge column is not a mispricing edge. See the header.
