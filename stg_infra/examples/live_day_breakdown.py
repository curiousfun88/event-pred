"""
live_day_breakdown.py

G2's main result at a cut, by quoting day (UTC), and the result with its most profitable day removed, beside random
at its share on the same days. Descriptive; the report's day-cluster paragraph (Chapter 6). Fills, settlement and the
main-result filters are the cut report's own (cut_report.read_ledger, apply_corrections, settle_times, L18).

USAGE (from repo root; LIVE_DIR = the copy of runs/live the cut report was run on):
    python stg_infra/examples/live_day_breakdown.py --self-test
    LIVE_DIR=<copy> python stg_infra/examples/live_day_breakdown.py --cut 2026-10-28T00 --settle-by 2026-10-30T00 \
        | tee logs/v2_forecast/live_day_breakdown_interim.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import pickle
import sys
from collections import defaultdict
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(_THIS))


def by_day(fills):
    """{UTC quoting day: [net_c, capital_c]} from fill tuples (ev, tk, side, price, qty, fee, net, cap, mk, H)."""
    d = defaultdict(lambda: [0.0, 0.0])
    for f in fills:
        k = dt.datetime.fromtimestamp(int(f[9]) / 1e9, dt.timezone.utc).date().isoformat()
        d[k][0] += f[6]
        d[k][1] += f[7]
    return dict(d)


def without(days: dict, drop: str):
    """(net_c, return %) over every day but `drop`."""
    n = sum(v[0] for k, v in days.items() if k != drop)
    c = sum(v[1] for k, v in days.items() if k != drop)
    return n, (100 * n / c if c else float("nan"))


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    day = 86400 * 10**9
    F = [("e", "t", 1, 50, 1, 0, 100.0, 1000.0, 0, 0), ("e", "t", 1, 50, 1, 0, -20.0, 500.0, 0, day),
         ("e", "t", 1, 50, 1, 0, 30.0, 500.0, 0, day)]
    d = by_day(F)
    check("two days, the second summing two fills", d == {"1970-01-01": [100.0, 1000.0], "1970-01-02": [10.0, 1000.0]})
    check("dropping the best day leaves +10c on 1000c = +1%", without(d, "1970-01-01") == (10.0, 1.0))
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def run(cut, settle_by):
    import cut_report as cr
    import paper_ledger as pl_
    m = pickle.loads((cr.LIVE / "paper" / "markets.pkl").read_bytes())
    res = {t: v.get("result") for t, v in m.items()}
    st = cr.settle_times(m)
    _, fills, _ = cr.read_ledger(cr.LEDGER)
    cr.apply_corrections(cr.LEDGER, fills)
    mf, cut_ns, sb = cr.ns_of(cr.MAIN_FROM), cr.ns_of(cut), cr.ns_of(settle_by)

    def done(arm):
        K = [k for k in fills[("primary", arm)] if cr.is_train23_key(k) and mf <= int(k[7]) < cut_ns
             and st.get(k[0]) is not None and st[k[0]] <= sb]
        return [pl_.as_fill(k, res.get(k[1])) for k in K]

    g, r = by_day(done("g2")), by_day(done("rnd2"))
    print(f"G2, main result, cut {cut}, settled by {settle_by}, by quoting day (UTC)")
    for k in sorted(g):
        print(f"  {k}  net ${g[k][0] / 100:+8.2f}  capital ${g[k][1] / 100:8.0f}")
    best = max(g, key=lambda k: g[k][0])
    n, ret = without(g, best)
    _, rret = without(r, best)
    print(f"most profitable day {best}: ${g[best][0] / 100:+.2f}")
    print(f"without it: G2 net ${n / 100:+.2f}, return {ret:+.2f}%; random {rret:+.2f}%; G2 minus random {ret - rret:+.2f} pts")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cut", default="2026-10-28T00")
    ap.add_argument("--settle-by", default="2026-10-30T00")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.cut.replace("-", "").replace(":", ""), a.settle_by.replace("-", "").replace(":", ""))


if __name__ == "__main__":
    main()
