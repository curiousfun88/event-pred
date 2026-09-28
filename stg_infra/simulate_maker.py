"""
simulate_maker.py

TAPE-DRIVEN MAKER (LIQUIDITY-PROVISION) SIMULATOR FOR KALSHI MECE LEGS.

Protocol: docs/planning/maker-simulator-preregistration.md (+ amendment A1).
Read it before changing anything here. Realism is not a tuning parameter:
fill models, fees, settlement P&L and limits are fixed by the protocol.

MECHANICS
  * Hourly refresh. At candle end H the book is known (candle close). Orders
    are posted at H and rest over (H, H+1h], then cancelled and re-posted.
  * A resting YES bid at b fills from taker SELLS (taker_side == "no"):
        optimistic  : trade yes_price <= b   (we are at the front of the queue)
        pessimistic : trade yes_price <  b   (the level at b was exhausted first)
    A resting YES ask at a fills from taker BUYS (taker_side == "yes"):
        optimistic  : trade yes_price >= a
        pessimistic : trade yes_price >  a
    An improved price (bid+1 / ask-1) is a level nobody else occupied, so both
    models fill on trades at or through it.
    Fill size = min(remaining order, trade count, room under the limits), in
    trade-time order. Fill price = our limit price.
  * No quoting at or after the market's close_time.
  * Held to settlement: a long YES pays 100 if result == yes; a short YES
    (sold at a) owes 100 if result == yes. Capital = b per long contract,
    100 - a per short contract (Kalshi collateral).
  * Maker fee, only on series whose fee_type charges makers at that month:
    0.25c/contract before 2025-07, then ceil(0.0175 * C * P * (1-P)) cents per fill.
  * Limits: |net YES position| <= 50 per leg, sum |position| <= 200 per event.
  * 1-hour markout: quoted mid at H+1h minus fill price, signed so positive =
    the price moved in our favour (adverse selection shows up as negative).

USAGE (from repo root)
  python stg_infra/simulate_maker.py --self-test
  python stg_infra/simulate_maker.py --grid --months 2025-05 2025-06          # development search
  python stg_infra/simulate_maker.py --config runs/maker/selected.json \
      --months 2025-07 2025-08 2025-09                                        # frozen test run
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
H_NS = 3_600_000_000_000
MAKER_SWITCH = "2025-07"
MAKER_FEE_TYPES = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}
FIRST_TEST_MONTH = "2025-07"
QUOTE_FILES = {"2025-05": "data/quotes/candles_1h_2025-05_06.parquet",
               "2025-06": "data/quotes/candles_1h_2025-05_06.parquet",
               "2025-07": "data/quotes/candles_1h_2025-07_09.parquet",
               "2025-08": "data/quotes/candles_1h_2025-07_09.parquet",
               "2025-09": "data/quotes/candles_1h_2025-07_09.parquet"}


@dataclasses.dataclass(frozen=True)
class Config:
    sides: str = "both"          # both | bid | ask
    improve: int = 0             # 0 = join the touch, 1 = improve by 1c
    band_lo: int = 1             # order-price band, cents, inclusive
    band_hi: int = 99
    min_spread: int = 2
    series: str = "all"          # all | taker_only
    q: int = 10
    basket: bool = False         # S3: bid every leg when sum(bid) <= 100 - sum(maker fee)
    pos_limit: int = 50
    event_limit: int = 200

    def name(self):
        return (f"sides={self.sides} improve={self.improve} band={self.band_lo}-{self.band_hi} "
                f"minspr={self.min_spread} series={self.series} q={self.q} basket={int(self.basket)}")


# ---------------------------------------------------------------- pure pieces

def maker_fee_c(price_c: float, count: float, charged: bool, month: str) -> float:
    if not charged or count <= 0:
        return 0.0
    if month < MAKER_SWITCH:
        return 0.25 * count
    p = price_c / 100.0
    return float(math.ceil(round(0.0175 * count * p * (1 - p) * 100, 6)))


def fills_for_order(side: int, price: int, qty: int, improved: bool, model: str,
                    tr_price, tr_count, tr_side, room_fn):
    """Walk the hour's trades in time order; return [(trade_idx, filled_qty)].
    side +1 = resting YES bid, -1 = resting YES ask. tr_side: +1 taker bought
    YES ('yes'), -1 taker sold YES ('no'). room_fn(side) -> contracts allowed now."""
    out, remaining, used = [], qty, 0
    strict = (model == "pess") and not improved
    for i in range(len(tr_price)):
        if remaining <= 0:
            break
        p, c, s = tr_price[i], tr_count[i], tr_side[i]
        if side > 0:
            hit = s < 0 and (p < price if strict else p <= price)
        else:
            hit = s > 0 and (p > price if strict else p >= price)
        if not hit:
            continue
        f = min(remaining, int(c), room_fn(side) - used)
        if f <= 0:
            continue
        out.append((i, f))
        remaining -= f
        used += f
    return out


def fill_pnl(side: int, price: int, qty: int, result_yes: bool, fee: float):
    """(net cents, capital cents) for a held-to-settlement fill."""
    if side > 0:
        gross = ((100 if result_yes else 0) - price) * qty
        capital = price * qty
    else:
        gross = (price - (100 if result_yes else 0)) * qty
        capital = (100 - price) * qty
    return gross - fee, capital


def cluster_ci(net_by_event, cap_by_event, n=2000, seed=0):
    net, cap = np.asarray(net_by_event, float), np.asarray(cap_by_event, float)
    if len(net) < 2 or cap.sum() <= 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(net), (n, len(net)))
    r = net[idx].sum(1) / np.maximum(cap[idx].sum(1), 1e-9) * 100
    return float(np.percentile(r, 2.5)), float(np.percentile(r, 97.5))


# ---------------------------------------------------------------- self-test

def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    big = lambda s: 10_000
    P = np.array([40, 39, 41]); C = np.array([5, 5, 5]); S = np.array([-1, -1, -1])
    check("bid @40, optimistic: sells at 40 and 39 fill (41 does not)",
          fills_for_order(+1, 40, 10, False, "opt", P, C, S, big) == [(0, 5), (1, 5)])
    check("bid @40, pessimistic: only the sell THROUGH 40 (at 39) fills",
          fills_for_order(+1, 40, 10, False, "pess", P, C, S, big) == [(1, 5)])
    check("bid @41 improved: pessimistic behaves like optimistic",
          fills_for_order(+1, 41, 20, True, "pess", P, C, S, big) == [(0, 5), (1, 5), (2, 5)])
    check("taker BUYS never fill a resting bid",
          fills_for_order(+1, 40, 10, False, "opt", P, C, np.array([1, 1, 1]), big) == [])
    Pa = np.array([60, 61]); Ca = np.array([4, 8]); Sa = np.array([1, 1])
    check("ask @60 optimistic, partial fills cap at order size 10: 4 then 6",
          fills_for_order(-1, 60, 10, False, "opt", Pa, Ca, Sa, big) == [(0, 4), (1, 6)])
    check("ask @60 pessimistic: only the buy at 61 fills",
          fills_for_order(-1, 60, 10, False, "pess", Pa, Ca, Sa, big) == [(1, 8)])
    check("position room caps the WHOLE order, not each trade (room 2 -> one fill of 2)",
          fills_for_order(-1, 60, 10, False, "opt", Pa, Ca, Sa, lambda s: 2) == [(0, 2)])
    check("long YES @40 settles YES: +60/contract, capital 40",
          fill_pnl(+1, 40, 1, True, 0.0) == (60, 40))
    check("short YES @60 settles NO: +60/contract, capital 40",
          fill_pnl(-1, 60, 1, False, 0.0) == (60, 40))
    check("short YES @60 settles YES: -40/contract",
          fill_pnl(-1, 60, 1, True, 0.0)[0] == -40)
    check("maker fee: taker-only series pays nothing",
          maker_fee_c(50, 10, False, "2025-08") == 0)
    check("maker fee: flat 0.25c/contract before July 2025",
          maker_fee_c(50, 10, True, "2025-05") == 2.5)
    check("maker fee: quadratic from July 2025 (0.0175*10*0.25 = 4.375 -> 5c)",
          maker_fee_c(50, 10, True, "2025-08") == 5)
    lo, hi = cluster_ci([10, 10, 10, 10], [100, 100, 100, 100], n=200)
    check("cluster CI of identical events collapses to the point (10%)", abs(lo - 10) < 1e-9 and abs(hi - 10) < 1e-9)
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


# ---------------------------------------------------------------- data

def load(months):
    import polars as pl
    qfiles = sorted({QUOTE_FILES[m] for m in months})
    q = pl.concat([pl.read_parquet(_REPO / f) for f in qfiles]).unique(["ticker", "end_ts"])
    q = q.with_columns(pl.col("end_ts").cast(pl.Datetime("ns")).cast(pl.Int64).alias("e"))
    lo = min(months)
    y, mo = map(int, max(months).split("-"))
    hi = f"{y + (mo == 12)}-{(mo % 12) + 1:02d}"
    q = q.filter((pl.col("end_ts") >= pl.datetime(int(lo[:4]), int(lo[5:]), 1)) &
                 (pl.col("end_ts") < pl.datetime(int(hi[:4]), int(hi[5:]), 1)))
    tickers = q["ticker"].unique().to_list()

    mk = pl.concat([pl.read_parquet(p, columns=["ticker", "event_ticker", "result", "close_time"])
                    for p in sorted((_REPO / "data/markets").glob("*/markets_2025-*.parquet"))]).unique("ticker")
    mk = mk.filter(pl.col("ticker").is_in(tickers) & pl.col("result").is_in(["yes", "no"]))

    def tfile(m):
        par = "even" if int(m[5:]) % 2 == 0 else "odd"
        return _REPO / f"data/trades/trades_kalshi_{par}/trades_{m}.parquet"
    tr = pl.concat([pl.scan_parquet(tfile(m)).filter(pl.col("ticker").is_in(tickers))
                    .select("ticker", "created_time", "yes_price", "count", "taker_side").collect()
                    for m in months])
    tr = tr.with_columns(pl.col("created_time").cast(pl.Datetime("ns")).cast(pl.Int64).alias("t"),
                         pl.when(pl.col("taker_side") == "yes").then(1).otherwise(-1).alias("s")).sort(["ticker", "t"])

    fee_types = json.loads((_REPO / "results/mece/kalshi_series_fee_types.json").read_text())
    changes = json.loads((_REPO / "results/mece/kalshi_series_fee_changes.json").read_text())
    first = {}
    for c in sorted(changes, key=lambda c: c["scheduled_ts"]):
        first.setdefault(c["series_ticker"], c)

    def charged(series, month):
        c = first.get(series)
        if c is not None and month < c["scheduled_ts"][:7]:
            return c["fee_type"] not in MAKER_FEE_TYPES
        return fee_types.get(series, "quadratic") in MAKER_FEE_TYPES

    legs = {}
    meta = {r["ticker"]: r for r in mk.iter_rows(named=True)}
    for (tk,), g in q.sort(["ticker", "e"]).group_by(["ticker"], maintain_order=True):
        if tk not in meta:
            continue
        m = meta[tk]
        close_ns = int(np.datetime64(m["close_time"].replace(tzinfo=None), "ns").astype(np.int64)) if m["close_time"] else None
        legs[tk] = {"event": m["event_ticker"], "series": m["event_ticker"].split("-")[0],
                    "yes": m["result"] == "yes", "close": close_ns,
                    "e": g["e"].to_numpy(), "bid": g["bid_close"].to_numpy(), "ask": g["ask_close"].to_numpy()}
    for (tk,), g in tr.group_by(["ticker"], maintain_order=True):
        if tk in legs:
            legs[tk]["tt"] = g["t"].to_numpy()
            legs[tk]["tp"] = g["yes_price"].to_numpy()
            legs[tk]["tc"] = g["count"].to_numpy()
            legs[tk]["ts"] = g["s"].to_numpy()
    events = {}
    for tk, L in legs.items():
        L.setdefault("tt", np.empty(0, np.int64)); L.setdefault("tp", np.empty(0)); L.setdefault("tc", np.empty(0)); L.setdefault("ts", np.empty(0))
        events.setdefault(L["event"], []).append(tk)
    return legs, events, charged


def month_of(ns: int) -> str:
    d = np.datetime64(int(ns), "ns").astype("datetime64[M]")
    return str(d)


# ---------------------------------------------------------------- simulation

def simulate(cfg: Config, model: str, legs, events, charged, months):
    fills = []   # (event, ticker, side, price, qty, fee, net, capital, markout)
    mset = set(months)
    for ev, tks in events.items():
        pos = {tk: 0 for tk in tks}
        hours = sorted({int(e) for tk in tks for e in legs[tk]["e"]})
        for H in hours:
            if month_of(H) not in mset:
                continue
            quotes = {}
            for tk in tks:
                L = legs[tk]
                j = np.searchsorted(L["e"], H)
                if j >= len(L["e"]) or L["e"][j] != H:
                    continue
                if L["close"] is not None and H >= L["close"]:
                    continue
                b, a = L["bid"][j], L["ask"][j]
                if b is None or a is None or np.isnan(b) or np.isnan(a):
                    continue
                b, a = int(round(b * 100)), int(round(a * 100))
                if not (0 < b < a < 100):
                    continue
                quotes[tk] = (b, a, j)
            if not quotes:
                continue
            if cfg.series == "taker_only":
                if charged(legs[next(iter(quotes))]["series"], month_of(H)):
                    continue
            if cfg.basket:
                if len(quotes) != len(tks):
                    continue
                mo = month_of(H)
                ch = charged(legs[tks[0]]["series"], mo)
                fee_pc = sum(maker_fee_c(quotes[tk][0], cfg.q, ch, mo) / cfg.q for tk in tks)
                if sum(quotes[tk][0] for tk in tks) > 100 - fee_pc:
                    continue
            for tk, (b, a, j) in quotes.items():
                L = legs[tk]
                spread = a - b
                if spread < cfg.min_spread:
                    continue
                orders = []
                want_bid = cfg.basket or cfg.sides in ("both", "bid")
                want_ask = (not cfg.basket) and cfg.sides in ("both", "ask")
                imp = cfg.improve and spread >= 3 and not cfg.basket
                if want_bid:
                    orders.append((+1, b + (1 if imp else 0)))
                if want_ask:
                    orders.append((-1, a - (1 if imp else 0)))
                orders = [(s, p) for s, p in orders if cfg.band_lo <= p <= cfg.band_hi]
                if not orders:
                    continue
                lo_i = np.searchsorted(L["tt"], H, side="right")
                hi_i = np.searchsorted(L["tt"], H + H_NS, side="right")
                if L["close"] is not None:
                    hi_i = min(hi_i, np.searchsorted(L["tt"], L["close"], side="left"))
                if hi_i <= lo_i:
                    continue
                tp, tc, ts = L["tp"][lo_i:hi_i], L["tc"][lo_i:hi_i], L["ts"][lo_i:hi_i]
                mid_next = None
                if j + 1 < len(L["e"]) and L["e"][j + 1] == H + H_NS:
                    bn, an = L["bid"][j + 1], L["ask"][j + 1]
                    if bn is not None and an is not None and not (np.isnan(bn) or np.isnan(an)):
                        mid_next = 50 * (bn + an)
                for side, price in orders:
                    def room(s, tk=tk):
                        leg_room = cfg.pos_limit - s * pos[tk]
                        ev_room = cfg.event_limit - sum(abs(v) for v in pos.values())
                        return max(0, min(leg_room, ev_room))
                    for _, f in fills_for_order(side, price, cfg.q, bool(imp), model, tp, tc, ts, room):
                        pos[tk] += side * f
                        mo = month_of(H)
                        fee = maker_fee_c(price, f, charged(L["series"], mo), mo)
                        net, cap = fill_pnl(side, price, f, L["yes"], fee)
                        mk = (side * (mid_next - price) * f) if mid_next is not None else np.nan
                        fills.append((ev, tk, side, price, f, fee, net, cap, mk))
    return fills


def summarise(fills):
    if not fills:
        return {"fills": 0, "events": 0, "contracts": 0, "net_c": 0.0, "ret": float("nan"),
                "lo": float("nan"), "hi": float("nan"), "markout_c_per_contract": float("nan")}
    ev = {}
    for f in fills:
        a = ev.setdefault(f[0], [0.0, 0.0])
        a[0] += f[6]
        a[1] += f[7]
    net = sum(v[0] for v in ev.values())
    cap = sum(v[1] for v in ev.values())
    lo, hi = cluster_ci([v[0] for v in ev.values()], [v[1] for v in ev.values()])
    mk = [f[8] for f in fills if not np.isnan(f[8])]
    qty_mk = sum(f[4] for f in fills if not np.isnan(f[8]))
    return {"fills": len(fills), "events": len(ev), "contracts": int(sum(f[4] for f in fills)),
            "net_c": float(net), "fees_c": float(sum(f[5] for f in fills)),
            "ret": 100 * net / cap if cap else float("nan"), "lo": lo, "hi": hi,
            "markout_c_per_contract": (sum(mk) / qty_mk) if qty_mk else float("nan")}


def fmt(r):
    return (f"ret {r['ret']:+7.2f}%  CI95 [{r['lo']:+7.2f}, {r['hi']:+7.2f}]  net ${r['net_c'] / 100:>9,.2f}  "
            f"fills {r['fills']:>6,}  contracts {r['contracts']:>7,}  events {r['events']:>5,}  "
            f"1h markout {r['markout_c_per_contract']:+.2f}c/ct")


def grid_configs():
    for sides, improve, band, ms, ser, basket in itertools.product(
            ["both", "bid", "ask"], [0, 1], [(1, 15), (15, 85), (85, 99), (1, 99)], [2, 4],
            ["all", "taker_only"], [False, True]):
        if basket and (sides != "bid" or improve):
            continue          # basket mode is a bid-only, join-the-touch rule
        yield Config(sides=sides, improve=improve, band_lo=band[0], band_hi=band[1],
                     min_spread=ms, series=ser, basket=basket)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--months", nargs="+", default=["2025-05", "2025-06"])
    ap.add_argument("--grid", action="store_true", help="development search (refused on test months)")
    ap.add_argument("--config", help="frozen config JSON for a test run")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.grid and max(args.months) >= FIRST_TEST_MONTH:
        raise SystemExit("REFUSED: --grid on test/confirmation months breaks the protocol (amendment A1).")

    legs, events, charged = load(args.months)
    print(f"months {args.months}: {len(legs):,} legs with quotes and a settled result, {len(events):,} events")

    if args.grid:
        rows = []
        for cfg in grid_configs():
            r = {m: summarise(simulate(cfg, m, legs, events, charged, args.months)) for m in ("opt", "pess")}
            rows.append((cfg, r))
            print(f"{cfg.name()}\n    OPT  {fmt(r['opt'])}\n    PESS {fmt(r['pess'])}", flush=True)
        ok = [(c, r) for c, r in rows if r["pess"]["fills"] >= 300 and r["pess"]["events"] >= 30]
        ok.sort(key=lambda cr: (cr[1]["pess"]["ret"], cr[1]["pess"]["fills"]), reverse=True)
        print("\n=== SELECTION (amendment A1: best pessimistic return, >=300 fills, >=30 events) ===")
        for c, r in ok[:10]:
            print(f"  {c.name()}\n      PESS {fmt(r['pess'])}\n      OPT  {fmt(r['opt'])}")
        if ok and args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(dataclasses.asdict(ok[0][0]), indent=2))
            print(f"\nselected config written to {args.out}")
    else:
        cfgs = [("S1 (pre-registered reference)", Config())]
        if args.config:
            cfgs.insert(0, ("SELECTED (frozen)", Config(**json.loads(Path(args.config).read_text()))))
        for label, cfg in cfgs:
            for m in ("opt", "pess"):
                print(f"{label:<30} {m.upper():<4} {fmt(summarise(simulate(cfg, m, legs, events, charged, args.months)))}")
    print("\nexit: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
