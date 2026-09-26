# Sample periods and MECE centrality in the nearest literature

Companion fact-sheet to `literature-mece-positioning.md`, added because the
supervisor's "twelve months is not enough data" objection turns on what
window this phenomenon is normally studied over. Verified 2026-09-26 against
each paper's own text.

**Headline qualification: only ONE of the three treats the sum-to-one
constraint as a primary object.** In the other two it is a minor category
alongside a different mechanism, and in both it turns out nearly empty. Any
window comparison must say so, or it overstates the precedent.

## The three papers

| Study | Window | Length | Sum-to-one component | Model / split |
|---|---|---|---|---|
| *Unravelling the Probabilistic Forest* (AFT 2025, arXiv 2508.03474) | 1 Apr 2024 to 1 Apr 2025 | **12 months** | **co-equal primary type** ("market rebalancing") | none / none |
| *Arbitrage Analysis in Polymarket NBA Markets* (arXiv 2605.00864) | 4 Feb 2026 to 4 Mar 2026 | **1 month** | marginal: 7 episodes across 3,042 markets, vs 290 combinatorial | none / none |
| *Executable Arbitrage and Market Efficiency* (arXiv 2608.00666) | 14 Apr 2026 to 19 May 2026 (order book panel) | **~5 weeks** | marginal: ~3% of value; 97% from a converter primitive | none / none |
| **This project (proposed)** | **2024-11 to 2025-11** | **13 months** | **sole mechanism** | STGAT / 7 walk-forward folds |

All three are on Polymarket. All three are detection studies.

### AFT 2025 — the only genuinely comparable one

Two arbitrage types, defined in the paper:

1. **Market rebalancing** (intra-market): YES prices across mutually
   exclusive outcomes deviate from 1; buy all outcomes when the sum is below
   $1, the reverse when above. *"The profit gained is the difference between
   the sum probabilities and 1."* **This is exactly the MECE mechanism.**
2. **Combinatorial** (inter-market): semantic dependencies across separate
   markets, e.g. an election-winner market and a margin market. A different
   mechanism from this project's.

Scale: 8,659 single-condition and 1,578 multiple-condition markets, 17,218
conditions. Detection via LLM semantic analysis
(DeepSeek-R1-Distill-Qwen-32B) plus historical order-book inspection. Reports
$40M realised profit **aggregated across both types**; the paper does not
break profit down by type, so no per-type share can be quoted.

### The two marginal ones

- **NBA paper**: 173 games, 3,042 markets, 75M+ limit order book snapshots,
  8.59M combinatorial states. Polling cycle 3.6 to 5.5 seconds, flagged by
  the authors as a structural lower bound on observed inefficiency. States
  explicitly: *"there is no train/test split because the analysis doesn't
  involve machine learning or out-of-sample validation."* Its single-market
  (sum-to-one) category is the degenerate two-leg case, and found **7
  episodes**.
- **Executable Arbitrage**: three non-overlapping panels — FPMM regime panel
  (51 mutually exclusive outcome sets, 235 binary markets, ~53,000 trades),
  CLOB transaction panel (32,702 events, 259M trades, listed through 31 Dec
  2025), and the hour-stratified level-2 order book panel above. Depth-aware
  portfolio reconstruction, no trained model. Settlement baskets are ~3% of
  the $1.12M measured value.

## What this supports, and what it does not

**Supports:** there is no precedent in this literature for requiring
multi-year windows. The one genuinely comparable study used 12 months,
slightly less than the proposed 13.

**Does not support:** that the two short windows say anything about
sum-to-one study length. Their windows were chosen for the mechanisms that
dominate their results. Citing "1 month" and "5 weeks" as precedent for this
project would be a misreading, and an examiner who opens either paper would
catch it.

**Does not support** either: that 13 months is sufficient for *training*. A
detection study needs enough observations to characterise a distribution; a
forecasting study needs enough to fit and evaluate out of sample. The
comparison establishes the absence of a demanding precedent, not adequacy.

## The more useful finding

Both Polymarket studies looked for sum-to-one violations and found almost
none: 7 episodes across 3,042 markets, and 3% of $1.12M in executable value.
This project identifies **7,581 fully covered basket-days across 44 months**
on Kalshi, 4,891 of them in the ten months already processed.

**Caution on how far to push this.** The two quantities are different
objects: the NBA paper detects instants at which posted *asks* satisfied
`Ask_A + Ask_B < $1`, polling every 3.6 to 5.5 seconds — a strictly
executable condition at a single moment. This project counts basket-days on
which every leg traded and the *last trade prices* did not sum to $1, with
those prints separated by a median of hours. `spread-artefact-finding.md`
shows that most of that deviation is the bid/ask spread. The honest claim is
that the *structure* is more present on Kalshi, not that the *arbitrage* is.

It does reinforce `literature-mece-positioning.md`'s framing: the Polymarket
literature studies *transient* arbitrage (median persistence 3.6 seconds),
while this project studies *persistent* dislocation, which is the only regime
where forecasting is a sensible question.

## Methodological consequence

None of the three trains a model, so this project has **no split-design
template to inherit from its own literature**. Expanding-window walk-forward
is borrowed from the financial time-series literature and should be cited
that way, not presented as standard practice in prediction-market arbitrage.

## Caveat

Sample periods were read from each paper's own methodology section via its
arXiv HTML or abstract page. The AFT figure (1 April 2024 to 1 April 2025)
comes from its Section 4. Worth spot-checking against the published LIPIcs
version (10.4230/LIPIcs.AFT.2025.27) before the figure goes into the thesis,
since a camera-ready revision could have changed the window.
