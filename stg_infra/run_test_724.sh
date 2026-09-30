#!/bin/bash
# The SINGLE test run (7/2/4 §4 + B2.3; maker A6.2/A6.3/A8-A11). Run once, from the repo root:
#   systemd-run --unit=test-724 -p MemoryMax=5800M -p MemorySwapMax=1500M -p WorkingDirectory=$PWD \
#     -p StandardOutput=append:$PWD/logs/v2_forecast/test_724/queue.log \
#     -p StandardError=append:$PWD/logs/v2_forecast/test_724/queue.log --setenv=PYTHONUNBUFFERED=1 \
#     /bin/bash stg_infra/run_test_724.sh
# Each finished step leaves a .done marker; a relaunch after a WSL restart skips completed
# steps and never re-scores one that finished.
set -u
PY=.venv/bin/python
TM="2025-08 2025-09 2025-10 2025-11"
L=logs/v2_forecast/test_724
mkdir -p $L
CK=$($PY -c "import json; print(' '.join(json.load(open('runs/tune/signal_model.json'))['checkpoints']))")
step() { [ -f $L/.$1.done ] && { echo "$(date) $1 already done"; return 1; }; echo "$(date) start $1"; return 0; }
fin() { touch $L/.$1.done; echo "$(date) done $1"; }

s=0
for c in $CK; do
  if step forecast_s$s; then
    $PY -u stg_infra/score_forecast.py --checkpoint $c --split test --cache cache_724 --months $TM \
      --supervise all --exclude-series-prefix KXMVE > $L/forecast_s$s.log 2>&1 || { echo "forecast_s$s FAILED"; exit 1; }; fin forecast_s$s; fi
  if step strata_s$s; then
    $PY -u stg_infra/score_mece_bidside.py --checkpoint $c --split test --cache cache_724 --months $TM \
      --bid-source quotes --quotes data/quotes/candles_1h_2024-11_2025-11.parquet --exclude-series-prefix KXMVE \
      > $L/strata_s$s.log 2>&1 || { echo "strata_s$s FAILED"; exit 1; }; fin strata_s$s; fi
  s=$((s+1))
done

if step signal; then
  $PY -u stg_infra/export_mid_signal.py --checkpoints $CK --cache cache_724 --months $TM --split test --exclude-series-prefix KXMVE \
    --out runs/maker/stgat_signal_test.parquet > $L/signal.log 2>&1 || { echo "signal FAILED"; exit 1; }; fin signal; fi

if step maker; then
  $PY -u stg_infra/simulate_maker.py --config runs/maker/selected_a10.json --secondary runs/maker/selected.json \
    --signal runs/maker/stgat_signal_test.parquet --months $TM --workers 3 --out runs/maker/test_result.json \
    > $L/maker.log 2>&1 || { echo "maker FAILED"; exit 1; }; fin maker; fi
echo "$(date) TEST RUN COMPLETE"
