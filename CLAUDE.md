# CLAUDE.md — FYP handoff

STGAT over no-arbitrage constraints in Kalshi event contracts. MECE baskets
(N legs, exactly one resolves YES, prices must sum to $1) and threshold
ladders (monotone in strike). Question: **where does a learned model add
value over the constraint itself, and where does the constraint suffice?**
Deadline: late Oct 2026.

## State

**Established (positive)**
- **Headline qualified 2026-09-27 (bid-side re-score, runs/README.md).** On
  test the pooled 0.909x has a cluster CI that includes 1.0 on every seed.
  The whole margin comes from the 18.6% of positions whose basket settles by
  t+h, where the target is exactly $1. On unsettled test positions the model
  scores **1.034x** the oracle (1.006-1.057; val 0.887x). On the bid-side
  target, unsettled, R=1h, it scores **1.465x** (1.42-1.54, CI excludes 1;
  n=117, k=56). The pre-registered rule gives the claim "forecasts basket
  microstructure and settlement convergence", not bid-side dislocation.
- Model beats an optimal shrinkage oracle by ~9%: **0.909x** test (range
  0.883-0.941 over 4 seeds), 0.823x val. This is the causal rerun
  `runs/v2_mece_causal_s0..s3`, pre-registered, with test scored once per
  seed. It replaces 0.851x/0.853x from `v2_mece`, whose inputs leaked
  (RESEARCH_LOG Revisions §7). Oracle's alpha* was fitted on the scored split
  (0.552 test). Under the old partial-basket `legacy` rule the same
  checkpoints score 1.21-1.66x.
- **STALE, from leaky `v2_mece`; re-run on causal checkpoints before citing:**
  (graph ablation only; the control result below was re-run)
  - Graph ablation: no-graph 0.988x vs full 0.851x -> graph supplied ~92% of
    the margin.
- **Model beats randomised-timing control: REPLICATED ON TEST 2026-09-27.**
  +$0.192/trade (4 seeds: 0.179-0.211, every CI above 0, k=312). Causal
  checkpoints, measured spreads, `--min-ttc 3600`, pre-registered. The paired
  design makes it cost-model invariant. It concentrates near resolution
  (+0.254 at ttc 1s, +0.037 at 24h, all 4/4 CIs above 0). The old +$0.170 was
  val-only on the leaky checkpoint; provenance is in
  `logs/v2_forecast/settlement_pnl_val_ttc_sweep.log`. **Strongest positive
  result.**
- **Unsettled-only retrain (last retrain): no skill beyond constraint + family.**
  Test 1.052x the per-series x horizon oracle (1.024-1.074, 0/4 CIs exclude 1),
  0.950x single-alpha, 0.781x persistence.

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
- **Ladder closure STALE (2026-09-27).** "All-pairs ratio minimised at
  epoch 0 (1.0015)" was measured on the leaky cache. There, 57% of scored
  ladder pairs (h=1) were sub-1.5h contracts replayed after close: 583 pairs,
  about 85k frozen copies, 0% moved. Persistence is exact on them, so learned
  reversion could only lose. `cache_causal/` removes them (past-close 0%, was
  66%). The causal MECE checkpoints (ladder weight 0, never selected on the
  ladder) score **0.982-0.993x oracle, 0.966-0.977x persistence** on test
  ladder pairs (n=99,646). This is exploratory: not pre-registered, no val
  figure, no CI, and the moved-pairs lead is 0.4-0.9% (s3 loses at 1.004x).
  Evidence: `logs/v2_forecast/ladder_timing{,_causal}.log`. Reprice timing
  is still not in the features. The no-pivot decision stands. Sub-2h ladders
  are out of scope, because contracts shorter than the 2h grid cannot be
  forecast on it; this is a limitation, not a task.

**Open, in priority order**
1. ~~Bid-side re-score~~ **DONE 2026-09-27**: model loses on the bid side;
   the last-print margin is settlement convergence (above). Open follow-up:
   what lets the model detect imminent settlement with `time_to_close`
   zeroed? Check for a legitimate cue (prices near 0/1) versus a leak.
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
docs/       RESEARCH_LOG.md (chronology + revisions), SCRIPTS.md (script index),
            REPO-LAYOUT.md (map)   1-detection/ 2-model/ 3-economics/ 4-data/
            5-literature/ planning/   reports/ (supervisor reports)
stg_infra/  stg/ (graph build)  model/ (arch, run_guards)  examples/ (probes)
            train_forecast.py  score_forecast.py  evaluate_*.py  diagnose_*.py  verify_*.py
results/    data_audit/ mece/ ladder/ baselines/ pairs_trading/   (results/README.md)
runs/       v1_reconstruction/  v2_*/  -- history committed, .pt local  (runs/README.md)
logs/       v1_reconstruction/  v2_forecast/  -- evidence for reported figures
cache/ data/  local only
```

Run every script from the repo root; all paths are root-relative.
Headline checkpoints: `runs/v2_mece_causal_s{0..3}/best.pt` on `cache_causal/`.
`runs/v2_mece/best.pt` is superseded (leaky inputs).

Key scripts: `examples/mece_sum_to_one_check.py` (basket identification),
`examples/mece_spread_artefact_check.py` (the overround test),
`examples/mece_yield_by_month.py` (window), `evaluate_mece_settlement_pnl.py` (PnL).

## Thesis shape

1. The constraint and how the population was identified.
2. **Lead with the measurement finding**: last-trade deviation is dominated
   by the overround; bid/ask decomposition; executable edge; fees.
3. Forecasting accuracy vs persistence and the shrinkage oracle + ablation.
4. Model vs control, and its cost-model invariance.
5. Ladder: how the post-close leak manufactured a false negative, with the
   small positive result on live pairs as exploratory.
6. Limitations: funnel (11,607 -> 3,354 -> 257), composition (58% weather
   above 5c), cross-leg non-simultaneity (406 min), no order-book data.