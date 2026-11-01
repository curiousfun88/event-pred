"""Pre-registered research backtest: Kalshi -> Polymarket catch-up.
Rule, cost model and verdict: docs/planning/cross-venue-preregistration.md
(fixed 2026-09-30, before any 2026 data was fetched). Do not change them.

Inputs: matched legs (match_polymarket_events.py), Kalshi hourly candles
(fetch_kalshi_events.py candles: ticker, end_s, bid, ask in dollars) and
Polymarket mid history (cross_venue_leadlag.fetch_pm cache).

    python stg_infra/examples/cross_venue_backtest.py --self-test
    python stg_infra/examples/cross_venue_backtest.py MATCH.parquet CANDLES.parquet
"""
import sys, argparse
import numpy as np

sys.path.insert(0, "stg_infra/examples")
H = 3600
GAP_MIN, K_MOVE_MIN, P_AWAY_MAX = 3.0, 1.0, 1.0      # pre-registered, cents
FEE_SENS = 1.0                                       # cents per contract round trip (sensitivity)


def asof(ts, vals, t):
    j = np.searchsorted(ts, t, side="right") - 1
    return vals[j] if j >= 0 else np.nan


def spread_from_mid(mid_c):
    """Pre-registered: half-cent mid -> 1c spread; whole cent or anything else -> 2c."""
    frac = round(mid_c % 1, 3)
    return 1.0 if abs(frac - 0.5) < 1e-6 else 2.0


def leg_trades(kq, pm_ts, pm_c, close_s, event, horizons=(1, 2, 6)):
    """kq: {hour_s: (bid_c, ask_c)} two-sided Kalshi quotes. pm_ts/pm_c: PM mid history (s, cents).
    Returns trades (event, H, dir, gap, net_1h, net_1h_fee, net_2h, net_6h); the one-open-position
    rule applies to the primary 1h exit."""
    out, busy_until = [], -1
    for Hh in sorted(kq):
        if Hh - H not in kq or (close_s is not None and Hh + H >= close_s) or Hh < busy_until:
            continue
        k0, km1 = sum(kq[Hh]) / 2, sum(kq[Hh - H]) / 2
        p0, pm1 = asof(pm_ts, pm_c, Hh), asof(pm_ts, pm_c, Hh - H)
        if np.isnan(p0) or np.isnan(pm1):
            continue
        gap = k0 - p0
        sg = np.sign(gap)
        if not (abs(gap) >= GAP_MIN and sg * (k0 - km1) >= K_MOVE_MIN and -sg * (p0 - pm1) < P_AWAY_MAX):
            continue
        nets = []
        for h in horizons:
            if close_s is not None and Hh + h * H >= close_s:
                nets.append(np.nan); continue
            p1 = asof(pm_ts, pm_c, Hh + h * H)
            nets.append(sg * (p1 - p0) - spread_from_mid(p0) / 2 - spread_from_mid(p1) / 2)
        out.append((event, Hh, int(sg), gap, nets[0], nets[0] - FEE_SENS, nets[1], nets[2]))
        busy_until = Hh + H
    return out


def mean_ci(v, groups, n_boot=4000, seed=0):
    ok = ~np.isnan(v)
    v, groups = v[ok], groups[ok]
    if len(v) == 0:
        return np.nan, (np.nan, np.nan), 0, 0
    _, inv = np.unique(groups, return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k)
    c = np.bincount(inv, minlength=k).astype(float)
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    m = s[idx].sum(1) / c[idx].sum(1)
    return v.mean(), tuple(np.percentile(m, [2.5, 97.5])), k, len(v)


def report(trades, label):
    ev = np.array([t[0] for t in trades])
    A = np.array([t[3:] for t in trades], float)
    print(f"\n{label}: {len(trades):,} trades in {len(np.unique(ev))} events; mean |gap| {np.abs(A[:, 0]).mean():.1f}c")
    for j, nm in ((1, "PRIMARY net 1h, fee 0      "), (2, "net 1h, fee 1c (sensitivity)"),
                  (3, "net 2h (secondary)          "), (4, "net 6h (secondary)          ")):
        m, (lo, hi), k, n = mean_ci(A[:, j], ev)
        print(f"  {nm}: {m:+.2f}c/contract  CI95 [{lo:+.2f}, {hi:+.2f}]  (k={k} events, n={n})")
    m, (lo, hi), k, n = mean_ci(A[:, 1], ev)
    return m, lo, hi


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted legs)")
    check("spread: 45.5c -> 1c, 45c -> 2c, 45.3c -> 2c",
          spread_from_mid(45.5) == 1 and spread_from_mid(45.0) == 2 and spread_from_mid(45.3) == 2)
    # Kalshi jumps 40 -> 46 at hour 2; PM at 40.5 then catches up to 45.5 by hour 3.
    kq = {h * H: (b, b + 2) for h, b in enumerate([39, 39, 45, 45, 45, 45, 45, 45, 45, 45])}
    pm_ts = np.array([h * H for h in range(10)])
    pm_c = np.array([40.5, 40.5, 40.5, 45.5, 45.5, 45.5, 45.5, 45.5, 45.5, 45.5])
    tr = leg_trades(kq, pm_ts, pm_c, None, "E")
    check("one signal, at hour 2, long PM", len(tr) == 1 and tr[0][1] == 2 * H and tr[0][2] == 1)
    check("net = 5c move - 0.5 - 0.5 = +4c", abs(tr[0][4] - 4.0) < 1e-9)
    check("fee sensitivity subtracts 1c", abs(tr[0][5] - 3.0) < 1e-9)
    # PM moved AWAY (opened the gap) -> no signal
    pm_c2 = np.array([40.5, 40.5, 35.5, 35.5, 35.5, 35.5, 35.5, 35.5, 35.5, 35.5])
    kq2 = {h * H: (39, 41) for h in range(10)}
    check("PM opened the gap -> no trade", leg_trades(kq2, pm_ts, pm_c2, None, "E") == [])
    # gap below threshold -> no signal
    kq3 = {h * H: (b, b + 2) for h, b in enumerate([39, 39, 41, 41, 41, 41, 41, 41, 41, 41])}
    check("gap < 3c -> no trade", leg_trades(kq3, pm_ts, np.full(10, 40.5), None, "E") == [])
    # close: exit must be before close
    check("no trade if H+1h >= close", leg_trades(kq, pm_ts, pm_c, 3 * H, "E") == [])
    # PM moves away after entry -> loss
    pm_c4 = np.array([40.5, 40.5, 40.5, 38.5, 38.5, 38.5, 38.5, 38.5, 38.5, 38.5])
    tr4 = leg_trades(kq, pm_ts, pm_c4, None, "E")
    check("adverse move -> loss (-2 - 0.5 - 0.5 = -3c)", len(tr4) == 1 and abs(tr4[0][4] + 3.0) < 1e-9)
    # one open position per leg
    kq5 = {h * H: (b, b + 2) for h, b in enumerate([39, 39, 45, 51, 57, 57, 57, 57, 57, 57])}
    tr5 = leg_trades(kq5, pm_ts, np.full(10, 40.5), None, "E")
    check("consecutive signals: exit at H+1h lets the next hour trade again", [t[1] for t in tr5] == [2 * H, 3 * H, 4 * H])
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="?")
    ap.add_argument("candles", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    import cross_venue_leadlag as c
    m = pl.read_parquet(a.match)
    k = pl.read_parquet(a.candles)
    cand = pl.read_parquet("data/polymarket/kalshi_2026_candidates.parquet").select("ticker", "close_time").unique("ticker")
    close = {r["ticker"]: int(r["close_time"].timestamp()) for r in cand.iter_rows(named=True)}
    trades = []
    for r in m.iter_rows(named=True):
        g = k.filter(pl.col("ticker") == r["kalshi_ticker"])
        kq = {int(h): (round(b * 100), round(x * 100)) for h, b, x in zip(g["end_s"], g["bid"], g["ask"])
              if b is not None and x is not None and 0 < b < x < 1}
        if len(kq) < 3:
            continue
        pts = c.fetch_pm(r["pm_token_yes"], min(kq) - 2 * H, max(kq) + 7 * H)
        if not pts:
            continue
        ts = np.array([t for t, _ in pts], dtype=np.int64)
        pc = np.array([p for _, p in pts]) * 100
        trades += [(*t, r["event_ticker"].split("-")[0]) for t in
                   leg_trades(kq, ts, pc, close.get(r["kalshi_ticker"]), r["event_ticker"])]
    print("PRE-REGISTERED TEST (docs/planning/cross-venue-preregistration.md), 2026 data, run once")
    print(f"matched legs {m.height}, events {m['event_ticker'].n_unique()}")
    if not trades:
        print("NO TRADES"); return
    mean, lo, hi = report([t[:-1] for t in trades], "ALL")
    print(f"\nVERDICT: mean net {mean:+.2f}c, CI95 [{lo:+.2f}, {hi:+.2f}] -> "
          + ("SUPPORTED (mean > 0, CI excludes 0)" if lo > 0 else "NOT SUPPORTED"))
    for s in sorted({t[-1] for t in trades}):
        sub = [t[:-1] for t in trades if t[-1] == s]
        report(sub, s)


if __name__ == "__main__":
    main()
