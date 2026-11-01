"""
diagnose_quote_candles.py

DESCRIPTIVE VALIDATION OF THE FETCHED HOURLY QUOTES, before any re-run uses
them. No model is loaded; nothing here is a forecasting result.

At every snapshot where a MECE basket is WHOLE (every listed leg linked) and
every leg is LIVE (traded in the window; the scorer's --supervise active
mask), each leg is joined to the candle ending at the window end. Reports:

  1. coverage   -- leg-snapshots with a candle; baskets with every leg quoted
  2. clock      -- last trade print vs quoted mid in the same hour. A clock
                   offset between the bundle (naive UTC) and the API would
                   show as a large, horizon-like gap; alignment shows ~0.
  3. proxy      -- trade-print bid (last taker_side=='no' print at or before
                   the window end, as score_mece_bidside.py used) vs quoted bid
  4. spread     -- quoted per-leg spread vs the trade-based 4.68-5.61c
  5. baskets    -- sum of bids / asks / mids / last prints vs $1, the direct
                   version of the overround decomposition

A bid of 0 or an ask of 1 is a one-sided book and is KEPT as the executable
price (you cannot sell for more than 0 into no bid).

USAGE (from repo root):
    python stg_infra/diagnose_quote_candles.py --self-test
    python stg_infra/diagnose_quote_candles.py --split test
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent


def quote_at(index: dict, ticker: str, end_ns: int):
    """(bid, ask) of the candle ending exactly at end_ns, or None."""
    return index.get((ticker, end_ns))


def basket_sums(legs):
    """legs: list of (last, bid, ask). Returns sums of last, bid, ask, mid."""
    last = sum(l for l, _, _ in legs)
    bid = sum(b for _, b, _ in legs)
    ask = sum(a for _, _, a in legs)
    return last, bid, ask, 0.5 * (bid + ask)


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    idx = {("A", 100): (0.40, 0.45), ("B", 100): (0.0, 0.03)}
    check("exact-hour join hits", quote_at(idx, "A", 100) == (0.40, 0.45))
    check("no candle at another hour -> None", quote_at(idx, "A", 200) is None)
    check("one-sided book kept (bid 0)", quote_at(idx, "B", 100) == (0.0, 0.03))
    s = basket_sums([(0.46, 0.40, 0.45), (0.56, 0.52, 0.58)])
    check("basket sums", all(math.isclose(a, b) for a, b in zip(s, (1.02, 0.92, 1.03, 0.975))))
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def run(args) -> int:
    import polars as pl
    import torch
    sys.path.insert(0, str(_THIS_DIR))
    sys.path.insert(0, str(_THIS_DIR / "examples"))
    from model.chunking import build_split_ranges, chunk_ranges
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.train import true_prices
    from train_forecast import PILOT_MONTHS, WINDOW, _supervision_masks
    from score_mece_bidside import _load_bids, _prev_month, bid_lookup

    q = pl.read_parquet(_REPO_ROOT / args.quotes)
    idx = {(t, int(e)): (b, a) for t, e, b, a in zip(
        q["ticker"].to_list(), q["end_ts"].cast(pl.Datetime("ns")).cast(pl.Int64).to_list(),
        q["bid_close"].to_list(), q["ask_close"].to_list())}
    print(f"quotes: {q.height:,} candles, {q['ticker'].n_unique():,} tickers")

    store = MonthlyBundleStore(build_month_paths(PILOT_MONTHS, _REPO_ROOT / args.cache), verbose=False)
    chunks = [c for c in chunk_ranges(build_split_ranges(store.timestamps), chunk_len=168, min_chunk_len=4)
              if c.split == args.split]
    months = sorted({f"{ts.year}-{ts.month:02d}" for c in chunks for ts in store.timestamps[c.start:c.end]})
    bids = _load_bids(sorted(set(months) | {_prev_month(months[0])}))
    empty = (np.empty(0, np.int64), np.empty(0))

    n_leg = n_hit = 0
    n_bk = n_bk_full = 0
    clock, proxy_all, proxy_1h, spreads, bk = [], [], [], [], []
    for c in chunks:
        ct = store.materialize_chunk(c)
        f, mask, adj = ct["features"], ct["mask"], ct["adjacency_by_type"]
        _, live = _supervision_masks(f, mask, adj, "active")
        prices = true_prices(f)
        hub_n = f[..., 3]
        ids = ct["node_ids"]
        e_adj = adj["mece_leg_to_basket"]
        for t in range(len(e_adj)):
            e = e_adj[t]
            if e.edge_index.numel() == 0:
                continue
            end_ns = int(np.datetime64(ct["timestamps"][t] + WINDOW, "ns").astype(np.int64))
            leg, hub = e.edge_index[0], e.edge_index[1]
            for hb in torch.unique(hub).tolist():
                members = leg[hub == hb].tolist()
                if len(members) != int(hub_n[t, hb]) or not all(bool(live[t, lg]) for lg in members):
                    continue
                n_bk += 1
                rows = []
                for lg in members:
                    n_leg += 1
                    qa = quote_at(idx, ids[lg], end_ns)
                    last = float(prices[t, lg])
                    if qa is None or qa[0] is None or qa[1] is None:
                        continue
                    n_hit += 1
                    b, a = qa
                    rows.append((last, b, a))
                    clock.append(last - 0.5 * (a + b))
                    if 0 < b < a < 1:
                        spreads.append(a - b)
                    tb, pb = bids.get(ids[lg], empty)
                    pbid, age = bid_lookup(tb, pb, end_ns)
                    if not math.isnan(pbid):
                        proxy_all.append(pbid - b)
                        if age <= 3600e9:
                            proxy_1h.append(pbid - b)
                if len(rows) == len(members):
                    n_bk_full += 1
                    two_sided = all(0 < b_ < a_ < 1 for _, b_, a_ in rows)
                    bk.append(basket_sums(rows) + (len(rows), float(two_sided)))
        del ct

    c = lambda x: 100.0 * np.asarray(x)
    print(f"\n=== {args.split.upper()}: whole baskets with every leg live ===")
    print(f"1. coverage : {n_hit / n_leg:.1%} of {n_leg:,} leg-snapshots have a quote at the window end; "
          f"{n_bk_full / n_bk:.1%} of {n_bk:,} basket-snapshots fully quoted")
    cl = c(clock)
    print(f"2. clock    : last print - quoted mid: median {np.median(cl):+.2f}c, mean {cl.mean():+.2f}c, "
          f"|.|<=2c for {np.mean(np.abs(cl) <= 2):.1%}")
    for name, v in (("all trade-print bids", proxy_all), ("prints <= 1h old", proxy_1h)):
        v = c(v)
        print(f"3. proxy    : {name}: trade-print bid - quoted bid: median {np.median(v):+.2f}c, "
              f"mean {v.mean():+.2f}c, exact match {np.mean(np.abs(v) < 0.5):.1%}, within 2c "
              f"{np.mean(np.abs(v) <= 2):.1%} (n={len(v):,})")
    sp = c(spreads)
    print(f"4. spread   : two-sided legs {len(sp) / max(n_hit, 1):.1%}; quoted spread median {np.median(sp):.2f}c, "
          f"mean {sp.mean():.2f}c, p90 {np.percentile(sp, 90):.1f}c  (trade-based estimates: 4.68-5.61c)")
    b = np.asarray(bk)
    if args.save_baskets:                 # 2026-10-22: per-snapshot sums for the report's Figure 4.x (off by default)
        out = _REPO_ROOT / args.save_baskets
        out.parent.mkdir(parents=True, exist_ok=True)
        pl.DataFrame({"sum_last": b[:, 0], "sum_bid": b[:, 1], "sum_ask": b[:, 2], "sum_mid": b[:, 3],
                      "n_legs": b[:, 4].astype(int), "two_sided": b[:, 5] == 1.0}).write_parquet(out)
        print(f"saved {len(b):,} basket-snapshots to {args.save_baskets}")
    print(f"5. baskets  (n={len(b):,}, median legs {np.median(b[:, 4]):.0f}):")
    for j, name in ((0, "last prints"), (1, "bids"), (2, "asks"), (3, "mids")):
        dv = c(b[:, j] - 1.0)
        print(f"     sum of {name:<11}: mean {1 + dv.mean() / 100:.4f}  (dev mean {dv.mean():+.2f}c, median {np.median(dv):+.2f}c, "
              f"|dev| median {np.median(np.abs(dv)):.2f}c)")
    lm = c(b[:, 0] - b[:, 3])
    print(f"     last-print sum - mid sum: mean {lm.mean():+.2f}c  (the overround share carried by print side)")
    sell = c(b[:, 1] - 1.0)
    buy = c(1.0 - b[:, 2])
    print(f"     executable edge before fees: sell-at-bids > $1 in {np.mean(sell > 0):.1%} "
          f"(mean when >0 {sell[sell > 0].mean() if (sell > 0).any() else float('nan'):.2f}c); "
          f"buy-at-asks < $1 in {np.mean(buy > 0):.1%} "
          f"(mean when >0 {buy[buy > 0].mean() if (buy > 0).any() else float('nan'):.2f}c)")
    for flag, name in ((1.0, "every leg two-sided"), (0.0, "some leg one-sided")):
        sb = b[b[:, 5] == flag]
        if len(sb):
            print(f"     [{name}: n={len(sb):,} ({len(sb) / len(b):.0%})] mid-sum dev mean "
                  f"{100 * (sb[:, 3] - 1).mean():+.2f}c | last-print dev mean {100 * (sb[:, 0] - 1).mean():+.2f}c | "
                  f"bid sum {sb[:, 1].mean():.4f}, ask sum {sb[:, 2].mean():.4f}")
    print("\nexit: 0")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--split", choices=["val", "test"], default="test")
    ap.add_argument("--cache", default="cache_causal")
    ap.add_argument("--quotes", default="data/quotes/candles_1h_2025-07_09.parquet")
    ap.add_argument("--save-baskets", default="", help="write per-snapshot basket sums (parquet) here")
    args = ap.parse_args()
    return self_test() if args.self_test else run(args)


if __name__ == "__main__":
    sys.exit(main())
