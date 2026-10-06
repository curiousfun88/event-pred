"""
smoke_test_2026.py

EXPLORATORY SMOKE TEST OF THE FROZEN POLICY G ON RECENT (2026) KALSHI MARKETS.

WHY. Before asking the supervisor for platform changes, check whether G still
earns on markets 16 months after its training data ended. Exploratory: not
pre-registered, reported as such, and nothing about G (model, threshold,
features) is changed because of it (decision recorded 2026-10-06, before the
run).

WHAT. Events of the series G scored in its test months (the 26 "trained"
series) whose markets closed in the window, fetched from Kalshi's public API
(settled markets, hourly bid/ask candles, trades with taker side). The data is
reshaped into simulate_maker's own `legs` / `events` structures, and the
simulator, the feature code (maker_policy.quote_features) and the frozen model
run unchanged. Arms: G (post if predicted > 1c), random selection of the same
share (5 seeds), quote everything. Fills: pessimistic (primary), optimistic,
strict.

DEVIATIONS (stated): leg membership uses the live basket rule of
live_signal_producer (Kalshi mutually-exclusive series history, 3-100 legs),
not build_mece_membership; trades with fractional counts below 1 contract
cannot fill (the simulator fills whole contracts).

USAGE (from repo root):
    python stg_infra/examples/smoke_test_2026.py --self-test
    python stg_infra/examples/smoke_test_2026.py --start 2026-09-07 --end 2026-10-05
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

H_NS = 3_600_000_000_000
CACHE = _REPO / "runs/live/smoke_cache"


def ts_ns(s: str) -> int:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int(d.timestamp()) * 1_000_000_000 + d.microsecond * 1000


def candle_quotes(payload: dict):
    """Candlesticks JSON -> (end_ns array, bid dollars, ask dollars). Live ('close_dollars') and
    archive ('close') formats; missing side -> nan."""
    e, b, a = [], [], []
    for c in payload.get("candlesticks", []):
        yb, ya = c.get("yes_bid") or {}, c.get("yes_ask") or {}
        vb = yb.get("close_dollars", yb.get("close"))
        va = ya.get("close_dollars", ya.get("close"))
        e.append(int(c["end_period_ts"]) * 1_000_000_000)
        b.append(np.nan if vb is None else float(vb))
        a.append(np.nan if va is None else float(va))
    return np.array(e, np.int64), np.array(b, float), np.array(a, float)


def trade_arrays(trades: list):
    """Trades JSON -> sorted (t ns, yes price cents, count, side +1 taker bought YES / -1 sold)."""
    rows = sorted((ts_ns(t["created_time"]),
                   round(float(t.get("yes_price_dollars", t.get("yes_price", 0) / 100)) * 100, 6),
                   float(t.get("count_fp", t.get("count", 0))),
                   1 if t["taker_side"] == "yes" else -1) for t in trades)
    if not rows:
        return np.empty(0, np.int64), np.empty(0), np.empty(0), np.empty(0)
    t, p, c, s_ = zip(*rows)
    return np.array(t, np.int64), np.array(p), np.array(c), np.array(s_)


def make_leg(m: dict, series: str, quotes, trades):
    e, b, a = quotes
    tt, tp, tc, ts = trades
    return {"event": m["event_ticker"], "series": series, "yes": m.get("result") == "yes",
            "close": ts_ns(m["close_time"]) if m.get("close_time") else None,
            "e": e, "bid": b, "ask": a, "tt": tt, "tp": tp, "tc": tc, "ts": ts}


# ---------------------------------------------------------------- fetch

def fetch(k, series_list, start_ns, end_ns, rps_note=""):
    """{series: [settled market dicts closing in [start, end)]} plus per-ticker candles and trades, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = {}
    for ser in series_list:
        cp = CACHE / f"{ser}_{start_ns}_{end_ns}.pkl"
        if cp.exists():
            out[ser] = pickle.loads(cp.read_bytes()); continue
        mk = list(k.pages("markets", "markets", series_ticker=ser, status="settled",
                          min_close_ts=start_ns // 10**9, max_close_ts=end_ns // 10**9, limit=1000))
        ev_n = {}
        for m in mk:
            ev_n[m["event_ticker"]] = ev_n.get(m["event_ticker"], 0) + 1
        legs = []
        for m in mk:
            if not (3 <= ev_n[m["event_ticker"]] <= 100) or m.get("result") not in ("yes", "no"):
                continue
            o = max(ts_ns(m["open_time"]), start_ns - 26 * H_NS)
            c = ts_ns(m["close_time"])
            cd = k.get(f"series/{ser}/markets/{m['ticker']}/candlesticks",
                       start_ts=o // 10**9, end_ts=c // 10**9 + 3600, period_interval=60)
            tr = list(k.pages("markets/trades", "trades", ticker=m["ticker"], min_ts=o // 10**9 - 86400,
                              max_ts=c // 10**9 + 3600, limit=1000))
            legs.append((m, cd, tr))
        cp.write_bytes(pickle.dumps(legs))
        out[ser] = legs
        print(f"  {ser}: {len(legs)} legs in {len({m['event_ticker'] for m, _, _ in legs})} events "
              f"(api calls so far {k.calls})", flush=True)
    return out


def build(raw, fee_types):
    legs, events = {}, {}
    for ser, rows in raw.items():
        for m, cd, tr in rows:
            L = make_leg(m, ser, candle_quotes(cd), trade_arrays(tr))
            legs[m["ticker"]] = L
            events.setdefault(L["event"], []).append(m["ticker"])
    mfee = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}

    def charged(series, month):
        return fee_types.get(series) in mfee
    return legs, events, charged


# ---------------------------------------------------------------- run

def run(a):
    import simulate_maker as s
    import maker_policy as mp
    import live_signal_producer as lp
    import polars as pl
    from policy_G_audit import ev_ret
    start = int(dt.datetime.fromisoformat(a.start).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    end = int(dt.datetime.fromisoformat(a.end).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    trained = sorted(pl.read_parquet(_REPO / "runs/maker/policy_G_scores_2025-08_2025-11.parquet")["ticker"]
                     .str.split("-").list.first().unique().to_list())
    k = lp.Kalshi(rps=a.rps)
    cache = lp.series_meta(k, trained, lp.load_state("series.pkl", {}), int(dt.datetime.now().timestamp()))
    lp.save_state("series.pkl", cache)
    keep = [x for x in trained if cache[x]["ok"] and x not in a.skip]
    print(f"series: {len(trained)} trained; {len(keep)} kept; skipped by --skip {sorted(a.skip)}; "
          f"fail the live basket rule {sorted(x for x in trained if not cache[x]['ok'])}")
    raw = fetch(k, keep, start, end)
    legs, events, charged = build(raw, {x: cache[x]["fee_type"] for x in keep})
    months = sorted({s.month_of(int(h)) for L in legs.values() for h in L["e"] if start <= h < end})
    print(f"legs {len(legs)}, events {len(events)}, months {months}, api calls {k.calls}")

    blob = pickle.loads(mp.model_path("G").read_bytes())
    lookup = mp.category_lookup()
    cand = []
    s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months, record=cand)
    cand = [c for c in cand if start <= int(c[2]) < end]
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a_ in cand:
        r = mp.quote_features(legs, events, charged, lookup, s.month_of(int(H)), ev, tk, int(H), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((tk, int(H), int(sd)))
    pred = blob["model"].predict(mp.to_matrix(rows, blob["cats"]))
    pol = {k_: float(p) for k_, p in zip(keys, pred)}
    share = float(np.mean(pred > 1.0))
    print(f"candidates in window {len(cand):,}; scored {len(pred):,}; G posts {share:.1%}")

    def in_win(fl):
        return [f for f in fl if start <= int(f[9]) < end]

    def report(nm, fl):
        r = s.summarise(fl)
        print(f"  {nm:<30} fills {r['fills']:>6,}  events {r['events']:>5}  net ${r['net_c'] / 100:>+9.2f}  "
              f"fees ${r.get('fees_c', 0) / 100:>7.2f}  ret {r['ret']:+6.2f}%  CI [{r['lo']:+.2f}, {r['hi']:+.2f}]  "
              f"markout {r['markout_c_per_contract']:+.2f}c")
        return r
    out = {}
    print(f"\nRESULTS, quoting hours {a.start} .. {a.end} (exploratory)")
    for model in ("pess", "opt", "strict"):
        print(f" fills = {model}")
        out[(model, "G")] = report("G (pred > 1c)", in_win(s.simulate(s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0}),
                                                                       model, legs, events, charged, months, policy_scores=pol)))
        out[(model, "all")] = report("quote everything", in_win(s.simulate(s.Config(**mp.BROAD), model, legs, events, charged, months)))
        if model == "pess":
            rets = []
            for seed in range(5):
                rng = np.random.default_rng(seed)
                rp = {k_: (2.0 if u < share else 0.0) for k_, u in zip(keys, rng.random(len(keys)))}
                rets.append(report(f"random {share:.0%} (seed {seed})", in_win(s.simulate(
                    s.Config(**{**mp.BROAD, "policy": "random", "policy_t": 1.0}), model, legs, events, charged,
                    months, policy_scores=rp)))["ret"])
            print(f"  random mean ret {np.nanmean(rets):+.2f}%")
    Fg = in_win(s.simulate(s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0}), "pess", legs, events, charged,
                           months, policy_scores=pol))
    print("\n G by series (pessimistic)")
    by = {}
    for f in Fg:
        by.setdefault(f[0].split("-")[0], []).append(f)
    for ser, fl in sorted(by.items(), key=lambda x: -len(x[1])):
        r = s.summarise(fl)
        print(f"  {ser:<18} fills {r['fills']:>5,}  events {r['events']:>4}  net ${r['net_c'] / 100:>+8.2f}  ret {r['ret']:+6.2f}%")


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted API payloads)")
    import simulate_maker as s
    import maker_policy as mp
    H0 = 1_788_000_000 // 3600 * 3600
    e, b, a = candle_quotes({"candlesticks": [
        {"end_period_ts": H0, "yes_bid": {"close_dollars": "0.4000"}, "yes_ask": {"close_dollars": "0.4400"}},
        {"end_period_ts": H0 + 3600, "yes_bid": {"close": "0.4100"}, "yes_ask": {"close": None}}]})
    check("candles: live and archive formats; missing ask -> nan",
          b.tolist() == [0.40, 0.41] and a[0] == 0.44 and np.isnan(a[1]) and e[1] - e[0] == H_NS)
    iso = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    tt, tp, tc, ts = trade_arrays([
        {"created_time": iso(H0 + 1800), "yes_price_dollars": "0.4000", "count_fp": "5.00", "taker_side": "no"},
        {"created_time": iso(H0 + 600), "yes_price_dollars": "0.4500", "count_fp": "2.00", "taker_side": "yes"}])
    check("trades: sorted by time, cents, counts, taker side (+1 bought YES)",
          tp.tolist() == [45.0, 40.0] and tc.tolist() == [2.0, 5.0] and ts.tolist() == [1, -1])
    m = {"ticker": "X-1", "event_ticker": "X", "result": "yes", "close_time": iso(H0 + 5 * 3600)}
    L = make_leg(m, "KXHIGHLAX", (e[:1], b[:1], a[:1]), (tt, tp, tc, ts))
    check("leg structure: settles YES, close in ns, one quote", L["yes"] and L["close"] == (H0 + 5 * 3600) * 10**9 and len(L["e"]) == 1)

    # end-to-end on the simulator: bid improved to 41 at H0 (spread 4); the taker SELL of 5 at 40 fills it
    # (an improved level fills at or through); the ask improved to 43 is filled by the taker BUY of 2 at 45.
    legs = {"X-1": L,
            "X-2": make_leg({**m, "ticker": "X-2", "result": "no"}, "KXHIGHLAX",
                            (e[:1], np.array([0.30]), np.array([0.32])), (np.empty(0, np.int64),) + (np.empty(0),) * 3),
            "X-3": make_leg({**m, "ticker": "X-3", "result": "no"}, "KXHIGHLAX",
                            (e[:1], np.array([0.20]), np.array([0.24])), (np.empty(0, np.int64),) + (np.empty(0),) * 3)}
    events = {"X": ["X-1", "X-2", "X-3"]}
    fl = s.simulate(s.Config(**mp.BROAD), "pess", legs, events, lambda sr, mo: False, [s.month_of(H0 * 10**9)])
    f1 = sorted(((f[2], f[3], f[4], f[6]) for f in fl if f[1] == "X-1"), reverse=True)
    check(f"planted fills: bid 41 x5 (taker sell at 40), ask 43 x2 (taker buy at 45): {f1}",
          [x[:3] for x in f1] == [(1, 41, 5), (-1, 43, 2)])
    check("planted P&L: long 5 at 41 settling YES = +295c; short 2 at 43 settling YES = -114c; no maker fee",
          abs(f1[0][3] - 295) < 1e-9 and abs(f1[1][3] + 114) < 1e-9)
    check("no fills on legs without trades", not [f for f in fl if f[1] != "X-1"])
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--start", default="2026-09-07")
    ap.add_argument("--end", default="2026-10-05")
    ap.add_argument("--rps", type=float, default=9.0)
    ap.add_argument("--skip", nargs="*", default=[],
                    help="series to leave out (e.g. hourly crypto ranges: tens of thousands of legs)")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a)


if __name__ == "__main__":
    main()
