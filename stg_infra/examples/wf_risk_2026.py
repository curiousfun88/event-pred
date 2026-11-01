"""
wf_risk_2026.py

EXPLORATORY NOTE 8 (2026-10-21, during the live test; offline only, nothing is selected or deployed): risk metrics
for G2's 2026 walk-forward, the L9 / A15 folds (test months 2026-04..08, G2-W3's recipe: trained on every earlier
month). The walk-forward table (runs/tune_gbm/features.npz) keeps each fill's month but not its hour, so Sharpe and
drawdown could not be computed from it. This script rebuilds the API-month fills exactly as tune_gbm.build() did,
keeping each fill's quoting hour, and computes the same risk metrics as the 2025 A16 addendum
(results/maker/a16_metrics_2025.json) with cut_report's own functions:

  daily series     each fill's final net on the day it was quoted (cut_report.tradedate_series), as A16
  capital          peak capital in open positions at any day end (cut_report.peak_open_capital)
  Sharpe           daily return over the 3-month T-bill rate (FRED DTB3), annualised over 365 days
  max drawdown     largest fall of the cumulative curve from its running peak, USD and % of peak capital
  benchmarks       S&P 500 and T-bill returns over 2026-04-01..2026-08-31, correlation with S&P daily returns
  control          random selection of the same number of fills per month, 5 seeds

Gates (the run stops if either fails): the rebuilt rows equal the walk-forward table's rows for every test month
(count, features and net), and each month's refitted return reproduces the recorded A15/L9 figure to 0.01 point.

USAGE (from repo root; reads runs/maker/api_cache, about 2 GB of RAM):
    python stg_infra/examples/wf_risk_2026.py --self-test
    systemd-run --user --scope -p MemoryMax=5G -p CPUQuota=200% -E OMP_NUM_THREADS=2 \\
        .venv/bin/python stg_infra/examples/wf_risk_2026.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "stg_infra"), str(_REPO / "stg_infra/examples")]

OUT = _REPO / "results/live/wf_risk_2026.json"
RECORDED = {"2026-04": 1.95, "2026-05": 2.30, "2026-06": 3.26, "2026-07": 3.46, "2026-08": 2.59}   # A15 hgb_a12
SEEDS = 5
DAY_NS = 86_400 * 10**9


def check_alignment(tm, n_rebuilt, n_table, X_rebuilt, X_table, net_rebuilt, net_table):
    """Gate 1: the rebuilt test-month rows must be the walk-forward table's rows, in order."""
    if n_rebuilt != n_table:
        raise SystemExit(f"{tm}: rebuilt {n_rebuilt} rows, the walk-forward table has {n_table}")
    if not np.allclose(X_rebuilt, X_table, equal_nan=True):
        raise SystemExit(f"{tm}: rebuilt features differ from the walk-forward table")
    if not np.allclose(net_rebuilt, net_table):
        raise SystemExit(f"{tm}: rebuilt net P&L differs from the walk-forward table")


def check_return(tm, ret):
    """Gate 2: the refitted fold must reproduce the recorded return."""
    if abs(round(ret, 2) - RECORDED[tm]) > 0.005:
        raise SystemExit(f"{tm}: return {ret:.2f} does not reproduce the recorded {RECORDED[tm]}")


def random_picks(idx, n, seed, tm):
    """n distinct rows of idx, drawn with a seed fixed by (seed, month)."""
    rng = np.random.default_rng([seed, int(tm.replace("-", ""))])
    return rng.choice(idx, size=n, replace=False)


def metrics(FL, settle, spy_ret, rf):
    """Risk metrics of a list of simulator fills, as the 2025 A16 addendum computes them."""
    import cut_report as cr
    day_ends, cum = cr.tradedate_series(FL)
    keys = [(f[0], f[1], f[2], f[3], f[4], f[5], f[7], f[9]) for f in FL]
    cap = cr.peak_open_capital(keys, settle, day_ends)
    dd = np.diff(np.concatenate([[0.0], cum]))
    dates = [dt.datetime.fromtimestamp((de - DAY_NS) / 1e9, dt.timezone.utc).date().isoformat() for de in day_ends]
    both = [(spy_ret[d], v / cap) for d, v in zip(dates, dd) if d in spy_ret and cap]
    risk = cr.risk_metrics(cum, cap, rf, ([x for x, _ in both], [y for _, y in both]) if both else None)
    net, capsum = sum(f[6] for f in FL) / 100, sum(f[7] for f in FL) / 100
    mdd = cr.max_drawdown(cum)
    return {"net_usd": round(net, 2), "ret_pct": round(100 * net / capsum, 2) if capsum else None, "fills": len(FL),
            "peak_open_capital_usd": round(cap, 2), "max_drawdown_usd": round(mdd, 2),
            "max_drawdown_pct_of_peak_capital": round(100 * mdd / cap, 2) if cap else None,
            "profitable_days_share": round(float(np.mean(dd > 0)), 3) if len(dd) else None, "risk": risk}


def run(out_path: Path):
    import maker_policy as mp
    import simulate_maker as s
    import live_signal_producer as lp
    import retrain_g2 as rg
    import tune_gbm as t
    import cut_report as cr
    from fetch_kalshi_api_months import SERIES_A13

    # rebuild the API-month fills with their quoting hours (tune_gbm.build, API part)
    lookup = mp.category_lookup()
    cache = lp.load_state("series.pkl", {})
    legs, events = rg.api_legs(rg.API, SERIES_A13)
    events = rg.single_winner_events(legs, events)
    charged = rg.fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES_A13})
    F = s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, rg.API)
    rows, fills = [], []
    for f in F:
        r = rg.features("G2", legs, events, charged, lookup, f[0], f[1], int(f[9]), int(f[2]), int(f[3]))
        if r is not None:
            rows.append(r); fills.append(f)
    D = t.load()
    X = rg.matrix("G2", rows, list(D["cats"]))
    mon = np.array([s.month_of(int(f[9])) for f in fills])
    net = np.array([f[6] for f in fills], float)
    print(f"rebuilt API fills with features: {len(fills):,}", flush=True)

    cat_col = list(D["feats"]).index("cat_i")
    g = t.GRID[0]
    assert g["name"] == "hgb_a12"
    picks, rnd, folds = [], {k: [] for k in range(SEEDS)}, {}
    for tm in t.TEST_MONTHS:
        tr, te = t.fold(D["month"], tm)
        mine = mon == tm
        check_alignment(tm, int(mine.sum()), int(te.sum()), X[mine], D["X"][te], net[mine], D["net_c"][te])
        pred, _ = t.fit_predict(g, D["X"][tr], D["y"][tr], np.ones(tr.sum()), cat_col, D["X"][te], D["month"][tr])
        sc = t.score(pred, D["net_c"][te], D["capital_c"][te], D["qty"][te])
        check_return(tm, sc["ret"])
        idx = np.flatnonzero(mine)
        keep = pred > t.THRESHOLD_C
        picks += [fills[i] for i in idx[keep]]
        for k in range(SEEDS):
            rnd[k] += [fills[i] for i in random_picks(idx, int(keep.sum()), k, tm)]
        folds[tm] = {"ret_pct": round(sc["ret"], 2), "fills": int(keep.sum())}
        print(json.dumps({tm: folds[tm], "gates": "passed"}), flush=True)

    settle = {ev: max((legs[tk]["close"] or 0) for tk in tks) or None for ev, tks in events.items()}
    bm = cr.fetch_spy_and_tbill(dt.date(2026, 4, 1), dt.date(2026, 8, 31))
    spy = bm.pop("spy_close", {})
    sd_ = sorted(spy)
    spy_ret = {sd_[i]: spy[sd_[i]] / spy[sd_[i - 1]] - 1 for i in range(1, len(sd_))}
    rf = bm.get("tbill_rate_pct", 0.0) / 100 if bm.get("tbill_rate_pct") else None
    out = {"note": "exploratory note 8 (lumid-forward-test-preregistration.md), 2026-10-21, during the live test; "
                   "offline only. L9/A15 walk-forward, G2-W3 recipe, test months 2026-04..08; metrics as the 2025 "
                   "A16 addendum (trade-date daily series)",
           "gates": "passed: rebuilt rows equal the walk-forward table; fold returns reproduce A15/L9",
           "folds": folds, "benchmarks": bm, "G2": metrics(picks, settle, spy_ret, rf),
           "random_same_share": [metrics(rnd[k], settle, spy_ret, rf) for k in range(SEEDS)]}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out, indent=1, default=float))
    print(f"-> {out_path}")


def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    H = lambda day, hour: (day * 24 + hour) * 3_600 * 10**9 + 1_790_000_000 * 10**9 // DAY_NS * DAY_NS
    f = lambda ev, net, cap, day, hour: (ev, ev + "-T", 1, 40, 10, 0.0, net, cap, 0.0, H(day, hour))
    # three days: +$1.00 (A, $4 capital), -$0.50 (B, $3), +$2.00 (C, $2); A settles day 1 noon, B day 3, C day 2 06:00
    FL = [f("A", 100.0, 400.0, 0, 3), f("B", -50.0, 300.0, 1, 3), f("C", 200.0, 200.0, 2, 1)]
    settle = {"A": H(1, 12), "B": H(3, 0), "C": H(2, 6)}
    m = metrics(FL, settle, {}, None)
    check(f"net and return (+$2.50 on $9 = 27.78%; got {m['net_usd']}, {m['ret_pct']})",
          m["net_usd"] == 2.5 and m["ret_pct"] == 27.78)
    check(f"max drawdown = the $0.50 fall from $1.00 to $0.50 (got {m['max_drawdown_usd']})", m["max_drawdown_usd"] == 0.5)
    check(f"peak open capital = A's $4 at the end of day 0 (got {m['peak_open_capital_usd']})",
          m["peak_open_capital_usd"] == 4.0)
    check(f"drawdown 12.5% of peak capital (got {m['max_drawdown_pct_of_peak_capital']})",
          m["max_drawdown_pct_of_peak_capital"] == 12.5)
    check(f"profitable days 2 of 3 (got {m['profitable_days_share']})", m["profitable_days_share"] == 0.667)
    check("three daily returns behind the Sharpe", m["risk"].get("days") == 3)

    idx = np.arange(100, 200)
    a, b = random_picks(idx, 30, 0, "2026-04"), random_picks(idx, 30, 0, "2026-04")
    check("random picks: the requested number, distinct, within the month's rows, reproducible",
          len(a) == 30 and len(set(a)) == 30 and set(a) <= set(idx) and np.array_equal(a, b))
    check("random picks: another seed or month draws a different set",
          not np.array_equal(a, random_picks(idx, 30, 1, "2026-04")) and not np.array_equal(a, random_picks(idx, 30, 0, "2026-05")))

    def stops(fn):
        try:
            fn()
        except SystemExit:
            return True
        return False
    Xa = np.arange(6.0).reshape(3, 2)
    check("gate 1 passes identical rows", not stops(lambda: check_alignment("m", 3, 3, Xa, Xa.copy(), np.ones(3), np.ones(3))))
    check("gate 1 stops on a different row count", stops(lambda: check_alignment("m", 3, 4, Xa, Xa, np.ones(3), np.ones(3))))
    check("gate 1 stops on a changed feature", stops(lambda: check_alignment("m", 3, 3, Xa, Xa + 0.5, np.ones(3), np.ones(3))))
    check("gate 1 stops on a changed net", stops(lambda: check_alignment("m", 3, 3, Xa, Xa, np.ones(3), np.zeros(3))))
    check("gate 2 passes the recorded return", not stops(lambda: check_return("2026-06", 3.2617)))
    check("gate 2 stops on a different return", stops(lambda: check_return("2026-06", 3.20)))
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.out)


if __name__ == "__main__":
    main()
