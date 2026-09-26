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
| **`v2_mece`** | `--w-ladder 0 --supervise all --select-on mece` | **Headline:** epoch 11; 0.851× oracle (val), 0.853× (test) | `forecast_mece.log`, `mece_test.log` | `checkpoints_mece` |
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
