# Ladder monotonicity violations are persistent, not transient

Written 2026-09-19. Script: `diagnose_ladder_reversion.py`. Model-free —
no checkpoint, no training, pure measurement on the val split.

---

## 1. The question

Training reported `alpha = 0.995` for the ladder gap and the model degraded
monotonically against persistence (1.001x -> 1.030x over five epochs). Before
accepting "the gap is unforecastable", one alternative had to be excluded: that
the *metric* was diluted. Half of all ladder pairs sit at a deep non-violation
(gap <= -5c) where nothing happens, and alpha is fitted with each pair weighted
by gap^2, so a single global coefficient is a weak summary of what may be a
strongly nonlinear relationship.

If large violations reverted while ordinary gaps drifted, a pooled alpha of ~1
would hide it — and nonlinearity is exactly what a model can capture and a
scalar cannot.

## 2. The measurement

Gap at *t* against gap at *t+h*, bucketed by the gap at *t*, with alpha fitted
**within each bucket**. Val split, n=89,715 pairs at h=1.

**h=1 (2 hours ahead)**

| bucket | n | share | mean gap t | mean gap t+h | alpha | shrink/persist | P(viol at t+h) |
|---|---|---|---|---|---|---|---|
| gap <= -5c | 44,970 | 50.1% | −0.2971 | −0.2962 | 0.9967 | 0.999 | 0.6% |
| −5c..−1c | 13,147 | 14.7% | −0.0280 | −0.0293 | 1.0393 | 0.997 | 0.5% |
| −1c..+1c | 11,238 | 12.5% | −0.0003 | −0.0014 | 1.0082 | 1.000 | 0.4% |
| +1c..+3c | 4,254 | 4.7% | 0.0198 | 0.0183 | 0.9283 | 0.996 | 98.3% |
| +3c..+8c | 6,662 | 7.4% | 0.0526 | 0.0514 | 0.9787 | 0.997 | 99.0% |
| **gap >= +8c** | 9,444 | 10.5% | **0.2237** | **0.2207** | **0.9908** | 0.996 | **99.1%** |

**h=12 (24 hours ahead)**

| bucket | alpha | mean gap t | mean gap t+h | P(viol at t+h) |
|---|---|---|---|---|
| gap <= -5c | 0.9943 | −0.3036 | −0.3020 | 0.6% |
| −1c..+1c | 1.0204 | −0.0002 | −0.0026 | 1.2% |
| +1c..+3c | **0.8768** | 0.0197 | 0.0177 | 95.7% |
| +3c..+8c | 0.9885 | 0.0527 | 0.0520 | 99.1% |
| **gap >= +8c** | **0.9921** | **0.2253** | **0.2233** | **99.2%** |

Pooled alpha: 0.9962 (h=1), 0.9954 (h=3), 0.9941 (h=12). Optimal shrinkage beats
persistence by **at most 1.6%** in any bucket at any horizon.

## 3. The result

**The dilution hypothesis is rejected. There is no hidden reversion.** Every
bucket at every horizon has alpha within ~12% of 1.0, and the violation buckets
are the *least* reverting of all apart from the smallest.

> A 22.5c monotonicity violation decays to 22.3c over 24 hours — **under 1%** —
> and is still a violation **99.2%** of the time.

These are not transient mispricings awaiting correction. They are stable
properties of the quoted prices.

The only bucket showing meaningful reversion is +1c..+3c (alpha 0.877 at h=12,
~12% decay per day). Those gaps are far below the 4.67c median per-leg spread,
so **the reversion exists precisely where it is economically worthless.**

## 4. Reconciliation with the staleness measurement

`diagnose_staleness.py` found violation survival drops to 33.5% once either leg
**reprices**. This measurement conditions on both legs **trading** (a leg is only
observed when it trades — see `staleness-correction.md`), and finds 99.2%
survival. Both are correct and together give the mechanism:

> Prices are sticky. Legs trade repeatedly at the same price, so violations
> persist. When a price finally moves, the violation usually closes. The gap is
> unforecastable because **price movement** is unforecastable — not because the
> gap lacks structure.

## 5. What this settles

**For the model.** The ladder term should carry weight zero. It is not a
training-metric artifact, a horizon problem or a capacity problem: there is no
linear or bucketed nonlinear structure in the gap to learn. The degradation
observed during training (1.001x -> 1.030x) was the optimiser spending capacity
on an unlearnable target and damaging the others.

`ladder-conclusion-overturned.md` later confirmed this from the opposite
direction: the all-pairs ratio is *minimised at epoch 0* (1.0015) and rises
monotonically under every mover weight tried (W=2: 1.058×, W=3: 1.070×,
moved-only: 1.98×), approaching 1.0 from above as W→0. It is not a tuning
problem. FINAL.

**For the thesis.** This is a result, not a failure, and it completes the
limits-to-arbitrage argument rather than weakening it:

> Ladder monotonicity violations on Kalshi persist rather than closing. They
> persist **because** they are not profitable to arbitrage — the median 4.67c
> per-leg spread exceeds what the median gap pays across two legs. The market
> leaves them alone because closing them loses money, and the prices reflect
> that equilibrium rather than an error.

That is a sharper claim than "arbitrage exists but is hard to capture": it says
the observed prices are a *stable* response to the cost structure, evidenced by
99.2% persistence over 24 hours on actively traded legs.

**Scope correction on the ladder population.** After the `yes_sub_title` fix,
the valid-pair pool is crypto/financials only — *narrower* in category coverage
than MECE, not broader. Any sentence implying the ladder result generalises
across the platform needs that qualification.

**For MECE, by contrast.** Basket dislocations DO mean-revert (alpha=0.870, ~13%
per horizon), and the model beats the optimal shrinkage scalar. The two
mechanisms behave differently and should be reported as such — the contrast is
itself informative, since MECE baskets have a natural anchor at $1.00 while a
ladder gap has none.

**Figure correction.** This document originally cited the MECE margin as
**5.2%** (0.00732 vs 0.00772, n=64,717). That was an intermediate epoch. The
final selected checkpoint is **0.006568 vs 0.007719 = 0.851×, a 14.9% margin**,
replicated at 0.853× on test. Use 14.9% / 0.851×; see `mece-test-result.md`.

**And one qualification on that margin**, added later: it is measured on the
basket sum of last trade prints, which `spread-artefact-finding.md` shows is
~92.5% bid/ask overround. The contrast with the ladder survives — an equality
constraint anchors a level, an inequality does not — but the MECE side's
*economic* label awaits the bid-side re-score.

**Symmetry worth noting.** The mechanism found here (prices are sticky; the
constraint appears violated because prints are stale) and the mechanism found
later for MECE (prices sit at bid or ask; the constraint appears violated
because prints are one-sided) are two instances of the same lesson: on this
venue, **apparent no-arbitrage violations in last-trade data are
microstructure until proven otherwise.** That is the thesis's throughline.
