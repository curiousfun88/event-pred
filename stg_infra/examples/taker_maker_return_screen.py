"""
taker_maker_return_screen.py

EXPLORATORY SCREEN, NOT A STRATEGY TEST. What did takers, and the makers on
the other side of them, actually earn at settlement on the Kalshi tape, net of
fees? Used to decide which strategy pathways are worth a pre-registered,
tape-driven simulation (runs/README.md).

Every trade has a taker and a maker:
  taker  bought `taker_side` at its price (yes_price if 'yes', else 100 - yes_price)
  maker  holds the opposite side, at 100 - the taker's price
Payoff at settlement is 100 for the side matching `result`, else 0 (cents).

FEES (verified 2026-09-27; see docs/RESEARCH_LOG.md):
  taker  ceil(0.07 * C * P * (1-P)) to the cent, per trade (C = trade count)
  maker  only on series whose fee_type charges makers:
           before 2025-07:  flat $0.0025 per contract
           from 2025-07:    ceil(0.0175 * C * P * (1-P)) to the cent
         Fee types come from the Kalshi API. Its fee-change log starts
         2025-10-04, so earlier months assume a series' first logged type (or
         its current type if none is logged) held throughout. Five series
         switched TO maker fees on 2025-11-15 and are treated as taker-only
         before that.

AGGREGATE MAKER RETURNS ARE NOT ACHIEVABLE BY A NEW ENTRANT. They are the
average over whoever was filled, including makers with queue priority. A
newcomer at the back of the queue is filled disproportionately when price is
about to move through them (adverse selection). This screen can show where a
positive edge exists; only a fill simulator can show whether it can be
captured.

Inference resamples EVENTS (outcomes within an event are dependent).

USAGE (from repo root):
    python stg_infra/examples/taker_maker_return_screen.py --self-test
    python stg_infra/examples/taker_maker_return_screen.py --months 2025-05 2025-06
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
MAKER_SWITCH = "2025-07"          # flat -> quadratic maker fee
MAKER_FEE_TYPES = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}


def taker_fee_c(price_c: float, count: float) -> float:
    p = price_c / 100.0
    return math.ceil(round(0.07 * count * p * (1 - p) * 100, 6))


def maker_fee_c(price_c: float, count: float, charged: bool, month: str) -> float:
    if not charged:
        return 0.0
    if month < MAKER_SWITCH:
        return 0.25 * count
    p = price_c / 100.0
    return math.ceil(round(0.0175 * count * p * (1 - p) * 100, 6))


def sides(yes_price: int, taker_side: str, result: str):
    """(taker price, taker payoff, maker price, maker payoff), all cents."""
    tp = yes_price if taker_side == "yes" else 100 - yes_price
    tpay = 100 if taker_side == result else 0
    return tp, tpay, 100 - tp, 100 - tpay


def event_bootstrap(net, stake, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(net), (n, len(net)))
    r = net[idx].sum(1) / stake[idx].sum(1) * 100
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    check("taker fee at 50c, 1 contract: 0.07*0.25 = 1.75c -> 2c (rounded up)", taker_fee_c(50, 1) == 2)
    check("taker fee at 50c, 100 contracts: exactly 175c", taker_fee_c(50, 100) == 175)
    check("taker fee at 97c, 1 contract rounds up to 1c", taker_fee_c(97, 1) == 1)
    check("maker fee zero on taker-only series", maker_fee_c(50, 100, False, "2025-09") == 0)
    check("maker fee flat 0.25c/contract before July 2025", maker_fee_c(50, 100, True, "2025-05") == 25)
    check("maker fee quadratic from July 2025: 0.0175*100*0.25 = 43.75 -> 44c", maker_fee_c(50, 100, True, "2025-08") == 44)
    tp, tpay, mp, mpay = sides(30, "yes", "no")
    check("taker buys YES at 30c, loses; maker holds NO at 70c, wins", (tp, tpay, mp, mpay) == (30, 0, 70, 100))
    tp, tpay, mp, mpay = sides(30, "no", "no")
    check("taker buys NO at 70c, wins; maker holds YES at 30c, loses", (tp, tpay, mp, mpay) == (70, 100, 30, 0))
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def run(args) -> int:
    import polars as pl

    def month_file(kind, m):
        par = "even" if int(m.split("-")[1]) % 2 == 0 else "odd"
        return _REPO / f"data/{kind}/{kind}_kalshi_{par}/{kind}_{m}.parquet"

    mk = pl.concat([pl.read_parquet(p, columns=["ticker", "event_ticker", "result"])
                    for p in sorted((_REPO / "data/markets").glob("*/markets_2025-*.parquet"))]).unique("ticker")
    tr = pl.concat([pl.read_parquet(month_file("trades", m), columns=["ticker", "count", "yes_price", "taker_side"])
                    .with_columns(pl.lit(m).alias("month")) for m in args.months])
    d = tr.join(mk, on="ticker", how="inner").filter(pl.col("result").is_in(["yes", "no"]))

    # fee type per series at each month
    changes = json.loads((_REPO / "results/mece/kalshi_series_fee_changes.json").read_text())
    first_logged = {}
    for c in sorted(changes, key=lambda c: c["scheduled_ts"]):
        first_logged.setdefault(c["series_ticker"], c)
    cur = json.loads((_REPO / args.series_fee_types).read_text()) if Path(_REPO / args.series_fee_types).exists() else {}

    def charged(series: str, month: str) -> bool:
        c = first_logged.get(series)
        if c is not None and month < c["scheduled_ts"][:7]:
            # before the first logged change: assume the type it changed FROM was taker-only
            # when it changed TO maker fees; otherwise assume its logged type held
            return c["fee_type"] not in MAKER_FEE_TYPES
        return cur.get(series, "quadratic") in MAKER_FEE_TYPES

    d = d.with_columns(pl.col("event_ticker").str.split("-").list.first().alias("series"))
    ch_map = {(s, m): charged(s, m) for s, m in d.select("series", "month").unique().iter_rows()}
    d = d.with_columns(pl.struct(["series", "month"]).map_elements(
        lambda r: ch_map[(r["series"], r["month"])], return_dtype=pl.Boolean).alias("maker_charged"))
    d = d.with_columns(
        pl.when(pl.col("taker_side") == "yes").then(pl.col("yes_price")).otherwise(100 - pl.col("yes_price")).alias("tp"),
        pl.when(pl.col("taker_side") == pl.col("result")).then(100).otherwise(0).alias("tpay"))
    d = d.with_columns((100 - pl.col("tp")).alias("mp"), (100 - pl.col("tpay")).alias("mpay"))
    p = pl.col("tp") / 100
    d = d.with_columns(
        (0.07 * pl.col("count") * p * (1 - p) * 100).round(6).ceil().alias("tfee"),
        pl.when(~pl.col("maker_charged")).then(0.0)
          .when(pl.col("month") < MAKER_SWITCH).then(0.25 * pl.col("count"))
          .otherwise((0.0175 * pl.col("count") * p * (1 - p) * 100).round(6).ceil()).alias("mfee"))
    d = d.with_columns(
        ((pl.col("tpay") - pl.col("tp")) * pl.col("count") - pl.col("tfee")).alias("t_net"),
        (pl.col("tp") * pl.col("count")).alias("t_stake"),
        ((pl.col("mpay") - pl.col("mp")) * pl.col("count")).alias("m_gross"),
        ((pl.col("mpay") - pl.col("mp")) * pl.col("count") - pl.col("mfee")).alias("m_net"),
        (pl.col("mp") * pl.col("count")).alias("m_stake"))

    print(f"months {args.months}: {d.height:,} settled trades, {d['event_ticker'].n_unique():,} events; "
          f"{d.filter(pl.col('maker_charged')).height / d.height:.1%} of trades on maker-fee series")

    def report(label, x, net, stake):
        e = x.group_by("event_ticker").agg(pl.col(net).sum(), pl.col(stake).sum())
        nv, sv = e[net].to_numpy().astype(float), e[stake].to_numpy().astype(float)
        lo, hi = event_bootstrap(nv, sv)
        ew = x.select((pl.col(net) / pl.col(stake)).mean() * 100).item()
        top = np.sort(sv)[::-1][:10].sum() / sv.sum()
        print(f"  {label:<34} contract-wtd {nv.sum() / sv.sum() * 100:+6.2f}%  CI95 [{lo:+6.2f}%, {hi:+6.2f}%]  "
              f"equal-wtd {ew:+6.2f}%  events {len(e):,}  top-10 events {top:.0%} of stake")

    print("\nTAKERS, net of taker fee:")
    report("all", d, "t_net", "t_stake")
    for lo_ in range(0, 100, 10):
        report(f"taker price {lo_}-{lo_ + 9}c", d.filter((pl.col("tp") >= lo_) & (pl.col("tp") < lo_ + 10)), "t_net", "t_stake")
    print("\nMAKERS (aggregate, NOT achievable by a newcomer; see docstring):")
    report("all, gross", d, "m_gross", "m_stake")
    report("all, net of maker fee", d, "m_net", "m_stake")
    report("taker-only series (no maker fee)", d.filter(~pl.col("maker_charged")), "m_net", "m_stake")
    report("maker-fee series, net", d.filter(pl.col("maker_charged")), "m_net", "m_stake")
    print("\nexit: 0")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--months", nargs="+", default=["2025-05", "2025-06"])
    ap.add_argument("--series-fee-types", default="results/mece/kalshi_series_fee_types.json")
    args = ap.parse_args()
    return self_test() if args.self_test else run(args)


if __name__ == "__main__":
    sys.exit(main())
