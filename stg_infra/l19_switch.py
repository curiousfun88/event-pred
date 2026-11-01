"""
l19_switch.py -- amendment L19: has the fallback to the 23 series been triggered, and apply it if so.

Trigger: counting from quoting hour 2026-10-17 07:00 UTC, 3 or more producer hours with no completed record
(runs/live/runs.jsonl) within any 24-hour window. --apply (inside the sandbox) rewrites ~/.lumid/producer_cmd with
`--series <the 23>`; it takes effect when the producer next starts (the next handover).

    python stg_infra/l19_switch.py --self-test
    python stg_infra/l19_switch.py                  # report
    python stg_infra/l19_switch.py --apply          # inside the sandbox, only if triggered
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
FROM = dt.datetime(2026, 10, 17, 7, tzinfo=dt.timezone.utc)
THRESHOLD, WINDOW_H = 3, 24


def failed_hours(runs_lines, now: dt.datetime, start: dt.datetime = FROM) -> list:
    """Quoting hours from `start` up to the last fully elapsed hour with no completed producer record."""
    done = set()
    for line in runs_lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "H" in d and "sha256" in d:
            done.add(d["H"])
    out, h = [], start
    last = now.replace(minute=0, second=0, microsecond=0) - dt.timedelta(hours=1)
    while h <= last:
        if h.strftime("%Y%m%dT%H") not in done:
            out.append(h.strftime("%Y%m%dT%H"))
        h += dt.timedelta(hours=1)
    return out


def triggered(failed: list) -> tuple:
    """(True, window_start) if any 24-hour window holds >= THRESHOLD failed hours."""
    ts = [dt.datetime.strptime(x, "%Y%m%dT%H") for x in failed]
    for i, t in enumerate(ts):
        n = sum(1 for u in ts[i:] if u < t + dt.timedelta(hours=WINDOW_H))
        if n >= THRESHOLD:
            return True, failed[i]
    return False, None


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    rec = lambda h: json.dumps({"H": h, "sha256": {}})
    now = dt.datetime(2026, 10, 18, 12, 30, tzinfo=dt.timezone.utc)
    hours = [(FROM + dt.timedelta(hours=i)).strftime("%Y%m%dT%H") for i in range(29)]
    lines = [rec(h) for h in hours if h not in ("20261017T09", "20261017T20")] + ["junk", json.dumps({"error": "x"})]
    f = failed_hours(lines, now)
    check(f"two failed hours found ({f})", f == ["20261017T09", "20261017T20"])
    check("two failures in 24 h: not triggered", triggered(f) == (False, None))
    f3 = failed_hours([l for l in lines if "20261018T02" not in l], now)
    check("a third failure within 24 h of the first: triggered", triggered(f3)[0] is True)
    spread = ["20261017T08", "20261018T09", "20261019T10"]
    check("three failures more than 24 h apart: not triggered", triggered(spread) == (False, None))
    check("hours before 2026-10-17 07:00 UTC never count", failed_hours([], FROM + dt.timedelta(minutes=30)) == [])
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--runs", default=str(_THIS.parent / "runs/live/runs.jsonl"))
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    lines = Path(a.runs).read_text().splitlines() if Path(a.runs).exists() else []
    f = failed_hours(lines, dt.datetime.now(dt.timezone.utc))
    trig, at = triggered(f)
    print(json.dumps({"failed_hours_since_rule": f, "triggered": trig, "window_start": at}))
    if a.apply:
        if not trig:
            sys.exit("not triggered: nothing applied")
        from fetch_kalshi_api_months import SERIES_A13
        cmd = Path("/home/curiouslearner842/.lumid/producer_cmd")
        base = cmd.read_text().strip()
        if "--series" not in base:
            cmd.write_text(base + " --series " + " ".join(SERIES_A13) + "\n")
        print("producer_cmd restricted to the 23 series; takes effect at the next handover:", cmd.read_text().strip())


if __name__ == "__main__":
    main()
