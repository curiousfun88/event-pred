# Literature: has anyone predicted MECE basket arbitrage?

Companion to `literature-ladder-positioning.md`. Same scope caveat: a
targeted search, not a systematic review.

## Short answer

**No.** Three papers cover sum-to-one arbitrage in prediction markets and
all three are detection-only. One states outright that "no machine
learning, neural networks, or statistical forecasting models are
employed". The forecasting question appears unasked.

But the more important finding is that **the literature measures a
different phenomenon from this project's**, and that distinction is what
makes the forecasting question coherent here and incoherent there.

> **One correction and one warning, both added later:**
>
> - **The comparison in "The phenomena are not the same" is invalid as originally
>   drawn.** It puts Polymarket's *order-book ask* counts at a single instant against
>   this project's *last-trade* counts separated by a median of 406 minutes. Those are
>   different objects and the inference "the mechanism is materially more present on
>   Kalshi" does not follow. Corrected below.
> - **The "honest limits" section named the sports-betting overround literature as
>   "the most likely place for a prior forecasting result to be hiding". It was the
>   most likely place for the project's *own* central finding to be hiding, and it
>   was.** See the new section at the end. This is the single most consequential
>   unfollowed lead in the project.

## What exists

**Unravelling the Probabilistic Forest** (AFT 2025, arXiv 2508.03474) —
its *Market Rebalancing* arbitrage is exactly this project's MECE
mechanism: YES prices across mutually exclusive outcomes should sum to 1.
Detection only: it measures when opportunities existed and when users
executed them. **Charges no fees**, because Polymarket does not.

*Verified since: its window is 1 Apr 2024 – 1 Apr 2025, **12 months** — slightly less
than this project's proposed 13 — and it is the **only** one of the three that treats
sum-to-one as a primary object. The $40M is aggregated across both its arbitrage
types with no per-type breakdown, so no per-type share can be quoted. Detection via
LLM semantic analysis plus historical order-book inspection, over 8,659
single-condition and 1,578 multiple-condition markets. See
`literature-sample-periods.md`.*

**Arbitrage Analysis in Polymarket NBA Markets** (arXiv 2605.00864) — 75M
order-book snapshots, 3,042 markets. Explicitly deterministic detection:
opportunities flagged when `Ask_A + Ask_B < $1.00`. Findings:

| | episodes | median persistence |
|---|---|---|
| single-market (sum-to-one) | **7** across 3,042 markets | **3.6 seconds** |
| combinatorial (moneyline–spread) | 290 across 173 games | 16 seconds |

The binding friction is **depth, not fees**: 76.9% of combinatorial
opportunities were capped at an average executable size of **14.8 shares**.

*Note its window is 4 Feb – 4 Mar 2026, **one month**, and its single-market category
is the degenerate two-leg case. Its polling cycle is 3.6–5.5 seconds, which the
authors flag as a structural lower bound on observed inefficiency — so the 3.6-second
median persistence is at the resolution floor and should be read as "at most one
polling interval", not as a precise measurement.*

**Executable Arbitrage and Market Efficiency in Prediction Markets**
(arXiv 2608.00666) — depth-aware executable portfolio values on Polymarket,
$1.12M, 97% from a converter primitive rather than settlement baskets.
Detection.

*Its order-book panel is 14 Apr – 19 May 2026 (~5 weeks). Settlement baskets are
~3% of its measured value, so it is **not** primarily a sum-to-one study. Its method
— **depth-aware executable** portfolio values rather than trade prints — is exactly
the methodological correction this project arrived at independently and much later.
It is the closest methodological neighbour in the whole search and deserves more
weight than this document originally gave it.*

## The phenomena are not the same — CORRECTED

The original version of this table read:

| | Polymarket NBA literature | this project (Kalshi) |
|---|---|---|
| opportunity lifetime | **3.6 seconds** (median) | persists across 2-hour snapshots |
| count | 7 episodes / 3,042 markets | ~~tens of thousands of basket-snapshots~~ |
| binding friction | order-book **depth** | **fees and spreads** |
| question asked | did an opportunity exist? | will a dislocation appear? |

**The count row does not compare like with like, and the conclusion drawn from it —
that the mechanism is materially more present on Kalshi — is withdrawn.**

- The NBA paper counts instants at which **posted asks** satisfied
  `Ask_A + Ask_B < $1`, polled every 3.6–5.5 seconds. That is a strictly executable
  condition at a single moment in a live order book.
- This project counts basket-days on which every leg **traded at all** and the
  **last trade prices** did not sum to $1, with those prints separated by a median of
  **406 minutes**.

`spread-artefact-finding.md` then showed that ~92.5% of this project's measured
deviation is the bid/ask overround — i.e. most of the count is not an executable
condition at all. The executable figure on the subset where both sides are priced
within an hour (n=662) is buy at $1.1334, sell at $0.9993, settle $1.0000: a gross
edge of **−0.07¢**.

**The defensible version of the row:** the *structure* is more present on Kalshi —
7,581 fully covered basket-days across 44 months, versus a literature that had to
look hard to find any sum-to-one baskets at all (7 episodes in one paper, ~3% of
value in another). The *arbitrage* is not. Say structure, never arbitrage.

The rest of the table stands, and the lifetime row is the important one:

A 3.6-second opportunity is **invisible at 2-hour resolution** — it opens
and closes inside a single snapshot of this project's data. Conversely a
dislocation that survives hours is not what a live-play NBA scanner is
looking for.

So the two literatures are studying **transient arbitrage** (a latency
race, correctly framed as detection) while this project studies
**persistent dislocation** (a slow-moving state variable, which is the only
regime where forecasting is even a sensible question). Forecasting a
3.6-second opportunity would be meaningless; forecasting a dislocation that
persists for hours is not.

That distinction should open the related-work section. It explains why the
forecasting question has not been asked without claiming everyone else
missed something obvious.

*And it now carries a second load: the reason a dislocation can persist for hours on
Kalshi while lasting 3.6 seconds on Polymarket is partly that the Kalshi quantity is
not an arbitrage. A persistent overround is not competed away because there is
nothing to compete away. State that rather than letting persistence stand as
evidence of inefficiency.*

## The right financial analogue

A basket whose price must equal the sum of its parts, deviates, and
mean-reverts is **ETF premium/discount** or a **closed-end fund discount**.
Unlike the prediction-market literature, that field *does* study
predictability — e.g. *ETF Arbitrage, Non-Fundamental Demand, and Return
Predictability* — so it is the methodological precedent for "deviation from
parity is a forecastable quantity", and worth citing as such. The
measured α ≈ 0.87–0.92 on MECE dislocation is directly comparable in spirit
to discount mean-reversion coefficients in that literature.

*Worth checking how that literature computes the premium — NAV against a *closing* or
*mid* price, not against last trades — before drawing the parallel too tightly. If it
uses mid, the analogue supports the project's *corrected* measurement rather than its
original one, which is a better position to be in but a different argument.*

## What this makes the MECE contribution — RESTATED

The original three claims, with their current status:

1. ~~**First forecasting model for sum-to-one dislocation in a prediction
   market.**~~ **Keep, but narrow it.** The model forecasts the basket sum of last
   trade prints, ~92.5% of whose deviation is overround. Until the bid-side re-score
   is run, the claim is "first forecasting model for the basket-sum dynamics of a
   prediction-market partition", which is true and defensible. "For sum-to-one
   dislocation" implies mispricing and should wait for the re-score.
2. **Evidence the quantity has structure beyond scalar mean reversion** —
   0.853× an optimal shrinkage oracle on held-out test, replicating val's
   0.851×, with the incremental gain stable at ~14.8% across splits that
   offered different amounts of reversion. **Stands**, with the graph ablation
   attributing ~92% of the margin to the cross-sectional structure.
3. **A cost-aware verdict the detection literature cannot give**, since AFT
   charges no fees at all and the NBA paper treats depth rather than fees
   as the binding constraint. **Stands, and is now much stronger than written.**
   The verdict is not merely "costs exceed the edge" but "the edge *is* the cost" —
   a decomposition, predicted in advance and confirmed. This has become the
   project's lead contribution and this document originally listed it third.

**A fourth, added:** a measurement finding that generalises beyond this venue.
Any study measuring a no-arbitrage identity from trade prints rather than from
quotes will inherit the same bias, in proportion to the order-flow imbalance and
the spread. The correction is arithmetic (`h(2p−1)` per leg) and the prediction was
stated before the measurement.

## A limitation this literature exposes in our own work

The NBA paper's depth finding is a direct warning. **76.9% of its
opportunities were capped near 14.8 shares.** This project's PnL assumes
**100 contracts per leg** filling at the touch, on a venue with no depth
data available to us.

If Kalshi's MECE legs are anything like that shallow, the per-trade dollar
figures throughout `mece-pnl-result.md` and `pnl-scorecard.md` are scaled
to a size that cannot actually be executed. The *ratios* (model vs random,
model vs oracle) survive, because every strategy is scaled identically —
but the dollar amounts do not.

This must be stated as a limitation. It does not change any conclusion,
since every conclusion is already negative on profitability, but a positive
result at 100 contracts/leg would have needed depth evidence to stand.

> **And the *second* limitation the same paper exposed, which this document did not
> extract at the time.** The NBA paper's detection condition is
> `Ask_A + Ask_B < $1` — **asks**, not last prints. It had already made the
> measurement choice this project had not: to test an executable condition you must
> use quotes on the side you would transact. The paper was read, the depth warning
> was taken, and the measurement warning sitting in the same equation was not. It
> took a further two weeks and a reader's scepticism to reach it independently.
>
> The lesson for the related-work chapter: when a neighbouring paper measures the
> same constraint differently from you, treat the *difference in measurement* as a
> finding to explain, not as a detail of their setup.

## The overround literature — the lead that should have been followed first

The original "honest limits" section listed, among things not covered:

> the sports-betting **overround** literature — where the sum of implied
> probabilities across runners is the same statistic and has decades of study,
> including Whelan's own *Estimating Expected Loss Rates in Betting Markets* — [is]
> the most likely place for a prior forecasting result to be hiding, and should be
> searched before any novelty claim is written down.

**This was exactly right and the reason was better than stated.** In sports betting,
the sum of implied probabilities across mutually exclusive runners exceeding 1 is not
an anomaly to be explained — it is the **bookmaker's margin**, the overround, and it
is the first thing that literature teaches. A basket of mutually exclusive outcomes
whose prices sum to more than $1 is the textbook object of that field.

This project spent several weeks treating a +5.25¢ mean basket overround as a
candidate arbitrage before deriving, from `taker_side` shares and the half-spread,
that it is the exchange-traded analogue of exactly that margin: the aggregate of
each leg's last print sitting on the ask rather than at mid. The derivation is sound
and the prediction-then-measurement is good method. But **the phenomenon had a name
and a literature the whole time**, and one search would have found it.

**Two consequences:**

1. **Cite it.** The finding is much stronger framed as "the exchange-traded analogue
   of the bookmaker's overround, measured and decomposed" than as a novel artefact.
   It connects the project to decades of work and pre-empts the obvious examiner
   question. Whelan is already cited elsewhere in this project, which makes the
   omission more awkward, not less.
2. **Search it before writing any novelty claim**, as the original note said. The
   overround literature may well contain prior work on forecasting the margin's
   dynamics, which would bear directly on contribution claim 1 above.

## Honest limits

Five queries, three papers read. Not covered: pre-2020 prediction-market
literature (IEM, Intrade, TradeSports), the sports-betting overround
literature (see above — no longer optional), and the limit-order-book deep
learning literature.

**Status of the overround search: still not done.** It is the highest-value
remaining literature task and should precede the related-work chapter.
