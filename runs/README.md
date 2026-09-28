# Training runs

One directory per run. `history.csv` (and `history.json` for v2) are
committed; weights (`best.pt`, `last.pt`) stay local and are git-ignored.
All runs are on the 5-month pilot (train May–Jun, val Jul–Aug, test Sep 2025).

Directories were renamed on 26 Sep 2026; logs and reports written before then
use the old names (right-hand column).

## v1 — masked-leg reconstruction (superseded)

| Run | Configuration | Outcome | Log | Old name |
|---|---|---|---|---|
| `v1_reconstruction` | `run_real_training.py`, constrained MECE/ladder heads, 50 epochs | Best epoch 43, val loss 0.0301. Checkpoint used by every v1 evaluation | `logs/v1_reconstruction/run_5mo_e60.log` | `checkpoints/` |

## v2 — forecasting (`train_forecast.py`)

| Run | Configuration | Outcome | Log | Old name |
|---|---|---|---|---|
| `v2_forecast` | First forecast run; weights node = ladder = mece = 1, `--supervise active` | 6 epochs; first test of the residual head | `train_forecast.log`, `forecast_smoke.log` | `checkpoints_forecast` |
| `v2_active` | `--supervise active` | 3 epochs | `forecast_active.log` | `checkpoints_active` |
| `v2_strat` | `--supervise all` | 6 epochs | `forecast_strat.log` | `checkpoints_strat` |
| **`v2_mece`** | `--w-ladder 0 --supervise all --select-on mece` | Former headline, **superseded** by `v2_mece_causal_s*` (leaky inputs, see below): epoch 11; 0.851× oracle (val), 0.853× (test) | `forecast_mece.log`, `mece_test.log` | `checkpoints_mece` |
| `v2_mece_noladder` | as `v2_mece`, `--drop-edges ladder_monotonic` | No detectable effect on MECE | — | `checkpoints_mece_noladder` |
| `v2_mece_nograph` | as `v2_mece`, `--drop-edges` with all three edge types (no spatial channel) | Margin over the oracle collapses (~92% of it came from the graph) | — | `checkpoints_mece_nograph` |
| `v2_ladder_weighted` | `--ladder-supervise weighted` | Ladder ratio best at epoch 0 | — | `checkpoints_ladder_weighted` |
| `v2_ladder_w2` | weighted, mover weight 2 | Ladder ratio best at epoch 0 | — | `checkpoints_ladder_w2` |
| `v2_ladder_moved` | `--ladder-supervise moved` | 0.958× persistence on moved pairs only; undeployable | — | `checkpoints_ladder_moved` |

Logs are under `logs/v2_forecast/`. The ablation and ladder runs have no
archived console log; their `history.*` files are the only record of them.
Their exact flags aren't recorded either — the configurations above come
from the run names and the Recess consult (Table 9).

## Clean MECE rerun, first attempt (pre-registered 2026-09-27) -- SUPERSEDED

Stopped before completion and never scored: the leakage audit that followed found
leaky ladder edge features, outcome-based basket selection and partial-basket
scoring. Its runs (`v2_mece_clean_s*`) are not committed and must not be cited.
The protocol below it is kept as a record.

### Original protocol

Two pipeline issues invalidated `v2_mece`'s inputs: resolved markets were
replayed after close (fixed in `cache_fixed/`, commit `2473561`), and
`time_to_close` leaked after-the-fact close times (zeroed in every split,
commit `b78d5da`). `v2_mece_fixed` has the first fix only and must not be cited.

| Run | Configuration |
|---|---|
| `v2_mece_clean_s0` … `s3` | as `v2_mece` (`--w-ladder 0 --supervise all --select-on mece --epochs 25`), `--cache cache_fixed`, slot 8 zeroed, seeds 0–3 |

**Protocol, fixed before training finished:**
1. Checkpoint per seed = that seed's `best.pt`, selected on val MECE as always.
   No seed is dropped or re-run.
2. Test (2025-09) is scored **once per seed** with `score_forecast.py`, no flags
   beyond `--checkpoint` and `--cache cache_fixed`.
3. The reported figure is the **mean and range across all four seeds** of
   model/oracle MECE MSE on test, next to the same statistic on val.
4. Whatever the result, it replaces 0.853× as the headline, with the old figure
   and both pipeline issues disclosed.

## Causal MECE rerun (pre-registered 2026-09-27, before any result)

Supersedes both plans above. Fixes in force (commits `2473561`, `b78d5da`, `b11d30d`):

| Fix | Setting |
|---|---|
| Resolved markets not replayed; post-close trades dropped | `cache_causal/` built by `run_real_training.py` |
| `time_to_close` zeroed as an input, every split | `zero_input_slots=(8,)` |
| Ladder edge features zeroed, every split | `zero_ladder_edge_features=True` |
| MECE membership: hindsight-curated in train months, **causal** in val/test (families qualified on instances known resolved >= 24h earlier; event's own outcome unused) | `results/mece/mece_membership.parquet` |
| Hub leg counts use only legs already listed, every split | `MeceMembership` |
| Score a basket only when every listed leg is present; value legs closed by t+h at settlement | `mece_rule="whole_settle"` |

| Run | Configuration |
|---|---|
| `v2_mece_causal_s0` … `s3` | `train_forecast.py --cache cache_causal --w-ladder 0 --supervise all --select-on mece --epochs 25 --seed {0..3}` (all fixes above are the defaults) |

**Protocol, fixed before training:**
1. Checkpoint per seed = that seed's `best.pt` (val MECE). No seed dropped or re-run.
2. Test (2025-09) scored **once per seed**: `score_forecast.py --checkpoint runs/v2_mece_causal_s{k}/best.pt --cache cache_causal`.
3. **Primary figure:** mean and range across the four seeds of model/oracle MECE MSE on test under `whole_settle`, beside the same on val.
4. **Secondary, for comparability only, never used for any choice:** the same checkpoints scored on test with `--mece-rule legacy`.
5. Also reported: basket-snapshot counts per split under the causal membership vs the old detection-based one.
6. Whatever the result, it replaces 0.853x as the headline, with every fix above disclosed.

### Result (scored 2026-09-27, test scored once per seed as registered)

Test = 2025-09 and val = 2025-07..08, both under `whole_settle`. Model/oracle
is the MECE MSE ratio against the shrinkage oracle, whose alpha is fitted on
the split being scored (val 0.556, test 0.552). Val is the selection split, so
it is optimistic.

| seed | best epoch | val vs oracle | val vs persist | **test vs oracle** | test vs persist | test vs oracle, `legacy` rule (secondary) |
|---|---|---|---|---|---|---|
| s0 | 14 | 0.817x | 0.572x | **0.921x** | 0.621x | 1.465x |
| s1 | 21 | 0.828x | 0.580x | **0.941x** | 0.634x | 1.658x |
| s2 | 24 | 0.813x | 0.570x | **0.891x** | 0.601x | 1.210x |
| s3 | 14 | 0.834x | 0.584x | **0.883x** | 0.595x | 1.325x |
| **mean (range)** | | 0.823x (0.813–0.834) | 0.577x | **0.909x (0.883–0.941)** | 0.613x | 1.415x (1.210–1.658) |

**Primary figure: 0.909x (range 0.883–0.941) on test.** It replaces 0.853x.
All four seeds beat the oracle. The margin is about 9%, down from 15%.

Scored MECE positions (the scorer's `n`; per-split basket-snapshot counts were
not logged separately, and there is no count for train):

| population | val | test |
|---|---|---|
| old: detection membership, `legacy` rule, `cache/` (`v2_mece`) | 64,717 | 41,700 |
| causal membership, `legacy` rule, `cache_causal/` | — | 51,029 |
| causal membership, `whole_settle`, `cache_causal/` (primary) | 58,354 | 37,392 |

The checkpoints fail under the `legacy` rule, even though they beat the oracle
under the rule they were selected on. The oracle itself also changes a lot:
test alpha is 0.552 here against 0.917 in `v2_mece`, so the whole-basket target
mean-reverts much more strongly. Both the model and the oracle gain from that
(0.61x vs persistence, where it was 0.82x). This figure is still against
mixed last-print basket sums; the bid-side re-score is open.

**Ladder, exploratory (not in the protocol above).** Test ladder pairs: 0.985 /
0.982 / 0.983 / 0.993x oracle (alpha 0.942) and 0.970 / 0.966 / 0.967 / 0.977x
persistence (n = 99,646). Moved pairs: 0.995 / 0.991 / 0.992 / 1.004x. The
runs had ladder weight 0, so there is no val figure. The old model was 1.031x.
See RESEARCH_LOG Revisions §7 for why the old ladder population was mostly
contracts replayed after close.

Logs: `logs/v2_forecast/forecast_mece_causal_s*.log` and `score_causal_s*{,_legacy}.log`.

## Bid-side re-score of the causal checkpoints (pre-registered 2026-09-27, before any result)

The 0.909x is measured against last-print basket sums, and about 92.5% of
last-print basket deviation is the bid/ask overround. This re-score asks
whether the forecast still beats the oracle when the target is the
**bid-side** basket sum, the side a basket seller would actually trade at.
It is a re-score, not a retrain: the same four `best.pt`, `cache_causal/`,
and the same basket positions `score_forecast.py` selects (`whole_settle`,
`--supervise active`).

**Leg bid.** The bid is taken from `yes_price` of the latest trade with
`taker_side == "no"` (the taker sold into the bid). Only trades at or before
the end of the snapshot window count, and bid prints from the previous month
may carry into the first window. The bid's age is the window end minus that
trade's time.

**Target at t+h.** For a leg settled by t+h, the target is its settlement
value (1 or 0), as under `whole_settle`. For any other leg, it is the leg's
bid at t+h.

**Eligible basket-position.** It must be one `whole_settle` already scores.
In addition, every leg not settled by the end of its window must have a bid
of age <= R, both at t and at t+h. **Primary R = 1h.** Sensitivity: R = 30min
and 2h, which are not used for any choice.

**Forecasts, all of the bid-side basket sum at t+h:**
- persistence: `B(t)`, the sum of leg bids at t (settled legs at t take their settlement value)
- model: `B(t) + (S_model(t) - S_last(t))`. This is the model's predicted
  change in the last-print basket sum, applied to the bid level. It rests on
  Roll's (1984) decomposition, trade price = efficient price +/- half-spread,
  so the half-spread cancels in the change if the spread is stable over h. It
  fails if the spread moves over h. That is a stated limitation.
- oracle: `1 + alpha * (B(t) - 1)`, with alpha fitted on the scored split and
  sample (optimistic, as before)

**Reported, per seed and as the mean and range over the 4 seeds:**
1. **Primary:** model/oracle MSE on the bid-side target, R = 1h, pooled over
   horizons, on val (2025-07..08) and test (2025-09).
2. The same split by stratum: **no leg settled by t+h** vs **some leg
   settled**. Settled legs pin the target to $1 mechanically, so the
   no-settled stratum is the one that measures forecasting of traded prices.
3. The last-print ratio recomputed on the same bid-eligible subset. This
   separates a change of population from a change of target.
4. A 95% cluster bootstrap CI by basket (event) on model/oracle, with alpha
   refit per resample, and the cluster count `k` printed.
5. Coverage: bid-eligible positions as a share of the `whole_settle` positions.
6. Reproduction guard: the script's last-print branch, on all positions, must
   match `score_forecast.py`'s MECE (model, persistence, n) exactly, or the
   run aborts.

**Order.** Val is run first, then test, once per seed. There is no retry and
no change of R, target or strata after seeing val.

**Prediction, stated before measuring.** On the bid-side target the margin
over the oracle shrinks from 0.909x toward 1.0. Most of what remains sits in
the some-leg-settled stratum. In the no-settled stratum the model is within
+/-3% of the oracle (0.97-1.03x). If instead no-settled is clearly below 0.97x
on test with a CI excluding 1.0, the headline is "forecasts traded-price
dislocation, bid side". Otherwise it is "forecasts basket microstructure and
settlement convergence".

Script: `stg_infra/score_mece_bidside.py` (with `--self-test`). Logs:
`logs/v2_forecast/bidside_{val,test}_s{0..3}.log`.

### Deviations, disclosed before test was scored

1. **Bug fix after seeing val s0.** The first val s0 run crashed in the
   some-settled bootstrap. On val, every some-settled position has all legs
   settled, so the target is exactly $1. The alpha = 0 oracle is then exact
   and model/oracle is undefined (0/0). The script now reports that stratum as
   undefined instead of crashing. R, target, strata and forecasts are
   unchanged. The partial output that was seen: val s0, R = 1h, all 24.5x
   (dominated by the settled stratum), no-settled 1.575x on n = 213 (74
   baskets, 0.4% coverage).
2. **Added after seeing val s0, not pre-registered, used for no choice:** the
   already-reported last-print headline split into no-settled vs some-settled
   over all `whole_settle` positions, with no bid filter. Motivation: 19.8% of
   val positions are fully settled baskets with a constant $1 target.
3. **Coverage finding.** Bid prints are sparse. The median age of a basket's
   stalest leg bid is about 16h, and 44% of unsettled val positions have a
   leg with no bid print in the lookback at all. The R = 1h primary is
   therefore estimable on well under 1% of positions. It is run and reported
   as registered anyway, with no change of R.

### Result (val then test, once per seed; logs `logs/v2_forecast/bidside_{val,test}_s*.log`)

The reproduction guard passed on every chunk and horizon. The test last-print
branch matches `score_forecast.py` exactly for all four seeds.

**Primary, bid-side target, R = 1h, model/oracle** (95% cluster CI, k baskets):

| seed | val no-settled | **test no-settled** | test all | test n (no-settled / all) |
|---|---|---|---|---|
| s0 | 1.575x | **1.450x** [1.078, 2.216] | 19.6x | 117 / 1,754 |
| s1 | 1.529x | **1.544x** [1.165, 2.301] | 17.9x | 117 / 1,754 |
| s2 | 1.543x | **1.451x** [1.047, 2.338] | 18.8x | 117 / 1,754 |
| s3 | 1.583x | **1.416x** [1.026, 2.208] | 16.5x | 117 / 1,754 |
| mean (range) | 1.558x | **1.465x (1.416–1.544)**, k = 56 | 18.2x | 0.3% / 4.7% of `whole_settle` |

On the bid side the model is **worse than the oracle** in the no-settled
stratum on every seed, and every CI excludes 1.0. The "all" row is dominated
by fully settled baskets. Their target is exactly $1, so the oracle with alpha
about 0 is nearly exact. The some-settled stratum's ratio is undefined (0/0).
The R = 30min and 2h sensitivities agree: test no-settled 1.53–1.91x and
1.59–1.65x. On the same no-settled subset, the last-print ratio is
0.90–0.95x (alpha 0.896). The model's predicted last-print change does not
carry over to the bid side.

**Post-hoc decomposition of the last-print headline** (added after val s0
was seen, used for no choice), over all `whole_settle` positions:

| seed | val no-settled | **test no-settled** (81.4% of positions) | test pooled (for reference) |
|---|---|---|---|
| s0 | 0.879x | **1.057x** [0.846, 1.447] | 0.921x [0.786, 1.169] |
| s1 | 0.876x | **1.034x** [0.812, 1.429] | 0.941x [0.794, 1.185] |
| s2 | 0.891x | **1.038x** [0.826, 1.419] | 0.891x [0.761, 1.138] |
| s3 | 0.901x | **1.006x** [0.822, 1.344] | 0.883x [0.777, 1.090] |
| mean | 0.887x | **1.034x**, k = 344 | 0.909x, k = 348 |

On test, **the whole 0.909x margin comes from the 18.6% of positions whose
basket settles by t+h.** There the target is exactly $1, and the model moves
toward it (0.11–0.21x persistence). A single-alpha oracle cannot do that. On
unsettled test positions the model does not beat the oracle. The pooled test
CI includes 1.0 on every seed.

**Against the prediction.** I predicted no-settled within 0.97–1.03x. The
observed 1.42–1.54x is worse than that. The pre-registered decision rule gives
the headline **"forecasts basket microstructure and settlement convergence",
not bid-side dislocation.** Caveats: the bid-side no-settled sample is small
(117 positions, 56 baskets) and selected for very active baskets. Bid prints
are not live quotes. The change-based forecast assumes a stable spread.

## Unsettled-only MECE retrain (pre-registered 2026-09-27, before training)

**Why.** On test, the causal checkpoints' whole 0.909x margin came from baskets
that settle by t+h, whose target is exactly $1. A shrinkage oracle fitted per
series x horizon absorbs about half the val margin. This retrain removes
settled baskets from the MECE loss and from selection. It asks whether any
forecasting skill on traded prices remains beyond the constraint plus
contract family. **This is the last forecasting retrain; no further variants
whatever the result.**

| Run | Configuration |
|---|---|
| `v2_mece_unsettled_s0` … `s3` | as `v2_mece_causal_s*` plus `--mece-rule whole_unsettled`: `train_forecast.py --cache cache_causal --w-ladder 0 --supervise all --select-on mece --epochs 25 --seed {0..3} --mece-rule whole_unsettled --checkpoint-dir runs/v2_mece_unsettled_s{k}` |

`whole_unsettled` is `whole_settle` with any basket that has a leg settled by
the end of window t+h dropped. Verified before training: on val with
`v2_mece_causal_s0` it selects exactly the 46,777 unsettled positions, and its
error sums match the independent dump.

**Protocol, fixed before training:**
1. Checkpoint per seed = `best.pt`, selected on val MECE under
   `whole_unsettled`. No seed is dropped or re-run.
2. Val first, then test (2025-09) once per seed:
   `score_mece_bidside.py --checkpoint runs/v2_mece_unsettled_s{k}/best.pt --split {val,test}`.
3. **Primary:** mean and range over seeds of last-print model/oracle on
   **unsettled** positions against the **per-series x horizon shrinkage
   oracle**. That oracle is fitted on the scored sample, so it is optimistic.
   Each seed gets a 95% cluster bootstrap CI by event, with group alphas refit
   per resample, and k printed.
4. **Secondary:** the same against the single-alpha oracle, and model/persistence.
   The bid-side sections the script prints are reported but not used.
5. **Decision rule:** the result is a positive forecasting claim only if the
   test mean is < 0.97x the family oracle **and** at least 3 of 4 seed CIs
   exclude 1.0. Otherwise the claim is "the constraint plus contract family
   suffices on traded prices".
6. **Caveats, stated now:**
   - The unsettled stratum conditions on the basket not settling within h,
     which is not strictly known at t (early closes). It is therefore a
     conditional evaluation, like the moved-pairs ladder metric.
   - September 2025 has now been scored for several model variants. The test
     result carries a multiple-look caveat.

**Prediction, stated before training:** about 0.95–1.05x the family oracle on
unsettled test positions, i.e. no clear positive. That is based on the causal
checkpoints: 1.034x single-alpha on unsettled test, and a val margin that has
been shrinking about 15 points from val to test.

## Settlement-timing control re-run on causal checkpoints (pre-registered 2026-09-27, before any result)

**Provenance of the old figure.** The +$0.170/trade [+0.107, +0.247] is
`evaluate_mece_settlement_pnl.py --split val --max-participation 0.25
--min-leg-volume 20 --min-ttc 3600` on `checkpoints_mece` (= leaky `v2_mece`).
It is one run of a three-setting `--min-ttc` sweep: +0.167 at 1s, +0.170 at 1h,
+0.056 at 24h, with all CIs above 0. It was scored on **val, the selection
split**, and every basket was costed at the global median spread. The output
was recovered from the user's terminal:
`logs/v2_forecast/settlement_pnl_val_ttc_sweep.log`.

**Re-run.** Same settings (`--max-participation 0.25 --min-leg-volume 20`,
h = 1, taker, 100 contracts, entry $0.01, `--n-boot 2000`), on
`runs/v2_mece_causal_s{0..3}/best.pt` with `--cache cache_causal`. The
`--spreads` default is now `mece_leg_spreads.parquet`. That changes absolute
net figures but not the paired gap, where the spread cancels.

| | |
|---|---|
| **Primary** | **test**, `--min-ttc 3600`: `model_timed - random_timed` $/trade, per seed, with the script's basket-clustered 95% CI; mean and range over the 4 seeds |
| Secondary | test at `--min-ttc 1` and `86400` (the full sweep); val at all three for comparability with the old figure |
| Decision rule | directional timing skill replicates if the test mean gap > 0 **and** at least 3 of 4 seed CIs exclude 0 |

**Caveats, stated now:**
- `--min-ttc` reads raw slot 8, built from recorded close times, so it selects
  on after-the-fact information (early closes).
- The paired gap measures timing skill only. Every strategy's absolute net
  remains negative after fees. Profitability stays withdrawn.
- `--n-boot` and the clustering are whatever the script does; k is to be
  printed per CLAUDE.md item 4. If the script does not print k, it is counted
  separately.

**Prediction, before running:** the gap shrinks relative to +0.170. That is
partly because test is held out, and partly because the causal model's
settlement skill is family-level shrinkage, which carries little one-step
timing information. My guess is test mean +0.02 to +0.10, with 2–4 of 4 CIs
excluding 0.

Runs after the unsettled retrain finishes (memory). Logs:
`logs/v2_forecast/settlepnl_{test,val}_ttc{1,3600,86400}_s{0..3}.log`.

### Results (2026-09-27): unsettled retrain and settlement-timing control

**Unsettled-only retrain.** Primary: last-print, unsettled, test, against the
per-series x horizon oracle. Logs: `logs/v2_forecast/unsettled_{val,test}_s*.log`.

| seed | val vs family oracle | **test vs family oracle** (95% CI, k = 344) | test vs single-alpha | test vs persistence |
|---|---|---|---|---|
| s0 | 0.907x | **1.024x** [0.863, 1.329] | 0.924x | 0.760x |
| s1 | 0.940x | **1.074x** [0.856, 1.491] | 0.970x | 0.797x |
| s2 | 0.914x | **1.063x** [0.851, 1.459] | 0.959x | 0.789x |
| s3 | 0.963x | **1.048x** [0.868, 1.391] | 0.946x | 0.778x |
| mean (range) | 0.931x | **1.052x (1.024–1.074)**, 0/4 CIs exclude 1 | 0.950x | 0.781x |

Decision rule (< 0.97x and 3/4 CIs excluding 1): **not met.** On traded prices,
**the constraint plus contract family suffices**; the prediction (0.95–1.05x)
held. This was the last retrain.

**Settlement-timing control** on `v2_mece_causal_s*`, `model_timed -
random_timed` $/trade. Logs: `logs/v2_forecast/settlepnl_{test,val}_ttc*_s*.log`.
The spreads are 100% measured per leg, and the bootstrap clusters by basket
(k = 312 on primary test).

| split, `--min-ttc` | s0 | s1 | s2 | s3 | mean | CIs excluding 0 |
|---|---|---|---|---|---|---|
| **test, 3600 (primary)** | **+0.179** [0.101, 0.272] | **+0.211** [0.125, 0.313] | **+0.180** [0.100, 0.274] | **+0.199** [0.116, 0.299] | **+0.192** | **4/4** |
| test, 1 | +0.237 | +0.277 | +0.242 | +0.262 | +0.254 | 4/4 |
| test, 86400 | +0.042 | +0.022 | +0.043 | +0.041 | +0.037 | 4/4 |
| val, 3600 | +0.198 | +0.223 | +0.195 | +0.217 | +0.208 | 4/4 |

Decision rule: **met.** The directional timing skill replicates on held-out
test with the causal checkpoints. The primary +$0.192 is close to the old val
figure (+0.170), and above my prediction (+0.02 to +0.10), which was wrong.

- **Where the skill sits.** The gap shrinks as baskets near close are
  excluded (+0.25 -> +0.19 -> +0.04). Most of the skill is in timing entries
  near resolution, consistent with the settlement-convergence behaviour
  (RESEARCH_LOG Revisions §7). That behaviour passed the causality and slot-8
  perturbation checks.
- **The caveats stand.** Absolute net is negative for every strategy except
  the cost gate. The model does not improve the gated rule
  (`model_timed_gated - cost_gated` < 0). `--min-ttc` is ex-post cleaned.

## Graph ablation on the causal setup (pre-registered 2026-09-27, before training)

**Question.** Does the graph carry the replicated timing skill (+$0.192/trade)?
The old "graph supplies ~92% of the margin" came from the leaky `v2_mece`
and its val history, so it is stale.

**Fix made first.** Checkpoints now record `drop_edges`, and the backbone
applies it itself (`STGATBackbone.drop_edges`). Every scoring script sets it
from the checkpoint. Before this, a no-graph checkpoint scored by
`score_forecast.py` / `evaluate_mece_*` would have been handed the full graph.
The old 0.988x came from training-time val, where the drop was applied, so it
was not affected. Verified: the attribute drop equals manual edge removal
exactly, and an empty drop reproduces the original output.

| Run | Configuration |
|---|---|
| `v2_mece_causal_nograph_s0` … `s3` | as `v2_mece_causal_s*` plus `--drop-edges ladder_monotonic mece_leg_to_basket mece_basket_to_leg` (no spatial channel; the MECE loss still uses the baskets) |

**Protocol, fixed before training:**
1. Checkpoint = `best.pt` (val MECE, `whole_settle`). No seed dropped or re-run.
2. **Primary:** test, `evaluate_mece_settlement_pnl.py`, same settings as the
   replicated control (`--max-participation 0.25 --min-leg-volume 20
   --min-ttc 3600`). Report the `model_timed - random_timed` mean over seeds
   and compare it with the full model's +0.192.
3. **Decision rule:**
   - **the graph carries the timing skill** if the no-graph mean is <= +0.096
     (<= 50% of full);
   - **the graph is not needed** if it is >= +0.154 (>= 80%);
   - otherwise **partial**.
4. **Secondary, test once:** `score_forecast.py` MECE vs single-alpha oracle
   (`whole_settle`), and `score_mece_bidside.py`'s unsettled vs
   per-series x horizon oracle, each beside the full model's figure. Val
   timing at ttc 3600 is reported for comparability.
5. **Caveat:** this is the fifth family of models scored on September 2025
   (multiple looks).

**Prediction, before training:** the graph carries most of the timing skill.
The timing decision depends on the predicted change in the *basket* sum, and
without MECE edges a leg cannot see its siblings. My guess is a no-graph mean
of +0.03 to +0.10. For forecasting, no-graph will be close to the oracle
(0.97–1.03x single-alpha).

### Result (2026-09-27). Logs: `logs/v2_forecast/{settlepnl_nograph_*,score_causal_nograph_s*,bidside_nograph_test_s*}.log`

Every scoring log confirms the backbone dropped all three edge types.

| | no-graph s0 | s1 | s2 | s3 | **no-graph mean** | full model mean |
|---|---|---|---|---|---|---|
| **timing gap, test, ttc 3600 (primary)** | +0.156 [0.080, 0.246] | +0.171 [0.090, 0.265] | +0.156 [0.077, 0.247] | +0.140 [0.064, 0.226] | **+0.156** (4/4 CIs > 0, k=312) | +0.192 |
| timing gap, val, ttc 3600 | +0.170 | +0.163 | +0.151 | +0.155 | +0.160 | +0.208 |
| MECE vs single-alpha oracle, test (`whole_settle`) | 1.128x | 1.117x | 1.134x | 1.134x | **1.128x** | 0.909x |
| MECE vs persistence, test | 0.760x | 0.753x | 0.764x | 0.764x | 0.760x | 0.613x |
| unsettled vs family oracle, test | 1.220x | 1.218x | 1.237x | 1.222x | **1.224x** (CIs exclude 1, above) | 1.052x (causal) |
| unsettled vs single-alpha, test | 1.102x | 1.100x | 1.117x | 1.103x | 1.106x | 0.950x (unsettled retrain) |

**Decision rule (timing): no-graph +0.156 >= +0.154, so the graph is "not
needed" for the timing skill.** This is marginal: it clears the cut-off by
0.002. The graph adds about +0.036/trade (about 19%), with no CI on that
difference; a paired full-vs-no-graph comparison was not pre-registered. My
prediction (+0.03 to +0.10) was **wrong**. Most of the timing skill comes from
each leg's own temporal history, not from cross-leg structure.

**Forecasting (secondary): the graph matters.** Without it, the model is
*worse* than the single-alpha oracle (1.128x pooled, 1.106x unsettled) and
clearly worse than the family oracle (1.224x, every CI above 1). With the
graph it is 0.909x pooled. The graph is what lets the model match or beat the
constraint-based baselines on price levels. It is not what gives it timing
skill.

## Quoted-price re-runs (pre-registered 2026-09-27, before any result)

The quotes come from hourly top-of-book candles
(`data/quotes/candles_1h_2025-07_09.parquet`, `fetch_quote_candles.py`).
Validation: 98% of scored leg-snapshots are quoted, and the clocks align
(`logs/v2_forecast/quote_validation_*.log`). Checkpoints are
`v2_mece_causal_s{0..3}` throughout. Only the price source changes; each
protocol is otherwise the one already registered above.

### A. Bid-side re-score with quoted bids

`score_mece_bidside.py --bid-source quotes`. A leg's bid is the latest candle
bid at or before the window end, and its age is the window end minus the
candle end. Settled legs take their settlement value, as before, and a bid of 0
is kept.
- **Primary:** R = 1h (the exact-hour candle, or the previous one), no-settled
  stratum, test, model/oracle on the bid target. Report per seed with the
  cluster CI and k, plus the mean and range.
- **Also reported:** R = 0.5h and 2h, the some-settled stratum, coverage, and
  last-print on the same subset. Val is run first.
- **Decision rule** (unchanged): no-settled test mean < 0.97x with 3 of 4 CIs
  excluding 1 means "forecasts traded-price dislocation, bid side". Otherwise
  "microstructure and settlement convergence" stands, now on near-full
  coverage.
- **Prediction:** 1.00–1.15x, i.e. no bid-side skill. The model's predicted
  last-print change is dominated by print side and settlement, and neither
  moves the quoted bid.

### B. Timing PnL at quoted prices

`evaluate_mece_settlement_pnl.py --prices quotes`, with the same settings as
the replicated control (`--max-participation 0.25 --min-leg-volume 20
--min-ttc 3600`, taker, h = 1).
- A sell fills at Σ quoted bids and a buy at Σ quoted asks, at the window end.
  The basket settles at exactly $1.
- The taker fee is charged on the executed price, with no separate spread
  charge. Gross can be negative.
- An event is kept only if every leg is quoted at both t and t+h.

**Primary 1, timing skill at executable prices:** the test `model_timed -
random_timed` $/trade over 4 seeds. It **survives** if the mean is > 0 and
at least 3 of 4 CIs exclude 0.

**Primary 2, economics:** net per trade and total for every strategy, on test.
At quotes, `cost_gated` enters only when the *quoted* executable edge beats
the fee. That is decidable at t, so a positive total would be executable
dislocation at top of book. **It is an upper bound in all cases:** depth is
unknown, the quote is an hourly candle close, and C contracts are assumed to
fill at the best price. **The profitability withdrawal stands** unless a
strategy nets > 0 on test with >= 30 entries **and** > 0 on val. Even then it
is reported as a depth-unverified candidate, never as "arbitrage".

**Secondary:** val, and the `--min-ttc 1` and `86400` sweep on test.

**Guard:** `--prices last` must reproduce the committed test s0 figure
(+0.1792) exactly before any quotes run is read.

**Prediction:** the timing gap shrinks at quotes, to +0.00 to +0.12 with 2–4
of 4 CIs above 0, because entry-price noise no longer cancels. `cost_gated`
fires on under 2% of events, with a total near $0.

Logs: `logs/v2_forecast/{bidside_quotes_*,settlepnl_quotes_*}.log`.

### Results: quoted-price re-runs (2026-09-27)

**Guard passed:** `--prices last` reproduced test s0 at +0.1792 exactly.

**A. Bid-side re-score at quoted bids** (`bidside_quotes_*`). Coverage is 80.2%
of `whole_settle` positions (30,001 no-settled on test, k = 344), against 0.3%
from trade prints. The reproduction guard passed on all 8 runs.

| no-settled, R = 1h | s0 | s1 | s2 | s3 | mean |
|---|---|---|---|---|---|
| val, BID model/oracle | 1.656x | 1.655x | 1.695x | 1.677x | 1.671x |
| **test, BID model/oracle** | **1.832x** [1.59, 2.17] | **1.802x** [1.58, 2.13] | **1.849x** [1.60, 2.21] | **1.805x** [1.58, 2.12] | **1.822x** (4/4 CIs above 1) |
| test, same subset on last prints | 1.001x | 0.980x | 0.983x | 0.954x | 0.980x |

Decision rule: **not met; conclusive.** At quoted bids the model is 1.8x the
oracle, and worse than persistence (about 1.47x). This is worse than my
predicted 1.00–1.15x. The model's predicted change in last prints does not
carry over to the bid.

**B1. Timing at quoted prices** (`settlepnl_quotes_*`). 2,554 events are fully
quoted at t and t+h (2.1% dropped); 2,090 are sized; k = 312.

| test, ttc 3600 | s0 | s1 | s2 | s3 | mean |
|---|---|---|---|---|---|
| **model - random** | **+1.094** [0.55, 1.73] | +0.462 [-0.03, 0.96] | **+1.284** [0.74, 1.91] | **+0.628** [0.13, 1.17] | **+0.867** (3/4 CIs above 0) |
| model - static_now (never wait) | **-0.730** | **-1.362** | **-0.539** | **-1.196** | **-0.957** (4/4 CIs *below* 0) |
| model waits (of 2,090) | 994 | 1,441 | 1,191 | 1,140 | random: 1,035 |

Secondary:
- ttc 1s: identical. The extra baskets are exactly those unquoted at t+h.
- ttc 24h: gap -0.006 to -0.015, 0/4 significant.
- val, ttc 3600: +0.49 / -0.09 / +0.64 / +0.28, 2/4 significant.

Decision rule B1: **met** (mean > 0, 3/4 CIs above 0). My prediction
(+0.00 to +0.12) was wrong. **But read it together with the static row:**
- At quoted prices, **waiting is costly**. Random, which waits about half the
  time, nets -$4.01 per trade against static's -$2.18.
- The model beats the coin flip, but **loses to never waiting on every seed**
  (CIs below 0). At last prints it beat static by +0.11.
- The control's wait rate is not matched to the model's (the model waits
  994–1,441 times, random 1,035), so part of the gap reflects *how often*
  each waits, not only *when*. A rate-matched control was not pre-registered.
- **Reading:** a formal replication of timing skill against a coin flip, but no
  executable timing value. The best policy at quotes is to enter immediately
  (or not at all).

**B2. Economics at quotes:** gross is negative on about 97% of trades (win
3.3%): selling at the bids or buying at the asks almost always captures less
than $1 per set.
- static_now: -$2.18 per trade, -$4,566 total.
- model_timed: -$2.72 to -$3.55 per trade.
- cost_gated fired **once** in 2,090 events, netting $0.07.
- Rule: **no strategy nets > 0 with >= 30 entries. The profitability
  withdrawal stands, now at executable quotes.**

## Maker (liquidity-provision) pathway (pre-registered 2026-09-28, before any code)

Full design, fill models, decision rules and predictions:
`docs/planning/maker-simulator-preregistration.md`. Month roles are fixed: May–June
for development only, July–September as test (scored once), October–November
as confirmation.
