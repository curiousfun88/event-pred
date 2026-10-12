#!/bin/bash
# GPU + environment smoke test. From ~/event-pred on the cluster:
#     sbatch cluster/smoke.sbatch
#     cat cluster/logs/fyp-smoke-<jobid>.out
# Other GPU types: sbatch --gpus=a100:1 cluster/smoke.sbatch
#SBATCH --job-name=fyp-smoke
#SBATCH --gpus=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:15:00
#SBATCH --output=cluster/logs/%x-%j.out
set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
source "${VENV:-.venv-cluster}/bin/activate"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
python - <<'EOF'
import time
import numpy as np
import torch
from torch_geometric.nn import GATv2Conv

print("torch", torch.__version__, "cuda available:", torch.cuda.is_available())
dev = "cuda" if torch.cuda.is_available() else "cpu"
n, d = 5000, 64
x = torch.randn(n, d, device=dev)
ei = torch.randint(0, n, (2, 50_000), device=dev)
conv = GATv2Conv(d, 16, heads=4, concat=True, add_self_loops=False).to(dev)
opt = torch.optim.Adam(conv.parameters(), 1e-3)
t = time.time()
for _ in range(50):
    opt.zero_grad(); conv(x, ei).pow(2).mean().backward(); opt.step()
if dev == "cuda":
    torch.cuda.synchronize()
print(f"GATv2Conv on {dev}: {(time.time() - t) / 50 * 1000:.1f} ms/step")

from sklearn.ensemble import HistGradientBoostingRegressor
X = np.random.default_rng(0).normal(size=(200_000, 14)); y = X[:, 0] + np.random.default_rng(1).normal(size=200_000)
t = time.time()
HistGradientBoostingRegressor(max_iter=400, learning_rate=0.03, min_samples_leaf=300).fit(X, y)
print(f"HistGradientBoosting, 200k x 14, 400 trees: {time.time() - t:.1f} s")
import lightgbm, xgboost, catboost
print("lightgbm", lightgbm.__version__, "xgboost", xgboost.__version__, "catboost", catboost.__version__)
EOF
