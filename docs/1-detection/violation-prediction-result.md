# Can the STGAT identify arbitrage that arithmetic cannot? — test/val result

Written 2026-09-19. Script: `evaluate_violation_prediction.py`. Uses the existing
checkpoint (`best.pt`, epoch 43, val_loss 0.0301); no retraining.

**Outcome in one line: the effect is strong on test, absent on validation, and
therefore cannot be claimed.**

**Note on era.** This used a *reconstruction-era* checkpoint
(`MeceOutputHead` / `LadderOutputHead`), not the forecasting-era checkpoint that
produced the 0.851× result. The two families are not interchangeable — see
`architecture-map.md` §5. Nothing here has been re-run under the residual-head
design, and it need not be: the line is closed.

---

## 1. Why this experiment exists

Every earlier evaluation asked whether the model could improve on a naive rule that
was assumed correct. `diagnose_staleness.py` showed that assumption is false: the
naive rule flags 2,489 violations of which **98.3% are artifacts of comparing two
stale last-trade prints**, and 90% of consecutive snapshot observations show no price
change at all. The comparison operator is not a strong baseline on the real task — it
only looked strong because it was scored against the same stale data that produced it.

That opens a genuine prediction problem:

```
signal at t  : model's estimated gap   vs   the stale arithmetic gap
label at t+k : violation computed only from freshly REPRICED legs
question     : which signal better predicts the violation the market confirms?
```

The target is unobservable at *t*, the baseline is non-trivial, and prediction markets
supply exact ground truth — the structural relation is a logical identity, so a
confirmed violation is unambiguous rather than a residual from an estimated
cointegration relationship. This is the cleanest statement of the project's central
claim that has been tested.

**Architectural note.** `LadderOutputHead` enforces `fair_a >= fair_b`, so within one
forward pass the model's gap is `<= 0` by construction and it can never predict a
violation. Each rung is therefore read from a pass in which only that rung is hidden;
the constraint binds within a pass, not across them, so the cross-pass gap can be
positive.

## 2. Result

**TEST split (September).** Model beats stale arithmetic at all five horizons.

| h | events | confirmed | base rate | stale prec | model prec | lift |
|---|---|---|---|---|---|---|
| 1 | 1,325 | 54 | 4.1% | 7.1% | 9.4% | 1.33× |
| 2 | 1,901 | 102 | 5.4% | 11.0% | 16.9% | 1.54× |
| 3 | 2,273 | 134 | 5.9% | 12.5% | 17.6% | 1.41× |
| 6 | 2,591 | 143 | 5.5% | 13.5% | 18.8% | 1.39× |
| 12 | 2,610 | 128 | 4.9% | 10.9% | **24.4%** | **2.23×** |

Budget sweep at h=12 has the correct shape — **lift is highest at the tightest budget
and decays monotonically**, which is what genuine ranking looks like:

| budget | k | stale | model | lift |
|---|---|---|---|---|
| 1% | 26 | 7.7% | **46.2%** | 6.00× |
| 2% | 52 | 3.8% | 26.9% | 7.00× |
| 5% | 130 | 11.5% | 22.3% | 1.93× |
| 10% | 261 | 8.8% | 13.4% | 1.52× |
| 20% | 522 | 8.2% | 9.4% | 1.14× |
| 50% | 1,305 | 5.9% | 6.4% | 1.08× |

Bootstrap over events (2,000 resamples, budget 119): lift 5th **1.40×**, median 2.07×,
95th 3.40×; model beats stale in **99.9%** of resamples. Interval excludes 1.0.

**VAL split (July + August). It does not replicate.**

| h | lift |
|---|---|
| 1 | 0.67× |
| 2 | 1.00× |
| 3 | 0.91× |
| 6 | 1.00× |
| 12 | 1.67× |

The h=12 budget sweep is incoherent — 1.33× at 1%, **0.35× at 5%**, 0.44×, 0.60×,
0.93× — with no monotonicity and no top-end advantage. Bootstrap: median **1.00×**,
5th percentile 0.21×, model beats stale in **43.5%** of resamples, i.e. a coin flip.
At h=6 it is worse: median 0.80×, 28.7%.

## 3. Reading it

**The claim cannot be made.** This is not "needs more data before claiming" — the
replication was run and it failed. Val is a different two months with almost entirely
different markets, and it is the split the checkpoint was *selected* on, so it should
favour the model if anything.

**What does replicate, on both splits:** both signals beat the random base rate
consistently — the model at 1.9–3.4× on val and ~2–5× on test, the stale rule at
2.0–3.5× on val and ~1.7–2.5× on test.

> Confirmed no-arbitrage violations are partially predictable ahead of the market
> adjudicating them, by both the model and by arithmetic on stale prints. What does
> not replicate is the model being **better at it** than the arithmetic.

That weaker statement is defensible and still non-obvious, given that 98.3% of
apparent violations are stale artifacts.

**Process error, recorded.** Test was run before val. Val should establish and test
should confirm; running it the other way makes the test number tempting in a way it
has not earned, and partially spends the test split for follow-ups. This is the same
discipline failure behind the other reversals in `stgat-results-and-limitations.md`
§5.5–§5.9. This is the origin of the project convention that splits run val-first and
strictly forward in time.

## 4. The one diagnostic still worth running — now below the cut line

The test advantage rests on 26 alerts at the 1% budget. Two very different stories fit:

- **concentrated** — one ladder family having an unusual month, in which case it is an
  artifact and the matter is closed;
- **broad** — spread across families and dates, in which case test and val genuinely
  differ and the question becomes *why*, answerable by adding months rather than
  abandoned.

`evaluate_violation_prediction.py` now reports the series/day composition of the top
alerts plus a **leave-one-series-out** lift. Validated against synthetic data: it
collapses a planted single-family artifact (1.19× → 0.74×) and preserves a broad
effect (1.76× → 1.70×).

```
python evaluate_violation_prediction.py --split test --sweep-horizon 12
```

**Do not spend time on this now.** The diagnostic was written but the question it
settles is about the *ladder* mechanism, which `ladder-conclusion-overturned.md`
closed on independent grounds: the all-pairs ratio is minimised at epoch 0 and rises
monotonically under every mover weight. Whether the 26 test alerts were concentrated
or broad no longer changes any decision. Keep the script and this document as the
record of a non-replicating result honestly reported.

## 5. Bearing on the residual-head proposal — since implemented

`stgat-results-and-limitations.md` §2a proposes `fair = last_value + model_output`.
That change was motivated independently — the model at the time lost 4.4× to its own
last-value baseline — and is unaffected by this result. If anything, the erratic
behaviour of the model's extreme predictions here (46.2% precision at the 1% budget on
test, 3.4% at the 5% budget on val) is consistent with the over-scaling measured in
the price-discovery calibration (predicted moves ~5× too large). The residual
parameterisation directly targets that failure.

**It was implemented** as `ResidualForecastHead` with the final `Linear`
zero-initialised in both weight and bias, so the model *starts* exactly at
persistence. That is what made every subsequent ratio interpretable, and it is what
the 0.851× in `mece-test-result.md` is measured against. The over-scaling is gone.
