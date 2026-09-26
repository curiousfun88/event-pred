# CLAUDE.md — FYP handoff

STGAT over no-arbitrage constraints in Kalshi event contracts. MECE baskets
(N legs, exactly one resolves YES, prices must sum to $1) and threshold
ladders (monotone in strike). Question: **where does a learned model add
value over the constraint itself, and where does the constraint suffice?**
Deadline: late Oct 2026.

## State

**Established (positive)**
- Model beats an optimal shrinkage oracle by ~15%: **0.851x** val, 0.853x
  test. Oracle's alpha* was fitted on the scored split.
- Graph ablation: no-graph 0.988x vs full 0.851x -> **graph supplies ~92%**
  of the margin. Node-level is 0.991x; the gain is in the basket aggregate.
- Model beats randomised-timing control: **+$0.170/trade, CI [+0.107,
  +0.247]**, cluster-bootstrapped by basket. Identical across three cost
  models, because the spread term cancels in a paired comparison -> this
  result is **provably cost-model invariant**. Strongest number in project.

**Established (negative, and the central contribution)**
- **92.5% of apparent basket deviation is the overround, not mispricing.**
  68.7% of trade prints are ask-side; with half-spread 2.8c that predicts
  +6.3c signed mean on a 6-leg basket. *Predicted before measured.*
  Measured +5.25c.
- Executable (legs within 1h, both sides priced, n=662): buy at ask
  **$1.1334**, sell at bid **$0.9993**, settles $1.0000. Selling nets
  **-0.07c gross** before fees. Kalshi taker fee on a 6-leg basket is
  **1.3-5.8c**.
- Gate makes selection *worse*: share with positive executable edge falls
  **84% -> 54%**, because large apparent deviation is produced by wide
  spread and wide-spread baskets execute worse.
- **Profitability claim WITHDRAWN.** Do not reintroduce. Never write
  "arbitrage"; write "dislocation in traded prices".
- Ladder forecast undeployable: all-pairs ratio minimised at epoch 0
  (1.0015), rises monotonically under every mover weight, approaches 1.0
  *from above* as weight -> 0. Reprice timing is not in the features.
  FINAL, closed.

**Open, in priority order**
1. **Re-score existing checkpoint with target = bid-side basket sum** (not
   mixed last prints). The 0.851x is on the basket aggregate, which is the
   92.5%-overround quantity. This decides whether the headline is
   "forecasts mispricing" or "forecasts microstructure". Re-score, not
   retrain. **Do this before anything else.**
2. Rebuild `cache/` for 2024-11..2025-11; move `PILOT_MONTHS` off
   2025-05..09; retrain.
3. Walk-forward: 7 expanding folds inside 2024-11..2025-11, strictly
   forward in time (fold 1 train 2024-11..2025-03, val 2025-04, test
   2025-05; ... fold 7 test 2025-11).
4. Print cluster count `k` alongside every bootstrap CI.
5. Check `KXCLUBWCGAME` leg rules (knockout tie vs winner may resolve on
   different bases -> not a partition). Not in val, so no reported figure
   is affected.
6. Rebuild `mece_leg_spreads.parquet` with `--window` (current file's
   global median 5.613c matches the *pooled* estimate 5.61c, not the
   drift-corrected 4.68c).

## Gotchas that cost hours — do not rediscover

| fact | consequence |
|---|---|
| `TIME_TO_CLOSE` is slot 8, in **SECONDS** ("0 if past") | `--min-ttc 24` is 24 seconds, not hours. 15.9% of the population sat at `ttc==0`: markets already closed |
| `taker_side="yes"` = taker lifted the **ask**; `"no"` = sold into the **bid** | Verified: median `mean(yes)-mean(no)` = **+3.82c** per ticker |
| `--spreads` default was the **ladder** results file (crypto/financials only) | Zero MECE legs matched; everything fell to a global median from another mechanism while being described as "measured". Default now `mece_leg_spreads.parquet`. A coverage guard banners below 50% measured |
| Graph grid is **hourly**; consecutive snapshots of one basket are frozen | Effective independent unit is the **basket-day** (5,806 in block B), not the ~46,000 basket-hours |
| Basket sums from daily **means** are unusable | Legs trade at different times of day; median cross-leg span is **406 min**. Use last prints, and constrain cross-leg span, not within-leg gap |
| Cost is a **sum over ~6 legs** | Reasoning from a median per-leg spread is wrong twice over; the mean governs and the distribution is right-skewed |
| `model/spatial_attention.py` reads only 3 adjacency keys | `mece_leg_to_basket`, `mece_basket_to_leg`, `ladder_monotonic`. Four other edge builders are dead code |
| `cost_gated` 100% win rate is **definitional** | It enters only when \|dev\|*C > *modelled* cost. No CI vs zero is meaningful; the result's exposure is to the cost model, not to sampling |

## Closed decisions — do not relitigate

- **No pivot to cointegration pairs trading.** Needs ~12 months formation
  *per pair* against contracts living days; bounded martingales with binary
  terminal payoffs have no stationary equilibrium; spurious cointegration
  guaranteed across 4.2M tickers.
- **No pivot to the ladder.** Closed (above), and narrower in category.
- **Data window = 2024-11..2025-11 (13 months).** 2021-06..2022-03 has zero
  candidate-leg trades; 2022-12..2024-10 averages 37 basket-days/month at a
  5.5h leg gap (staleness, not mispricing); platform notional grew 369x
  across the archive so pooling crosses liquidity regimes.
- **2022-04..2022-11 is a labelled BACKCAST only**, never a test set —
  it predates the training window.
- **Not doing:** coverage extension (error 1.49x signal), no-graph
  reconvergence, maker execution (fee shape unverified), the 21-month
  ambition.

## Conventions

- Every new script gets `--self-test` exercising planted cases with known
  answers before it touches real data.
- Robustness filters default **off**, so prior figures reproduce exactly.
- Report both filtered and unfiltered; never silently replace one.
- Splits strictly forward in time.
- State predictions *before* measuring them where possible.

## Layout

```
docs/       INDEX.md (chronology), CORRECTIONS.md (retractions + self-caught errors),
            REPO-LAYOUT.md (map)   1-detection/ 2-model/ 3-economics/ 4-data/
            5-literature/ planning/   reports/ (supervisor reports)
            RESEARCH_LOG.md, SCRIPTS.md (narrative + script index)
stg_infra/  stg/ (graph build)  model/ (arch, run_guards)  examples/ (probes)
            train_forecast.py  score_forecast.py  evaluate_*.py  diagnose_*.py  verify_*.py
results/    data_audit/ mece/ ladder/ baselines/ pairs_trading/   (results/README.md)
runs/       v1_reconstruction/  v2_*/  -- history committed, .pt local  (runs/README.md)
logs/       v1_reconstruction/  v2_forecast/  -- evidence for reported figures
cache/ data/  local only
```

Run every script from the repo root; all paths are root-relative.
Headline checkpoint: `runs/v2_mece/best.pt` (was `checkpoints_mece/`).

Key scripts: `examples/mece_sum_to_one_check.py` (basket identification),
`examples/mece_spread_artefact_check.py` (the overround test),
`examples/mece_yield_by_month.py` (window), `evaluate_mece_settlement_pnl.py` (PnL).

## Thesis shape

1. The constraint and how the population was identified.
2. **Lead with the measurement finding**: last-trade deviation is dominated
   by the overround; bid/ask decomposition; executable edge; fees.
3. Forecasting accuracy vs persistence and the shrinkage oracle + ablation.
4. Model vs control, and its cost-model invariance.
5. Ladder as diagnosed negative control.
6. Limitations: funnel (11,607 -> 3,354 -> 257), composition (58% weather
   above 5c), cross-leg non-simultaneity (406 min), no order-book data.