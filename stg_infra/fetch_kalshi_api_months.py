"""
fetch_kalshi_api_months.py

FETCH SETTLED MECE LEGS FOR WHOLE MONTHS FROM KALSHI'S PUBLIC API (maker amendment A13).

WHAT. For each series and month: every settled market that CLOSED in that month,
in an event with 3-100 legs, with its hourly bid/ask candles and its full trade
tape. Stored as compact arrays, one pickle per (series, month), ready to become
simulate_maker `legs` (smoke_test_2026.make_leg).

ENDPOINTS. Kalshi moves settled markets and old trades to an archive
(GET /historical/cutoff). Markets: archive list (paged through the whole series:
the archive ignores close-time filters) plus live settled markets in the month.
Candles: the archive endpoint for archived markets, else the live one. Trades: by
time against the trades cutoff -- archive if the market closed before it, live if
it opened after it, both (deduplicated by trade_id) if it spans it.

USAGE (from repo root):
    python stg_infra/fetch_kalshi_api_months.py --self-test
    python stg_infra/fetch_kalshi_api_months.py --months 2026-08 2026-07 ... 2025-12
"""
from __future__ import annotations

import argparse
import datetime as dt
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "examples"))

OUT = _REPO / "runs/maker/api_cache"
H_NS = 3_600_000_000_000
SERIES_A13 = ["KXAPRPOTUS", "KXBUNDESLIGAGAME", "KXEPLGAME", "KXEURUSD", "KXF1RACE", "KXFEAR", "KXFEDDECISION",
              "KXHIGHAUS", "KXHIGHCHI", "KXHIGHDEN", "KXHIGHLAX", "KXHIGHMIA", "KXHIGHNY", "KXHIGHPHIL",
              "KXHMONTHRANGE", "KXINX", "KXLAGODAYS", "KXLALIGAGAME", "KXLIGUE1GAME", "KXLLM1", "KXMLSGAME",
              "KXNASCARRACE", "KXNASDAQ100"]


def month_bounds(m: str):
    y, mo = map(int, m.split("-"))
    a = dt.datetime(y, mo, 1, tzinfo=dt.timezone.utc)
    b = dt.datetime(y + (mo == 12), mo % 12 + 1, 1, tzinfo=dt.timezone.utc)
    return int(a.timestamp()) * 10**9, int(b.timestamp()) * 10**9


def select_markets(markets: list, lo: int, hi: int, ts_ns):
    """Settled yes/no markets closing in [lo, hi), in events with 3-100 legs (counted over all listed markets)."""
    n = {}
    for m in markets:
        n[m["event_ticker"]] = n.get(m["event_ticker"], 0) + 1
    return [m for m in markets if m.get("result") in ("yes", "no") and 3 <= n[m["event_ticker"]] <= 100
            and lo <= ts_ns(m["close_time"]) < hi]


def trade_sources(open_ns: int, close_ns: int, cutoff_ns: int):
    if close_ns < cutoff_ns:
        return ["historical"]
    if open_ns >= cutoff_ns:
        return ["live"]
    return ["historical", "live"]


def dedupe(trades: list) -> list:
    seen, out = set(), []
    for t in trades:
        if t["trade_id"] not in seen:
            seen.add(t["trade_id"]); out.append(t)
    return out


def compact(m, candles_payload, trades, ts_ns, candle_quotes, trade_arrays):
    e, b, a = candle_quotes(candles_payload)
    tt, tp, tc, tsd = trade_arrays(trades)
    return {"ticker": m["ticker"], "event": m["event_ticker"], "result": m["result"],
            "open_ns": ts_ns(m["open_time"]), "close_ns": ts_ns(m["close_time"]),
            "e": e, "bid": b.astype(np.float32), "ask": a.astype(np.float32),
            "tt": tt, "tp": tp.astype(np.float32), "tc": tc.astype(np.float32), "ts": tsd.astype(np.int8)}


def series_markets(k, ser, months_lo, months_hi, ts_ns):
    """All markets of a series that could close in the window: archive (whole series) + live settled."""
    hist = list(k.pages("historical/markets", "markets", series_ticker=ser, limit=1000))
    live = list(k.pages("markets", "markets", series_ticker=ser, status="settled",
                        min_close_ts=months_lo // 10**9, max_close_ts=months_hi // 10**9, limit=1000))
    for m in hist:
        m["_archive"] = True
    seen = {m["ticker"] for m in hist}
    return hist + [m for m in live if m["ticker"] not in seen]


def run(a):
    import live_signal_producer as lp
    from smoke_test_2026 import ts_ns, candle_quotes, trade_arrays
    k = lp.Kalshi(rps=a.rps)
    cut = k.get("historical/cutoff")
    cutoff = ts_ns(cut["trades_created_ts"])
    bounds = {m: month_bounds(m) for m in a.months}
    lo_all, hi_all = min(b[0] for b in bounds.values()), max(b[1] for b in bounds.values())
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for ser in a.series:
        todo = [m for m in a.months if not (OUT / f"{ser}_{m}.pkl").exists()]
        if not todo:
            continue
        allm = series_markets(k, ser, lo_all, hi_all, ts_ns)
        for mo in todo:
            lo, hi = bounds[mo]
            rows = []
            for m in select_markets(allm, lo, hi, ts_ns):
                o, c = ts_ns(m["open_time"]), ts_ns(m["close_time"])
                s_ = max(o, lo - 26 * H_NS) // 10**9
                path = (f"historical/markets/{m['ticker']}/candlesticks" if m.get("_archive")
                        else f"series/{ser}/markets/{m['ticker']}/candlesticks")
                cd = k.get(path, start_ts=s_, end_ts=c // 10**9 + 3600, period_interval=60)
                tr = []
                for src in trade_sources(o, c, cutoff):
                    ep = "historical/trades" if src == "historical" else "markets/trades"
                    tr += list(k.pages(ep, "trades", ticker=m["ticker"], min_ts=s_ - 86400,
                                       max_ts=c // 10**9 + 3600, limit=1000))
                rows.append(compact(m, cd, dedupe(tr), ts_ns, candle_quotes, trade_arrays))
            (OUT / f"{ser}_{mo}.pkl").write_bytes(pickle.dumps(rows))
            print(f"  {ser} {mo}: {len(rows)} legs in {len({r['event'] for r in rows})} events  "
                  f"(calls {k.calls}, {time.time() - t0:.0f}s)", flush=True)


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    from smoke_test_2026 import ts_ns, candle_quotes, trade_arrays
    lo, hi = month_bounds("2026-03")
    check("month bounds: March 2026 is 31 days; December rolls the year",
          (hi - lo) == 31 * 24 * H_NS and month_bounds("2025-12")[1] == month_bounds("2026-01")[0])
    mk = lambda tk, ev, res, close: {"ticker": tk, "event_ticker": ev, "result": res, "close_time": close}
    ms = [mk("A1", "A", "yes", "2026-03-05T00:00:00Z"), mk("A2", "A", "no", "2026-03-05T00:00:00Z"),
          mk("A3", "A", "no", "2026-03-05T00:00:00Z"),
          mk("B1", "B", "yes", "2026-03-06T00:00:00Z"), mk("B2", "B", "no", "2026-03-06T00:00:00Z"),
          mk("C1", "C", "yes", "2026-04-01T00:00:00Z"), mk("C2", "C", "no", "2026-04-01T00:00:00Z"),
          mk("C3", "C", "no", "2026-04-01T00:00:00Z"),
          mk("D1", "D", "", "2026-03-07T00:00:00Z"), mk("D2", "D", "no", "2026-03-07T00:00:00Z"),
          mk("D3", "D", "no", "2026-03-07T00:00:00Z")]
    got = sorted(m["ticker"] for m in select_markets(ms, lo, hi, ts_ns))
    check(f"selection: 3-leg event in month kept; 2-leg event, next-month close, unresolved leg dropped: {got}",
          got == ["A1", "A2", "A3", "D2", "D3"])
    cut = ts_ns("2026-08-07T00:00:00Z")
    check("trades: closed before the cutoff -> archive only",
          trade_sources(ts_ns("2026-08-01T00:00:00Z"), ts_ns("2026-08-02T00:00:00Z"), cut) == ["historical"])
    check("trades: opened after the cutoff -> live only",
          trade_sources(ts_ns("2026-08-08T00:00:00Z"), ts_ns("2026-08-09T00:00:00Z"), cut) == ["live"])
    check("trades: spanning the cutoff -> both",
          trade_sources(ts_ns("2026-08-06T00:00:00Z"), ts_ns("2026-08-08T00:00:00Z"), cut) == ["historical", "live"])
    check("trades deduplicated by trade_id across endpoints",
          [t["trade_id"] for t in dedupe([{"trade_id": "x"}, {"trade_id": "y"}, {"trade_id": "x"}])] == ["x", "y"])
    m = {**mk("A1", "A", "yes", "2026-03-05T00:00:00Z"), "open_time": "2026-03-04T00:00:00Z"}
    c = compact(m, {"candlesticks": [{"end_period_ts": 1772600400, "yes_bid": {"close": "0.40"},
                                      "yes_ask": {"close": "0.44"}}]},
                [{"created_time": "2026-03-04T10:00:00Z", "yes_price_dollars": "0.4100", "count_fp": "3.00",
                  "taker_side": "no", "trade_id": "t"}], ts_ns, candle_quotes, trade_arrays)
    check("compact record: quotes, trade price in cents, side -1 for a taker sell, result kept",
          abs(c["bid"][0] - 0.40) < 1e-6 and abs(c["tp"][0] - 41) < 1e-4 and c["ts"][0] == -1 and c["result"] == "yes")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--months", nargs="*", default=[])
    ap.add_argument("--series", nargs="*", default=SERIES_A13)
    ap.add_argument("--rps", type=float, default=9.0)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a)


if __name__ == "__main__":
    main()
