# Kalshi Arbitrage FYP — Naive-Analysis Findings Summary

> ## ⚠ SUPERSEDED — retained as the audit trail, not as current findings
>
> _Written 2026-09-05, at the end of the naive detection + PnL backtest phase, before
> any model existed. Five later documents cite this one **as the thing being
> corrected**, which is why it is kept rather than deleted._
>
> **Replaced by:** `docs/RESEARCH_LOG.md` (chronology), `spread-artefact-finding.md` (the
> central finding), `four-week-plan-and-reframe.md` (current status).
>
> **Four things in here are now known to be wrong**, marked ❌ inline where they
> appear:
> 1. §2 — the 618-snapshot / 267-opportunity counts, and "byte-identical across all
>    candidate-pool sizes". Stale: after the `FAMILY_RE` fix, `MAX_LEGS` 60→100 and a
>    wider month range, it is **4,891** full-basket snapshots for 2025-02…11 and
>    **7,581** covered basket-days across 44 months.
> 2. §2 — "every 14+ leg family has **NEVER** contributed a single full-basket
>    snapshot at any MAX_LEGS setting tested". False on May–Sep 2025: `KXF1RACE`
>    (20 legs) and `KXNASCARRACE` (41 legs) both do.
> 3. §2 — "**no bid/ask spread signal exists in this data**". False, and this is the
>    consequential one: the `taker_side` column supplies exactly that signal, and
>    using it showed ~92.5% of apparent MECE deviation is bid/ask overround. This
>    sentence is the justification for the arbitrary flat haircut that the whole §2
>    PnL rests on.
> 4. §2 — "93% of opportunities are weather". True on Oct+Nov 2025; on the window the
>    model was trained and evaluated on, sports is 51.9% of all baskets and weather is
>    58.0% of dislocations above 5¢.
>
> **One outstanding item is hereby closed:** three other documents flag that this file
> "may still carry" the AFT citation as *"~$39.6M apparent, ~1% exploited"*. **Checked
> — it does not.** That phrasing is not in this version. The correction still needs
> applying to the LaTeX before submission, but not here.
>
> **And one paragraph in §2 deserves reading before anything else in the repo**: the
> `264/267 one-directional` observation. It is the overround, spotted and named as a
> candidate mechanism three weeks before it was tested. See the note there.

_Last updated: 2026-09-05. Covers Oct+Nov 2025 Kalshi trades data. This is the checkpoint
at the end of the "naive detection + PnL backtest" phase for both arbitrage mechanisms
scoped into this project — ladder monotonicity and MECE sum-to-$1._

## 1. Pairwise ladder monotonicity (nested threshold no-arbitrage)

**Mechanism:** for nested thresholds T_low < T_high on the same underlying and direction,
no-arbitrage requires yes_ask(T_low) >= yes_bid(T_high). A same-side violation is a locked-in
minimum profit of yes_price(T_high) - yes_price(T_low) per contract.

**Scope:** crypto (`KXBTCD`/`KXETHD`/`KXXRPD`/`KXDOGED`) and financials
(`KXNASDAQ100U`/`KXINXU`/`KXUSDJPYH`) "D/threshold"-series markets only — confirmed via direct
`yes_sub_title` inspection that these are structurally distinct from same-category
bracket-basket series (`KXBTC`, `KXNASDAQ100`, etc.), which are MECE-shaped, not ladders.
Weather and other categories correctly excluded (100% bracket-classified sub_titles, zero
upper/lower_tail legs to pair).

*This scope statement is correct and it is the one that dissolved the earlier weather
ladder headline (~50% violation rate, 5.4× gap/spread) reported in
`taker-side-investigation-notes.md`. Worth noting the sequence: the identification fix
came first, the retraction of the finding it invalidated came later.*

**Result:** 464,709 valid pairs found (100% correctly classified pair types across every
category). Violation rate ~14-15% raw, ~9-10% for crypto after liquidity filtering (robust
across min_n=10/20/50/100 sweeps); financials' apparent ~24% violation rate collapses to 0%
at strict liquidity (min_n=100, n=3) — a liquidity artifact, not real mispricing.

**PnL:** idealized +$5,213.10 (zero friction) / realistic -$9,221.66 (Kalshi taker fees +
full trade-implied spread haircut, 9.2% win rate) / fees-only +$2,683.43 (61.4% win rate).
Sensitivity sweep: breakeven haircut fraction ~20-23% of the full measured spread, for both
crypto and financials.

**Verdict:** narrow, real, execution-cost-sensitive edge concentrated in crypto. Financials'
edge does not survive liquidity filtering. Genuine but fragile — needs roughly 4-5x tighter
execution than the full measured spread to be profitable.

> **Verdict corrected.** "Genuine but fragile" overstates it in two ways.
>
> *Economically:* the realistic figure is **−$9,221.66 at a 9.2% win rate**, and
> "needs execution 4–5× tighter than the measured spread" describes something no taker
> can do. A rule that is profitable only at a quarter of the observed spread is not a
> fragile edge; it is an edge that exists only in the absence of the spread. And these
> figures come from **last trade prints**, with no bid/ask decomposition ever run on
> the ladder population — on the MECE mechanism the equivalent decomposition removed
> 92.5% of the apparent value, so the prior here should be that most of the idealized
> +$5,213 is overround too.
>
> *For the thesis:* the ladder line is **closed on forecasting grounds** and is now the
> project's negative control. Violations do collapse sharply conditional on a reprice
> (+18.5¢ → +0.07¢, eighteen cells across two splits), but the all-pairs ratio is
> minimised at epoch 0 and rises monotonically under every mover weight, because
> reprice *timing* is not in the features. FINAL. See
> `ladder-conclusion-overturned.md`.

## 2. MECE sum-to-$1 (single-winner N-way baskets)

**Mechanism:** for a full partition of one outcome space (exactly one leg resolves YES),
no-arbitrage requires the sum of all legs' YES prices = $1.00. Deviation = arbitrage signal
(sell every leg if sum > $1, buy every leg if sum < $1).

*The mechanism statement is exactly right and never needed correcting. What needed
correcting is the assumption that **a last trade price is the price in that equation**.
It is not: a trade prints at the bid or the ask, never at mid.*

**Candidate identification (validated/audited):**
- Family-level consistency check (an event's ticker-prefix "family" must resolve n_yes==1 across
  >=3 historical instances) structurally self-rejects real ladders and combo-prop bundles even
  when title-keyword filtering misses them.
- Fixed `FAMILY_RE` bug (was truncating at first digit, wrongly merging e.g. `KXNASDAQ100`
  bracket-basket with `KXNASDAQ100U` ladder into one family) — recovered 58 candidate events,
  zero regressions, verified via dedicated diagnostic script.
- Raised `MAX_LEGS` 60 -> 100 after an audit found 2,989 excluded events, almost entirely
  `KXDOGE` (64-67 legs) — a crypto bracket-basket family structurally identical to already-
  validated `KXBTC`/`KXETH`/`KXSHIBA`, just needing more brackets. ❌ Confirmed via rerun this
  produced zero change in actual full-basket evidence (see below) — the exclusion wasn't
  hiding evidence, size wasn't the binding constraint.
- 29 families manually eyeballed (full leg lists) and confirmed as genuine MECE partitions,
  not combo-prop grab-bags.

*The identification work all stands. **29 families** is correct for the Oct+Nov 2025
window; pooled over all 54 months of the archive there are **86**. The "size wasn't the
binding constraint" conclusion is ❌ — see the next block.*

**❌ Key empirical finding — full-basket coverage is a small-cluster phenomenon:** across three
runs at increasing candidate-pool sizes (741 -> 799 -> 2,354 candidates as filters were fixed),
the actual full-basket simultaneous-trading evidence was BYTE-IDENTICAL every time: exactly 618
fully-covered (event, day) snapshots, out of 2,083 event-days with >=1 trade. Every 14+ leg
family (crypto/FX brackets, Spotify/Billboard chart families, Treasury yield brackets) has
NEVER contributed a single full-basket snapshot at any MAX_LEGS setting tested, despite large
underlying trading volume. Only weather (6-leg `KXHIGH*` families) and `KXAPRPOTUS` (8-leg,
presidential approval rating) ever achieve full coverage. This mirrors the K-of-N liquidity-
fragmentation wall found earlier in the project — it reappears once a genuinely single-winner
basket gets large enough.

> **This entire block is superseded, and the way it failed is instructive.**
>
> The counts: **618** full-basket snapshots became **4,891** for 2025-02…2025-11, and
> **7,581** covered basket-days across 44 months once identification was pooled over
> the full archive (86 families rather than 29). The byte-identical stability across
> three candidate-pool sizes was real *and misleading* — it was stable because all
> three runs were on the same two months with the same buggy `FAMILY_RE`. **Stability
> under variations that don't touch the binding constraint is not robustness.** The
> binding constraint was the month range, and no run varied it.
>
> The absolute claim: `KXF1RACE` (20 legs, 76 snapshots above 5¢, median |dev| 20¢) and
> `KXNASCARRACE` (41 legs, 52 snapshots, median 30¢) both achieve full coverage on
> May–Sep 2025, and they carry the **largest dislocations in the dataset**. They remain
> untradeable for the documented reason — 41 legs × ~4.7¢ of spread is ~96¢ of cost
> against 30¢ of gross — which is the leg-count mechanism in its most extreme
> observable form and a useful concrete illustration for the economics chapter.
>
> Three other documents were written referring to this sentence and then had to
> qualify it. **Never write NEVER about a population you have measured on one window.**
> See `mece-population-composition.md` §2.

**PnL (267 of 618 snapshots exceed $0.05 "meaningfully mispriced" threshold):**
- Idealized (zero friction): +$2,609.00
- Fees-only (Kalshi taker fees, no execution haircut): +$1,662.42, 97.8% win rate
- Realistic (fees + a flat, non-data-driven per-leg execution haircut — ❌ **no bid/ask spread
  signal exists in this data**, unlike the ladder result): **+$84.42 at 1c/leg haircut**
  (38.6% win rate, NEGATIVE median PnL per opportunity of -$0.63 — mean is carried by a few
  large-deviation days)
- **Sensitivity sweep is the decisive result:** zero-crossing sits between 1 and 2 cents per
  leg. At 2c/leg: -$1,493.58 (10.5% win rate). At 5c/leg: -$6,227.58 (1.1% win rate). This is
  a MUCH thinner margin than the ladder's ~20-23%-of-full-spread breakeven — friction is
  charged once per leg (avg 5.9 legs/opportunity), so even a "minimum tick" assumption is
  really a ~6-cent aggregate cost on the basket.
- ❌ weather/climate is 249/267 (93%) of opportunities and 90% of idealized PnL, and is NET
  NEGATIVE (-$26.49) even at the gentlest (1c/leg) haircut. Politics (KXAPRPOTUS, n=6) and
  sports (n=12) hold up marginally longer (positive through 2c/leg) but sample sizes are too
  small to trust as a standalone pattern.
- 264/267 opportunities are one-directional (`sell_all_legs`, i.e. basket overpriced) — only 3
  are `buy_all_legs`. Possible systematic retail-taker overpricing bias on weather brackets, or
  a sampling artifact of which days achieved full coverage; not yet distinguished.
- Evidence is also correlated, not 618 independent bets: several top snapshots come from the
  same event on consecutive days (`KXAPRPOTUS-25NOV21` x3, late-Oct Chicago/Philadelphia
  cluster).

> **❌ "No bid/ask spread signal exists in this data" is false, and it is load-bearing.**
>
> The `trades` file carries a **`taker_side`** column (`"yes"` = the taker lifted the
> ask, `"no"` = sold YES into the bid). It was already known to exist when this was
> written — `taker-side-investigation-notes.md`, dated 2026-08-31, five days earlier,
> is entirely about it, and ends by proposing exactly this use. Splitting each leg's
> prints by that column gives a per-leg implied spread directly, and it is the whole
> basis of the eventual finding.
>
> Because the signal was declared absent, the "realistic" scenario used a **flat,
> arbitrary 1¢/leg** haircut — chosen as a "minimum tick" rather than measured — and
> the headline **+$84.42** is a function of that choice. The measured per-leg spread on
> MECE legs is **4.68¢** (windowed, drift-corrected) to **5.61¢** (pooled), i.e. four to
> five times the assumed haircut and two to five times past this document's own
> zero-crossing. **The sensitivity sweep already contained the negative answer; only
> the spread measurement was missing to read it off.** At 5¢/leg this document reports
> −$6,227.58 at a 1.1% win rate, and that is the row closest to reality.
>
> Compare §1's lesson, learned earlier on the ladder and recorded in
> `stgat-results-and-limitations.md` §7.6: *an assumption that determines the sign of
> the result is not a parameter; it is the result.* It was stated for the ladder haircut
> and then repeated on the MECE side five days later.

> ## ⚠ The `264/267 one-directional` paragraph — the finding, three weeks early
>
> > *264/267 opportunities are one-directional (`sell_all_legs`, i.e. basket
> > overpriced) — only 3 are `buy_all_legs`. **Possible systematic retail-taker
> > overpricing bias on weather brackets**, or a sampling artifact of which days
> > achieved full coverage; not yet distinguished.*
>
> **98.9% of a supposedly two-sided arbitrage signal pointing one way is not a
> property of arbitrage.** A genuine mispricing has no reason to be signed. The
> observation was made, the correct mechanism was named as the first hypothesis —
> "systematic taker overpricing bias" is the overround in plain words — and it was
> filed as "not yet distinguished".
>
> What it turned out to be, measured on 2026-09-26: **68.7% of trade prints are
> ask-side.** At a 2.8¢ half-spread each leg's last print sits `h(2p−1) = 1.05¢` above
> mid, so a 6-leg basket shows **+6.3¢** of signed deviation from order-flow imbalance
> alone. Predicted before measuring; measured **+5.25¢**. Repriced at executable
> quotes: buy at asks $1.1334, sell at bids $0.9993, settles $1.0000 — **−0.07¢**
> gross, before a 1.3–5.8¢ taker fee.
>
> The one-directional split is that mechanism's signature, and it was visible in the
> very first PnL table the project produced. Three things made it possible to file and
> move on: the alternative hypothesis offered in the same sentence (a coverage sampling
> artifact) was cheaper to believe; the sentence directly above it declared the data
> could not answer the question; and the number next to it was positive.
>
> **The methodological rule this earns, and it belongs in the dissertation:** when a
> signal that theory says should be symmetric comes out 99% one-sided, that asymmetry
> is the most informative measurement in the table. Test it before anything else in
> the analysis is believed. Do not record it as an open item next to a profit figure.

**Verdict:** weaker and more fragile than the ladder result. Idealized PnL is real but rests on
a small, correlated set of full-basket days; realistic PnL is at or below breakeven under any
plausible (non-minimum-tick) execution-cost assumption, and the one category with enough data
to trust (weather) is already negative at the gentlest assumption tested.

> **This verdict is the most nearly-correct thing in the document and was not acted on.**
> "At or below breakeven under any plausible execution-cost assumption" is, in
> substance, the eventual conclusion. The project then spent three weeks building a
> hold-to-settlement structure that recovered a positive figure (+$292 to +$757) by
> changing the trade's cost structure rather than by revisiting its gross term — and
> the gross term was where the problem was.

## 3. STGAT scoping decision

Recommended target: **single-winner MECE N-way clusters, not binary markets.** Rationale:
(a) a single binary market trivially satisfies yes+no=~$1 by construction — no graph/relational
structure for attention to operate over; (b) MECE clusters provide genuine multi-node relational
structure (N legs, one shared no-arbitrage constraint) that a GAT architecture is built to
exploit; (c) MECE is the best-evidenced mechanism investigated in this project, even though its
naive PnL is fragile; (d) binary arbitrage has never been investigated here and would need an
entirely separate, unvalidated methodology with ~1 month remaining.

The reframe: this naive-analysis phase (both mechanisms) shows a consistent pattern — small
clusters can be tested directly and show real (if fee/haircut-sensitive) evidence; large
clusters structurally cannot be naively tested due to liquidity fragmentation, and even where
naive testing *is* possible (MECE's 618 small-cluster snapshots), the edge is right at the
margin of realistic execution cost. That's the direct empirical case for the professor's
"Direction B" — a GAT that prices illiquid legs from liquid neighbors is aimed exactly at the
gap this phase couldn't close with naive per-leg analysis.

> **The scoping decision was correct and stands.** MECE remained the target and the
> reasoning in (a)–(d) held up; the eventual graph ablation vindicated (b) specifically,
> attributing **~92%** of the model's forecasting margin to the cross-sectional
> structure. The decision not to pivot — to the ladder, or to cointegration pairs
> trading — was revisited later and reaffirmed on independent grounds
> (`mece-yield-by-month.md` §5).
>
> One clause did not survive: the **coverage** path, "price illiquid legs from liquid
> neighbours to generate signals where the naive rule has zero coverage". It was
> implemented and abandoned: the estimation error on an inferred leg price is
> **1.49× the signal** it is meant to reveal, so the inferred prices cannot support a
> trade. It is below the cut line and should be reported as a measured negative rather
> than an untried extension.

## 4. Is there "actually" arbitrage? (framing for the writeup)

Raw Kalshi prices genuinely violate their theoretical no-arbitrage conditions (ladder ordering,
MECE sum-to-$1) at a rate too high to be noise — that's a real, measured phenomenon, and the
"idealized" PnL numbers above are the literal dollar size of those violations. But "arbitrage"
in the strict sense (a riskless profit net of ALL costs of implementing the trade) mostly
doesn't survive contact with realistic execution costs: the ladder needs execution roughly 4-5x
tighter than the measured spread to be profitable, and MECE's breakeven sits at 1-2 cents of
per-leg friction, near the theoretical floor. This is consistent with "limits to arbitrage"
market-efficiency literature — persistent mispricings whose size tracks the transaction cost
required to close them, not evidence the market or the analysis is broken.

> **The answer, now that it is measured: no, and the framing above has the causality
> backwards in an interesting way.**
>
> "Persistent mispricings whose size tracks the transaction cost required to close
> them" is the right observation with the wrong mechanism. The size does not merely
> *track* the transaction cost — it **is** the transaction cost, mechanically. Each
> leg's last print sits above mid by half a spread times the order-flow imbalance, so
> the measured deviation is the spread, aggregated over legs. That is why it "tracks"
> so neatly, and it is a stronger and more precise statement than the limits-to-
> arbitrage framing.
>
> So: raw Kalshi last-trade prices violate the constraints, and the violations are
> real *as measurements of last-trade prices*. They are not mispricings. The
> "idealized" PnL figures are not "the literal dollar size of those violations" in any
> economically meaningful sense; they are the dollar size of the overround. At
> executable quotes the no-arbitrage band on MECE partitions is effectively
> everywhere-binding.
>
> The thesis keeps the limits-to-arbitrage literature as context but leads with the
> sharper claim: **a naive last-trade backtest on prediction-market partitions
> manufactures profit that does not exist**, and the size of the manufactured profit is
> predictable in advance from the ask-side print share and the half-spread.

**Professor's requirement** (model must beat baseline strategies and show PnL to be made) is
compatible with this: it's a relative comparison, not a requirement to find bigger mispricings
than exist in the data. The naive rule-based strategies backtested above (trade every violation
over a fixed dollar threshold, size to the deviation) ARE the baseline the professor is asking
for, and their realistic PnL is already known (see §5 table). The STGAT has two concrete,
measurable paths to beat them without needing to discover new mispricing: (a) **selection** —
predict which of the naive rule's flagged opportunities will actually clear realistic costs
(the naive rule trades everything above threshold indiscriminately, which is why MECE's mean
realistic PnL is positive but its median is negative), and (b) **coverage** — price illiquid
legs from liquid neighbors (the GAT's core mechanism) to generate tradeable signals on the
14+ leg families where the naive full-basket rule has literally zero opportunities to trade
(0% coverage, not just unprofitable coverage). Any positive realized PnL there is by
construction "PnL the baseline couldn't find."

> **Both paths were built. Both failed, and the failures are measured.**
>
> **(a) Selection.** Implemented as the cost gate in
> `evaluate_mece_settlement_pnl.py`: enter only when `|dev(t)|·C` exceeds the entry
> cost, no fitted parameter. It produces a positive backtest, and at executable prices
> it makes selection **worse** — the share of gated baskets with a positive executable
> edge falls from **84% to 54%**, because large apparent deviation is *produced by* wide
> spreads and wide-spread baskets execute worst. The gate selects the observations where
> the artefact is largest. Separately, the *model* does not improve on the gate: four
> tests give a mean point estimate of −0.005, best-powered test +0.005, CI
> [−0.065, +0.093]. A well-powered null.
>
> **(b) Coverage.** Abandoned: estimation error 1.49× signal (§3 note).
>
> **What the model does beat, and it is the surviving answer to the requirement:** its
> own randomised-timing control, by **+$0.170/trade, CI [+0.107, +0.247]**,
> cluster-bootstrapped by basket and **identical under three cost models** — because
> the spread term is `sum(leg spreads) × multiplier × C`, depends only on the tickers
> and the size, both fixed per event, and therefore cancels exactly in a paired
> comparison. Provably cost-model invariant. Plus 0.851×/0.853× against an optimal
> shrinkage oracle on forecasting accuracy, with the graph supplying ~92%.
>
> So the honest answer to the requirement is: **beats baselines yes, PnL no**, and the
> "PnL no" is a measured contribution rather than a shortfall. See
> `settlement-arbitrage-result.md` §7 and `four-week-plan-and-reframe.md`.

## 5. Baseline metrics table (KIV — fixed comparison point for the STGAT)

Produced by `baselines.py`, run 2026-09-05, from `pairwise_monotonicity_pnl_results.parquet`
and `mece_sum_to_one_pnl_results.parquet`. `coverage_pct` = opportunities traded / upstream
candidate-pool size (464,709 valid ladder pairs; 2,354 MECE candidate events).
`cross_sectional_sharpe` = mean/std of per-opportunity PnL (not an annualized financial
Sharpe — these are one-off captures, not a continuous return series). `max_drawdown_usd` is
only computable for MECE (its opportunities carry a real trade date; the ladder's are a
cross-sectional per-pair summary with no chronological ordering).

| mechanism | scenario  | n   | universe | cov%  | total_pnl   | win_rate | sharpe | max_dd  |
|-----------|-----------|-----|----------|-------|-------------|----------|--------|---------|
| ladder    | idealized | 801 | 464,709  | 0.17  | $5,213.10   | 100.0%   | 0.999  | n/a     |
| ladder    | fees_only | 801 | 464,709  | 0.17  | $2,683.43   | 61.4%    | 0.512  | n/a     |
| ladder    | realistic | 801 | 464,709  | 0.17  | -$9,221.66  | 9.2%     | -1.075 | n/a     |
| mece      | idealized | 267 | 2,354    | 11.34 | $2,609.00   | 100.0%   | 1.647  | $0.00   |
| mece      | fees_only | 267 | 2,354    | 11.34 | $1,662.42   | 97.8%    | 1.135  | -$0.37  |
| mece      | realistic | 267 | 2,354    | 11.34 | $84.42      | 38.6%    | 0.058  | -$92.72 |

**The row to beat is `realistic`, for both mechanisms.** The `coverage_pct` column is the
other axis worth tracking even if PnL doesn't move much: both naive baselines trade a small
sliver of their own identified candidate pool (0.17% / 11.34%), and neither can trade at all
on the large (14+ leg) clusters — a model that raises coverage on that segment is demonstrating
value the PnL total alone won't show if those new trades are small.

Local artifact: `baseline_results_summary.parquet` (same 6 rows, machine-readable — score the
STGAT with the same `metrics_row()` function in `baselines.py` for a direct comparison).

> **This table was never the comparison the thesis ended up making, and should not be
> reproduced as a baseline.** Three reasons:
>
> 1. **`idealized` win rates of 100.0% are definitional, not empirical.** The rule
>    enters only when the deviation exceeds the modelled cost, so a zero-friction run
>    wins by construction. The same objection applies to the later `cost_gated` row:
>    no confidence interval against zero is meaningful for it, and its exposure is to
>    the cost model, not to sampling.
> 2. **The `realistic` MECE row rests on the arbitrary 1¢/leg haircut** (§2). At the
>    measured 4.68–5.61¢ it is between the −$1,493 and −$6,227 rows of the sensitivity
>    sweep.
> 3. **The baselines that matter for a forecasting claim are different ones.**
>    Persistence and the optimal shrinkage oracle, both computed inside
>    `model/forecast_objective.py`, and a direction-randomised control on identical
>    events. Those were committed to in advance (`stgat-forecasting-redesign.md` §6)
>    precisely so the result could not be graded against a straw man, and the
>    shrinkage oracle is *harder* than anything in this table because its α is fitted
>    with hindsight on the split being scored.
>
> The `coverage_pct` axis is the one genuinely good idea here and it was tested — and
> came back negative at 1.49× error-to-signal. Report it as measured.

## 6. Open threads / not yet done

- `pairwise_monotonicity_pnl_out_of_sample.py` — deliberately deprioritized (predates the
  corrected pair-builder, rebuilds its own weather-specific ladder pairs from scratch).
- `mece_family_audit.py` has not been rerun at `MAX_LEGS=100` (only `mece_sum_to_one_check.py`
  was rerun after that change) — low priority since the full-basket evidence has already been
  shown to be identical across all three candidate-pool sizes tested.
- STGAT architecture design/implementation — not yet started. Scoped to single-winner MECE
  N-way clusters per §3 above. Evaluation harness should reuse `baselines.py`'s metric
  definitions so STGAT results are directly comparable to §5 without re-deriving metrics.

> **Statuses, closing this document out:**
>
> - `pairwise_monotonicity_pnl_out_of_sample.py` — **do not run it.** Its weather ladder
>   pairs are the population the `yes_sub_title` correction invalidated. Still
>   deprioritized, now permanently: the ladder line is closed.
> - `mece_family_audit.py` at `MAX_LEGS=100` — **rerun, and the "low priority" reasoning
>   was wrong.** The justification was the byte-identical stability across candidate-pool
>   sizes, which was stability under a variation that did not touch the binding
>   constraint. The 14+ leg conclusion changed once it was rerun over a wider month
>   range.
> - STGAT — **built.** `TypeSpecificProjection` → `TwoChannelSpatialAttention` (GATv2,
>   MECE hyperedge + ladder chain channels) → causal `TemporalAttention` →
>   `ResidualForecastHead` with a zero-initialised final layer, so the model starts
>   exactly at persistence. Results: 0.851× val / 0.853× test against the shrinkage
>   oracle, graph supplying ~92%, and the model-vs-control result above. **The
>   evaluation harness did not reuse `baselines.py`'s metrics**, and that was the right
>   call — see the §5 note.
