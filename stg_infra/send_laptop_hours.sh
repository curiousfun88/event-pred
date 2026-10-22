#!/bin/bash
# Send the hours the laptop fallback produced (L12) to a restored sandbox, so its paper trader books them like any
# other hour (2026-10-22). Run on the LAPTOP from the repo root, AFTER stopping the laptop producer
# (bash stg_infra/laptop_fallback.sh stop) and BEFORE starting the sandbox keeper:
#
#   bash stg_infra/send_laptop_hours.sh <since YYYYMMDDTHH> <office|home>
#
# Copies the decision files (scores, stamps, payloads) of hours >= since, the producer's warm caches (runs/live/state),
# and appends to the sandbox's runs.jsonl the laptop's lines for hours the sandbox does not have yet. Checks the
# sandbox's record afterwards. Nothing is started.
set -euo pipefail
SINCE=${1:?usage: send_laptop_hours.sh <since YYYYMMDDTHH> <office|home>}
case "${2:?site}" in office) PORT=31226 ;; home) PORT=31223 ;; *) echo "site must be office or home"; exit 2 ;; esac
S="ssh -o ConnectTimeout=20 -p $PORT -i $HOME/.ssh/lumid_sbx_ed25519 gw@lum.id"
R=/home/curiouslearner842/event-pred
cd "$(dirname "$0")/.."
systemctl --user is-active -q maker-producer && { echo "the laptop producer is still running: stop it first"; exit 3; }

FILES=$(cd runs/live && for d in scores stamps payloads; do ls $d 2>/dev/null | awk -v s="$SINCE" -v d="$d" '{h=$0; sub(/^[a-z]+_/, "", h); if (substr(h, 1, 11) >= s) print d"/"$0}'; done)
[ -n "$FILES" ] || { echo "no laptop files for hours >= $SINCE"; exit 4; }
echo "decision files: $(echo "$FILES" | wc -l)"
(cd runs/live && tar -czf - $FILES state) | $S "cd $R/runs/live && tar -xzf - && echo extracted"
python3 - "$SINCE" <<'EOF' > /tmp/laptop_runs_lines.jsonl
import json, sys
for line in open("runs/live/runs.jsonl"):
    try:
        if json.loads(line).get("H", "") >= sys.argv[1]:
            print(line.rstrip("\n"))
    except Exception:
        pass
EOF
echo "runs.jsonl lines to merge: $(wc -l < /tmp/laptop_runs_lines.jsonl)"
cat /tmp/laptop_runs_lines.jsonl | $S "cd $R && /home/curiouslearner842/venv/bin/python -c '
import json, sys
have = set()
for l in open(\"runs/live/runs.jsonl\"):
    try: have.add(json.loads(l).get(\"H\"))
    except Exception: pass
new = [l for l in sys.stdin.read().splitlines() if l.strip() and json.loads(l).get(\"H\") not in have]
with open(\"runs/live/runs.jsonl\", \"a\") as f:
    for l in new: f.write(l + \"\n\")
print(\"appended\", len(new), \"hours; sandbox record now ends at\", json.loads(open(\"runs/live/runs.jsonl\").read().splitlines()[-1])[\"H\"])
'"
