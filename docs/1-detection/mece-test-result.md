# MECE forecasting: confirmed on held-out test

**Status: positive, replicated.** This is the project's first result that
survives a held-out split against a non-trivial baseline.

Checkpoint: `runs/v2_mece/best.pt` (originally `checkpoints_mece/`), epoch 11, selected on `val_mece`.
Trained with `--w-ladder 0 --select-on mece`. Scored once on test with
`score_forecast.py`, no tuning, no re-runs.

## Headline

| quantity | val (n=64,717) | test (n=41,700) |
|---|---|---|
| model MSE | 0.006568 | 0.00397 |
| persistence | 0.008251 | 0.00485 |
| shrinkage oracle | 0.00772 (α=0.870) | 0.00466 (α=0.917) |
| **model / oracle** | **0.851×** | **0.853×** |
| model / persistence | 0.796× | 0.819× |

Val and test agree to within 0.002 on the ratio that matters. The
selection bias I expected from taking the minimum of thirteen noisy epochs
did not materialise on the oracle-relative metric.

## Why the agreement is stronger than it looks

The two splits are not equally easy. α is the optimal shrinkage
coefficient, fitted on the split being scored, so it measures how much
mean reversion was available to exploit:

| | val | test |
|---|---|---|
| oracle's improvement over persistence | 6.4% | **3.9%** |
| model's improvement over persistence | 20.4% | 18.1% |
| **model's incremental gain over the oracle** | **14.9%** | **14.7%** |

The test period offered *less* reversion (α=0.917 vs 0.870), so the oracle
captured less of it — and the model's incremental contribution held at
~14.8% across both. The edge is not "the model rediscovered mean
reversion", because on test there was substantially less reversion to
rediscover and the margin was unchanged.

## What the target actually is — read this with the headline

The quantity being forecast is the **basket sum of last trade prints**.
`spread-artefact-finding.md` later established that ~92.5% of that quantity's
deviation from $1 is bid/ask overround rather than mispricing: 68.7% of prints
are ask-side, and at a 2.8¢ half-spread a 6-leg basket carries +6.3¢ of
predicted signed deviation from order-flow imbalance alone (measured +5.25¢).

The 0.851× / 0.853× is therefore a real forecasting result on a real
observable, but its **economic label is unsettled**: the model may be
forecasting the partition's microstructure rather than its mispricing. The
decisive check is a re-score of this same checkpoint against **bid-side**
basket sums — a re-score, not a retrain. See
`mece-graph-ablation-result.md` §5, which is where the graph's entire
contribution was localised to this same aggregate.

Nothing above needs retracting. What needs care is the sentence in the thesis
that says what the 15% is a 15% improvement *at*.

## Ladder: confirmed negative

Scored on the same test split, same checkpoint:

- 0.00420 vs persistence 0.00408 = **1.028×**
- vs shrinkage oracle 0.00407 (α=0.990) = **1.031×**
- n = 250,427

α=0.990 on test matches the ~0.99 found in every bucket by
`diagnose_ladder_reversion.py`. The best possible scalar improves ladder
gap prediction by **0.25%** over doing nothing at all. There is no signal
for a model to lose.

**Caveat, stated plainly:** this checkpoint was trained with
`--w-ladder 0`, so it never optimised the ladder gap. Taken alone this
number shows only that a MECE-trained model does not incidentally forecast
ladder. It is evidence because it *agrees* with the earlier run that
trained on ladder directly and reached 1.030× — training on it made no
difference. The two runs bracket the claim from both sides.

`ladder-conclusion-overturned.md` closed this line definitively afterwards,
including under every mover-weighting scheme. It is FINAL.

## The structural explanation

The α gap is the finding, and it follows from the constraint geometry
rather than from the data:

- **MECE baskets are pinned to a level.** The legs must sum to 1 at
  resolution, so a sum of 1.06 has a specific value it must return to.
  There is something to forecast, and the model finds ~15% more of it than
  the best single scalar can.
- **Ladder pairs are bounded by an inequality.** `gap ≤ 0` is satisfied by
  an entire half-line. There is no level to revert to, and α≈0.99 is what
  that looks like empirically.

This makes the two mechanisms a controlled comparison — same model, same
features, same graph, same training loop — rather than one success and one
failure.

## Node-level, for completeness

- moved: 0.990× on 118,559 positions (val: 0.991× on 497,865)
- flat: 74% of positions on test, where persistence is exact by
  construction and no forecast can beat a tie

The pooled node ratio of 1.010× is an artifact of including flats and
should not be reported as a headline. The `moved` stratum is the honest
per-node number.

Note that the node-level figure is ~0.990–0.991× — essentially nil — which is
why the graph ablation localises the entire gain to the basket aggregate. The
two facts are the same fact seen twice.

## What this does NOT establish — and what has since been established

The result is a **forecasting** result, not a trading result. MSE on
basket dislocation is not money. The ladder side already showed what
happens when costs are applied properly: measured spreads (median 4.67¢
per leg) turned +$12,618 into +$948 / −$15,700.

The MECE-side cost-aware evaluation has since been run, and it is negative.
`settlement-arbitrage-result.md` and `spread-artefact-finding.md`: repriced at
executable quotes on the subset where both sides are observed within an hour
(n=662), the basket buys at $1.1334, sells at $0.9993 and settles $1.0000, so
selling nets **−0.07¢ gross** before a 1.3–5.8¢ taker fee. **Do not present
this document as a step toward a profitable strategy.** The ~15% MSE
improvement carried no implication about profitability, and the profitability
question is now answered in the negative.

What remains positive alongside it: the model beats a randomised-timing
control by **+$0.170/trade, CI [+0.107, +0.247]**, cluster-bootstrapped by
basket and provably invariant to the cost model, because the spread term
cancels in a paired comparison.
