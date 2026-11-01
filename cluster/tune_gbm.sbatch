#!/bin/bash
# GBM walk-forward tuning (stg_infra/examples/tune_gbm.py) on GPU. From ~/event-pred:
#   GPU check, synthetic data only (no real data needed, no amendment needed):
#     sbatch --export=ALL,MODE=bench cluster/tune_gbm.sbatch
#   The grid, one task per (setting, fold), after the amendment is set and
#   runs/tune_gbm/features.npz has been copied up:
#     sbatch --array=0-74 cluster/tune_gbm.sbatch      # 0-74: see `tune_gbm.py tasks`
#   CPU instead of GPU: sbatch --gpus=0 --export=ALL,DEVICE=cpu --array=0-74 cluster/tune_gbm.sbatch
# The hgb_a12 reference tasks run on CPU whatever DEVICE says (scikit-learn has no GPU).
#SBATCH --job-name=fyp-tune-gbm
#SBATCH --gpus=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=cluster/logs/%x-%A_%a.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source "${VENV:-.venv-cluster}/bin/activate"
DEVICE=${DEVICE:-cuda}
if [ "${MODE:-fit}" = bench ]; then
    nvidia-smi --query-gpu=name --format=csv,noheader || true
    python stg_infra/examples/tune_gbm.py --self-test
    python stg_infra/examples/tune_gbm.py bench --device cpu
    python stg_infra/examples/tune_gbm.py bench --device "$DEVICE"
else
    python stg_infra/examples/tune_gbm.py fit --device "$DEVICE"
fi
