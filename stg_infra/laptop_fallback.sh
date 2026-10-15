#!/bin/bash
# Laptop fallback for the live producer while the Lumid office sandbox service is down (2026-10-15).
# Points the (disabled) laptop service maker-producer at the current producer command -- hourly
# Research Fleet records (L5), no Lumid publishing -- with CPU/memory caps, and starts it.
#
#   bash stg_infra/laptop_fallback.sh start    # install the unit and start the producer
#   bash stg_infra/laptop_fallback.sh stop     # stop it (do this before Lumid's producer resumes)
#   bash stg_infra/laptop_fallback.sh status
#   bash stg_infra/laptop_fallback.sh paper    # start the paper trader + live ledger (L10) beside the producer
#   bash stg_infra/laptop_fallback.sh paper-stop
#
# Never run this while a Lumid sandbox producer is running: two producers would log the same hours.
set -u
UNIT=/root/.config/systemd/user/maker-producer.service
REPO=/home/fyp/event-pred
case "${1:-status}" in
  start)
    [ -f "$UNIT.bak-20261015" ] || cp "$UNIT" "$UNIT.bak-20261015"
    cat > "$UNIT" <<EOF
[Unit]
Description=Live maker signal producer (laptop fallback while Lumid office is down; fleet records, no publishing)
After=network-online.target

[Service]
WorkingDirectory=$REPO
Environment=OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2
ExecStart=/bin/bash -c 'exec nice -n 5 $REPO/.venv/bin/python stg_infra/live_signal_producer.py --loop --fleet --bulk --pat-file /root/.lumid_pat >> logs/v2_forecast/live_producer_service.log 2>&1'
Restart=always
RestartSec=60
MemoryMax=3500M
CPUQuota=200%

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload && systemctl --user restart maker-producer
    sleep 5; systemctl --user is-active maker-producer; tail -3 "$REPO/logs/v2_forecast/live_producer_service.log"
    ;;
  paper)
    systemctl --user is-active -q maker-producer || { echo "producer not running: start it first"; exit 2; }
    systemd-run --user --unit=paper-trader --working-directory="$REPO" -p MemoryMax=3000M -p CPUQuota=200% \
      -p Restart=always -p RestartSec=60 -E OMP_NUM_THREADS=2 -E OPENBLAS_NUM_THREADS=2 \
      /bin/bash -c "exec nice -n 10 $REPO/.venv/bin/python stg_infra/paper_trader.py --loop --ledger --fleet --pat-file /root/.lumid_pat >> logs/v2_forecast/paper_trader_service.log 2>&1"
    sleep 5; systemctl --user is-active paper-trader
    ;;
  paper-stop)
    systemctl --user stop paper-trader; systemctl --user is-active paper-trader
    ;;
  stop)
    systemctl --user stop maker-producer; systemctl --user is-active maker-producer
    ;;
  status)
    echo "producer: $(systemctl --user is-active maker-producer)  paper-trader: $(systemctl --user is-active paper-trader)"
    tail -2 "$REPO/logs/v2_forecast/live_producer_service.log" | cut -c1-300
    tail -2 "$REPO/logs/v2_forecast/paper_trader_service.log" 2>/dev/null | cut -c1-300
    ;;
esac
