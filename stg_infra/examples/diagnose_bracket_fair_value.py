"""
diagnose_bracket_fair_value.py

DIAGNOSTIC (exploratory): is an EXTERNAL fair value for the index / FX bracket baskets
(KXINX, KXNASDAQ100, KXEURUSD) worth adding to the maker? Upper-bound check before any
live feed or new arm is built.

FAIR VALUE (no parameter fitted on Kalshi data). Each basket settles on one number: the
S&P 500 / Nasdaq-100 end-of-day value (close_ns = 4pm ET) or the EUR/USD 10am ET price.
At quoting hour H:
  level   index: last index hourly close known at H, carried forward by the front futures
          (ES=F / NQ=F) move since then (futures trade overnight); FX: EURUSD=X spot at H.
  vol     index: VIX / VXN at H (annualised); FX: realised vol of the last 480 hourly bars.
  clock   index: hours inside the 6.5h session before close_ns weigh 1, other weekday hours
          0.1, weekends 0, annualised over 252 x 8.25 h; FX: weekday hours, 260 x 24 h.
  model   log-normal, martingale drift; leg prob = P(settle in [floor, cap]) or tail.
Yahoo bars are stamped at their START; a bar counts as known only from start + 1h (as-of).

STRIKES are parsed from tickers (the API month cache stores none): B legs carry a bracket
mid-point (truncated for KXINX: B8037 = 8025..8049.99), width w = spacing of the B values,
floor = w * floor(B / w), cap = floor + w; the lower T leg is "below", the upper "above". The self-test checks the parse against the real floor/cap of every market
in the validation metadata.

ANALYSES
  A  calibration, 2025-12..2026-08 (API cache): Brier of fair value vs the Kalshi mid.
  B  quote-everything fills (BROAD, pessimistic), 2025-12..2026-08, binned by fair-value
     edge for the side posted: edge = side * (100 * fair - price), in cents.
  C  quote everything + "post only if edge > t", t in {0, 2}c (fixed before running),
     2025-12..2026-08, pessimistic and strict, against no filter.
  D  validation 2026-09-07..10-04: G2-W3 fills on these series binned by edge, and G2-W3
     + the t = 0 filter. G2-W3 trained on 2025-12..2026-08, so it is only scored on D.
  E  (--extra, added after the first run of A-D) quote everything + filter on validation;
     2025-12..2026-08 by hours to close (quote everything vs the t = 2c filter); paired
     event-bootstrap CI of the filter's lift over quote everything.

PREDICTIONS (written before the first run):
  A  the Kalshi mid beats the fair value on Brier (the market already prices the underlying).
  B  fills with edge > 0 earn more than fills with edge < 0 (monotone across the bins).
  C  the filter lifts quote-everything's return; the lift on G2-W3 (D) is smaller, because
     G2 already avoids most adverse fills.

USAGE (from repo root, memory-capped):
    python stg_infra/examples/diagnose_bracket_fair_value.py --self-test
    python stg_infra/examples/diagnose_bracket_fair_value.py
    python stg_infra/examples/diagnose_bracket_fair_value.py --extra
"""
from __future__ import annotations

import argparse
import functools
import datetime as dt
import json
import math
import pickle
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

H_NS = 3_600_000_000_000
SERIES = ["KXINX", "KXNASDAQ100", "KXEURUSD"]
UNDERLYING = {"KXINX": ("^GSPC", "ES=F", "^VIX"), "KXNASDAQ100": ("^NDX", "NQ=F", "^VXN"),
              "KXEURUSD": ("EURUSD=X", None, None)}
MONTHS = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
PRICE_DIR = _REPO / "data/ext_prices"
P1, P2 = int(dt.datetime(2025, 11, 1, tzinfo=dt.timezone.utc).timestamp()), \
    int(dt.datetime(2026, 10, 9, tzinfo=dt.timezone.utc).timestamp())
EDGE_BINS = [(-np.inf, -5), (-5, -2), (-2, 0), (0, 2), (2, 5), (5, np.inf)]
THRESHOLDS = [0.0, 2.0]
SESSION_H, OFF_W = 6.5, 0.1


# ---------------------------------------------------------------- strikes

def parse_strikes(tickers):
    """{ticker: (floor, cap)} for one event; floor None = below cap, cap None = above floor."""
    num = {t: float(t.rsplit("-", 1)[1][1:]) for t in tickers}
    bs = sorted(num[t] for t in tickers if t.rsplit("-", 1)[1][0] == "B")
    ts = sorted((num[t], t) for t in tickers if t.rsplit("-", 1)[1][0] == "T")
    if len(bs) < 2:
        return {}
    w = float(np.median(np.diff(bs)))
    fl = lambda b: w * math.floor(b / w + 1e-9)
    out = {t: (fl(num[t]), fl(num[t]) + w) for t in tickers if t.rsplit("-", 1)[1][0] == "B"}
    lo_b, hi_b = fl(bs[0]), fl(bs[-1]) + w
    for v, t in ts:
        if abs(v - lo_b) <= abs(v - hi_b):
            out[t] = (None, v)          # below the lowest bracket
        else:
            out[t] = (v, None)          # above the highest bracket
    return out


# ---------------------------------------------------------------- external prices

def fetch(sym):
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    p = PRICE_DIR / f"{sym.replace('^', '').replace('=', '_')}_60m_{P1}_{P2}.json"
    if not p.exists():
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}"
               f"?interval=60m&period1={P1}&period2={P2}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        p.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    r = json.loads(p.read_text())["chart"]["result"][0]
    t = np.asarray(r["timestamp"], dtype=np.int64) * 10**9 + H_NS      # known from bar END
    c = np.asarray([np.nan if x is None else x for x in r["indicators"]["quote"][0]["close"]], float)
    ok = ~np.isnan(c)
    return t[ok], c[ok]


def asof(series, H):
    """(known_at_ns, value) of the last bar known at H, or (None, nan)."""
    t, c = series
    i = np.searchsorted(t, H, side="right") - 1
    return (int(t[i]), float(c[i])) if i >= 0 else (None, float("nan"))


class Underlying:
    def __init__(self, ser):
        idx, fut, vol = UNDERLYING[ser]
        self.fx = fut is None
        self.idx = fetch(idx)
        self.fut = None if self.fx else fetch(fut)
        self.vol = None if self.fx else fetch(vol)

    def level(self, H):
        ti, li = asof(self.idx, H)
        if self.fx or ti is None:
            return li
        _, f_now = asof(self.fut, H)
        _, f_ref = asof(self.fut, ti)
        return li * f_now / f_ref if f_ref and not math.isnan(f_now) else li

    def sigma(self, H):
        if not self.fx:
            return asof(self.vol, H)[1] / 100.0
        t, c = self.idx
        i = np.searchsorted(t, H, side="right")
        r = np.diff(np.log(c[max(0, i - 481):i]))
        return float(np.std(r) * math.sqrt(260 * 24)) if len(r) > 100 else float("nan")


@functools.lru_cache(maxsize=None)
def var_years(H, T, fx):
    """Variance clock between H and settlement T (ns), in years."""
    if T <= H:
        return 0.0
    w = 0.0
    step = 15 * 60 * 10**9
    close_h = dt.datetime.fromtimestamp(T / 1e9, dt.timezone.utc).hour
    for x in range(H, T, step):
        d = dt.datetime.fromtimestamp(x / 1e9, dt.timezone.utc)
        if d.weekday() >= 5:
            continue
        if fx:
            w += 0.25
            continue
        # session = the 6.5h before the same UTC clock time as the settlement close
        close_today = d.replace(hour=close_h, minute=0, second=0, microsecond=0)
        in_session = close_today - dt.timedelta(hours=SESSION_H) <= d < close_today
        w += 0.25 * (1.0 if in_session else OFF_W)
    return w / (260 * 24 if fx else 252 * (SESSION_H + OFF_W * (24 - SESSION_H)))


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def leg_prob(S, sigma, tau, floor, cap):
    if not (S > 0) or not (sigma > 0) or math.isnan(sigma):
        return float("nan")
    if tau <= 0:
        return float((floor is None or S >= floor) and (cap is None or S <= cap))
    sd = sigma * math.sqrt(tau)
    z = lambda k: (math.log(k / S) + 0.5 * sd * sd) / sd
    lo = 0.0 if floor is None else norm_cdf(z(floor))
    hi = 1.0 if cap is None else norm_cdf(z(cap))
    return max(0.0, hi - lo)


class FairValue:
    def __init__(self, legs, events):
        self.und = {s: Underlying(s) for s in SERIES}
        self.strikes = {}
        for ev, tks in events.items():
            if legs[tks[0]]["series"] in SERIES:
                self.strikes.update(parse_strikes(tks))
        self.legs = legs
        self._lvl = {}

    def __call__(self, tk, H):
        if tk not in self.strikes:
            return float("nan")
        L = self.legs[tk]
        ser, T = L["series"], L["close"]
        key = (ser, H)
        if key not in self._lvl:
            u = self.und[ser]
            self._lvl[key] = (u.level(H), u.sigma(H))
        S, sig = self._lvl[key]
        f, c = self.strikes[tk]
        return leg_prob(S, sig, var_years(H, T, ser == "KXEURUSD"), f, c)


# ---------------------------------------------------------------- report helpers

def line(r):
    return (f"fills {r['fills']:>6,}  events {r['events']:>4}  net ${r['net_c'] / 100:+9.2f}  "
            f"ret {r['ret']:+6.2f}% CI [{r['lo']:+6.2f}, {r['hi']:+6.2f}]  markout {r['markout_c_per_contract']:+.2f}c")


def edge_of(fv, f):
    p = fv(f[1], int(f[9]))
    return float("nan") if math.isnan(p) else f[2] * (100.0 * p - f[3])


def by_edge(fills, fv, summarise, title):
    print(f"  {title}")
    e = [edge_of(fv, f) for f in fills]
    for lo, hi in EDGE_BINS:
        sub = [f for f, x in zip(fills, e) if lo <= x < hi]
        if sub:
            print(f"    edge [{lo:>4g},{hi:>4g})c  {line(summarise(sub))}")
    miss = [f for f, x in zip(fills, e) if math.isnan(x)]
    if miss:
        print(f"    no fair value      {line(summarise(miss))}")


def candidate_scores(cand, fv):
    out = {}
    for ev, tk, H, sd, pr, b, a in cand:
        p = fv(tk, int(H))
        out[(tk, int(H), int(sd))] = -np.inf if math.isnan(p) else int(sd) * (100.0 * p - int(pr))
    return out


# ---------------------------------------------------------------- run

def run():
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import live_signal_producer as lp
    import diagnose_g2_event_timing as dg

    cache = lp.load_state("series.pkl", {})
    charged = rg.fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES})

    # ---- A, B, C on 2025-12..2026-08 (quote everything; no model trained on Kalshi data here)
    print(f"== 2025-12..2026-08, API cache, series {SERIES}")
    br_fair, br_mid = [], []
    QE = {"pess": [], "strict": []}
    QE_EDGE = []
    FIL = {(t, m): [] for t in THRESHOLDS for m in ("pess", "strict")}
    for mo in MONTHS:
        legs, events = rg.api_legs([mo], SERIES)
        fv = FairValue(legs, events)
        for tk, L in legs.items():
            if tk not in fv.strikes:
                continue
            for j, H in enumerate(L["e"]):
                H = int(H)
                b, a = float(L["bid"][j]), float(L["ask"][j])
                if H >= L["close"] or not (0 < b < a < 1):
                    continue
                p = fv(tk, H)
                if not math.isnan(p):
                    br_fair.append((p - L["yes"]) ** 2)
                    br_mid.append((0.5 * (a + b) - L["yes"]) ** 2)
        for m in ("pess", "strict"):
            fl = s.simulate(s.Config(**mp.BROAD), m, legs, events, charged, [mo])
            QE[m] += fl
            if m == "pess":
                QE_EDGE += [edge_of(fv, f) for f in fl]
        cand = []
        s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, [mo], record=cand)
        sc = candidate_scores(cand, fv)
        for t in THRESHOLDS:
            for m in ("pess", "strict"):
                FIL[(t, m)] += s.simulate(s.Config(**mp.BROAD, policy="x", policy_t=t), m, legs, events, charged,
                                          [mo], policy_scores=sc)
        print(f"  {mo}: legs {len(legs):,}  with strikes {len(fv.strikes):,}  "
              f"fair value missing on {sum(math.isnan(x) for x in QE_EDGE)} fills so far", flush=True)

    fb, mb = float(np.mean(br_fair)), float(np.mean(br_mid))
    print(f"\nA  calibration over {len(br_fair):,} quoted leg-hours: Brier fair {fb:.5f}  Kalshi mid {mb:.5f}  "
          f"(fair / mid = {fb / mb:.3f})")
    print("\nB  quote everything, pessimistic, by fair-value edge of the side posted")
    for lo, hi in EDGE_BINS:
        sub = [f for f, x in zip(QE["pess"], QE_EDGE) if lo <= x < hi]
        if sub:
            print(f"    edge [{lo:>4g},{hi:>4g})c  {line(s.summarise(sub))}")
    print("\nC  quote everything, with and without 'post only if fair-value edge > t'")
    for m in ("pess", "strict"):
        print(f"  no filter      [{m:<6}] {line(s.summarise(QE[m]))}")
        for t in THRESHOLDS:
            print(f"  edge > {t:>3g}c   [{m:<6}] {line(s.summarise(FIL[(t, m)]))}")

    # ---- D: validation, G2-W3 (trained on the months above, so scored only here)
    print(f"\n== D  validation {rg.VAL[0]}..{rg.VAL[1]}: G2-W3 on {SERIES}")
    legs, events, charged_v, start, end = rg.val_data()
    months = ["2026-09", "2026-10"]
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end and legs[f[1]]["series"] in SERIES]
    fv = FairValue(legs, events)
    pol = dg.scores_g2_w3(legs, events, charged_v, start, end, months)
    cand = []
    s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged_v, months, record=cand)
    price = {(tk, int(H), int(sd)): int(pr) for ev, tk, H, sd, pr, b, a in cand}
    gp = {}
    for k, v in pol.items():
        p = fv(k[0], k[1]) if legs[k[0]]["series"] in SERIES else float("nan")
        gp[k] = v if (math.isnan(p) or k not in price or k[2] * (100 * p - price[k]) > 0) else -np.inf
    cfg = rg.sim_cfg("G2", policy="x", policy_t=1.0)
    for m in ("pess", "strict"):
        G = win(s.simulate(cfg, m, legs, events, charged_v, months, policy_scores=pol))
        by_edge(G, fv, s.summarise, f"G2-W3 [{m}] by fair-value edge")
        F = win(s.simulate(cfg, m, legs, events, charged_v, months, policy_scores=gp))
        print(f"  G2-W3            [{m:<6}] {line(s.summarise(G))}")
        print(f"  G2-W3 + edge > 0 [{m:<6}] {line(s.summarise(F))}")


TTC_BINS = [(0, 1), (1, 2), (2, 4), (4, 8), (8, 24), (24, 72), (72, np.inf)]


def run_extra():
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import live_signal_producer as lp

    cache = lp.load_state("series.pkl", {})
    charged = rg.fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES})
    QE, F2, F0 = [], [], []
    QEs, F2s = [], []
    close = {}
    for mo in MONTHS:
        legs, events = rg.api_legs([mo], SERIES)
        close.update({t: L["close"] for t, L in legs.items()})
        fv = FairValue(legs, events)
        cand = []
        s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, [mo], record=cand)
        sc = candidate_scores(cand, fv)
        QE += s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, [mo])
        QEs += s.simulate(s.Config(**mp.BROAD), "strict", legs, events, charged, [mo])
        for t, out, m in ((2.0, F2, "pess"), (0.0, F0, "pess"), (2.0, F2s, "strict")):
            out += s.simulate(s.Config(**mp.BROAD, policy="x", policy_t=t), m, legs, events, charged, [mo],
                              policy_scores=sc)
        print(f"  {mo} done", flush=True)
    print("\nE1  filter minus quote everything, 2025-12..2026-08, event-paired bootstrap")
    for nm, a, b in (("edge > 0c [pess  ]", F0, QE), ("edge > 2c [pess  ]", F2, QE), ("edge > 2c [strict]", F2s, QEs)):
        d = rg.paired_diff_ci(a, b)
        print(f"  {nm}: {d[0]:+.2f} pts CI [{d[1]:+.2f}, {d[2]:+.2f}]")
    print("\nE2  by hours to close (quoting hour H to the leg's close), pessimistic, 2025-12..2026-08")
    for nm, fl in (("quote everything", QE), ("edge > 2c", F2)):
        print(f"  {nm}")
        for lo, hi in TTC_BINS:
            sub = [f for f in fl if lo <= (close[f[1]] - int(f[9])) / H_NS < hi]
            if sub:
                print(f"    [{lo:g},{hi:g})h  {line(s.summarise(sub))}")
        for ser in SERIES:
            print(f"    {ser:<12} {line(s.summarise([f for f in fl if f[1].startswith(ser + '-')]))}")

    print(f"\nE3  validation {rg.VAL[0]}..{rg.VAL[1]}: quote everything with and without the filter")
    legs, events, charged_v, start, end = rg.val_data()
    months = ["2026-09", "2026-10"]
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end and legs[f[1]]["series"] in SERIES]
    fv = FairValue(legs, events)
    cand = []
    s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged_v, months, record=cand)
    sc = candidate_scores([c for c in cand if legs[c[1]]["series"] in SERIES], fv)
    for m in ("pess", "strict"):
        q = win(s.simulate(s.Config(**mp.BROAD), m, legs, events, charged_v, months))
        print(f"  no filter      [{m:<6}] {line(s.summarise(q))}")
        for t in THRESHOLDS:
            f = win(s.simulate(s.Config(**mp.BROAD, policy="x", policy_t=t), m, legs, events, charged_v, months,
                               policy_scores=sc))
            print(f"  edge > {t:>3g}c   [{m:<6}] {line(s.summarise(f))}")


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
        ok &= bool(c)

    ev = ["X-E-T7424.9999", "X-E-T7350", "X-E-B7362", "X-E-B7387", "X-E-B7412"]
    st = parse_strikes(ev)
    check("upper T is 'above'", st["X-E-T7424.9999"] == (7424.9999, None))
    check("lower T is 'below'", st["X-E-T7350"] == (None, 7350.0))
    check("B mid-point -> [mid-w/2, mid+w/2]", st["X-E-B7387"] == (7375.0, 7400.0))
    check("leg_prob tails + brackets sum to 1",
          abs(sum(leg_prob(100.0, 0.2, 0.01, f, c) for f, c in [(None, 95), (95, 100), (100, 105), (105, None)]) - 1) < 1e-9)
    check("leg_prob at tau=0 is the indicator", leg_prob(100.0, 0.2, 0.0, 95, 105) == 1.0 and leg_prob(100.0, 0.2, 0.0, 101, 105) == 0.0)
    check("higher vol spreads mass to tails",
          leg_prob(100.0, 0.4, 0.01, None, 90) > leg_prob(100.0, 0.1, 0.01, None, 90))
    sat = int(dt.datetime(2026, 10, 3, 12, tzinfo=dt.timezone.utc).timestamp() * 1e9)
    check("weekend hours carry no variance", var_years(sat, sat + 12 * H_NS, False) == 0.0)
    mon_close = int(dt.datetime(2026, 10, 5, 20, tzinfo=dt.timezone.utc).timestamp() * 1e9)
    full = var_years(mon_close - int(6.5 * H_NS), mon_close, False)
    check("one session = 1/252 year", abs(full - 6.5 / (252 * (SESSION_H + OFF_W * (24 - SESSION_H)))) < 1e-9)
    t = np.array([10, 20, 30], dtype=np.int64)
    check("asof uses bars known at H", asof((t, np.array([1., 2., 3.])), 25) == (20, 2.0) and asof((t, np.array([1., 2., 3.])), 5)[0] is None)

    # parse vs real metadata (validation window)
    try:
        import retrain_g2 as rg
        import smoke_test_2026 as st_
        start = int(dt.datetime.fromisoformat(rg.VAL[0]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
        end = int(dt.datetime.fromisoformat(rg.VAL[1]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
        bad = n = 0
        for ser in SERIES:
            rows = pickle.loads((st_.CACHE / f"{ser}_{start}_{end}.pkl").read_bytes())
            evs = {}
            for m, _, _ in rows:
                evs.setdefault(m["event_ticker"], []).append(m)
            for ms in evs.values():
                got = parse_strikes([m["ticker"] for m in ms])
                for m in ms:
                    n += 1
                    f, c = got.get(m["ticker"], (0, 0))
                    tf, tc = m.get("floor_strike"), m.get("cap_strike")
                    if m["strike_type"] == "between":
                        bad += not (abs(f - tf) < 1e-3 and abs(c - tc) < 1e-3 * max(1, tc) + 0.011)
                    elif m["strike_type"] == "greater":
                        bad += not (c is None and abs(f - tf) < 1e-6)
                    else:
                        bad += not (f is None and abs(c - tc) < 1e-6)
        check(f"ticker parse matches metadata floor/cap on {n} validation markets (mismatches {bad})", n > 0 and bad == 0)
    except FileNotFoundError as e:
        check(f"validation metadata available ({e})", False)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--extra", action="store_true", help="section E only")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run_extra() if a.extra else run()


if __name__ == "__main__":
    main()
