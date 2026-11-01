"""
partition_quotes.py

Merge every hourly quote file written by fetch_quote_candles.py (finished
files and in-progress .parts) into ONE FILE PER MONTH, mirroring the trades
layout:

    data/quotes/by_month/quotes_YYYY-MM.parquet

A candle is filed under the month of its END time (end_ts, naive UTC), which
is also the snapshot window end it is joined to. Duplicate (ticker, end_ts)
rows across source files are dropped. Source files are left untouched, so this
is idempotent: re-run it after any new fetch and nothing is re-downloaded.

USAGE (from repo root):
    python stg_infra/partition_quotes.py --self-test
    python stg_infra/partition_quotes.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def partition(src_dir: Path, out_dir: Path) -> dict:
    import polars as pl
    files = sorted(src_dir.glob("*.parquet")) + sorted(src_dir.glob("*.parts/*.parquet"))
    if not files:
        raise SystemExit(f"no quote files under {src_dir}")
    df = (pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")
          .unique(["ticker", "end_ts"], keep="first")
          .with_columns(pl.col("end_ts").dt.strftime("%Y-%m").alias("_m"))
          .sort(["ticker", "end_ts"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for (m,), g in df.group_by(["_m"], maintain_order=True):
        g.drop("_m").write_parquet(out_dir / f"quotes_{m}.parquet")
        counts[m] = (g.height, g["ticker"].n_unique())
    return counts


def self_test() -> int:
    import polars as pl
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    with tempfile.TemporaryDirectory() as td:
        src, out = Path(td) / "q", Path(td) / "q" / "by_month"
        (src / "x.parts").mkdir(parents=True)
        row = lambda t, d, b: {"ticker": t, "end_ts": d, "bid_close": b, "ask_close": b + 0.05}
        pl.DataFrame([row("A", dt.datetime(2025, 5, 31, 23), 0.40), row("A", dt.datetime(2025, 6, 1, 0), 0.41)]).write_parquet(src / "a.parquet")
        pl.DataFrame([row("A", dt.datetime(2025, 6, 1, 0), 0.41), row("B", dt.datetime(2025, 6, 2, 5), 0.10)]).write_parquet(src / "x.parts" / "p.parquet")
        c = partition(src, out)
        check("two month files written", sorted(c) == ["2025-05", "2025-06"])
        check("candle filed under the month of its END time", c["2025-05"] == (1, 1))
        check("duplicate (ticker, end_ts) across files dropped; parts included", c["2025-06"] == (2, 2))
        check("sources left untouched", (src / "a.parquet").exists() and (src / "x.parts" / "p.parquet").exists())
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--src", default="data/quotes")
    ap.add_argument("--out", default="data/quotes/by_month")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    counts = partition(_REPO / args.src, _REPO / args.out)
    for m, (n, k) in sorted(counts.items()):
        print(f"  {m}: {n:>10,} candles  {k:>7,} tickers")
    print(f"wrote {len(counts)} monthly files to {args.out}\nexit: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
