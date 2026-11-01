#!/usr/bin/env bash
# Run every script's --self-test (planted cases with known answers; no data needed). From the repo root:
#     bash scripts/run_self_tests.sh            # about 2-3 minutes; exit code 1 if any test fails
set -u
cd "$(dirname "$0")/.."
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python
pass=0; fail=0; failed=()
for f in $(find stg_infra scripts -name "*.py" -not -path "*/stg/*" -not -path "*/model/*" -not -path "*__pycache__*" \
           | xargs grep -l -- "--self-test" | sort); do
    if timeout 300 "$PY" "$f" --self-test > /tmp/self_test_$$.log 2>&1; then
        pass=$((pass + 1)); echo "PASS  $f"
    else
        fail=$((fail + 1)); failed+=("$f"); echo "FAIL  $f"; tail -5 /tmp/self_test_$$.log | sed 's/^/      /'
    fi
done
rm -f /tmp/self_test_$$.log
echo; echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ] || { printf 'failed: %s\n' "${failed[@]}"; exit 1; }
