# Hold-to-settlement PnL: a positive backtest, and why it is not real

**Status: the profitability claim is WITHDRAWN.** The hold-to-settlement
structure and the cost gate are correct as *mechanics*, and the model-null in
§4 stands. But the quantity being gated — last-trade deviation from $1 — was
later measured to be ~92.5% bid/ask overround rather than mispricing
(`spread-artefact-finding.md`). The net figures below are therefore
**backtest artefacts at last-trade prices, not executable profit**, and §6
and §7 have been corrected accordingly. Extends `pnl-scorecard.md`, which
evaluated only the round trip.

## 1. What changed

Every earlier PnL result evaluated a **round trip**: enter at `t`, exit at
`t+h`. That pays fees and crosses the spread twice on every leg, and the
arithmetic forbids it (break-even 33.5¢ against a 2.26¢ mean move).

`evaluate_mece_settlement_pnl.py` evaluates the **hold-to-settlement**
structure instead. The legs must sum to $1 at resolution, so a position held
to settlement captures `|dev(t)|` deterministically and pays **one-way**
costs. That single change is worth about $21/trade — more than every
modelling decision in this project combined.

This reasoning is sound but load-bearing on one assumption that turned out to
be false: that `dev(t)` measured at last trade prints is a price you could
have transacted at. It is not — see §6.

## 2. The rule, and what its numbers are worth

Cost gate = enter only when `|dev(t)|·C` exceeds the entry cost. No model,
no fitted parameter; both sides are observable at `t`.

| cap | crossing | cost model | gated trades | net/trade | total (2 mo) |
|---|---|---|---|---|---|
| uncapped | 0.5× | borrowed flat | 877 | +$11.11 | +$9,747 |
| 10% | 0.5× | borrowed flat | 351 | +$1.016 | +$356 |
| 25% | 0.5× | borrowed flat | 579 | +$1.145 | +$663 |
| 25% | 1.0× | borrowed flat | 204 | +$1.315 | +$268 |
| **25%** | **0.5×** | **measured per-leg (windowed file)** | **782** | **+$0.968** | **+$757** |

Positive in every configuration tested. Ungated `static_now` loses in all of
them (−$0.75 to −$2.88), so the gate is the entire difference.

**Read these as a sensitivity table on the cost model, not as profit.** The
gross term in every row is `|dev(t)|`, and `spread-artefact-finding.md`
decomposes that: at an ask-side print share of 68.7% and a half-spread of
2.8¢, each leg's last print sits ~1.05¢ above mid, so a 6-leg basket shows
+6.3¢ of signed deviation from order-flow imbalance alone. Predicted +6.3¢,
measured +5.25¢. Repriced at executable quotes the same population gives
buy-at-ask $1.1334, sell-at-bid $0.9993 against a $1.0000 settlement — a
gross edge of **−0.07¢** before a 1.3–5.8¢ taker fee.

### On the +$757 vs +$292 discrepancy

A later run of the same script at cap 25% with measured per-leg spreads
reported **+$292**, not +$757. This is **not an error in either run**: it is
a different spreads file.

| run | spreads file | global median | total net |
|---|---|---|---|
| §2 last row | **windowed** (`--window 2h`, drift-corrected) | 4.68¢ | +$757 |
| later run | **pooled** (all trades per side over ticker life) | 5.613¢ | +$292 |

Cost is a **sum over ~6 legs**, so a 0.93¢ difference in the per-leg median
moves basket cost by ~5.6¢ — comparable to the whole gross. Rebuilding
`mece_leg_spreads.parquet` with `--window` is the open item; until then, quote
the pooled (more conservative) figure.

## 3. Per-leg costing changes the gate — and the sign of the change was mispredicted

Replacing the single borrowed median with measured per-leg spreads from the
windowed file (`build_mece_leg_spreads.py --window 2h`):

| | borrowed flat 4.70¢ | measured per-leg (windowed) |
|---|---|---|
| cost/trade | $2.14 | **$1.65** |
| gated trades | 579 | **782** (+35%) |
| total net | +$663 | **+$757** (+14%) |

The medians are nearly identical (4.70¢ vs 4.68¢), so this is not a level
effect. It is a **dispersion** effect: the spread distribution is
right-skewed (mean 5.43¢ against median 4.68¢) and the traded population
skews toward the tighter legs, so a single median systematically over-costs
it. A cost gate given per-leg information finds 35% more opportunities.

**Correction to the reasoning, not the table.** The same argument was later
used to predict that per-leg costing against the *pooled* file would also
raise net PnL. It lowered it (442 → 292). The error was reasoning from a
*median* per-leg spread when basket cost is a *sum* over ~6 legs: the mean
governs the sum, and the distribution is right-skewed, so the mean-vs-median
gap compounds six-fold. Do not reason about basket cost from a per-leg
median.

Source mix after the substitution: `ticker=16,696, series=46,952,
global=1,320` — all now derived from MECE legs rather than borrowed from
ladder pairs. (The script's `--spreads` default was at that time still
pointing at the *ladder* results file, which contains only crypto/financials
pairs; any run that did not pass `--spreads` explicitly silently costed every
leg from a global median belonging to a different mechanism. Fixed, and a
coverage guard now banners when under 50% of legs are costed from a measured
spread.)

## 4. The model does not improve the rule — four tests

| configuration | gated n | model_timed_gated − cost_gated | CI |
|---|---|---|---|
| cap 10%, borrowed, 0.5× | 351 | −0.067 | [−0.174, +0.015] |
| cap 25%, borrowed, 0.5× | 579 | −0.011 | [−0.118, +0.104] |
| cap 25%, borrowed, 1.0× | 204 | +0.053 | [−0.071, +0.222] |
| **cap 25%, measured, 0.5×** | **782** | **+0.005** | **[−0.065, +0.093]** |

Mean point estimate **−0.005**. The best-powered test, at the measured
spread, sits essentially on zero. This is a null, not an underpowered
result. **This section is unaffected by the spread finding** — it is a paired
comparison on identical events, so the overround enters both arms equally.

A fifth test at an assumed flat 1¢ spread did give +0.066 with the CI
excluding zero — but the spread has since been measured at 4.68–5.61¢, so
that configuration does not describe this market. It is recorded here so the
conditionality is on the record, not as a finding.

**What the model does still win.** Entry timing beats a direction-randomised
control in every run, CIs always excluding zero: +$0.59 uncapped, +$0.089 at
cap 25%, +$0.037 at cap 10%, +$0.0886 under measured spreads. Identical
events, sizes and costs; only the decision differs. Because the spread term
is `sum(leg spreads) × multiplier × C` and depends only on the tickers and
the size — both fixed per event — it **cancels exactly** in this paired
comparison. That is why this is the one result the spread finding cannot
touch, and it is now the project's headline. The consolidated figure across
the full population is **+$0.170/trade, CI [+0.107, +0.247]**,
cluster-bootstrapped by basket.

## 5. The spread, triangulated three ways

| estimate | value |
|---|---|
| borrowed (ladder global median) | 4.70¢ |
| pooled (MECE legs, all trades) | 5.61¢ |
| **windowed (MECE legs, drift-corrected)** | **4.68¢** |

The pooled estimator conflates bid-ask with price drift, because it averages
each side over a ticker's whole life and the two sides rarely trade at the
same times. Estimating inside 2-hour windows and taking the per-ticker
median removes that; it accounted for 17% of the pooled figure.

Validated on synthetic trades with a planted 2¢ spread plus 20¢ of drift:
the pooled estimator reported 5.17¢, the windowed one 1.96¢.

**The borrowed figure was right to within 0.4%.** No earlier result requires
retraction *on level grounds*, and the substitution is now defended by
measurement rather than convenience. Note that the file currently on disk is
the **pooled** one (global median 5.613¢); §2 records what that does to the
net figures.

Coverage: 1,585 of 11,758 legs (13.5%) clear `--min-n 10` with 3+ qualifying
windows, so most legs still resolve through the series tier — but that tier
is now built from MECE legs, not ladder pairs.

## 6. Scale — corrected

The earlier version of this section read: *"$757 over two months … Roughly
$4.5k/year. A real positive number, not a business."* **That is withdrawn.**

The $757 is the sum of `|dev(t)|·C` minus modelled cost over 782 gated
basket-events, where `dev(t)` is measured from last trade prints that sit at
bid or ask, never at mid, and whose cross-leg prints are separated by a
median of 406 minutes. Repriced at simultaneous executable quotes on the
subset where both sides are observed within an hour (n=662):

- buy the basket at asks: **$1.1334**
- sell the basket at bids: **$0.9993**
- settlement: **$1.0000**

Selling therefore nets **−0.07¢ gross per basket**, before a Kalshi taker fee
of `0.07 × C × p × (1−p)` per leg, which on a 6-leg basket is 1.3¢ (peaked)
to 5.8¢ (flat). The annualised figure is not $4.5k; it is negative at any
size.

Worse, the gate is **anti-selective** at executable prices: among gated
baskets the share with a positive executable edge falls from 84% to 54%,
because large apparent deviation is *produced by* wide spreads, and
wide-spread baskets execute worst. The gate selects the observations where
the artefact is largest.

What to report: the no-arbitrage band on Kalshi MECE partitions **is**
effectively everywhere-binding once the overround is removed, and a naive
last-trade backtest manufactures profit that does not exist. That is a
methodological finding worth stating, and it is stronger than the $4.5k
would have been.

## 7. The supervisor's requirement — corrected

> *"The model must beat baseline strategies and show PnL to be made."*

The earlier version answered *"PnL to be made: yes, demonstrated at
executable size."* **Withdrawn.** The honest answer is:

- **PnL to be made: no, not from this mechanism at taker prices.** The
  apparent edge is the overround; the executable edge is under one tick
  against a 1.3–5.8¢ fee. Measured, predicted in advance, and reproducible.
- **The model beats baseline strategies: yes, against its causal control,
  everywhere, and cost-model invariantly** (+$0.170/trade, CI [+0.107,
  +0.247]). **Against the cost gate, no** — four tests, null. And the gate
  itself is not profitable.
- **The model also beats an optimal shrinkage oracle by ~15%** on
  forecasting accuracy (0.851× val, 0.853× test), with the graph supplying
  ~92% of that margin.

So the deliverable is not a profitable strategy; it is a **decomposition**:
the constraint is already enforced at executable prices, the apparent
violations are microstructure, and a learned spatio-temporal model
nonetheless forecasts the partition's joint dynamics better than persistence,
an optimal shrinkage oracle, or a timing control. Both halves are measured
rather than asserted.

**Open caveat on the forecasting half.** The 0.851× is on the *basket
aggregate* — which is the ~92.5%-overround quantity. Re-scoring the existing
checkpoint against **bid-side** basket sums is the highest-priority open
check; see `mece-graph-ablation-result.md` §5 and
`four-week-plan-and-reframe.md` §2.

## 8. This line is finished

Further validation runs will not change §4, and §6 closes the PnL line
entirely. The remaining work is:

1. ~~One test run at cap 25%, measured per-leg spreads.~~ **Do not spend
   test on this.** There is no positive result to confirm.
2. Rebuild `mece_leg_spreads.parquet` with `--window` so the two spread
   files stop disagreeing (§2).
3. Write it up, leading the results chapter with §6 rather than §2.

## 9. Method notes

- The comparison in §4 was absent from the first version of the evaluation
  script, which compared `model_timed` to the gate but never the *gated*
  model to the gate — the only question that matters once the gate is known
  to be the binding rule.
- The "use the model to select which dislocations will converge" framing was
  considered and discarded: a basket held to settlement converges by
  construction, so there is nothing to forecast. Entry timing is what
  remains, and it is what §4 tests.
- `cost_gated`'s 100% win rate is **definitional**, not empirical: it enters
  only when `|dev|·C` exceeds the *modelled* cost, so no confidence interval
  against zero is meaningful. Its exposure is to the cost model, which §6 is
  the failure of.
- Three opt-in robustness filters were added later (`--min-leg-volume`,
  `--min-ttc`, `--exclude-families`), all defaulting **off** so every figure
  above reproduces exactly. See `settlement-pnl-robustness.md`. Note
  `TIME_TO_CLOSE` is in **seconds**: `--min-ttc 24` is 24 seconds, and it
  revealed that 15.9% of the evaluated population sat at `ttc == 0`, i.e.
  markets already past close.
