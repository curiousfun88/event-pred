"""Exploratory (development months only): does Polymarket lead Kalshi on
matched MECE legs at the hourly scale?

For every matched leg (match_polymarket_events.py output) and quoting hour H
at which the Kalshi leg has a two-sided quote at H and at H+1h:
  y   = Kalshi quoted mid(H+1h) - mid(H)                     [target, cents]
  xk  = Kalshi mid(H) - mid(H-1h)                            [own last move]
  xp  = Polymarket price(H) - price(H-1h)                    [PM last move]
  gap = Polymarket price(H) - Kalshi mid(H)                  [level gap]
Polymarket prices are taken as-of (last point at or before the hour), so
nothing after H is used as an input. Hours at or after the Kalshi leg's close
are dropped.

Models: zero move; y ~ a*xk; y ~ b*xp; y ~ c*gap; y ~ xk + xp + gap (no
intercept). Every coefficient is fitted leave-one-EVENT-out, so no event is
scored by a fit that saw it. Reported: MSE / MSE(zero) with a 95% CI that
resamples events. The reverse direction (Kalshi predicting Polymarket's next
move) is reported for symmetry.

Rough tradability (not a strategy test): take the combined model's
out-of-fold prediction, trade 1 contract on Kalshi when |pred| > half the
quoted spread, entering at the ask (long) or bid (short). Exit at H+1h is
shown at the MID (optimistic) and at the BID/ASK (pessimistic round trip),
gross and after the Kalshi taker fee on entry (plus exit, pessimistic).

    python stg_infra/examples/cross_venue_leadlag.py --self-test
    python stg_infra/examples/cross_venue_leadlag.py data/polymarket/match_dev.parquet
"""
import sys, json, math, time, argparse
from pathlib import Path
import numpy as np

H = 3600
PM_DIR = Path("data/polymarket/prices")
CLOB = "https://clob.polymarket.com/prices-history"


def taker_fee_c(p_c):
    p = p_c / 100.0
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6))


# ---------------------------------------------------------------- data
def fetch_pm(token, start, end):
    """Hourly Polymarket history for one YES token, in <=14-day windows, cached."""
    import urllib.request
    PM_DIR.mkdir(parents=True, exist_ok=True)
    f = PM_DIR / f"{token}.json"
    if f.exists():
        return json.loads(f.read_text())
    pts, s = {}, int(start)
    while s < end:
        e = min(s + 14 * 86400 - 60, int(end))
        url = f"{CLOB}?market={token}&startTs={s}&endTs={e}&fidelity=60"
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; event-pred)"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    for p in json.load(r).get("history", []):
                        pts[int(p["t"])] = float(p["p"])
                break
            except Exception:
                time.sleep(2 * (attempt + 1))
        s = e
        time.sleep(0.15)
    out = sorted(pts.items())
    f.write_text(json.dumps(out))
    return out


def asof(ts_sorted, vals, t):
    """Last value at or before t, else nan."""
    j = np.searchsorted(ts_sorted, t, side="right") - 1
    return vals[j] if j >= 0 else np.nan


def build_rows(kq, pm_pts, close_ts, event, leg):
    """kq: dict hour_ts -> (bid_c, ask_c) two-sided Kalshi quotes. pm_pts: [(t, p)].
    Returns list of (event, leg, H, y, xk, xp, gap, bid, ask, yp) in cents;
    yp = PM move over (H, H+1h] for the reverse test."""
    if not pm_pts:
        return []
    pt = np.array([t for t, _ in pm_pts], dtype=np.int64)
    pv = np.array([p for _, p in pm_pts]) * 100
    rows = []
    for Hh in sorted(kq):
        if close_ts is not None and Hh + H >= close_ts:
            continue
        if Hh + H not in kq or Hh - H not in kq:
            continue
        b0, a0 = kq[Hh]; b1, a1 = kq[Hh + H]; bm, am = kq[Hh - H]
        m0, m1, mm = (b0 + a0) / 2, (b1 + a1) / 2, (bm + am) / 2
        p0, pm1, pp1 = asof(pt, pv, Hh), asof(pt, pv, Hh - H), asof(pt, pv, Hh + H)
        if np.isnan(p0) or np.isnan(pm1):
            continue
        rows.append((event, leg, Hh, m1 - m0, m0 - mm, p0 - pm1, p0 - m0, b0, a0, pp1 - p0))
    return rows


# ---------------------------------------------------------------- models
def loeo_predict(X, y, groups):
    """Leave-one-group-out least squares without intercept."""
    pred = np.zeros_like(y)
    for g in np.unique(groups):
        tr, te = groups != g, groups == g
        if tr.sum() < X.shape[1] + 1:
            continue
        beta, *_ = np.linalg.lstsq(X[tr], y[tr], rcond=None)
        pred[te] = X[te] @ beta
    return pred


def ratio_ci(y, pred, groups, n_boot=2000, seed=0):
    """MSE(pred)/MSE(zero) and 95% CI resampling groups."""
    _, inv = np.unique(groups, return_inverse=True)
    k = inv.max() + 1
    se_m = np.bincount(inv, weights=(y - pred) ** 2, minlength=k)
    se_z = np.bincount(inv, weights=y ** 2, minlength=k)
    point = se_m.sum() / se_z.sum() if se_z.sum() > 0 else np.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    num, den = se_m[idx].sum(1), se_z[idx].sum(1)
    r = num[den > 0] / den[den > 0]
    return point, tuple(np.percentile(r, [2.5, 97.5])), k


def mean_ci(v, groups, n_boot=2000, seed=0):
    if len(v) == 0:
        return np.nan, (np.nan, np.nan), 0
    _, inv = np.unique(groups, return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k)
    c = np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    m = s[idx].sum(1) / c[idx].sum(1)
    return v.mean(), tuple(np.percentile(m, [2.5, 97.5])), k


def analyse(rows, label="ALL"):
    ev = np.array([r[0] for r in rows])
    A = np.array([r[3:] for r in rows], dtype=float)
    y, xk, xp, gap, bid, ask, yp = A.T
    out = {"n": len(y), "events": len(np.unique(ev))}
    specs = {"own last move (xk)": xk[:, None], "PM last move (xp)": xp[:, None],
             "level gap (gap)": gap[:, None], "combined (xk+xp+gap)": np.c_[xk, xp, gap]}
    print(f"\n{label}: n={len(y):,} leg-hours, {out['events']} events; "
          f"share of hours with Kalshi mid unchanged {np.mean(y == 0):.0%}")
    for name, X in specs.items():
        p = loeo_predict(X, y, ev)
        r, (lo, hi), k = ratio_ci(y, p, ev)
        out[name] = r
        print(f"  Kalshi next move ~ {name:<22}: {r:.3f}x zero-move  CI95 [{lo:.3f}, {hi:.3f}]  (k={k})")
    ok = ~np.isnan(yp)
    p = loeo_predict(xk[ok, None] * 0 + np.c_[-gap[ok]], yp[ok], ev[ok])
    r, (lo, hi), k = ratio_ci(yp[ok], p, ev[ok])
    out["reverse"] = r
    print(f"  REVERSE: PM next move ~ -gap (Kalshi leads): {r:.3f}x zero-move  CI95 [{lo:.3f}, {hi:.3f}]  (k={k})")

    pred = loeo_predict(np.c_[xk, xp, gap], y, ev)
    half = (ask - bid) / 2
    trade = np.abs(pred) > half
    side = np.sign(pred)
    mid1 = (bid + ask) / 2 + y
    entry = np.where(side > 0, ask, bid)
    gross_mid = side * (mid1 - entry)
    # pessimistic exit at the opposite touch at H+1: approximate with the H spread
    exit_touch = mid1 - side * half
    gross_touch = side * (exit_touch - entry)
    fee_in = np.array([taker_fee_c(e) for e in entry])
    fee_out = np.array([taker_fee_c(max(1, min(99, x))) for x in exit_touch])
    t = trade
    print(f"  trades (|pred| > half-spread): {t.sum():,} of {len(y):,} leg-hours; median spread {np.median(ask - bid):.1f}c")
    for nm, v in (("exit at mid, gross", gross_mid), ("exit at mid, - entry fee", gross_mid - fee_in),
                  ("exit at touch, gross", gross_touch), ("exit at touch, - both fees", gross_touch - fee_in - fee_out)):
        m, (lo, hi), k = mean_ci(v[t], ev[t])
        print(f"    {nm:<28}: {m:+.2f}c/contract  CI95 [{lo:+.2f}, {hi:+.2f}]  (k={k})")
    out["trades"] = int(t.sum())
    return out


# ---------------------------------------------------------------- self-test
def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted series)")
    rng = np.random.default_rng(1)

    def make(lag, n_ev=30, T=60):
        rows = []
        for e in range(n_ev):
            true = np.clip(50 + np.cumsum(rng.normal(0, 3, T + 3)), 5, 95)
            pm = true + rng.normal(0, 0.3, T + 3)
            k = np.roll(true, lag) if lag else true + rng.normal(0, 3, T + 3)
            kq = {h * H: (round(k[h]) - 1, round(k[h]) + 1) for h in range(T + 3)}
            pts = [(h * H, pm[h] / 100) for h in range(T + 3)]
            rows += build_rows(kq, pts, None, f"E{e}", "L")
        return rows
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        lagged = analyse(make(lag=1), "planted lag")
        indep = analyse(make(lag=0), "planted independent")
    check(f"Kalshi lagging PM by 1h: PM-move model << zero-move ({lagged['PM last move (xp)']:.2f})",
          lagged["PM last move (xp)"] < 0.7)
    check(f"independent noise: PM-move model ~ zero-move ({indep['PM last move (xp)']:.2f})",
          0.9 < indep["PM last move (xp)"] < 1.1)
    check("lagged market is tradeable (trades happen)", lagged["trades"] > 0)
    # as-of never looks ahead
    pt, pv = np.array([0, 3600, 7200]), np.array([10., 20., 30.])
    check("asof at 3599 uses t=0 value", asof(pt, pv, 3599) == 10.0)
    check("asof at 3600 uses t=3600 value", asof(pt, pv, 3600) == 20.0)
    kq = {0: (40, 42), H: (41, 43), 2 * H: (42, 44), 3 * H: (43, 45)}
    rows = build_rows(kq, [(0, .4), (H, .41), (2 * H, .42), (3 * H, .43)], close_ts=3 * H, event="E", leg="L")
    check("rows stop before close (H+1h >= close dropped)", [r[2] for r in rows] == [H])
    check("taker fee at 50c = 2c", taker_fee_c(50) == 2)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("match", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    m = pl.read_parquet(a.match)
    q = pl.concat([pl.read_parquet(f) for f in sorted(Path("data/quotes/by_month").glob("quotes_*.parquet"))
                   if "2024-10" < f.stem[-7:] <= "2025-07"], how="diagonal_relaxed")
    q = q.filter(pl.col("ticker").is_in(m["kalshi_ticker"].to_list()))
    q = q.with_columns((pl.col("end_ts").dt.epoch("s")).alias("h"))
    mk = pl.scan_parquet("data/markets/markets_kalshi/*.parquet").select("ticker", "close_time").filter(
        pl.col("ticker").is_in(m["kalshi_ticker"].to_list())).collect().unique("ticker")
    close = {r["ticker"]: int(r["close_time"].timestamp()) for r in mk.iter_rows(named=True) if r["close_time"]}
    cat = lambda ev: ev.split("-")[0]
    rows = []
    for r in m.iter_rows(named=True):
        g = q.filter(pl.col("ticker") == r["kalshi_ticker"])
        kq = {}
        for h, b, a_ in zip(g["h"].to_list(), g["bid_close"].to_list(), g["ask_close"].to_list()):
            if b is None or a_ is None or not (0 < b < a_ < 1):
                continue
            kq[int(h)] = (round(b * 100), round(a_ * 100))
        if len(kq) < 3:
            continue
        pts = fetch_pm(r["pm_token_yes"], min(kq) - 2 * H, max(kq) + 2 * H)
        rows += build_rows(kq, pts, close.get(r["kalshi_ticker"]), r["event_ticker"], r["kalshi_ticker"])
    print(f"development months only; {m['event_ticker'].n_unique()} matched events, {m.height} legs")
    analyse(rows, "ALL")
    for c in sorted({cat(r[0]) for r in rows}):
        sub = [r for r in rows if cat(r[0]) == c]
        if len({r[0] for r in sub}) >= 3:
            analyse(sub, c)


if __name__ == "__main__":
    main()
