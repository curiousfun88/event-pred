#!/bin/bash
# Queue after the STGAT tuning (7/2/4 B3, maker A10). Run from the repo root:
#   systemd-run --unit=after-tuning -p MemoryMax=5800M -p MemorySwapMax=1500M \
#     -p WorkingDirectory=$PWD -p StandardOutput=append:$PWD/logs/v2_forecast/after_tuning.log \
#     -p StandardError=append:$PWD/logs/v2_forecast/after_tuning.log --setenv=PYTHONUNBUFFERED=1 \
#     /bin/bash stg_infra/run_after_tuning.sh
# One job at a time. Each finished step leaves a .done marker, so a relaunch
# after a WSL restart skips completed work (an interrupted seed restarts).
set -u
PY=.venv/bin/python

while systemctl is-active --quiet tune-stgat; do sleep 300; done
if [ ! -f runs/tune/winner.json ]; then
    echo "$(date) tune-stgat stopped WITHOUT winner.json: nothing started (relaunch tuning first)"; exit 1
fi

# B3: the tuned defaults + quote inputs, 4 seeds, identical otherwise.
for s in 0 1 2 3; do
    d=runs/tune/b3_quotes_s$s
    [ -f $d/.done ] && { echo "$(date) $d already done"; continue; }
    mkdir -p $d
    cmd=$($PY -c "
import sys; sys.path.insert(0, 'stg_infra'); import tune_stgat as t
from pathlib import Path
print(' '.join(t.command(dict(t.DEFAULTS, quote_features=True), t.FINAL_EPOCHS, $s, Path('$d'))))")
    echo "$(date) B3 seed $s: $cmd"
    $cmd > $d/train.log 2>&1 || { echo "$(date) B3 seed $s FAILED (rc=$?), stopping"; exit 1; }
    touch $d/.done
done

if [ ! -f runs/tune/signal_model.json ]; then
    $PY stg_infra/select_signal_model.py || { echo "$(date) selection FAILED"; exit 1; }
fi

# Maker A10: robust re-selection on development months only.
if [ ! -f runs/maker/.a10_done ]; then
    echo "$(date) starting A10"
    $PY stg_infra/simulate_maker.py --robust --workers 3 --out runs/maker/selected_a10.json \
        && touch runs/maker/.a10_done || { echo "$(date) A10 FAILED"; exit 1; }
fi
echo "$(date) queue complete: ready for the single test run"
