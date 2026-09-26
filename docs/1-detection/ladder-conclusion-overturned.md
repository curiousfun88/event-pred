# Ladder: conclusion overturned, then closed

**FINAL.** Supersedes the ladder claims in `stgat-results-and-limitations.md`
(§0, §3b), `ladder-persistence-result.md` and `mece-test-result.md`. Also
corrects two things I asserted while investigating: a constraint-geometry
explanation the data contradicts, and a "not deployable" claim that was
right for the wrong reason.

**Scope, added later:** after the `yes_sub_title` correction the validated
ladder pair pool is **crypto and financials only**. Weather pairs, which
carried the headline violation rate in
`taker-side-investigation-notes.md`, are not a validated monotone chain.
Everything below is measured on the corrected pool and stands; do not
describe the ladder result as a platform-wide property.

## 1. The pooled α was measuring untradedness, not dynamics

| split | horizon | frozen share | pooled α | α on MOVED |
|---|---|---|---|---|
| val | h=1 | 89.8% | 0.9962 | 0.9273 |
| **test** | **h=1** | **85.0%** | **0.9928** | **0.8760** |
| test | h=3 | 79.0% | 0.9886 | 0.8482 |
| test | h=12 | 75.1% | 0.9879 | 0.8797 |

A pair where neither leg reprices has `gap(t+h) == gap(t)` exactly —
verified on both splits, max drift 0.000000. It contributes α = 1 by
arithmetic, not economics.

## 2. Conditional on a reprice, violations collapse (test)

| bucket, h=1 | n | gap t | gap t+h | α | shrink ratio |
|---|---|---|---|---|---|
| +1¢..+3¢ | 110 | +1.90¢ | **−4.85¢** | −2.28 | 0.726 |
| +3¢..+8¢ | 174 | +5.13¢ | **−5.55¢** | −0.94 | 0.741 |
| ≥ +8¢ | 184 | +18.51¢ | **+0.07¢** | 0.01 | **0.421** |

Eighteen cells across two splits and three horizons all agree. Cross-check:
`diagnose_staleness.py` independently reported survival collapsing to 33.5%
at h=1; val's +1¢..+3¢ bucket gives 33.6%. **This market finding is solid.**

## 3. The structure is learnable — conditionally

`--ladder-supervise moved`: `ladder_moved` = 0.958× persistence, **0.971×
the shrinkage oracle** (α = 0.931 once frozen pairs are removed).

## 4. But it cannot be made deployable. Definitively.

Three training configurations, all val:

| config | best all-pairs ladder | best ladder_moved |
|---|---|---|
| moved-only | 1.98× | 0.958× |
| weighted, W=3 | 1.070× | 0.959× |
| weighted, W=2 | **1.058×** | 0.965× |

Under W=2, epoch by epoch:

| epoch | all-pairs | moved | frozen RMSE | budget RMSE |
|---|---|---|---|---|
| 0 | **1.0015** | 0.9867 | 0.59¢ | 0.56¢ |
| 4 | 1.0394 | 0.9689 | 1.29¢ | 0.86¢ |
| 8 | 1.0579 | 0.9648 | 1.48¢ | 0.91¢ |

**The all-pairs ratio rises monotonically with every epoch and falls with
every reduction in mover weight.** Its best value is at epoch 0, where the
zero-initialised residual head is still essentially persistence.

The trade is fixed and unfavourable: from epoch 0 to 8 the model gained
2.2pp on movers and lost 7.8pp on the full population — **~4 units of
frozen degradation per unit of mover gain.**

As W → 0 the model converges to persistence and the all-pairs ratio
approaches 1.0 **from above**. There is no weight at which the curve
crosses 1.0. This is not a tuning problem.

## 5. Why: the model cannot tell which pairs will move

Frozen pairs contribute exactly zero to the persistence baseline (verified:
`0.019325 × 0.1500 = 0.002898`), so a model that predicted "no change"
perfectly on them would score `all_ratio == moved_ratio ≈ 0.96`. That
ceiling is real and reachable in principle.

It is not reached because the reversion the model learns is applied
indiscriminately. Whether a leg reprices is not in the features in any form
the model can exploit, so every unit of learned mean-reversion bleeds onto
the 85% of pairs that will not move — where persistence is exactly right
and any deviation is pure loss.

> **The missing quantity is not the size of the correction. It is the
> timing.** The model knows what happens when a ladder pair reprices. It
> does not know which pairs are about to.

## 6. Economics: the static arbitrage already captures this

The reversion needs no forecast to exploit. Enter a violated pair and hold;
the collapse arrives when it arrives. The ex-ante arithmetic rule values
that at **+$7,703 / +$4,046**, with no model. A round-trip forecast
strategy would cross four times (~18.7¢ before fees) against violations
averaging 1.9–18.5¢.

A working forecast would add capital efficiency — not parking money in the
75–85% that will sit still. Real, but second-order, and now measured as
unavailable.

**Correction to the +$7,703 / +$4,046 figures.** Treat these the way the MECE
settlement figures are treated in `settlement-arbitrage-result.md` §6: they are
computed from *last trade prints*, which sit at bid or ask and never at mid. On
the MECE side the equivalent quantity was measured to be ~92.5% overround, and
the executable edge came out at **−0.07¢** before fees. No equivalent bid/ask
decomposition has been run on the ladder population, so these two numbers are
**unvalidated at executable prices** and must not be reported as realisable.
Given how the MECE case resolved, the prior should be that most of them is
spread. Running `mece_spread_artefact_check.py`'s logic against the corrected
ladder pool would settle it; it is below the cut line because the line is closed
on forecasting grounds anyway.

## 7. Where my reasoning was wrong

- **Constraint geometry.** I argued a ladder is bounded by an *inequality*
  so there is nothing to revert to. Contradicted: on a reprice the gap
  snaps past the boundary. There is an effective attractor.
- **Deployability, first pass.** I said the all-pairs metric is inherently
  diluted. It is not — frozen pairs contribute zero to persistence, so the
  ceiling is `moved_ratio`, not 1.0. The correct reason it fails is §5.
- **Weighted reporting bug.** The mover weight was applied to the reported
  metric as well as the loss, which tripled the persistence baseline
  (`0.006012 = 3 × 0.002004`) and made `val_ladder` read 0.996× when the
  true figure was 1.070×. `vs_shrink` compared a weighted model against an
  unweighted baseline and printed 2.992×, which is not a quantity. Fixed;
  the weight now touches only the loss.

`diagnose_ladder_reversion.py` bucketed by gap *magnitude* to defeat the
dilution objection — a real control, just not for the variable doing the
damage. The moved/flat stratification had already been decisive on the node
forecast and was documented as such, then not applied here.

**One more, added later.** The constraint-geometry argument also appeared in
`mece-test-result.md` as the explanation for why MECE works and ladder does
not ("MECE is pinned to a level, a ladder gap has no anchor"). §7 above
retracts half of that: the ladder *does* have an effective attractor on a
reprice. The surviving distinction is not geometry, it is **timing
observability** — the MECE basket converges by settlement on a known date,
whereas a ladder gap closes whenever someone happens to reprice. Use that
version.

## 8. What the chapter should say

> Ladder violations mean-revert sharply — a +18.5¢ violation collapses to
> +0.07¢ — but only in the 15–25% of pair-snapshots where a leg actually
> reprices. Pooling over the frozen majority yields α ≈ 0.99 and the
> appearance of a random walk; conditioning correctly reveals α ≈ 0.01–0.48
> in the violation buckets, replicated across val and test. A model trained
> on that population beats an optimal shrinkage oracle (0.971×). It cannot
> be deployed: whether a pair will reprice is not predictable from these
> features, so the learned correction is applied indiscriminately and costs
> ~4 units of error on unmoved pairs per unit gained on moved ones. The
> all-pairs ratio is minimised at initialisation and rises monotonically
> thereafter under every mover weight tested. The forecastable object is
> the *size* of the correction; the unforecastable one is its *timing*, and
> only the latter is needed, because the static arbitrage already captures
> the correction by holding.

Add, if the chapter quotes any dollar figure: *the static arbitrage's value is
measured at last-trade prices and has not been repriced at executable quotes;
on the MECE mechanism the same measurement lost 92.5% of its value when it
was.*

## 9. Standing caveats

- Cell sizes 95–251 in the violation × MOVED cells. Credibility rests on 18
  cells agreeing across two splits, not on any single α.
- `ladder_moved` was stdout-only until after the first retrain, so that
  run's selected epoch-8 best is unrecoverable. Fixed.
- All training results are val. No test run was spent on the ladder model,
  deliberately — the all-pairs ratio never crossed 1.0 on val, so there was
  nothing worth confirming.
- The validated pair pool is crypto/financials only (see the header). Any
  category-level claim from before the `yes_sub_title` fix is void.
- The ex-ante dollar figures in §6 are pre-spread-decomposition. See §6.

## 10. Why this belongs in the thesis

The ladder is the project's **negative control**, and it is a good one
precisely because it is so nearly the same object as the MECE basket: same
venue, same features, same graph, same training loop, same residual head, a
no-arbitrage constraint in both cases. One of them the model adds measurable
value to; the other it provably cannot, with an identified mechanism
(magnitude is learnable, timing is not, and only timing pays).

A two-mechanism comparison where one works and one does not, with the
difference traced to a structural property rather than to tuning, is stronger
than either result alone — and it means none of this work is discarded.
