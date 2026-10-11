#!/bin/bash
# Starts the sandbox keeper (which starts and watches the signal producer) in the current Lumid
# sandbox, unless one is already running here. Called over the SSH gateway by the previous
# sandbox's keeper at handover, or by hand for the first start. See lumid_sandbox_keeper.py.
set -eu
U=curiouslearner842
cd /home/$U/event-pred
mkdir -p logs
if pgrep -f "[l]umid_sandbox_keeper.py --run" > /dev/null; then
    echo "keeper already running on $(hostname)"
    exit 0
fi
setsid nohup /home/$U/venv/bin/python stg_infra/lumid_sandbox_keeper.py --run \
    >> logs/sbx_keeper.out 2>&1 < /dev/null &
echo "keeper started on $(hostname)"
