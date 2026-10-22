#!/bin/bash
# Restore the live forward test on a fresh Lumid sandbox from GitHub (2026-10-22, after the home-volume outage).
#
#   code and models   github.com/curiousfun88/event-pred (branch below; the live models are committed in runs/maker)
#   live state        github.com/curiousfun88/event-pred-live (ledger, decisions, tape, runs.jsonl, stamps, keeper log)
#   secrets           NOT on GitHub: copy into ~/.lumid by hand (sbx_pat, sbx_key, lumid_pat, backup_key, known_hosts)
#
# Run INSIDE the sandbox, from anywhere:   bash restore_on_site.sh <office|home>
# It starts nothing: the keeper is started afterwards with stg_infra/lumid_start.sh, once the laptop producer (if any)
# is stopped and its hours have been sent across (stg_infra/send_laptop_hours.sh). Safe to re-run: it never overwrites
# live files that are newer than the backup's.
set -euo pipefail
U=curiouslearner842
H=/home/$U
BR=fix/post-close-carry-forward
SITE=${1:?usage: restore_on_site.sh <office|home>}
PY=$H/venv/bin/python
cd "$H"
mkdir -p .lumid
chmod 700 .lumid

echo "1. code and models ($BR)"
if [ -d event-pred ] && [ ! -d event-pred/.git ]; then
    mv event-pred "event-pred.old-$(date -u +%Y%m%dT%H%M)"            # an older copied (non-git) tree is kept aside
fi
[ -d event-pred/.git ] || git clone -q -b "$BR" https://github.com/curiousfun88/event-pred.git event-pred
git -C event-pred fetch -q origin "$BR"
git -C event-pred checkout -q -f "$BR"
git -C event-pred reset -q --hard "origin/$BR"
echo "   at $(git -C event-pred log -1 --format='%h %ci')"

echo "2. live state from the backup"
[ -d live-backup/.git ] || git clone -q https://github.com/curiousfun88/event-pred-live.git live-backup
git -C live-backup pull -q --rebase https://github.com/curiousfun88/event-pred-live.git main
git -C live-backup remote set-url origin git@github.com:curiousfun88/event-pred-live.git   # pushes use backup_key
git -C live-backup config user.name "event-pred live backup"
git -C live-backup config user.email "live-backup@users.noreply.github.com"
L=event-pred/runs/live
mkdir -p "$L" event-pred/logs
cp -a -n live-backup/runs/live/. "$L"/                    # no-clobber: keeps any newer local file
B=live-backup/runs/live/runs.jsonl
if [ ! -f "$L/runs.jsonl" ] || [ "$(wc -l < "$B")" -gt "$(wc -l < "$L/runs.jsonl")" ]; then
    cp "$B" "$L/runs.jsonl"                               # the tracked copy from git is older than the backup's
fi
[ -f event-pred/logs/sbx_keeper.log ] || cp live-backup/logs/sbx_keeper.log event-pred/logs/sbx_keeper.log
echo "   producer record to $(tail -1 "$L/runs.jsonl" | cut -c1-24), ledger to $(ls "$L/paper/ledger/entries" | tail -1)"
# the settlement cache (backed up as text since 2026-10-22): without it every settled event counts as open
if [ ! -f "$L/paper/markets.pkl" ] && [ -f "$L/paper/markets.jsonl" ]; then
    (cd event-pred && "$PY" -c "import pickle, sys; sys.path.insert(0, 'stg_infra'); from pathlib import Path; import live_backup as b
Path(b.MARKETS_PKL).write_bytes(pickle.dumps(b.import_markets(Path(b.MARKETS_TXT))))")
fi
if [ -f "$L/paper/markets.pkl" ]; then
    echo "   settlement cache: $("$PY" -c "import pickle; print(len(pickle.load(open('$L/paper/markets.pkl', 'rb'))))") markets"
else
    echo "   settlement cache: MISSING (run stg_infra/rebuild_markets_cache.py before starting the paper trader)"
fi

echo "3. Research Fleet posted list (not in the backup): mark every hour and entry already on record as posted"
"$PY" - "$L" <<'EOF'
import json, sys
from pathlib import Path
L = Path(sys.argv[1]); f = L / "fleet_backfilled.json"
done = json.loads(f.read_text()) if f.exists() else {}
done = done if isinstance(done, dict) else {n: None for n in done}
n0 = len(done)
for line in (L / "runs.jsonl").read_text().splitlines():
    try:
        H = json.loads(line).get("H")
    except Exception:
        continue
    if H:
        done.setdefault(f"fwdtest-hour-{H}", None)
for e in sorted((L / "paper/ledger/entries").glob("*.json")):
    done.setdefault(f"fwdtest-pnl-{e.stem}", None)
f.write_text(json.dumps(done))
print(f"   {len(done) - n0} names added ({len(done)} in total)")
EOF

echo "4. site and commands"
echo "$SITE" > .lumid/site
SERIES=$(cd event-pred && "$PY" -c "import sys; sys.path.insert(0, 'stg_infra'); from fetch_kalshi_api_months import SERIES_A13; print(' '.join(SERIES_A13))")
echo "$PY stg_infra/live_signal_producer.py --loop --fleet --bulk --ots --pat-file $H/.lumid/lumid_pat --series $SERIES" > .lumid/producer_cmd
echo "$PY stg_infra/paper_trader.py --loop --ledger --fleet --ots --pat-file $H/.lumid/lumid_pat" > .lumid/paper_cmd
echo "   site=$(cat .lumid/site); producer: $(wc -w < .lumid/producer_cmd) words, $(echo "$SERIES" | wc -w) series"

echo "5. OpenTimestamps client"
[ -x "$H/venv/bin/ots" ] || "$H/venv/bin/pip" install -q opentimestamps-client
"$H/venv/bin/ots" --version 2>/dev/null | head -1 || true

echo "6. checks"
cd event-pred
for f in live_signal_producer paper_ledger paper_trader lumid_sandbox_keeper; do
    echo "   $f: $("$PY" stg_infra/$f.py --self-test 2>&1 | tail -1)"
done
echo "   models: $(sha1sum runs/maker/policy_G_model.pkl runs/maker/policy_G2_W3_model.pkl runs/maker/policy_G2P_W3_model.pkl | cut -c1-16 | tr '\n' ' ')"
echo "   (live fingerprints: e39cc4ca97bbebd4 de87439617ba9476 fcad35080c11d957)"
for s in sbx_pat sbx_key lumid_pat backup_key known_hosts; do
    [ -s "$H/.lumid/$s" ] && echo "   secret $s: present" || echo "   secret $s: MISSING (copy it into $H/.lumid/)"
done
echo "restore done; start nothing yet"
