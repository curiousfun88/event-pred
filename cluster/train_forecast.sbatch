#!/bin/bash
# STGAT training on one GPU. From ~/event-pred on the cluster, after
# cluster/smoke.sbatch passes and cache_causal/ has been copied up:
#     sbatch cluster/train_forecast.sbatch                       # seed 0, causal MECE recipe
#     sbatch --export=ALL,SEED=1,OUT=runs/gpu_test_s1 cluster/train_forecast.sbatch
#     sbatch --export=ALL,EXTRA="--epochs 2" cluster/train_forecast.sbatch   # quick timing test
# Same arguments as the v2_mece_causal_s* recipe (runs/README.md) plus --device cuda.
# GPU runs are not bit-identical to CPU runs: write them to a NEW checkpoint dir and
# never use them in place of a reported figure. CPU stays the default everywhere else.
#SBATCH --job-name=fyp-train
#SBATCH --gpus=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=03:00:00
#SBATCH --output=cluster/logs/%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source "${VENV:-.venv-cluster}/bin/activate"
SEED=${SEED:-0}
OUT=${OUT:-runs/gpu_test_s${SEED}}
nvidia-smi --query-gpu=name,memory.total --format=csv
python stg_infra/train_forecast.py --device cuda \
    --cache cache_causal --w-ladder 0 --supervise all --select-on mece \
    --epochs 25 --seed "$SEED" --checkpoint-dir "$OUT" ${EXTRA:-}
