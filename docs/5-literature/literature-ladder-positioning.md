# Literature: has anyone predicted ladder arbitrage?

Scope note: this is a targeted search (≈6 queries, 4 papers read), not a
systematic review. It is enough to position the contribution and to find
the right analogue literature; a dissertation related-work chapter needs a
proper database search on top of it.

> **The most important thing in this document is the Pérignon paragraph, and its
> significance was missed at the time.** Pérignon attributes option monotonicity
> violations to **bid-ask bounce**, with violation rates falling from 12.5–28.1% to
> **3–6% once trade direction is controlled for**. That is the same mechanism, the
> same correction, and roughly the same magnitude as this project's central finding
> (~92.5% of apparent MECE deviation attributable to one-sided prints) — found
> independently three weeks later. The precedent was read, summarised accurately, and
> not applied to our own measurement. See the new section at the end.

## Short answer

**No paper found attempts to FORECAST ordered-threshold ("ladder")
monotonicity violations, in prediction markets or in options.** The
literature detects them, attributes them, and in one case repairs them.
Prediction is the gap.

## Prediction markets

**Unravelling the Probabilistic Forest: Arbitrage in Prediction Markets**
(AFT 2025, arXiv 2508.03474) — Polymarket. Defines two arbitrage types:
*Market Rebalancing* (YES prices should sum to 1 — this project's MECE
mechanism) and *Combinatorial* (portfolios across two markets). On ladders
it is explicit: the scope is "single market and two market dependencies as
an initial study", and richer dependencies are "out of the scope of this
work". **Detection only** — it measures when opportunities existed and when
users executed them, with no forecasting. It also charges **no fees**,
because Polymarket does not charge per trade.

> Note: this project's summary doc described this paper as "~$39.6M
> apparent, ~1% exploited". The abstract reports "a realized estimate of 40
> million USD of profit extracted" and quantifies no apparent-opportunity
> total and no capture rate. Corrected in `mece-pnl-result.md`.

*Its window is 1 Apr 2024 – 1 Apr 2025 (12 months), which is the most useful single
fact in this document for answering the supervisor's "twelve months is not enough"
objection — the only genuinely comparable study used twelve. See
`literature-sample-periods.md`.*

**Executable Arbitrage and Market Efficiency in Prediction Markets**
(arXiv 2608.00666) — Polymarket. Opens "contrary to assumptions of
unprofitability", i.e. unprofitability after costs is the field's default
prior. Finds $1.12M using **depth-aware executable portfolio values**, 97%
of it from a converter primitive rather than settlement baskets. Detection,
not forecasting.

*The phrase "depth-aware executable portfolio values" is the methodological standard
this project eventually adopted under its own steam. Its order-book panel is ~5 weeks
and settlement baskets are ~3% of its value, so it is not a sum-to-one study — but on
**how to measure**, it was right first.*

**Semantic Non-Fungibility and Violations of the Law of One Price**
(arXiv 2601.01706) — 100k+ events, ten venues. Finds 2–4% execution-aware
deviations persisting in liquid venues, with high-yield opportunities
"typically short-lived". Descriptive; no predictive model.

*Note "**execution-aware** deviations of 2–4%" — a plausible order of magnitude for
what genuinely survives costs across venues, against this project's raw +5.25¢ (~5%)
that does **not** survive. Useful as a sanity check: a residual of a few percent is
the credible size for this class of effect, and anything much larger measured from
trade prints should be suspected of being microstructure.*

**Whelan, Makers and Takers: The Economics of the Kalshi Prediction
Market** — average return ≈ −20%; makers −9.64% vs takers −31.46%; makers
+2.6% above 50c. Through April 2025 Kalshi charged takers only.

*Whelan also wrote *Estimating Expected Loss Rates in Betting Markets*, which is in
the overround literature — the literature that names this project's central finding.
See `literature-mece-positioning.md`.*

## The closer analogue: options across strikes

Ladder arbitrage in prediction markets is formally the same constraint as
**vertical-spread arbitrage in options**. This is the literature to cite.

**Cohen et al., Detecting and repairing arbitrage in traded option prices**
(arXiv 2008.09454) — the direct methodological ancestor. Defines vertical
spread arbitrage as the failure of `C₁ ≥ C₂ for K₁ < K₂`, which is exactly
the ladder constraint with strikes in place of thresholds. It enforces
monotonicity and convexity across strikes and formulates **data repair as
constrained optimisation** — explicitly detection-and-repair, **not
predictive**. Two points worth borrowing:

- Its executability test is cleaner than a spread haircut: if the minimal
  repair pushes prices *outside* the bid-ask bounds, an executable
  arbitrage must exist. Worth citing next to this project's measured-spread
  approach.
- It finds executable violations **rare in liquid major pairs** and
  clustered in less liquid ones — the same liquidity story this project
  measures directly.

> **The first bullet was the answer and it was written down three weeks early.**
> "If the minimal repair pushes prices outside the bid-ask bounds, an executable
> arbitrage must exist" is precisely the test this project should have run on day
> one: compare the constraint violation against the **bid-ask bounds**, not against a
> spread *haircut* subtracted from a mid-less last price. The haircut approach
> treats the spread as a cost sitting on top of a real dislocation; the bounds
> approach asks whether the dislocation exists *outside* the spread at all. Those are
> different questions and only the second is the right one.
>
> When this project finally ran the bounds version — buy the basket at asks, sell at
> bids, compare to the $1 settlement — the answer was **−0.07¢**: the repair does
> *not* push outside the bounds, so no executable arbitrage exists. Cohen et al.
> would have predicted the right test; the project reached it independently as
> `mece_spread_artefact_check.py`'s four-way repricing.
>
> Cite Cohen et al. **for the test, not only for the constraint.** It makes the
> project's central method a documented one rather than an invention, which is a
> stronger position with an examiner.

**Pérignon, Testing the Monotonicity Property of Option Prices** —
violations at 12.5–28.1% tick-by-tick, 4–17% daily. Attributed to
**bid-ask bounce** (rates fall to 3–6% once trade direction is controlled),
limited liquidity, and end-of-day trading urgency — microstructure, not
mispricing. **Explicitly does not examine predictability, persistence over
time, or exploitability.**

> Caveat, do not overstate this one: Pérignon tests monotonicity in the
> *underlying* (option price moving opposite to the index), not across
> strikes. It is a sibling constraint, not the same one. Cohen et al. is
> the cross-strike reference.

## Where this project sits

The standard pattern in both literatures is: **document violations →
attribute them to microstructure → stop.** This project continues past
that point, and the continuation is the contribution:

1. **Asks whether violations are forecastable.** Not found elsewhere for
   ordered-threshold constraints.
2. **Answers it with the right conditioning.** Pooled α ≈ 0.99 looks like a
   random walk; conditioning on whether either leg repriced gives α ≈
   0.01–0.48 in the violation buckets, replicated on val and test.
3. **Shows a model can learn the conditional structure** (0.971× an optimal
   shrinkage oracle on moved pairs) **and that it still cannot be
   deployed**, with the trade quantified at ~4 units of error on unmoved
   pairs per unit gained on moved ones.
4. **Supplies a mechanism for what the literature observes.** Cohen et al.
   find executable violations rare in liquid markets; Pérignon attributes
   violations to illiquidity. This project measures the dynamics behind
   that: violations persist because legs do not reprice, and collapse
   sharply (+18.5¢ → +0.07¢) when they do.

> **A correction to the framing, and it is uncomfortable.** The sentence
> "the standard pattern is document → attribute to microstructure → **stop**" is
> written as though stopping there were a shortcoming of the literature. On the
> economics, the literature was right and this project spent weeks arriving at the
> same place: the violations *are* microstructure. Pérignon's 12.5–28.1% → 3–6%
> under trade-direction control is the same correction as this project's 92.5%.
>
> What survives as genuinely additional, stated without the implied criticism:
>
> - **Forecastability** (items 1–3). The literature did not ask; this project asked
>   and answered, positively for MECE (0.851× an oracle, graph supplying ~92%) and
>   negatively-with-mechanism for the ladder. This is the real contribution and it is
>   unaffected.
> - **The decomposition is quantitative and was predicted in advance.** Pérignon
>   controls for trade direction and reports the residual; this project *predicts*
>   the artefact's magnitude from first principles (`h(2p−1)` per leg, +6.3¢ on six
>   legs at a 68.7% ask share) and then measures +5.25¢. Predicting the size of an
>   artefact before measuring it is a step beyond controlling for it.
> - **A venue where the structure is abundant.** 7,581 covered basket-days across 44
>   months, against a prediction-market literature that struggled to find sum-to-one
>   baskets at all.
>
> Item 4 should be reworded. "Supplies a mechanism for what the literature observes"
> is fair for the *reprice-timing* mechanism, which is new. It is not fair as a
> general claim, because on the ladder side the mechanism the literature already had
> (bid-ask bounce) is the one this project confirmed on the MECE side.

## A methodological warning worth stating

Neither literature conditions its persistence or reversion statistics on
**whether the price moved at all**. A pair whose legs are both untraded has
`gap(t+h) ≡ gap(t)` by arithmetic, and contributes α = 1 carrying no
economic information. At 75–90% frozen shares, that mass dominates any
pooled coefficient.

This project reached "the ladder gap is a random walk" from exactly that
artifact before catching it. Any study regressing a no-arbitrage residual
on its own lag in a market with sparse trading faces the same trap.

*This warning stands and is original. Pair it with the second one the project
subsequently earned: **and neither conditions on which side of the book the print
landed on**, except Pérignon, which does and should be cited for it.*

## The precedent that was read and not applied

Worth recording explicitly, because it is the clearest process lesson in the
project.

On 2026-09-19 this document summarised Pérignon accurately: monotonicity violations
at 12.5–28.1%, falling to **3–6% once trade direction is controlled**, attributed to
**bid-ask bounce** — "microstructure, not mispricing". The summary is correct and the
mechanism is named.

At that moment the project's own MECE population was being measured from **last
trade prints with no trade-direction control at all**, and a +$757 profit figure was
being prepared for the thesis on that basis. The `taker_side` column needed for the
control was already known to exist, had already been investigated
(`taker-side-investigation-notes.md`, 2026-08-31), and its use for exactly this
purpose was described there as "still worth building".

The gap was closed on 2026-09-26, and only because a reader asked whether the MECE
mechanism had been measured wrongly.

**Three things to take from this:**

1. **Cite Pérignon in the methods chapter as the precedent for the control**, not
   just in related work as a description of options markets. It makes the project's
   central measurement a standard one rather than an ad-hoc discovery.
2. **The caveat that "Pérignon tests monotonicity in the underlying, not across
   strikes" is correct but was load-bearing in the wrong direction.** It was a reason
   to weight the paper less as a *constraint* reference — and it was silently applied
   to the paper's *methodological* content too, which has nothing to do with which
   constraint is being tested. A caveat about one aspect of a paper should not
   discount the rest of it.
3. **When a paper reports that a control changed its headline by a factor of four,
   that is not a fact about their data.** It is a specification for a check to run on
   yours.

## Honest limits of this search

Six queries, four papers read in depth. Not covered: pre-2020 prediction
market literature (Iowa Electronic Markets, Intrade, Betfair), the
sports-betting arbitrage literature, which has ordered-threshold structure
in totals/handicap markets and may be the closest untapped analogue, and
the limit-order-book deep learning literature on short-horizon price
prediction. A claim of novelty in the dissertation should rest on a
systematic search, not on this.

**Update on one of those gaps:** the sports-betting literature is no longer merely
"the closest untapped analogue" for ordered thresholds — its **overround** strand
names this project's central finding. See `literature-mece-positioning.md`. Search
it before the related-work chapter.
