#!/bin/bash
# One-off environment setup on the cluster login node, from ~/event-pred:
#     bash cluster/setup_env.sh
#     VENV=/path/with/space/fyp-venv bash cluster/setup_env.sh   # if home is too small
# Installs CUDA PyTorch, PyTorch Geometric (the STGAT's GATv2Conv), the tabular
# models used for the maker policy and its benchmark, and the stg package itself
# WITHOUT its declared dependencies (sentence-transformers is not needed here and
# is large). pip's cache is disabled so the CUDA wheels are not stored twice.
# Needs python >= 3.10; if python3 is older, load a newer one (`module avail python`).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=${VENV:-.venv-cluster}

python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --no-cache-dir --upgrade pip
pip install --no-cache-dir torch
pip install --no-cache-dir torch_geometric
pip install --no-cache-dir numpy polars pyarrow pandas networkx scikit-learn lightgbm xgboost catboost
pip install --no-cache-dir --no-deps -e stg_infra
mkdir -p cluster/logs
python -c "import stg, sklearn, polars; print('stg ok; sklearn', sklearn.__version__)"
echo "venv: $VENV  (jobs use the same VENV variable)"
