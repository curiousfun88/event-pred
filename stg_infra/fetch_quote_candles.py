"""
fetch_quote_candles.py

FETCH HOURLY TOP-OF-BOOK QUOTES (best bid / best ask) FOR MECE BASKET LEGS.

WHY. Every executable-price result so far inferred the bid/ask: from
taker_side of sparse trade prints (bid-side re-score: 0.3% of baskets fully
priced) or as last print +/- a modelled half-spread (PnL). The markets file
cannot help: it is one post-settlement snapshot per ticker (finalized,
yes_bid 0 / yes_ask 100). Kalshi's public historical candlesticks carry the
resting book's best bid and ask per period, including hours with no trades.
Probed 2026-09-27: 96.7% of live test leg-snapshots have an hourly candle
ending exactly at the snapshot window end.

SOURCE. GET /trade-api/v2/historical/markets/{ticker}/candlesticks
(markets settled before GET /historical/cutoff = 2026-07-29 live there).
Unauthenticated, read-only. Max 5,000 candles per request, so hourly ranges
are split into 4,999-hour requests. Rate-limited well under the Basic tier.

WHICH LEGS. Every leg that appears on a mece_leg_to_basket edge in the given
months of a cache, over [first window end - 2h, last window end + 1h].

OUTPUT. One parquet, one row per (ticker, hour):
    ticker, end_ts (naive UTC, = candle end = snapshot window end),
    bid_open/high/low/close, ask_open/high/low/close (dollars, null if absent),
    price_close, volume, open_interest
A bid of 0 or an ask of 1 is a REAL one-sided book (nothing resting), not
missing data; analyses must keep it. Resumable: tickers already in the
output are skipped.

USAGE (from repo root):
    python stg_infra/fetch_quote_candles.py --self-test
    python stg_infra/fetch_quote_candles.py --cache cache_causal \
        --months 2025-07 2025-08 2025-09 --out data/quotes/candles_1h_2025-07_09.parquet
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

BASE = "https://api.elections.kalshi.com/trade-api/v2/historical/markets/{}/candlesticks"
MAX_CANDLES = 5000
H = 3600


def _f(x):
    return None if x is None else float(x)


def parse_candles(ticker: str, payload: dict) -> list:
    """API JSON -> row dicts. Dollar strings -> floats; null stays None."""
    rows = []
    for k in payload.get("candlesticks", []):
        b, a, p = k.get("yes_bid") or {}, k.get("yes_ask") or {}, k.get("price") or {}
        rows.append({
            "ticker": ticker,
            "end_ts": dt.datetime.fromtimestamp(int(k["end_period_ts"]), dt.timezone.utc).replace(tzinfo=None),
            "bid_open": _f(b.get("open")), "bid_high": _f(b.get("high")),
            "bid_low": _f(b.get("low")), "bid_close": _f(b.get("close")),
            "ask_open": _f(a.get("open")), "ask_high": _f(a.get("high")),
            "ask_low": _f(a.get("low")), "ask_close": _f(a.get("close")),
            "price_close": _f(p.get("close")),
            "volume": _f(k.get("volume")), "open_interest": _f(k.get("open_interest")),
        })
    return rows


def split_range(start_ts: int, end_ts: int, step_s: int = H, max_n: int = MAX_CANDLES - 1):
    """[start, end] -> list of (s, e) with at most max_n candles each, contiguous."""
    out, s, span = [], start_ts, step_s * max_n
    while s < end_ts:
        e = min(end_ts, s + span)
        out.append((s, e))
        s = e
    return out


def utc_ts(d: dt.datetime) -> int:
    """Naive datetimes in this repo are UTC (verified: last print vs quoted
    mid at the same hour differ by +0.4c on average; an offset would not)."""
    return int(d.replace(tzinfo=dt.timezone.utc).timestamp())


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    payload = {"candlesticks": [
        {"end_period_ts": 1757430000, "open_interest": "350.00", "volume": "0.00",
         "price": {"close": None}, "yes_bid": {"open": "0.0000", "high": "0.4000", "low": "0.0000", "close": "0.4000"},
         "yes_ask": {"open": "0.6300", "high": "0.6300", "low": "0.4200", "close": "0.4500"}},
        {"end_period_ts": 1757433600, "yes_bid": {"close": None}, "yes_ask": {"close": "1.0000"}, "price": {}},
    ]}
    r = parse_candles("X", payload)
    check("two candles parsed", len(r) == 2)
    check("dollar strings -> floats", r[0]["bid_close"] == 0.40 and r[0]["ask_close"] == 0.45)
    check("end_ts is naive UTC", r[0]["end_ts"] == dt.datetime(2025, 9, 9, 15, 0) and r[0]["end_ts"].tzinfo is None)
    check("null price kept as None (no trade that hour)", r[0]["price_close"] is None)
    check("null bid kept as None; ask of 1.0 kept (one-sided book)", r[1]["bid_close"] is None and r[1]["ask_close"] == 1.0)

    parts = split_range(0, 10_000 * H)
    check("range split under the 5,000-candle limit", all((e - s) // H <= MAX_CANDLES - 1 for s, e in parts))
    check("split is contiguous and complete", parts[0][0] == 0 and parts[-1][1] == 10_000 * H
          and all(a[1] == b[0] for a, b in zip(parts, parts[1:])))
    check("short range is one request", split_range(0, 48 * H) == [(0, 48 * H)])
    check("naive datetime treated as UTC", utc_ts(dt.datetime(2025, 9, 9, 15)) == 1757430000)

    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def leg_ranges(cache: Path, months: list) -> dict:
    """ticker -> (first window end, last window end) over MECE leg edges."""
    sys.path.insert(0, str(_THIS_DIR))
    sys.path.insert(0, str(_THIS_DIR / "examples"))
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.chunking import build_split_ranges, chunk_ranges
    from train_forecast import WINDOW

    store = MonthlyBundleStore(build_month_paths(months, cache), verbose=False)
    chunks = chunk_ranges(build_split_ranges(store.timestamps), chunk_len=168, min_chunk_len=1)
    rng = {}
    for c in chunks:
        ct = store.materialize_chunk(c)
        e = ct["adjacency_by_type"].get("mece_leg_to_basket")
        if e is None:
            continue
        for t in range(len(e)):
            if e[t].edge_index.numel() == 0:
                continue
            we = ct["timestamps"][t] + WINDOW
            for lg in set(e[t].edge_index[0].tolist()):
                tk = ct["node_ids"][lg]
                lo, hi = rng.get(tk, (we, we))
                rng[tk] = (min(lo, we), max(hi, we))
        del ct
    return rng


def run(args) -> int:
    import polars as pl
    import requests

    out = Path(args.out)
    if not out.is_absolute():
        out = _REPO_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(args.cache)
    if not cache.is_absolute():
        cache = _REPO_ROOT / cache

    rng = leg_ranges(cache, args.months)
    done = set()
    parts_dir = out.with_suffix(".parts")
    parts_dir.mkdir(exist_ok=True)
    for p in parts_dir.glob("*.parquet"):
        done |= set(pl.read_parquet(p, columns=["ticker"])["ticker"].unique().to_list())
    done |= set((parts_dir / "empty.txt").read_text().split()) if (parts_dir / "empty.txt").exists() else set()
    todo = sorted(t for t in rng if t not in done)
    print(f"{len(rng):,} MECE legs in {args.months}; {len(done):,} already fetched; {len(todo):,} to fetch")

    sess = requests.Session()
    buf, n_req, n_err, empty = [], 0, 0, []
    t_start = time.time()
    for i, tk in enumerate(todo):
        lo, hi = rng[tk]
        rows = []
        for s, e in split_range(utc_ts(lo) - 2 * H, utc_ts(hi) + H):
            for attempt in range(5):
                time.sleep(1.0 / args.rate)
                r = sess.get(BASE.format(tk), params={"start_ts": s, "end_ts": e, "period_interval": 60}, timeout=30)
                n_req += 1
                if r.status_code == 200:
                    rows += parse_candles(tk, r.json())
                    break
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                n_err += 1
                print(f"  {tk}: HTTP {r.status_code} {r.text[:120]}")
                break
        if rows:
            buf += rows
        else:
            empty.append(tk)
        if len(buf) >= 50_000 or i == len(todo) - 1:
            if buf:
                pl.DataFrame(buf).write_parquet(parts_dir / f"part_{int(time.time() * 1000)}.parquet")
                buf = []
            with open(parts_dir / "empty.txt", "a") as fh:
                fh.write("".join(f"{t}\n" for t in empty))
            empty = []
        if (i + 1) % 250 == 0:
            el = time.time() - t_start
            print(f"  {i + 1:,}/{len(todo):,} legs, {n_req:,} requests, {n_err} errors, {el / 60:.1f} min")

    parts = sorted(parts_dir.glob("*.parquet"))
    df = pl.concat([pl.read_parquet(p) for p in parts]).unique(["ticker", "end_ts"]).sort(["ticker", "end_ts"])
    df.write_parquet(out)
    n_empty = len((parts_dir / "empty.txt").read_text().split()) if (parts_dir / "empty.txt").exists() else 0
    print(f"\nwrote {out}: {df.height:,} candles, {df['ticker'].n_unique():,} tickers "
          f"({n_empty:,} legs returned no candles), {n_err} request errors")
    two = df.filter((pl.col("bid_close") > 0) & (pl.col("ask_close") < 1) & (pl.col("bid_close") < pl.col("ask_close")))
    print(f"two-sided candles: {two.height / max(df.height, 1):.1%}; "
          f"quoted spread median {100 * (two['ask_close'] - two['bid_close']).median():.1f}c, "
          f"mean {100 * (two['ask_close'] - two['bid_close']).mean():.2f}c")
    print("exit: 0")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cache", default="cache_causal")
    ap.add_argument("--months", nargs="+", default=["2025-07", "2025-08", "2025-09"])
    ap.add_argument("--out", default="data/quotes/candles_1h_2025-07_09.parquet")
    ap.add_argument("--rate", type=float, default=5.0, help="requests per second (Basic tier ~20)")
    args = ap.parse_args()
    return self_test() if args.self_test else run(args)


if __name__ == "__main__":
    sys.exit(main())
