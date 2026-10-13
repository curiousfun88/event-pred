#!/usr/bin/env bash
# One-off L5 deploy (2026-10-13): waits for minute 40 of the hour, checks the hour's cycle is logged, copies the
# producer, switches producer_cmd to no-publish + --fleet (old cmd kept as producer_cmd.publish_bak), then stops
# the producer in a SEPARATE ssh call so the keeper's watchdog restarts it on the new command. Log: logs/deploy_l5.log
cd /home/fyp/event-pred || exit 1
S="ssh -i /root/.ssh/lumid_sbx_ed25519 -o IdentitiesOnly=yes -p 31226 gw@lum.id"
until [ "$(date -u +%-M)" -ge 40 ]; do sleep 20; done
stamp=$(date -u +%Y%m%dT%H)
n=0
for i in 1 2 3 4 5 6; do
  n=$($S "grep -c '\"H\": \"$stamp\"' /home/curiouslearner842/event-pred/runs/live/runs.jsonl" 2>/dev/null)
  [ "$n" = "1" ] && break
  sleep 120
done
echo "$(date -u +%H:%M:%S) hour $stamp logged: $n"
[ "$n" = "1" ] || { echo "ABORT: hour not logged; nothing changed"; exit 3; }
tar -cf - stg_infra/live_signal_producer.py | $S 'cd /home/curiouslearner842/event-pred && tar -xf - && grep -c "def post_fleet" stg_infra/live_signal_producer.py && cp /home/curiouslearner842/.lumid/producer_cmd /home/curiouslearner842/.lumid/producer_cmd.publish_bak && echo "/home/curiouslearner842/venv/bin/python stg_infra/live_signal_producer.py --loop --fleet --pat-file /home/curiouslearner842/.lumid/lumid_pat" > /home/curiouslearner842/.lumid/producer_cmd && cat /home/curiouslearner842/.lumid/producer_cmd' \
  || { echo "ABORT: step 1 failed; producer untouched"; exit 4; }
$S 'pkill -f "[l]ive_signal_producer.py"; echo stopped'
for i in $(seq 1 14); do
  sleep 30
  out=$($S 'ps -eo lstart,args | grep "[l]ive_signal_producer.py --loop"' 2>/dev/null)
  [ -n "$out" ] && { echo "RESTARTED $(date -u +%H:%M:%S): $out"; exit 0; }
done
echo "NOT RESTARTED within 7 min: check the keeper"; exit 5
