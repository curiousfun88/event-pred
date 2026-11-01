"""
ask_side_share.py

Share of Kalshi trades whose taker bought YES (taker_side == "yes": the taker paid the ask), all trades, per month.
Report: numbers_offline.tex \\AskSideShare (July 2025, 68.7%); the order-flow prediction of the overround, Section 3.5.

Reads data/trades/trades_kalshi_{even,odd}/trades_YYYY-MM.parquet (scripts/data_split_by_month.py layout).

USAGE (from repo root):
    python stg_infra/examples/ask_side_share.py --self-test
    python stg_infra/examples/ask_side_share.py --year 2025 | tee logs/v2_forecast/ask_side_share_by_month_2025.log
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import polars as pl

_REPO = Path(__file__).resolve().parents[2]
TRADES = _REPO / "data/trades"


def month_file(month: str) -> Path | None:
    for parity in ("even", "odd"):
        p = TRADES / f"trades_kalshi_{parity}" / f"trades_{month}.parquet"
        if p.exists():
            return p
    return None


def share(df: pl.DataFrame) -> tuple[int, int, int]:
    """(trades, taker bought YES at the ask, taker sold YES into the bid)."""
    c = df.group_by("taker_side").len()
    d = dict(zip(c["taker_side"].to_list(), c["len"].to_list()))
    return int(df.height), int(d.get("yes", 0)), int(d.get("no", 0))


def self_test() -> bool:
    df = pl.DataFrame({"taker_side": ["yes", "yes", "no", "yes"]})
    ok = share(df) == (4, 3, 1)
    print(f"  [{'PASS' if ok else 'FAIL'}] 3 of 4 planted trades are ask-side")
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--year", type=int, default=2025)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    print("# Share of Kalshi trades whose taker bought YES (taker_side == 'yes', i.e. paid the ask), all trades, per month.")
    print(f"# Source: data/trades/trades_kalshi_{{even,odd}}/trades_{a.year}-MM.parquet (stg_infra/examples/ask_side_share.py).")
    print(f"{'month':<9}{'trades':>12}{'yes (ask)':>12}{'no (bid)':>12}{'ask share':>10}")
    for m in range(1, 13):
        month = f"{a.year}-{m:02d}"
        p = month_file(month)
        if p is None:
            continue
        n, y, no = share(pl.read_parquet(p, columns=["taker_side"]))
        print(f"{month:<9}{n:>12,}{y:>12,}{no:>12,}{100 * y / n:>9.1f}%")


if __name__ == "__main__":
    main()
