# Split design: corrected to be strictly forward in time

**Supersedes** `mece-yield-by-month.md` §3 ("train on B, hold out A") and
`four-week-plan-and-reframe.md` §4. That design was **wrong for a
forecasting thesis** and is retracted.

---

## 1. What was wrong

The earlier recommendation was: train on block B (2024-11…2025-11), hold
out block A (2022-04…2022-11) as a second test set. Block A is **26 months
earlier than the training data**. For a model whose stated task is
predicting future values, that is a backcast presented as a test set.

It is not information leakage in the narrow sense — the model never sees
block A during fitting — but it breaks the thing a forecasting evaluation
exists to establish: that the model works on data the researcher could not
have seen when the model was built. Applying a 2025-trained model to 2022
inverts that. Any examiner will object, and correctly.

## 2. Corrected design

### Primary: time-ordered splits inside block B, with walk-forward folds

Block B (2024-11 → 2025-11, 13 months, 5,806 basket-days) is one liquidity
regime and is the densest usable window. Split it strictly in order, and
instead of one fixed split use **expanding-window walk-forward**:

| fold | train | val | test |
|---|---|---|---|
| 1 | 2024-11…2025-03 | 2025-04 | 2025-05 |
| 2 | 2024-11…2025-04 | 2025-05 | 2025-06 |
| 3 | 2024-11…2025-05 | 2025-06 | 2025-07 |
| 4 | 2024-11…2025-06 | 2025-07 | 2025-08 |
| 5 | 2024-11…2025-07 | 2025-08 | 2025-09 |
| 6 | 2024-11…2025-08 | 2025-09 | 2025-10 |
| 7 | 2024-11…2025-09 | 2025-10 | 2025-11 |

Every fold trains only on its own past. This does three things at once:

1. **Seven forward test evaluations instead of one.** The PnL and the
   model-minus-control gap become distributions with dispersion across
   folds, not single point estimates. That is the direct answer to "ten
   months is too few": the constraint was never the calendar, it was that
   one split extracted one evaluation from it.
2. **Every month serves as a test month once**, so the whole window is
   used for evaluation rather than 15% of it.
3. **Covers a full winter** (2024-11 → 2025-03), which the five-month
   summer pilot could not. Weather is 58% of the >5¢ opportunity
   population, so the summer-only confound between "does not generalise"
   and "a different season is a different market" is finally resolvable.

Report the per-fold results and their spread. A result that holds in 6 of
7 folds is a far stronger claim than one test month, and a result that
holds in 3 of 7 is something you need to know before the viva.

### Secondary: block A as a labelled backcast, NOT a test set

Block A (2022-04…2022-11) still has value, but only as a **structural
transfer check**, explicitly labelled:

> The block-B-trained model was additionally applied to 2022-04…2022-11, a
> period 26 months before the training window on a venue roughly 60×
> thinner and under the previous ticker convention. This is a **backcast**
> and is not evidence of forecasting performance; it tests only whether
> the learned basket structure holds in an earlier liquidity regime.

Framed that way it is legitimate and interesting. Framed as out-of-sample
test performance it is indefensible. Never merge it into the headline
metric.

Technical risk unchanged: block A families are `HIGHNY`, `HIGHCHI`,
`USDJPY` (pre-`KX`). If `TypeSpecificProjection` or any adjacency builder
keys on family or the `KX` prefix, it will fail or project through the
wrong type. Either map old families to their `KX` equivalents, or report it
as zero-shot transfer to unseen families.

### Not used for training: the 2022-12…2024-10 trough

861 basket-days over 23 months at 8.1¢ median deviation and a 5.5-hour
median leg gap — stale prices, not mispricing. Including it in training
would teach wrong dynamics. It may be cited as a data-availability figure;
it should not be fitted on. An ablation that adds it is optional and
expected to hurt.

## 3. "Is ten months enough?" — two different questions

The worry conflates two things that have different answers.

**For fitting, the data is not scarce.** The model trains on hourly
snapshots across 500–1,100 active nodes per timestep. Block B is roughly
9,000 hourly graph snapshots; that is ample gradient signal for a model of
this size, and the zero-initialised residual head means it starts at
persistence rather than from noise.

**For inference, the effective unit is the basket-day, and it is modest.**
Block B has 5,806 of them, and the PnL confidence intervals are cluster
bootstrapped by basket, so the effective n is the number of distinct
baskets — not the 11,607 basket-hours. This is the number that needs
stating, and the cluster count `k` should be printed alongside every CI.

On current evidence the primary claim is **adequately powered**:
model-minus-control is +0.170 with a cluster-bootstrapped CI of
[+0.107, +0.247], comfortably excluding zero on the five-month pilot
alone. Going to 13 months and 7 folds is not needed for significance — it
is needed for **generalisation**, which is the real content of the
supervisor's objection.

## 4. What is gained immediately

Moving off `PILOT_MONTHS = 2025-05…09` to the full block B:

| | current pilot | block B | gain |
|---|---|---|---|
| months | 5 | 13 | 2.6× |
| basket-days | 3,242 | 5,806 | 1.8× |
| seasons covered | summer only | full year | winter added |
| forward test evaluations | 1 | 7 | 7× |

That is available now with a cache rebuild and retrain — no new data, no
ordering violation.

## 5. Revised Week 2–3

1. Rebuild the monthly bundle `cache/` for 2024-11…2025-11; move
   `PILOT_MONTHS` off the five-month pilot.
2. Implement expanding-window walk-forward over the seven folds. Report
   per-fold PnL, per-fold model-minus-control, and the spread across
   folds.
3. Print the cluster count `k` behind every bootstrap CI.
4. Only then, and clearly labelled as a backcast, score block A.
