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
