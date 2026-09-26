# Maker execution: control passed, profitability did not generalise

**Status: the control result stands and is the project's headline; the maker route
itself is CLOSED, below the cut line.** Supersedes two earlier versions. The second
revision stated that the no-model reversion rule "loses in both" configurations —
true but misleading, and corrected below: in the realistic configuration the model
loses to it, significantly.

> **Why the maker route is closed** (three independent reasons, none of them
> available when this was written):
>
> 1. **The fee shape was never verified.** Kalshi's maker rate is quoted at 0.0175
>    but no run confirmed the formula against the published schedule.
> 2. **There is no fill model with adverse selection.** `net_flow × side < 0` derives
>    fills from order flow, which is better than assuming them, but it does not model
>    being filled *because* the price is about to move against you.
> 3. **The decisive one.** If the apparent dislocation *is* the bid/ask overround —
>    and ~92.5% of it is (`spread-artefact-finding.md`) — then earning the spread
>    instead of paying it does not harvest a dislocation, it makes you the market
>    maker. That is a different business whose central risk is the one item 2 does not
>    model. The $29/trade in Result 3 is real as an *execution* saving and is not a
>    path to profit.
>
> **What survives intact: Result 1.** It is a paired comparison on identical events
> at identical cost, so the spread term cancels exactly and the finding is invariant
> to everything the cost work later changed.

## The two configurations

Test split, h=1, same 2,366 model signals, flow fill model.

**all_or_nothing** — trade only when every leg fills at the posted price:

| row | trades | baskets | win% | net/trade | 95% CI |
|---|---|---|---|---|---|
| maker_taker (model) | 99 | 89 | 73.7% | **+$2.98** | [1.13, 5.21] |
| mk_tk[random] | 108 | 63 | 46.3% | −$0.97 | [−2.28, 1.39] |
| mk_tk[revert] | 585 | 165 | 45.1% | −$2.77 | [−3.32, −2.10] |

**cross_remainder** — also trade the 68.9% that fill partially:

| row | trades | baskets | win% | net/trade | 95% CI |
|---|---|---|---|---|---|
| maker_taker (model) | 1,729 | 295 | 56.0% | **−$18.39** | [−19.28, −17.40] |
| mk_tk[random] | 1,726 | 273 | 39.0% | −$20.89 | [−22.24, −19.49] |
| mk_tk[revert] | 4,509 | 341 | 38.2% | −$14.59 | [−15.36, −13.78] |

Basket counts are healthy throughout (63–341), so the cluster bootstrap
has enough independent units and the intervals can be trusted.

## Result 1: the causal control passed, twice

`mk_tk[random]` uses the identical entry gate, identical fill filter and
identical execution — only the direction differs. The gap, with its own
bootstrap interval:

| configuration | model − coin flip | 95% CI |
|---|---|---|
| all_or_nothing (n=99) | **+$3.95** | [+1.99, +5.93] |
| cross_remainder (n=1,729) | **+$2.50** | [+0.72, +4.21] |

Both exclude zero, across a 17× change in sample size. **The STGAT's
direction is worth $2.50–$4.00 per trade over a coin flip executed
identically.** This is the defensible forecasting claim.

> **Why this is the one result that survived the spread finding, stated so it can go
> straight into the thesis.** The spread cost of an event is
> `sum(leg spreads) × multiplier × C` — it depends only on which tickers are in the
> basket and how large the trade is, both of which are **fixed per event** and
> identical between the two arms. So the cost term subtracts out exactly, and the gap
> is a pure function of the direction decision. Measured identically under three
> different cost models, which is the empirical confirmation of the algebra. It is
> therefore **provably cost-model invariant** — the strongest claim available about
> any number in this project.
>
> The consolidated figure across the full population, under the correct
> hold-to-settlement structure and with the cluster bootstrap by basket, is
> **+$0.170/trade, CI [+0.107, +0.247]**. Prefer that over the $2.50–$4.00 above: it
> is smaller, better identified, on more events, and on the trade structure the
> project actually recommends. Quote `k`, the cluster count, alongside it.
>
> One honest qualification. The direction being forecast is the direction of the next
> move in the basket sum of last trade prints, which is ~92.5% microstructural. The
> comparison is valid; what it demonstrates is skill at forecasting the partition's
> joint short-run dynamics, not skill at finding mispricing. State it that way.

## Result 2: against a real alternative strategy, it depends on the configuration

`mk_tk[revert]` is *not* a same-gate control — it has its own entry rule
and its own trade set. It is a competing strategy.

| configuration | model − reversion | 95% CI | |
|---|---|---|---|
| all_or_nothing | +$5.75 | [+4.12, +7.59] | model better |
| cross_remainder | **−$3.80** | [−5.04, −2.58] | **model significantly WORSE** |

In the realistic configuration a one-line rule beats the model.

*Because the two strategies trade different baskets at different sizes, this
comparison is **not** cost-invariant — unlike Result 1 — so it is conditional on the
cost model, which at the time was the borrowed ladder median. Under measured MECE
spreads the equivalent comparison (model-timed gate vs cost gate, four
configurations) gives a mean point estimate of −0.005 with the best-powered test at
+0.005, CI [−0.065, +0.093]. That is a **well-powered null** rather than a loss, and
it is the figure to report. See `settlement-arbitrage-result.md` §4.*

## Why: the model's signal and its trading cost are correlated

| | model | reversion | ratio |
|---|---|---|---|
| gross edge / trade | $3.55 | $1.12 | **3.2× better** |
| cost / trade | $21.95 | $15.72 | **40% more expensive** |
| net / trade | −$18.39 | −$14.59 | |

The signal is not the problem — it is more than three times stronger. The
trades are the problem. The model's signal advantage ($2.43) is smaller
than its cost disadvantage ($6.23).

The mechanism is structural. The entry gate fires on |delta_pred| > 1c,
and a basket with more legs has more room for its sum to deviate, so large
predicted dislocations concentrate in large baskets — signalled baskets
average 5.04 legs against 3.89 overall. Fees and spread crossings both
scale with leg count. **Signal strength and execution cost share a common
cause, so selecting on the first selects for the second.**

> **This diagnosis was correct and it turned out to be deeper than stated.** The
> common cause is not only leg count. Apparent deviation is *produced by* the spread
> — each leg's last print sits `h(2p−1)` above mid, so deviation grows with both the
> number of legs and the width of each leg's spread. Selecting on large apparent
> deviation therefore selects for **wide-spread** baskets specifically, which is why
> a cost gate makes executable selection *worse*: the share of gated baskets with a
> positive executable edge falls from **84% to 54%**. The correlation identified here
> is not a fixable trade-selection problem; it is the signal and the cost being
> partly the same quantity.
>
> That is also why `mece-population-composition.md` finds `|dev|/N` peaking at six
> legs in the families with the widest per-leg spreads (weather, approval), and why
> §3 of that document now carries a caveat against reading its table as a pure
> mispricing gradient.

## Result 3: maker execution is worth ~$29/trade

Holding signals fixed and changing only execution: −$30.59 → −$1.15 per
trade. Fees fall from $6.76 to $4.08; spreads go from −$26.76 to $0
because a posted entry earns half the spread and a crossed exit pays it
back. Mechanical, model-free, consistent with Whelan's maker/taker gap.

Still loses money.

*Real as an execution accounting fact, and worth one sentence in the economics
chapter as the magnitude of the maker/taker asymmetry on this venue. Not a route to
profit — see the header. And note the construction caveat below: the spread nets to
exactly $0 by design, so this figure is the size of the spread bill, not an estimate
of what a maker would actually earn.*

## Why the +$2.98 is not the headline

It exists only in the 4.2% of signals where every leg fills. The
composition profile shows what that filter selected:

| | all | filled | change |
|---|---|---|---|
| mean \|delta_pred\| | 0.0327 | 0.0349 | **+7%** |
| mean \|delta_real\| | 0.0458 | 0.0635 | **+39%** |
| legs/basket | 5.04 | 3.66 | −27% |
| mean leg price | 22.95c | 32.07c | +40% |

Prediction magnitude barely moves; the realised move jumps 39%. The filter
selects volatile periods and smaller, cheaper-to-trade baskets — not
signals the model was more confident about. Add 99 trades across five
months and the capacity is negligible.

*This self-audit is worth keeping as a template. The +$2.98 was the most attractive
number the project produced at the time and it was dismantled by the author rather
than by a reviewer, using a composition table that cost minutes to build. The same
move — profile what a filter selected on, not just what it produced — is what later
caught the cost gate being anti-selective.*

## What to report

1. **Forecasting:** 0.853× the shrinkage oracle on held-out test (val
   0.851×), incremental gain over the oracle stable at ~14.8%, with the graph
   ablation attributing ~92% of that margin to the graph.
2. **Direction, controlled:** **+$0.170/trade, CI [+0.107, +0.247]**,
   cluster-bootstrapped by basket, identical under three cost models and
   provably cost-model invariant. *(The +$2.50–$4.00 above is the round-trip-era
   figure on smaller samples.)*
3. **Execution:** maker worth $29.44/trade over taker, as an accounting fact about
   the spread bill. Not pursued as a strategy.
4. **Profitability:** negative in every configuration, and the reason is not
   capacity or fees but the target itself — ~92.5% of apparent basket deviation is
   bid/ask overround, and the executable edge is **−0.07¢** before a 1.3–5.8¢ taker
   fee. Against the cost gate the model is a well-powered null; the gate is itself
   unprofitable.

Point 4 is the honest answer to "must the model beat baseline PnL": against
the causal control, yes, invariantly; against a competing strategy, a measured null;
and there is no PnL for either to compete over.

## Methodological notes

- `_gap_bootstrap` resamples baskets once per replicate and applies the
  draw to both books. Verified at 94% coverage under the null, 100% power
  at a true +$2 gap. **This is why the model-vs-control CI is valid despite hourly
  autocorrelation** — the resampling unit is the basket, not the snapshot.
- **Bug found and fixed:** the gap verdict was one-sided and printed a
  significantly negative gap ([−5.04, −2.58]) as "INCLUDES 0". The
  intervals in the logs are correct; only the verdict text was wrong. Same
  class of error as the one-sided bootstrap verdict in
  `evaluate_violation_prediction.py`.
- CIs are clustered on baskets; below ~10 baskets a cluster bootstrap
  collapses rather than widens, so basket counts are printed per row. **Print `k`
  with every CI**, not only when it looks small.
- maker_taker's spread nets to $0 *by construction* — one static per-leg
  spread on both sides. Exit slippage is unmodelled.
- The cost model used here is the **borrowed ladder median**, because `--spreads`
  defaulted to the ladder results file and no MECE leg matched it. Measured MECE
  per-leg spreads are 4.68¢ (windowed) / 5.61¢ (pooled) against the borrowed 6.9¢,
  so this run over-costed itself. Conclusions unaffected; the levels are not the
  best available.

## Do NOT act on the cost-concentration finding using test data

Gating on predicted-dislocation-per-unit-cost is the obvious fix and would
plausibly work. The expected cost is computable ex ante from Kalshi's
published fee schedule and the leg count, so the rule itself needs no test
data — but the *hypothesis* came from looking at test results, so fitting
and selecting it must happen on val, and any further test reading must be
disclosed as a second look.

> **Moot, and instructively so.** The fix was implemented as the cost gate in
> `evaluate_mece_settlement_pnl.py` and it did produce a positive backtest. At
> executable quotes it makes selection **worse** (84% → 54% positive), because the
> quantity it gates on is manufactured by the spread it is trying to clear. "Would
> plausibly work" was the right prior on the information available; the discipline
> note was also right and was followed. Both can be true.
