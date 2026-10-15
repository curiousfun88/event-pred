#!/bin/bash
# Laptop fallback for the live producer while the Lumid office sandbox service is down (2026-10-15).
# Points the (disabled) laptop service maker-producer at the current producer command -- hourly
# Research Fleet records (L5), no Lumid publishing -- with CPU/memory caps, and starts it.
#
#   bash stg_infra/laptop_fallback.sh start    # install the unit and start the producer
#   bash stg_infra/laptop_fallback.sh stop     # stop it (do this before Lumid's producer resumes)
#   bash stg_infra/laptop_fallback.sh status
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
    systemctl --user daemon-reload && systemctl --user start maker-producer
    sleep 5; systemctl --user is-active maker-producer; tail -3 "$REPO/logs/v2_forecast/live_producer_service.log"
    ;;
  stop)
    systemctl --user stop maker-producer; systemctl --user is-active maker-producer
    ;;
  status)
    systemctl --user is-active maker-producer; tail -5 "$REPO/logs/v2_forecast/live_producer_service.log"
    ;;
esac
