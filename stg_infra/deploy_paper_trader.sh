#!/usr/bin/env bash
# Deploy the paper trader into the production sandbox (L3 item 3, L7). Run from the laptop repo root.
#   bash stg_infra/deploy_paper_trader.sh check    # copy files, then (in the producer's quiet minutes) run the
#                                                  # P&L-free candidate check; computes no fills or P&L
#   bash stg_infra/deploy_paper_trader.sh enable   # write ~/.lumid/paper_cmd and restart the KEEPER only (the
#                                                  # producer keeps running); the keeper then starts the paper trader
# Nothing here touches files the producer imports. Log: logs/deploy_paper_trader.log
set -u
cd /home/fyp/event-pred || exit 1
S="ssh -i /root/.ssh/lumid_sbx_ed25519 -o IdentitiesOnly=yes -p 31226 gw@lum.id"
R=/home/curiouslearner842/event-pred
PY=/home/curiouslearner842/venv/bin/python

wait_quiet() {   # producer logged this hour and minute < 58 (sandbox clock)
  while true; do
    q=$($S "cd $R && H=\$(date -u +%Y%m%dT%H); M=\$(date -u +%-M); grep -q \"\\\"H\\\": \\\"\$H\\\", \\\"snap_ns\\\"\" runs/live/runs.jsonl && [ \$M -lt 50 ] && echo QUIET" 2>/dev/null)
    [ "$q" = "QUIET" ] && return 0
    echo "$(date -u +%H:%M) waiting for the producer's quiet minutes..."; sleep 60
  done
}

case "${1:-}" in
check)
  tar -cf - stg_infra/paper_trader.py stg_infra/lumid_sandbox_keeper.py stg_infra/examples/train_baselines.py \
      stg_infra/examples/fetch_kalshi_api_months.py docs/planning/l4_candidate_pool.json \
      runs/maker/policy_lin2_W3_model.pkl runs/maker/policy_lin2_W3_model.json \
      runs/maker/policy_mlp2_W3_model.pkl runs/maker/policy_mlp2_W3_model.json \
    | $S "cd $R && tar -xf - && sha1sum runs/maker/policy_lin2_W3_model.pkl runs/maker/policy_mlp2_W3_model.pkl | cut -c1-16 && $PY stg_infra/paper_trader.py --self-test | tail -1 && $PY stg_infra/lumid_sandbox_keeper.py --self-test | tail -1" \
    || { echo "ABORT: copy or self-test failed"; exit 2; }
  wait_quiet
  echo "$(date -u +%H:%M) running the P&L-free check (fetches missing tape and market results, quiet-gated, 2 req/s)"
  $S "cd $R && $PY stg_infra/paper_trader.py --fetch-tape --check 2>&1 | tail -5"
  ;;
enable)
  $S "echo '$PY stg_infra/paper_trader.py --loop' > /home/curiouslearner842/.lumid/paper_cmd && cat /home/curiouslearner842/.lumid/paper_cmd" || exit 3
  $S 'pkill -f "[l]umid_sandbox_keeper.py --run"; echo keeper stopped'
  sleep 3
  $S "bash $R/stg_infra/lumid_start.sh"
  sleep 20
  $S 'ps -eo etime,args | grep "[l]ive_signal_producer.py\|[l]umid_sandbox_keeper.py\|[p]aper_trader.py" | cut -c1-110'
  ;;
*) echo "usage: $0 check|enable"; exit 1 ;;
esac
