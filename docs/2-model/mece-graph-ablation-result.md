# The graph supplies 92% of the MECE forecasting edge

**Status: positive, provisional on two caveats — §4 (convergence) and §5 (what
the basket aggregate actually measures).** This is the ablation that
identifies *where* the model's advantage comes from. It supersedes the earlier
"no detectable effect" ablation note in `stgat-results-and-limitations.md`
§3b, which was invalid — see §6.

## 1. Setup

Paired ablation on the identical val population. `train_forecast.py
--drop-edges ladder_monotonic mece_leg_to_basket mece_basket_to_leg`,
verified at startup by the `BACKBONE WILL SEE: NOTHING -- no spatial
channel at all` line. Everything else unchanged: same split, same
n = 64,717, same baselines.

Because the baselines are computed from the data rather than the model,
they are bit-identical across the two runs, which makes this a clean paired
comparison with no population confound:

- persistence 0.008251
- shrinkage oracle 0.007719 at α = 0.869975

## 2. Headline

| config | best val_mece | vs persistence | **vs shrinkage oracle** | gain over oracle |
|---|---|---|---|---|
| full graph (MECE + ladder channels) | 0.006568 | 0.796× | **0.851×** | **14.9%** |
| **no graph at all** | 0.007624 | 0.924× | **0.988×** | **1.2%** |

Removing the spatial channel raises MECE MSE by **16.1%** and collapses the
margin over the oracle from 14.9% to 1.2%.

**The graph accounts for ~92% of the model's entire forecasting edge.**

## 3. What this establishes

The no-graph model is a temporal model with a residual head. It rediscovers
the optimal shrinkage coefficient and then stops — 1.2% better than a single
scalar fitted with hindsight on the split being scored.

So the contribution is not "a deep sequence model beats mean reversion". It
is specifically the **cross-sectional structure**: legs attending to their
basket hub and to each other. That is the defensible novelty claim, and it
is now measured rather than asserted.

This is also the answer to the standing "why not just run static arbitrage"
objection at the *forecasting* level: the thing the model adds is not speed
and not a better reversion constant, it is a joint view of the basket.

It is worth being explicit that this is a claim about **forecasting the basket
sum**, not about profiting from it. The economic line is closed separately and
negatively (`spread-artefact-finding.md`, `settlement-arbitrage-result.md` §6).

## 4. The first caveat: the no-graph run had not converged

Its best `val_mece` is at epoch 24 — the final epoch — and still descending
(0.007681 → 0.007642 → 0.007624 at epochs 19/20/24). The full-graph run's
best was epoch 11 of 17, comfortably interior.

Therefore **0.988× is an upper bound on the no-graph model's ability, and
13.7pp is an upper bound on the graph's contribution.** Rerunning no-graph to
40–50 epochs would tighten this; with four weeks to deadline it sits below the
cut line, so **quote the figure with this caveat attached rather than
resolving it.** If it were to plateau near 0.98× the claim stands unchanged;
if it drifted to 0.95× the contribution is ~10pp — still decisive, but the
reported figure would need correcting.

## 5. The second caveat, and it is the important one: the graph acts ONLY on the basket aggregate

No-graph node/moved = **0.991×** persistence (n = 194,784). The full model's
moved-stratum node ratio is ~0.990×. Indistinguishable.

So the graph is not improving individual leg forecasts at all. Its entire
contribution is to the **basket aggregate**. Mechanistically coherent: the
hyperedge lets the model coordinate errors *across* legs so the sum is
correct even where individual legs are not. That is a sharper and more
interesting claim than "the graph helps".

**But the basket aggregate is now known to be ~92.5% overround.**
`spread-artefact-finding.md` decomposed the basket sum of last trade prints:
68.7% of prints are ask-side, and at a 2.8¢ half-spread a 6-leg basket carries
+6.3¢ of predicted signed deviation from order-flow imbalance alone (measured
+5.25¢). The quantity the graph is helping the model track is therefore
dominated by bid/ask position and order-flow imbalance, not by mispricing.

This does not make the result wrong — the basket sum of last prints is a
genuine observable and the 14.9% margin over an optimal shrinkage oracle is
real. It changes the **economic label**: the honest reading may be that the
model forecasts the *microstructure* of the partition rather than its
mispricing. The two readings are not distinguishable from the runs recorded
here.

**The decisive check, and it outranks everything else in the project:**
re-score the existing checkpoint with the target defined as the **bid-side
basket sum** instead of the mixed last-print sum. This is a re-score, not a
retrain.

- If the model still beats the oracle on bid-side sums, the economic
  interpretation survives and the thesis is straightforward.
- If it does not, the claim becomes "the model forecasts the partition's
  microstructure", which is still a contribution and still 14.9% over an
  oracle, but must be labelled that way.

Nothing else should be built until this is known.

**Also verify before publishing** by reading the full-graph run's
`val_node_ratio` on the moved stratum directly from its `history.csv`,
rather than from the ~0.990× quoted from the test-split summary.

Pooled node ratios (1.018× train, 1.019× val) remain uninformative: 76% of
positions do not move and persistence is exact on those. Report the `moved`
stratum, as established elsewhere.

## 6. The earlier ablation was invalid

The previously logged "graph context has no detectable effect" result came
from a run whose `--drop-edges` option list contained two names that do not
exist in the cache (`leg_to_hub`, `hub_to_leg`) while omitting the real key
`mece_basket_to_leg`. argparse accepted them because they were in `choices`.

Caught because `mece_nograph` came back **bit-for-bit identical to
`mece_noladder`** across all 18 epochs — impossible if the graph input had
changed. Fixed: corrected key names, plus a startup verifier that raises
`SystemExit` on any name absent from the materialised chunk and always
prints what the backbone will actually see.

The `--drop-edges ladder_monotonic` run used a valid key and stands. But the
conclusion drawn from it — "the graph contributes nothing" — had no support,
because the MECE channel was intact in both runs. That conclusion is
withdrawn and reversed by the present result.

## 7. What this does not rescue

Nothing in §4 of `stgat-results-and-limitations.md` or in
`pnl-scorecard.md`. Forecast accuracy and tradeability came apart and stay
apart: the edge is concentrated in baskets too thin to fill, and the
model-minus-oracle per-contract advantage crosses zero at ~25%
participation. The later spread work went further and closed the economic
line entirely (`settlement-arbitrage-result.md` §6).

**This strengthens the forecasting chapter. It does not change the PnL
chapter, and §5 means its own interpretation is not yet settled.**
