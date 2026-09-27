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
