"""
lumid_signal_probe.py

PLUMBING PROBE (not a forward-test arm): does a custom signal published through
signal.publish make a deployed .lqts strategy trade on Lumid?

Publishes `probe_bid` / `probe_ask` at a fixed positive value (default 5c = 500 ticks)
on a few instruments that are on Lumid's tradable list and whose trades Lumid records
(fast crypto series), every --every seconds until --until (UTC). The strategy
`stg_infra/lqt/probe_maker_v1.lqts` reads them. After the contracts settle, a Lumid
backtest with the instrument named explicitly should show real tape (`pg_tape`) and
actions > 0. Zero actions with a positive signal on real tape = a pipeline problem.

Separate signal names keep the forward-test arms' signal history (g2_*, g_*, ...) clean.
Publishing follows the operator guidance via live_signal_producer.publish_paced
(one request at a time, >= 7 s apart, retry 429/5xx with the same msg_id).

USAGE (from repo root):
    python stg_infra/examples/lumid_signal_probe.py --self-test
    python stg_infra/examples/lumid_signal_probe.py --tickers T1 T2 --until 2026-10-10T20:55 [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))

import live_signal_producer as lp  # noqa: E402

NAMES = ("probe_bid", "probe_ask")
LOG = _REPO / "runs/live/probe_publish.jsonl"


def rows_for(tickers, value_c, ts_ns):
    return [{"signal_name": nm, "instrument_id": tk, "score_ticks": lp.to_ticks(value_c), "confidence_bps": 10000,
             "ts_event_ns": int(ts_ns)} for tk in tickers for nm in NAMES]


def run(a):
    import requests
    pat = Path(a.pat_file).expanduser().read_text().strip()
    until = dt.datetime.fromisoformat(a.until).replace(tzinfo=dt.timezone.utc).timestamp()
    post = lambda body: requests.post(lp.SUBMIT_URL, json=body, headers={"Authorization": f"Bearer {pat}"}, timeout=60)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    while time.time() < until:
        t = time.time_ns()
        rows = rows_for(a.tickers, a.value_c, t)
        stamp = dt.datetime.fromtimestamp(t / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        sent = "dry-run" if a.dry_run else lp.publish_paced(rows, pat, f"probe-{stamp}", 100, 7.0, post, budget_s=300)
        rec = {"at": stamp, "rows": len(rows), "tickers": a.tickers, "value_c": a.value_c, "sent": sent}
        print(json.dumps(rec), flush=True)
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        if a.once:
            return
        nxt = time.time() + a.every
        while time.time() < min(nxt, until):
            time.sleep(10)


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
        ok &= bool(c)
    r = rows_for(["A", "B"], 5.0, 123)
    check("2 signals per ticker, both probe names", len(r) == 4 and {x["signal_name"] for x in r} == set(NAMES))
    check("5c -> 500 ticks, same scale as the arms' signals", all(x["score_ticks"] == 500 for x in r))
    check("probe names never collide with forward-test arm signals",
          not any(n.startswith(tuple(a + "_" for a in lp.SCORE_ARMS)) for n in NAMES))
    env = lp.envelope(r, "P", "probe-x-0")
    check("same envelope as the producer", env["records"][0]["topic"] == "signal.publish")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--tickers", nargs="*", default=[])
    ap.add_argument("--value-c", type=float, default=5.0)
    ap.add_argument("--until", help="UTC, YYYY-mm-ddTHH:MM")
    ap.add_argument("--every", type=float, default=900.0, help="seconds between publishes")
    ap.add_argument("--pat-file", default="~/.lumid_pat")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if not a.tickers or not a.until:
        ap.error("--tickers and --until are required")
    run(a)


if __name__ == "__main__":
    main()
