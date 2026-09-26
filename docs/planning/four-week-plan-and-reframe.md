# Four-week plan and final reframe (v2)

**Supersedes v1**, which was built around the settlement PnL as the
headline. `spread-artefact-finding.md` removed that, so the priorities
below are reordered. Deadline: late October 2026.

---

## 1. The reframe

**Question:** *Where does a learned spatio-temporal model add value to a
constraint-based market structure, and where does the constraint already
suffice?*

| finding | status |
|---|---|
| Model beats an optimal shrinkage oracle by ~15% (0.851× val, 0.853× test) | **positive, primary** |
| Graph supplies ~92% of that margin (no-graph 0.988×) | **positive, architectural** |
| Model beats its randomised-timing control, +$0.170/trade, CI [+0.107, +0.247], cost-model invariant | **positive** |
| 92.5% of apparent basket deviation is the overround; executable edge is one tick against 1.3–5.8¢ fees | **negative, diagnosed, and a contribution in itself** |
| Ladder forecast undeployable (timing not in features) | **negative, diagnosed** |

The thesis is a **decomposition with a methodological finding at its
centre**: a naive last-trade backtest on prediction-market partitions
manufactures profit that does not exist at executable prices, because the
deviation it measures is order-flow imbalance against the spread. The
prediction was stated in advance (+6.3¢ from a 68.7% ask-side share) and
measured at +5.25¢.

**Do not claim profitability.** Do not claim the model finds arbitrage.

## 2. THE OPEN QUESTION THAT OUTRANKS EVERYTHING

The 0.851× is on the **basket aggregate** metric; the node-level figure is
0.991×, and the ablation notes attribute the graph's contribution
specifically to the basket aggregate. That aggregate is the quantity now
known to be ~92.5% overround.

So the primary positive result may be measuring skill at forecasting
**spread and order-flow dynamics**, not mispricing. The forecasting accuracy
is real either way — the basket sum is a genuine observable — but the
economic label changes.

**Check, before anything else:** re-score the existing checkpoint with the
target defined as the **bid-side basket sum** rather than the mixed
last-print sum. This is a re-score, not a retrain.

- If the model still beats the oracle on bid-side sums, the economic
  interpretation survives and the thesis is straightforward.
- If it does not, the honest claim becomes "the model forecasts the
  microstructure of the partition," which is still a contribution but must
  be labelled correctly.

Nothing else should be built until this is known. Expanding the data window
to improve a result whose meaning is unsettled is wasted effort.

## 3. The data window: recommendation unchanged

**Use 2024-11 to 2025-11 (13 months) with seven expanding-window
walk-forward folds, strictly forward in time.** Full detail in
`split-design-correction.md`; the reasoning is unaffected by the spread
finding:

- densest liquidity regime (5,806 basket-days, 1.8× the current pilot)
- covers a full winter, which the summer-only pilot could not
- seven forward test evaluations instead of one, which is the real answer to
  "twelve months is not enough"
- 2022-04 to 2022-11 retained only as a **clearly labelled backcast**, never
  as a test set

What changed is the *justification*. The window no longer needs to support a
PnL sample; it needs to support forecasting folds. That is a weaker
requirement, so the case for 13 months is if anything stronger.

**New check worth 30 minutes:** run the artefact check per month and report
ask-side share and signed mean deviation by month. If the overround is
stable across block B, pooling is safe. If it drifts with the liquidity
growth inside the window, the target is non-stationary and that is a further
argument for walk-forward, where each fold trains on recent data.

## 4. Schedule, with a cut line

**Week 1 — must**
1. Re-score against bid-side basket sums (§2). Decides what the headline
   result is.
2. Send the data-window memo to the supervisor. His answer gates Week 2 and
   cannot wait.

**Week 2 — must**
3. Rebuild the monthly bundle `cache/` for 2024-11 to 2025-11; move
   `PILOT_MONTHS` off the five-month pilot; retrain.

**Week 3 — should**
4. Walk-forward folds across the seven splits; report per-fold results and
   their spread.
5. Per-month artefact stability (§3).

**Week 4 — must**
6. Write-up. Reserve the whole week; every prior stage has overrun.

**Below the cut line, in order of what to drop first:**
- The 2022 backcast. Promoted in v1, now the first thing to cut: it costs a
  cache build and serves a generalisation claim that is secondary.
- Any further PnL work. The executable edge is one tick; no configuration
  rescues it.
- The 21-month ambition.
- Coverage extension (error was 1.49× signal).
- Re-running the no-graph ablation to convergence.
- Maker execution.

## 5. What to write, in order

1. The constraint and how the basket population was identified.
2. **The measurement finding**: last-trade deviation is dominated by the
   overround; the bid/ask decomposition; the executable edge; fees. Lead the
   results chapter with this.
3. Forecasting accuracy against persistence and the shrinkage oracle, with
   the graph ablation.
4. The model-versus-control timing result and its cost-model invariance.
5. The ladder as a diagnosed negative control.
6. Limitations: the collection funnel (11,607 → 3,354 → 257), the
   composition (58% weather at >5¢), the cross-leg non-simultaneity (median
   406-minute span), and the absence of order-book data.
