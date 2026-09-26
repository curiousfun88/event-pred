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
