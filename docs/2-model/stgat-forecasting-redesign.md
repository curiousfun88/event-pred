# Redesign: from masked reconstruction to arbitrage forecasting

Written 2026-09-19, after the evaluation in `stgat-results-and-limitations.md`
established that (a) selection among *observed* arbitrage opportunities is arithmetic
rather than prediction, and (b) the only unobservable terms in the problem are the
execution cost and the future state of the market.

Revised the same day after re-reading the original FYP proposal (§2 Background
Motivation, §3 Project Idea), which reframes the whole diagnosis. **§0 is the most
important section of this document** and should be read first.

> **Status: this redesign was carried out.** The head, the targets and the baselines
> below are what the current pipeline implements. Outcomes have since been measured,
> and they are recorded inline at each section rather than left as open proposals.
> Two of the document's hoped-for routes are closed (the one-leg reversion trade, §0a;
> the maker route, §8) and the primary target changed from the ladder gap to the MECE
> basket sum. What the model actually achieved is in `mece-test-result.md` and
> `mece-graph-ablation-result.md`.

---

## 0. THE DIAGNOSIS: a structural relationship removed the prediction problem

The proposal's subject is **statistical arbitrage** — pairs trading, in which
"deviations from this relationship are interpreted as temporary mispricings that will
eventually revert." The profit comes from **reversion**.

Moving from correlated pairs to MECE/ladder was correct for the structural gap the
proposal identifies in §2.2 — "dependencies such as mutual exclusivity and conditional
outcomes are rarely formalised in a way that can be incorporated into a trading
strategy." MECE *is* mutual exclusivity; the ladder *is* conditional outcomes. A
structural identity is also strictly stronger than an estimated cointegration
relationship: exact rather than fitted, and it cannot break down.

**But it silently changed the nature of the problem.** A structural identity carries a
*guaranteed* payoff, and a guaranteed payoff is what makes selection arithmetic
(results doc §3e). The certainty that made the relationship reliable is the same
property that removed everything there was to predict.

| classical pairs trading | this project as built |
|---|---|
| cointegration relationship | MECE sum-to-1 / ladder monotonicity |
| relationship estimated, can break | relationship exact, cannot break — **stronger** |
| spread = deviation from relationship | gap / basket deviation |
| entry: spread exceeds *k*σ | violation exceeds threshold |
| **profit: the spread reverts** | **replaced by hold-to-settlement** |
| risk: it fails to revert | eliminated — but at the cost of two legs |

The entry signal was kept and the reversion trade was replaced by holding to
settlement. That substitution is what forces **two legs**, and two legs of measured
spread is the entire −$15,700 in the results doc.

**What restoring reversion buys.** "Will this deviation revert, and how fast" is not
observable at *t*. No arithmetic produces it. It is a real prediction target, it is
what the proposal always claimed, and it is what an ST-GAT is for.

**This diagnosis held up, and the table above is still the right framing for the
methods chapter.** The reason to keep it: it explains why the project ended up
measuring a *forecasting* result rather than a trading one, and it does so from the
structure of the problem rather than as an excuse after the fact. What the later work
added is a third column the table did not anticipate — the deviation being measured
turned out to be mostly **bid/ask position**, so neither the reversion trade nor the
hold-to-settlement trade had the payoff both columns assume. See
`spread-artefact-finding.md`.

### 0a. The one-leg reversion trade — NOT PURSUED

This also gives the model its only defensible job in a trading strategy, using the one
capability that is already proven (results doc §2: 4.2× better than any baseline at
ladder fair value).

A ladder violation means rung A is underpriced, or rung B is overpriced, or both. The
naive rule cannot tell which — it sees only the difference. A fair-value model can.
If the mispricing is **concentrated in one leg** (A is 8¢ cheap, B is fair), the
reversion can be captured by trading **that leg alone**:

- **one leg of spread instead of two**, against a cost that currently exceeds the
  signal;
- the edge comes from identifying *which* leg and *by how much*, which is exactly
  what no naive rule can compute;
- it is the statistical-arbitrage trade of the original proposal, not a riskless one.

**The trade-off must be stated plainly: this surrenders the guarantee.** A single leg
is directional and carries variance the two-leg arbitrage does not. That is what makes
it *statistical* arbitrage — and what makes it a prediction problem.

> **Outcome: not pursued, and the premise did not survive.** Two things closed it.
>
> First, the "4.2× better than any baseline" figure is **reconstruction-era**, measured
> against reconstruction baselines with the constrained `LadderOutputHead`. Under the
> residual-head redesign the model's advantage against the right baseline
> (persistence) is far smaller, and the whole point of §5's zero-init head was to stop
> flattering comparisons like that one. Do not carry 4.2× forward.
>
> Second, `ladder-conclusion-overturned.md` §5 established that the ladder model cannot
> tell *which pairs are about to reprice*, and the one-leg trade needs strictly more
> than that — it needs to know which *leg* moves and when. The all-pairs ratio is
> minimised at epoch 0 under every mover weight. There is no configuration to build
> this on.

---

## 1. What the model currently computes, and why it is not forecasting

Current objective (`MaskedLegReconstructionObjective`): at timestamp *t*, hide a
random subset of legs and reconstruct their prices **at the same *t***, using the
rest of the graph at *t* plus causal history. Evaluation compares `fair_a` against
`prices[t, a]` — identical *t*.

This is reconstruction (nowcasting). The train/val/test split is temporal — train on
May+June, select on July+August, test on September — so the model is validated
**out-of-sample in time**, which is a real and non-trivial property given near-total
node churn between months. But out-of-sample in time is not the same as forecasting,
and the two are routinely conflated. The precise claim available at the time was:

> validated on a later period, on a contemporaneous reconstruction task.

*(Superseded: the pipeline now forecasts `t+h` and the claim is a forecasting one. The
distinction drawn here is still worth making in the methods chapter, because it is the
distinction the reconstruction-era checkpoints do not satisfy and several early
evaluation scripts still read those checkpoints.)*

## 2. The canonical STGNN formulation

Across the traffic-forecasting literature the task is

```
f(A, X_{t-P+1:t})  ->  X_{t+1:t+Q}
```

given P historical steps on graph A, predict Q future steps
([STG4Traffic survey](https://arxiv.org/html/2307.00495v2);
[STGAT, Kong et al., IEEE Access 2020](https://ieeexplore.ieee.org/document/9146162/)).
Standard benchmarks are METR-LA and PEMS-BAY, evaluated at multiple horizons with
MAE / RMSE / MAPE.

*(For where this project's architecture sits relative to that literature — given-graph
vs learned-graph, and what licenses each departure from Kumar et al. — see
`literature-architecture-positioning.md`.)*

## 3. The current work is stage 1 of a documented two-stage pipeline

Masked reconstruction is not an alternative to forecasting — it is the standard
**pre-training** objective for forecasting STGNNs.

[STEP (KDD 2022)](https://dl.acm.org/doi/10.1145/3534678.3539396) masks 75% of
time-series patches and reconstructs only the masked positions, explicitly so the
encoder learns "high-level semantics" rather than trivial interpolation; the
pre-trained encoder is then **frozen** and its representations fused into a
downstream forecasting STGNN predicting 12 steps ahead. The same
masked-pretrain-then-forecast pattern appears in
[GPT-ST (NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/file/de7858e3e7f9f0f7b2c7bfdc86f6d928-Paper-Conference.pdf)
and [STD-MAE (IJCAI 2024)](https://arxiv.org/html/2312.00516v3).

**Therefore:** the trained checkpoint (`best.pt`, val_loss 0.0301, 4.2× the best
reconstruction baseline) is a pre-trained encoder with a documented role. Stage 2 is
a head and a target, not a rewrite.

> **What actually happened: the two-stage plan was dropped, and that is fine.**
> `train_forecast.py` trains the forecasting objective **from scratch**; it does not
> load the reconstruction checkpoint as a frozen encoder. The citations above remain
> useful for justifying masked reconstruction as a *legitimate* objective in the
> methods chapter, but **do not claim a STEP-style pre-train/fine-tune pipeline**,
> because none was run. The reconstruction era is honestly described as an earlier
> design that was replaced, not as stage 1 of the current one.

## 4. Why forecasting escapes both negative results

**§3a of the results doc (output-head degeneracy) does not apply.** The identities
`Σ(observed − predicted) ≡ sum − 1` and `model_gap ≥ g/2` arise *because* the heads
are constrained to satisfy no-arbitrage by construction. A forecasting head that
predicts raw future prices per node carries no such constraint, so its residual is
not forced to track the gap.

**§3e (selection is arithmetic) does not apply.** That argument turns on every term
being observable at decision time. `gap_{t+k}` is not observable at *t*. The model is
no longer competing against a calculator.

**The spread target folds into the same architecture.** Spread is another node-level
quantity at *t+h*. Forecast price and spread jointly and the trading rule becomes

```
predicted_gap x contracts  >  fees + predicted_spread x contracts
```

which is exactly the ex-ante rule of results §1b with both unknowns supplied by the
network instead of by hindsight. §1b prices the spread half at **$6,755-$19,746 per
month**.

> **Both escapes held. The spread-forecasting extension was never built, and the
> $6,755–$19,746 figure should not be quoted.** That number values the ability to
> forecast the spread *given* that crossing it is the only obstacle to a real edge.
> `spread-artefact-finding.md` shows the spread is not merely a cost sitting on top of
> a real dislocation — it substantially *is* the apparent dislocation. Perfect
> foreknowledge of the spread would not produce the payoff this section prices, because
> subtracting the spread leaves −0.07¢ before fees.
>
> The cost model was instead handled by measurement (`build_mece_leg_spreads.py`) and
> by making the model-vs-control comparison **paired**, so the spread term cancels
> exactly. That turned out to be worth more than forecasting it: it is why the
> +$0.170/trade result is provably cost-model invariant.

## 5. Proposed design — IMPLEMENTED

**Inputs.** P snapshots of history (2-hourly graph -> P=12 is 24h, P=84 one week —
the existing chunk length). Same graph, same typed edges, same features.

**Backbone.** Unchanged: `TypeSpecificProjection` -> `TwoChannelSpatialAttention` ->
`TemporalAttention` (already causal, which is required for forecasting and is a
property the current setup does not exploit).

**Head.** New, and deliberately **unconstrained**: per-node price at each horizon
`h = 1..Q`. Do NOT reuse `LadderOutputHead` or `MeceOutputHead` — their constraints
are the cause of the degeneracy.

> **Built as `ResidualForecastHead`, with one addition this section did not
> anticipate and which turned out to be the keystone**: `pred = base_price + delta`,
> with the final `Linear` **zero-initialised in weight and bias**. The model therefore
> *starts* exactly at persistence, so every ratio reported anywhere in the project is
> attributable to learned structure rather than to initialisation. It is also what
> makes the shrinkage-oracle comparison interpretable, and it is what
> `verify_pipeline.py --only residual_head` asserts (max|pred − price| == 0 at init).
> Justified in the literature by ReZero and Fixup; see
> `literature-architecture-positioning.md`.

**Targets, in increasing order of directness:**

| target | rationale | risk | outcome |
|---|---|---|---|
| price at *t+h* per node | most faithful to the STGNN literature; gap derived as `p_B - p_A` | price levels are near-random-walk; persistence is brutal | **built**; node-level moved-stratum ratio ~0.990×, i.e. essentially nil |
| **gap at *t+h*** per ladder edge | relative quantity, far more forecastable than levels; directly the object of interest | needs edge-level head | **built**; unforecastable in deployable form — timing not in features. CLOSED |
| **time-to-reversion** of an open violation | the pairs-trading target of §0a; drives the one-leg trade | censoring at settlement | **not built** — §0a closed |
| spread at *t+h* per node | the §1b unknown, worth $6,755-$19,746/mo | labels sparse (1.6% of parquet rows) | **not built** — see §4 note; measurement + pairing replaced it |
| P(violation at *t+h*) | classification; matches "predict arbitrage opportunities" literally | class imbalance | **built as `evaluate_violation_prediction.py`**, reconstruction-era; did not replicate val→test |

Recommended: **gap at *t+h*** as primary, spread at *t+h* as secondary, both from the
same backbone. Report node-level price MAE too, for comparability with the STGNN
literature.

> **The primary target changed.** The recommendation above put the ladder gap first;
> the ladder is now a closed negative. The primary target is the **MECE basket sum at
> *t+h***, where the model reaches 0.851× the shrinkage oracle (0.853× on test), and
> `--w-ladder 0`. The recommendation was reasonable on the evidence available when it
> was written — the reversal came from the frozen/moved stratification, which did not
> exist yet. Recorded rather than quietly edited, because the ordering of these two
> targets is the single biggest course change in the project.
>
> One qualification on the surviving target, added later: the basket sum is measured
> from last trade prints, ~92.5% of whose deviation is overround. Re-scoring against
> **bid-side** basket sums is the open item that decides whether the 0.851× is
> forecasting mispricing or microstructure.

**Evaluation, two layers.**

1. *Literature-comparable*: MAE / RMSE / MAPE per horizon, against the baseline
   ladder in §6.
2. *Economic*: of the violations predicted at *t* for *t+k*, how many materialise,
   and what is the PnL of trading them under measured spreads — scored with the same
   cost model as `evaluate_arbitrage_ladder.py` so the numbers sit in one frame.

*Both layers were built. Layer 2's answer is negative and is the thesis's central
finding; see `settlement-arbitrage-result.md` §6.*

## 6. Baselines that must be beaten (decided BEFORE training)

This list exists because of correction §5.6 in the results document: *a filter that
beats "no filter" has not been shown to beat "the obvious filter."* The obvious
filter is named here, in advance, so the result cannot be graded against a straw man.

1. **Persistence / random walk** — `gap_{t+k} = gap_t`. In financial series this is
   the hard baseline, and in a near-efficient market it is often unbeatable. **This
   is the number that decides the thesis claim.**
2. **Historical average** — per ladder family, per time-of-day.
3. **VAR / ARIMA** on the gap series.
4. **Non-graph LSTM** on each edge independently — isolates whether the *graph*
   contributes anything.
5. **Non-attention graph model** (STGCN / Graph WaveNet class) — isolates whether
   *attention* contributes anything.

Baselines 4 and 5 are what convert "my STGAT works" into "the spatial-temporal
attention is what makes it work," which is the architectural claim the project
actually needs.

> **Status of each, and this is the section an examiner will check:**
>
> 1. **Persistence — beaten.** 0.796× on val, 0.819× on test. Committing to this in
>    advance was the single best process decision in the project.
> 2. **Historical average — not run.** Superseded by something strictly harder: the
>    **optimal shrinkage oracle**, `α·dev_t` with α fitted *on the split being scored*,
>    i.e. with hindsight. The model beats it by 14.9% / 14.7%. A per-family historical
>    average cannot be stronger than a hindsight-fitted scalar on this target, so
>    dropping it costs nothing and should be said that way rather than left blank.
> 3. **VAR / ARIMA — not run.** Same argument: on a near-martingale, the shrinkage
>    oracle is the relevant linear competitor and it is already fitted with hindsight.
>    Worth one sentence of justification in the thesis; an examiner may still ask.
> 4. **Non-graph — run, as an ablation rather than an LSTM.** `--drop-edges` removing
>    all three adjacency keys: 0.988× the oracle against the full model's 0.851×, so
>    **the graph supplies ~92% of the margin**. Caveat: the no-graph run had not
>    converged (best at its final epoch 24), so 0.988× is an upper bound on its ability
>    and 13.7pp an upper bound on the graph's contribution.
> 5. **Non-attention graph model — NOT run, and this is the real gap.** There is no
>    comparison against a published spatio-temporal baseline (STGCN, DCRNN, AGCRN,
>    Graph WaveNet). The architectural claim rests on an *internal* ablation. With four
>    weeks left this stays unrun; the mitigation in
>    `literature-architecture-positioning.md` §6 is to cite the parallel AGCRN result on
>    a related Kalshi task, where no configuration beat predict-zero and the learned
>    adjacency recovered 0 of 4 validated edges — subject to the supervisor agreeing
>    that citing a concurrent project is acceptable.
>
> So of the two baselines that convert "it works" into "the attention is what makes it
> work", one was answered and one was not. Say so plainly in the limitations section
> rather than letting §4's ablation stand in for §5's comparison.

## 7. Feasibility check to run FIRST (`diagnose_persistence.py`)

Before any head is written:

> Of the test-split violations, what fraction are still violations one snapshot
> later? Two? Six? And how does the gap decay over those horizons?

The conditional-survival column **is the mean-reversion curve**: a violation that is
no longer a violation at *t+h* has reverted. The measurement decides which of the two
live strategies the data supports, and they want **opposite** answers:

| outcome | reversion trade (§0a) | maker/forecast route (§8) |
|---|---|---|
| fast decay (half-life 1-2 snapshots) | **live** — deviations revert, trade the reversion | dead — a resting order never fills |
| slow decay / sticky | dead — nothing reverts | **live** — time to rest an order, forecasting well posed |
| no decay at all | dead | dead — hold-to-settlement only; limits-to-arbitrage stands as the final result |

It also *is* baseline 1, so it is not preliminary work; it is the first result. The
framing above was recorded **before** the measurement was run, so that whichever
answer arrives is not retrofitted.

> **The answer arrived and it was none of the three, which is why pre-registering the
> table was worth doing.** The ladder gap is **sticky when pooled and fast-decaying
> conditional on a reprice**:
>
> - pooled α ≈ 0.99 at every horizon — reads as "no decay at all", the dead/dead row;
> - but 75–90% of pair-snapshots are **frozen** (neither leg trades), and a frozen pair
>   has `gap(t+h) == gap(t)` exactly, contributing α = 1 by arithmetic;
> - conditional on a reprice, a +18.5¢ violation collapses to **+0.07¢** — the
>   fast-decay row.
>
> The row that actually obtains is "fast decay, but only in the minority of snapshots
> where a leg reprices, and which those are is not predictable from these features."
> That combination makes both columns dead for the reason neither anticipated: not the
> speed of the decay, but the **observability of its timing**. Full detail in
> `ladder-conclusion-overturned.md`.
>
> Keep this table in the thesis exactly as written, with the outcome appended. A
> pre-registered decision table whose measured answer falls outside all three cells is
> better evidence of honest method than one that lands neatly in a box.

## 8. Why forecasting matters economically: taker to maker — CLOSED

The measured-spread result is that trading every violation loses **$15,700** at full
spread. That entire loss is the cost of **crossing** the spread on both legs as a
taker.

A model that anticipates a violation before it appears permits **resting limit
orders** instead. This does not reduce the spread cost — it reverses its sign. It is
the one mechanism by which the strategy's dominant cost term could become a revenue
term, and it is only reachable through forecasting.

Hypothesis, not result. Requires §7 to show persistence, and a fill model that does
not assume resting orders always execute.

> **Closed, on three independent grounds.** (1) §7's answer removed the predictability
> the route needs. (2) No fill model was built, and the maker fee shape was never
> verified — recorded as provisional in `maker-execution-provisional.md`. (3) The
> deeper problem: if the apparent dislocation *is* the spread, then earning the spread
> instead of paying it does not harvest a dislocation, it just makes you the market
> maker — a different business, with adverse selection as its central risk, and nothing
> in this project measures that.
>
> The honest version of this section's insight survives and belongs in the thesis: the
> strategy's economics are dominated by which side of the spread you are on. The
> project's contribution is showing that this is true to a stronger degree than
> expected — the side of the spread does not merely determine the profit, it
> manufactures the apparent opportunity.

## 9. What would then be claimable

If the forecasting model beats persistence on gap at *t+k*, and the predicted
violations are profitable under measured spreads:

> An STGAT pre-trained by masked reconstruction and fine-tuned for horizon
> forecasting predicts no-arbitrage violations in prediction markets ahead of their
> appearance, beating persistence and non-graph baselines, and converting a
> taker-cost-dominated strategy into a maker-side one.

Or, on the reversion branch of §0a:

> Structural no-arbitrage relations (mutual exclusivity, conditional outcomes) supply
> exact spread definitions where classical pairs trading must estimate a
> cointegration relationship that may break. An STGAT attributes each observed
> violation to the mispriced leg and predicts its reversion, enabling a single-leg
> statistical-arbitrage strategy at half the execution cost of the riskless two-leg
> alternative.

Either is the project's stated aim, stated in a form that survives the controls this
evaluation has already applied to weaker claims. If both fail against persistence, the
finding is that these violations are unforecastable — which, combined with the
limits-to-arbitrage result already established, is still a complete and publishable
thesis.

> **Neither claim is available, and the closing sentence's fallback is not quite right
> either.** The model **did** beat persistence and the non-graph ablation, so the
> violations are not unforecastable. But the predicted dislocations are **not
> profitable under measured spreads**, and no pre-training was used, so the first
> claim fails on two clauses. The second fails with §0a.
>
> The claim that is actually supported:
>
> > Where a market's structure supplies an exact cross-sectional identity, a
> > spatio-temporal graph attention model forecasts the joint dynamics of that
> > structure substantially better than persistence or an optimally shrunk mean
> > reversion, and the graph is what supplies the margin. The identity's apparent
> > violations, however, are dominated by bid-ask overround rather than mispricing:
> > 92.5% of measured deviation is attributable to one-sided trade prints, predicted
> > in advance from the ask-side print share and confirmed to within 1.05¢. At
> > executable quotes the constraint is effectively everywhere-binding. The model's
> > forecasting advantage is therefore real and its economic interpretation is
> > microstructural, and a naive last-trade backtest of the same mechanism
> > manufactures profit that does not exist.
>
> That is a decomposition rather than a strategy, and it is both defensible and
> non-obvious. The document's instinct — "if both fail, the negative result is still a
> complete thesis" — was right, and is the reason the project has something to submit.
> What it did not anticipate is that the negative result would come from the
> *measurement* rather than from the model.

---

## Sources

- [STGAT: Spatial-Temporal Graph Attention Networks for Traffic Flow Forecasting (Kong et al., IEEE Access 2020)](https://ieeexplore.ieee.org/document/9146162/)
- [STG4Traffic: A Survey and Benchmark of Spatial-Temporal Graph Neural Networks for Traffic Prediction](https://arxiv.org/html/2307.00495v2)
- [STEP: Pre-training Enhanced Spatial-temporal Graph Neural Network for Multivariate Time Series Forecasting (KDD 2022)](https://dl.acm.org/doi/10.1145/3534678.3539396)
- [GPT-ST: Generative Pre-Training of Spatio-Temporal Graph Neural Networks (NeurIPS 2023)](https://proceedings.neurips.cc/paper_files/paper/2023/file/de7858e3e7f9f0f7b2c7bfdc86f6d928-Paper-Conference.pdf)
- [STD-MAE: Spatial-Temporal-Decoupled Masked Pre-training for Spatiotemporal Forecasting (IJCAI 2024)](https://arxiv.org/html/2312.00516v3)

*The three masked-pretraining citations (STEP, GPT-ST, STD-MAE) justify masked
reconstruction as an objective but are no longer descriptions of this pipeline, which
trains the forecasting objective directly. Cite them for the former, not the latter.*
