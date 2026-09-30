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
# Amendment A4: 7 months train (search) / 2 months validation (shortlist only) / 4 months test (once)
TRAIN_MONTHS = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL_MONTHS = ["2025-06", "2025-07"]
TEST_MONTHS = ["2025-08", "2025-09", "2025-10", "2025-11"]
FIRST_VAL_MONTH = VAL_MONTHS[0]
SHORTLIST_K = 10
# Bump when simulation logic changes: cached results from older logic are then ignored.
SIM_VERSION = "3"   # 3: fills record hour_ns (A9); results unchanged
CACHE_DIR = _REPO / "runs/maker/cache"


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
    universe: str = "mece"       # mece | liquid
    min_trades_24h: int = 0      # causal liquidity rule: trades in (H-24h, H]
    stgat: str = ""              # A6.3: "" (no model) | "s4" (filter) | "s5" (model-led); needs --signal
    min_ttc_h: int = 0           # A10: no quote on a leg within this many hours of its close
    policy: str = ""             # A12: learned policy scores (parquet: ticker, hour_ns, side, pred); "" = off
    policy_t: float = 1.0        # A12: post an order only if its predicted P&L per contract > policy_t

    def name(self):
        return (f"univ={self.universe} sides={self.sides} improve={self.improve} band={self.band_lo}-{self.band_hi} "
                f"minspr={self.min_spread} series={self.series} liq24h>={self.min_trades_24h} inv={self.pos_limit} "
                f"basket={int(self.basket)}" + (f" stgat={self.stgat}" if self.stgat else "")
                + (f" min_ttc={self.min_ttc_h}h" if self.min_ttc_h else ""))


# A6.3 S5, fixed before the base test: all MECE legs, 1-99c, spread >= 4c,
# inventory 25, improve by 1c (when spread >= 3c), both sides, model-gated.
S5_CONFIG = Config(sides="both", improve=1, band_lo=1, band_hi=99, min_spread=4,
                   pos_limit=25, universe="mece", stgat="s5")


# ---------------------------------------------------------------- pure pieces

def maker_fee_c(price_c: float, count: float, charged: bool, month: str) -> float:
    if not charged or count <= 0:
        return 0.0
    if month < MAKER_SWITCH:
        return 0.25 * count
    p = price_c / 100.0
    return float(math.ceil(round(0.0175 * count * p * (1 - p) * 100, 6)))


def fills_for_order(side: int, price: int, qty: int, improved: bool, model: str,
                    tr_price, tr_count, tr_side, room_fn, orig_price=None):
    """Walk the hour's trades in time order; return [(trade_idx, filled_qty)].
    side +1 = resting YES bid, -1 = resting YES ask. tr_side: +1 taker bought
    YES ('yes'), -1 taker sold YES ('no'). room_fn(side) -> contracts allowed now."""
    out, remaining, used = [], qty, 0
    # "strict" (A6.1): an IMPROVED order fills only on trades strictly beyond the ORIGINAL
    # touch (as if a competitor matched our improvement); otherwise identical to "pess".
    if model == "strict" and improved and orig_price is not None:
        price_cmp, strict = orig_price, True
    else:
        price_cmp, strict = price, (model in ("pess", "strict")) and not improved
    for i in range(len(tr_price)):
        if remaining <= 0:
            break
        p, c, s = tr_price[i], tr_count[i], tr_side[i]
        if side > 0:
            hit = s < 0 and (p < price_cmp if strict else p <= price_cmp)
        else:
            hit = s > 0 and (p > price_cmp if strict else p >= price_cmp)
        if not hit:
            continue
        f = min(remaining, int(c), room_fn(side) - used)
        if f <= 0:
            continue
        out.append((i, f))
        remaining -= f
        used += f
    return out


def recent_trades(tt, H: int, window_ns: int = 24 * H_NS) -> int:
    """Trades in the window (H - window, H]. Causal: never looks past H."""
    return int(np.searchsorted(tt, H, side="right") - np.searchsorted(tt, H - window_ns, side="right"))


def fill_pnl(side: int, price: int, qty: int, result_yes: bool, fee: float):
    """(net cents, capital cents) for a held-to-settlement fill."""
    if side > 0:
        gross = ((100 if result_yes else 0) - price) * qty
        capital = price * qty
    else:
        gross = (price - (100 if result_yes else 0)) * qty
        capital = (100 - price) * qty
    return gross - fee, capital


SIGNAL_GRID_NS = 2 * H_NS   # STGAT snapshots: 2 h windows ending on even UTC hours


def signal_at(signal, ticker, H):
    """A9: m_hat (cents) from the snapshot whose window ends EXACTLY at H, or
    None. A snapshot ending at H - 1h forecasts (H - 1h, H], an hour already
    over at H, so it is not a signal for an order posted at H.
    ``signal[ticker] = (end_ns sorted, m_hat_c)``."""
    rec = signal.get(ticker) if signal else None
    if rec is None:
        return None
    e, m = rec
    j = np.searchsorted(e, H, side="left")
    return float(m[j]) if j < len(e) and e[j] == H else None


def is_signal_hour(H) -> bool:
    """A9 secondary report: quoting hours on the 2 h snapshot grid."""
    return int(H) % SIGNAL_GRID_NS == 0


def stgat_sides(mode, want_bid, want_ask, m_hat, spread):
    """A6.3 / B1.5 order gating by the predicted next-hour mid move m_hat (cents).
    s4: the base, minus an ask when m_hat > +s/2 and a bid when m_hat < -s/2;
        no signal -> the base order stands.
    s5: a bid only if m_hat > +s/2, an ask only if m_hat < -s/2; no signal -> nothing."""
    if mode == "s4":
        if m_hat is None:
            return want_bid, want_ask
        return want_bid and not (m_hat < -spread / 2), want_ask and not (m_hat > spread / 2)
    if mode == "s5":
        if m_hat is None:
            return False, False
        return want_bid and m_hat > spread / 2, want_ask and m_hat < -spread / 2
    return want_bid, want_ask


def paired_diff_ci(ev_a, ev_b, n=2000, seed=0):
    """(point, lo, hi) of ret(A) - ret(B), percent, resampling the union of
    events so both strategies see the same draw. ev_* = {event: (net_c, capital_c)}."""
    keys = sorted(set(ev_a) | set(ev_b))
    if len(keys) < 2:
        return float("nan"), float("nan"), float("nan")
    a = np.array([ev_a.get(k, (0.0, 0.0)) for k in keys], float)
    b = np.array([ev_b.get(k, (0.0, 0.0)) for k in keys], float)

    def ret(x, idx=None):
        x = x if idx is None else x[idx]
        return x[..., 0].sum(-1) / np.maximum(x[..., 1].sum(-1), 1e-9) * 100

    point = float(ret(a) - ret(b))
    idx = np.random.default_rng(seed).integers(0, len(keys), (n, len(keys)))
    d = ret(a, idx) - ret(b, idx)
    return point, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


DEV_MONTHS = TRAIN_MONTHS + VAL_MONTHS
A10_MIN_FILLS, A10_MIN_EVENTS, A10_MIN_ACTIVE_MONTHS, A10_MIN_STRICT_POS_MONTHS = 300, 30, 7, 6


def robust_select(rows, n_months):
    """A10 selection rule, fixed before any test-month simulation.
    rows: dicts with cfg, pess (summary), strict (summary), pess_active_months
    (months with >= 1 pessimistic fill) and strict_monthly_ret ({month: ret%}).
    Eligible: >= 300 pessimistic fills, >= 30 events, fills in >= 7 of the months.
    Qualifies: pooled pessimistic return > 0 AND strict return > 0 in >= 6 months
    (a month without strict fills is not positive).
    Winner: highest pooled strict return; ties -> more pessimistic fills. None if none qualify."""
    need_active = A10_MIN_ACTIVE_MONTHS if n_months >= 9 else max(1, round(n_months * 7 / 9))
    need_pos = A10_MIN_STRICT_POS_MONTHS if n_months >= 9 else max(1, round(n_months * 6 / 9))
    ok = [r for r in rows
          if r["pess"]["fills"] >= A10_MIN_FILLS and r["pess"]["events"] >= A10_MIN_EVENTS
          and r["pess_active_months"] >= need_active
          and r["pess"]["ret"] == r["pess"]["ret"] and r["pess"]["ret"] > 0
          and sum(1 for v in r["strict_monthly_ret"].values() if v == v and v > 0) >= need_pos
          and r["strict"]["ret"] == r["strict"]["ret"]]
    ok.sort(key=lambda r: (r["strict"]["ret"], r["pess"]["fills"]), reverse=True)
    return (ok[0] if ok else None), ok


def robust_grid_configs():
    """A10 space: the A1-A5 grid x min_ttc_h {0, 24}."""
    for c in grid_configs():
        yield c
        yield dataclasses.replace(c, min_ttc_h=24)


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
    check("strict, improved bid @41 (touch 40): only sells strictly below 40 fill",
          fills_for_order(+1, 41, 20, True, "strict", P, C, S, big, orig_price=40) == [(1, 5)])
    Pa2 = np.array([59, 60, 61]); Ca2 = np.array([3, 3, 3]); Sa2 = np.array([1, 1, 1])
    check("strict, improved ask @59 (touch 60): only buys strictly above 60 fill",
          fills_for_order(-1, 59, 10, True, "strict", Pa2, Ca2, Sa2, big, orig_price=60) == [(2, 3)])
    check("strict on a non-improved order equals pessimistic",
          fills_for_order(+1, 40, 10, False, "strict", P, C, S, big, orig_price=40)
          == fills_for_order(+1, 40, 10, False, "pess", P, C, S, big))
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
    tt = np.array([1, 5, 20, 30]) * H_NS
    check("liquidity rule: at H=30h only the trades at 20h and 30h are inside (H-24h, H]",
          recent_trades(tt, 30 * H_NS) == 2)
    check("liquidity rule never looks ahead: at H=4h only the 1h trade counts", recent_trades(tt, 4 * H_NS) == 1)
    lo, hi = cluster_ci([10, 10, 10, 10], [100, 100, 100, 100], n=200)
    check("cluster CI of identical events collapses to the point (10%)", abs(lo - 10) < 1e-9 and abs(hi - 10) < 1e-9)
    # A6.3 signal and gating
    sig = {"A": (np.array([10, 12]) * H_NS, np.array([3.0, -5.0]))}
    check("A9: a snapshot ending exactly at H is used (10h, 12h)",
          signal_at(sig, "A", 10 * H_NS) == 3.0 and signal_at(sig, "A", 12 * H_NS) == -5.0)
    check("A9: stale snapshot (ended H-1h) is no signal (H=11h -> none)", signal_at(sig, "A", 11 * H_NS) is None)
    check("signal never looks ahead (H=9h -> none)", signal_at(sig, "A", 9 * H_NS) is None)
    check("signal hours are the even UTC hours", is_signal_hour(10 * H_NS) and not is_signal_hour(11 * H_NS))
    check("signal: unknown ticker -> none", signal_at(sig, "B", 11 * H_NS) is None)
    check("S4 skips the ask when m_hat > +s/2 (3 > 2)", stgat_sides("s4", False, True, 3.0, 4) == (False, False))
    check("S4 keeps the ask at m_hat = +s/2 exactly", stgat_sides("s4", False, True, 2.0, 4) == (False, True))
    check("S4 skips a bid when m_hat < -s/2", stgat_sides("s4", True, True, -3.0, 4) == (False, True))
    check("S4 without a signal = the base", stgat_sides("s4", False, True, None, 4) == (False, True))
    check("S5 bids only when m_hat > +s/2", stgat_sides("s5", True, True, 3.0, 4) == (True, False))
    check("S5 asks only when m_hat < -s/2", stgat_sides("s5", True, True, -3.0, 4) == (False, True))
    check("S5 posts nothing inside the band", stgat_sides("s5", True, True, 1.0, 4) == (False, False))
    check("S5 without a signal posts nothing", stgat_sides("s5", True, True, None, 4) == (False, False))
    check("no model: sides unchanged", stgat_sides("", True, False, 9.0, 4) == (True, False))
    ev = {"e1": (10.0, 100.0), "e2": (-5.0, 50.0), "e3": (3.0, 30.0)}
    pt, lo, hi = paired_diff_ci(ev, ev, n=200)
    check("paired CI of a strategy against itself is exactly 0", pt == 0 and lo == 0 and hi == 0)
    pt, lo, hi = paired_diff_ci({"e1": (20.0, 100.0), "e2": (10.0, 100.0)}, {"e1": (10.0, 100.0), "e2": (0.0, 100.0)}, n=200)
    check("paired CI: +10pp on every event -> point and CI exactly +10", abs(pt - 10) < 1e-9 and abs(lo - 10) < 1e-9 and abs(hi - 10) < 1e-9)
    check("S5 config matches A6.3", (S5_CONFIG.band_lo, S5_CONFIG.band_hi, S5_CONFIG.min_spread, S5_CONFIG.pos_limit,
                                     S5_CONFIG.improve, S5_CONFIG.sides, S5_CONFIG.universe) == (1, 99, 4, 25, 1, "both", "mece"))
    # A10
    def row(ret_p, ret_s, fills=400, events=40, active=9, pos=9, tag=""):
        return {"cfg": tag, "pess": {"ret": ret_p, "fills": fills, "events": events}, "strict": {"ret": ret_s},
                "pess_active_months": active,
                "strict_monthly_ret": {f"m{i}": (1.0 if i < pos else -1.0) for i in range(9)}}
    w, ok = robust_select([row(5, 2, tag="a"), row(5, 3, tag="b"), row(9, 1, tag="c")], 9)
    check("A10: highest pooled STRICT return wins (not highest pessimistic)", w["cfg"] == "b")
    w, _ = robust_select([row(5, 3, pos=5, tag="a"), row(5, 1, pos=6, tag="b")], 9)
    check("A10: strict positive in only 5 of 9 months is excluded", w["cfg"] == "b")
    w, _ = robust_select([row(-1, 9, tag="a"), row(2, 1, tag="b")], 9)
    check("A10: pooled pessimistic return must be > 0", w["cfg"] == "b")
    w, _ = robust_select([row(5, 9, fills=299, tag="a"), row(5, 9, events=29, tag="b"),
                          row(5, 9, active=6, tag="c"), row(5, 1, tag="d")], 9)
    check("A10: eligibility (300 fills, 30 events, 7 active months)", w["cfg"] == "d")
    w, _ = robust_select([row(5, 2, fills=500, tag="a"), row(5, 2, fills=400, tag="b")], 9)
    check("A10: ties broken by more fills", w["cfg"] == "a")
    w, ok = robust_select([row(-1, -1, tag="a")], 9)
    check("A10: nothing qualifies -> None (A6 winner stays)", w is None and ok == [])
    r0 = row(5, 2); r0["strict_monthly_ret"] = {f"m{i}": (float("nan") if i < 4 else 1.0) for i in range(9)}
    check("A10: a month without strict fills is not positive", robust_select([r0], 9)[0] is None)
    check("A10 grid doubles the A1-A5 grid", sum(1 for _ in robust_grid_configs()) == 2 * sum(1 for _ in grid_configs()))
    check("A10: min_ttc_h=0 keeps old cache keys; 24 enters the key",
          "min_ttc_h" not in _cfg_key_dict(Config()) and _cfg_key_dict(Config(min_ttc_h=24))["min_ttc_h"] == 24)
    check("configs without a model keep their old cache keys",
          "stgat" not in _cfg_key_dict(Config()) and _cfg_key_dict(Config(stgat="s4"))["stgat"] == "s4")
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


# ---------------------------------------------------------------- data

def load(months, universe="mece"):
    import polars as pl
    # Prefer the monthly partition (partition_quotes.py) when it is UP TO DATE: every
    # requested month present and newer than every raw download file. Otherwise read
    # the raw files, so a stale partition can never silently drop data.
    qdir = _REPO / "data/quotes"
    raw = sorted(qdir.glob("*.parquet")) + sorted(qdir.glob("*.parts/*.parquet"))
    part = [qdir / "by_month" / f"quotes_{m}.parquet" for m in months]
    newest_raw = max((f.stat().st_mtime for f in raw), default=0)
    if all(f.exists() for f in part) and min(f.stat().st_mtime for f in part) >= newest_raw:
        qfiles = part
    else:
        qfiles = raw
    q = pl.concat([pl.read_parquet(f) for f in qfiles], how="diagonal_relaxed").unique(["ticker", "end_ts"])
    q = q.with_columns(pl.col("end_ts").cast(pl.Datetime("ns")).cast(pl.Int64).alias("e"))
    lo = min(months)
    y, mo = map(int, max(months).split("-"))
    hi = f"{y + (mo == 12)}-{(mo % 12) + 1:02d}"
    q = q.filter((pl.col("end_ts") >= pl.datetime(int(lo[:4]), int(lo[5:]), 1)) &
                 (pl.col("end_ts") < pl.datetime(int(hi[:4]), int(hi[5:]), 1)))
    mem = pl.read_parquet(_REPO / "results/mece/mece_membership.parquet")
    causal = set(mem.filter(pl.col("q_from").is_not_null() & (pl.col("q_from") <= pl.col("leg_created")))["ticker"].to_list())
    if universe == "mece":
        q = q.filter(pl.col("ticker").is_in(list(causal)))
    tickers = q["ticker"].unique().to_list()

    mk = pl.concat([pl.read_parquet(p, columns=["ticker", "event_ticker", "result", "close_time"])
                    for p in sorted((_REPO / "data/markets").glob("*/markets_*.parquet"))]).unique("ticker")
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

def simulate(cfg: Config, model: str, legs, events, charged, months, signal=None, policy_scores=None, record=None):
    """record: if a list, append every candidate order (event, ticker, H, side, price, bid, ask) after all
    quoting filters and simulate NO fills (used to score candidates with the simulator's own logic).
    policy_scores: {(ticker, H, side): predicted c/contract}; with cfg.policy set, only orders scoring
    > cfg.policy_t are posted (A12). Inventory limits and fills are then simulated as usual."""
    fills = []   # (event, ticker, side, price, qty, fee, net, capital, markout, hour_ns)
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
                if cfg.min_ttc_h and L["close"] is not None and L["close"] - H < cfg.min_ttc_h * H_NS:
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
                if cfg.min_trades_24h and recent_trades(L["tt"], H) < cfg.min_trades_24h:
                    continue
                spread = a - b
                if spread < cfg.min_spread:
                    continue
                orders = []
                want_bid = cfg.basket or cfg.sides in ("both", "bid")
                want_ask = (not cfg.basket) and cfg.sides in ("both", "ask")
                if cfg.stgat:
                    want_bid, want_ask = stgat_sides(cfg.stgat, want_bid, want_ask,
                                                     signal_at(signal, tk, H), spread)
                imp = cfg.improve and spread >= 3 and not cfg.basket
                if want_bid:
                    orders.append((+1, b + (1 if imp else 0), b))
                if want_ask:
                    orders.append((-1, a - (1 if imp else 0), a))
                orders = [(s, p, o) for s, p, o in orders if cfg.band_lo <= p <= cfg.band_hi]
                if record is not None:
                    record.extend((ev, tk, H, s, p, b, a) for s, p, o in orders)
                    continue
                if cfg.policy:
                    orders = [(s, p, o) for s, p, o in orders
                              if policy_scores.get((tk, H, s), -np.inf) > cfg.policy_t]
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
                for side, price, orig in orders:
                    def room(s, tk=tk):
                        leg_room = cfg.pos_limit - s * pos[tk]
                        ev_room = cfg.event_limit - sum(abs(v) for v in pos.values())
                        return max(0, min(leg_room, ev_room))
                    for _, f in fills_for_order(side, price, cfg.q, bool(imp), model, tp, tc, ts, room, orig):
                        pos[tk] += side * f
                        mo = month_of(H)
                        fee = maker_fee_c(price, f, charged(L["series"], mo), mo)
                        net, cap = fill_pnl(side, price, f, L["yes"], fee)
                        mk = (side * (mid_next - price) * f) if mid_next is not None else np.nan
                        fills.append((ev, tk, side, price, f, fee, net, cap, mk, H))
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


def data_fingerprint(months) -> str:
    """Name+size of every quote file the run would read, so re-partitioned or
    re-downloaded data never silently reuses results computed on older data."""
    import hashlib
    qdir = _REPO / "data/quotes"
    part = [qdir / "by_month" / f"quotes_{m}.parquet" for m in sorted(months)]
    files = part if all(f.exists() for f in part) else (sorted(qdir.glob("*.parquet")) + sorted(qdir.glob("*.parts/*.parquet")))
    return hashlib.sha1("|".join(f"{f.name}:{f.stat().st_size}" for f in files).encode()).hexdigest()[:12]


def _cfg_key_dict(cfg: Config) -> dict:
    """Config as hashed into the cache key. ``stgat`` is left out when unset,
    so every configuration cached before A6.3 keeps its key."""
    d = dataclasses.asdict(cfg)
    for k in ("stgat", "min_ttc_h"):      # added later (A6.3, A10): unset -> old key
        if not d[k]:
            d.pop(k)
    if not d["policy"]:                   # A12: no policy -> old key
        d.pop("policy"); d.pop("policy_t")
    return d


SIGNAL_PATH = None   # set by --signal; its fingerprint enters the key of model-gated runs


def cache_key(cfg: Config, model: str, months) -> str:
    import hashlib
    blob = {"cfg": _cfg_key_dict(cfg), "model": model, "months": sorted(months), "v": SIM_VERSION,
            "data": data_fingerprint(months)}
    if cfg.stgat:
        st = Path(SIGNAL_PATH).stat()
        blob["signal"] = f"{Path(SIGNAL_PATH).name}:{st.st_size}:{int(st.st_mtime)}"
    if cfg.policy:
        st = Path(cfg.policy).stat()
        blob["policy_file"] = f"{Path(cfg.policy).name}:{st.st_size}:{int(st.st_mtime)}"
    blob = json.dumps(blob, sort_keys=True)
    return hashlib.sha1(blob.encode()).hexdigest()[:16]


_G = {}   # data shared with forked workers (copy-on-write)


def run_one(task):
    """Simulate one (config, model), or reuse the cached result. Saves every fill."""
    cfg, model, months = task
    key = cache_key(cfg, model, months)
    summ_f = CACHE_DIR / f"{key}.json"
    if summ_f.exists():
        return cfg, model, json.loads(summ_f.read_text()), True
    fills = simulate(cfg, model, _G["legs"], _G["events"], _G["charged"], months, _G.get("signal"),
                     _G.get("policy", {}).get(cfg.policy) if cfg.policy else None)
    r = summarise(fills)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # NO polars in forked workers: polars' thread pool can deadlock after fork()
    # (seen 2026-09-29: 6 workers idle for 31 min). numpy only.
    if fills:
        cols = list(zip(*fills))
        np.savez_compressed(CACHE_DIR / f"{key}.fills.npz",
                            event=np.array(cols[0], dtype=object), ticker=np.array(cols[1], dtype=object),
                            side=np.array(cols[2]), price=np.array(cols[3]), qty=np.array(cols[4]),
                            fee_c=np.array(cols[5]), net_c=np.array(cols[6]), capital_c=np.array(cols[7]),
                            markout_c=np.array(cols[8], dtype=float), hour_ns=np.array(cols[9], dtype=np.int64))
    summ_f.write_text(json.dumps({**r, "config": dataclasses.asdict(cfg), "model": model, "months": months}))
    return cfg, model, r, False


def run_many(tasks, workers):
    """Run tasks, reusing cached ones; data is loaded lazily and only if needed."""
    todo = [t for t in tasks if not (CACHE_DIR / f"{cache_key(*t)}.json").exists()]
    print(f"{len(tasks)} simulations requested; {len(tasks) - len(todo)} cached; {len(todo)} to run on {workers} workers", flush=True)
    results = {}
    import multiprocessing as mp
    for univ in sorted({t[0].universe for t in todo}):
        sub_t = [t for t in todo if t[0].universe == univ]
        months = sorted({m for t in sub_t for m in t[2]})
        _G.clear()
        _G["legs"], _G["events"], _G["charged"] = load(months, univ)
        if any(t[0].stgat for t in sub_t):
            _G["signal"] = load_signal(SIGNAL_PATH)
        _G["policy"] = {pth: load_policy(pth) for pth in {t[0].policy for t in sub_t if t[0].policy}}
        print(f"loaded universe={univ} {months[0]}..{months[-1]}: {len(_G['legs']):,} legs, "
              f"{len(_G['events']):,} events; running {len(sub_t)} simulations", flush=True)
        with mp.get_context("fork").Pool(workers) as pool:
            for cfg, model, r, _ in pool.imap_unordered(run_one, sub_t):
                results[(cfg, model)] = r
                print(f"  done: {model.upper():<4} {cfg.name()} -> ret {r['ret']:+.2f}% ({r['fills']:,} fills)", flush=True)
        _G.clear()
    for t in tasks:
        if (t[0], t[1]) not in results:
            results[(t[0], t[1])] = json.loads((CACHE_DIR / f"{cache_key(*t)}.json").read_text())
    return results


def load_policy(path):
    """A12 policy scores parquet -> {(ticker, hour_ns, side): pred c/contract}."""
    import polars as pl
    df = pl.read_parquet(path)
    return {(tk, int(h), int(sd)): float(pr) for tk, h, sd, pr in
            zip(df["ticker"].to_list(), df["hour_ns"].to_list(), df["side"].to_list(), df["pred"].to_list())}


def load_signal(path):
    """export_mid_signal.py output -> {ticker: (end_ns sorted, m_hat cents)}."""
    import polars as pl
    df = pl.read_parquet(path).sort(["ticker", "end_ns"])
    off = df.filter(pl.col("end_ns") % SIGNAL_GRID_NS != 0).height
    if off:
        raise SystemExit(f"{off} signal rows are not on the 2 h grid: A9's signal hours would be wrong")
    return {tk: (g["end_ns"].to_numpy(), g["m_hat_c"].to_numpy())
            for (tk,), g in df.group_by(["ticker"], maintain_order=True)}


def event_totals(cfg: Config, model: str, months, signal_hours_only=False) -> dict:
    """{event: (net_c, capital_c)} from a run's saved fills (empty if none).
    ``signal_hours_only`` (A9 secondary): fills from quotes posted on the 2 h grid."""
    f = CACHE_DIR / f"{cache_key(cfg, model, months)}.fills.npz"
    if not f.exists():
        return {}
    z = np.load(f, allow_pickle=True)
    keep = np.ones(len(z["net_c"]), bool)
    if signal_hours_only:
        if "hour_ns" not in z.files:
            raise SystemExit(f"{f.name} predates A9 (no hour_ns); delete it and rerun")
        keep = (z["hour_ns"] % SIGNAL_GRID_NS) == 0
    out = {}
    for e, n, c in zip(z["event"][keep], z["net_c"][keep], z["capital_c"][keep]):
        a = out.setdefault(str(e), [0.0, 0.0])
        a[0] += float(n)
        a[1] += float(c)
    return {k: tuple(v) for k, v in out.items()}


def monthly_returns(cfg: Config, model: str, months) -> dict:
    """{month: return %} from a run's saved fills, by the month of the quoting hour."""
    f = CACHE_DIR / f"{cache_key(cfg, model, months)}.fills.npz"
    out = {m: float("nan") for m in months}
    if not f.exists():
        return out
    z = np.load(f, allow_pickle=True)
    if "hour_ns" not in z.files:
        raise SystemExit(f"{f.name} predates hour_ns; delete it and rerun")
    mon = np.array([month_of(h) for h in z["hour_ns"]])
    for m in months:
        k = mon == m
        cap = float(z["capital_c"][k].sum())
        out[m] = 100 * float(z["net_c"][k].sum()) / cap if cap > 0 else float("nan")
    return out


def fmt(r):
    return (f"ret {r['ret']:+7.2f}%  CI95 [{r['lo']:+7.2f}, {r['hi']:+7.2f}]  net ${r['net_c'] / 100:>9,.2f}  "
            f"fills {r['fills']:>6,}  contracts {r['contracts']:>7,}  events {r['events']:>5,}  "
            f"1h markout {r['markout_c_per_contract']:+.2f}c/ct")


def grid_configs():
    for univ, sides, improve, band, ms, ser, basket, liq, inv in itertools.product(
            ["mece"], ["both", "bid", "ask"], [0, 1], [(1, 15), (15, 85), (85, 99), (1, 99)], [2, 4],   # A5: MECE only
            ["all", "taker_only"], [False, True], [0, 5], [50, 25]):
        if basket and (sides != "bid" or improve or univ != "mece"):
            continue          # basket mode: bid-only, join-the-touch, MECE baskets only
        yield Config(universe=univ, sides=sides, improve=improve, band_lo=band[0], band_hi=band[1],
                     min_spread=ms, series=ser, basket=basket, min_trades_24h=liq, pos_limit=inv)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--months", nargs="+", default=TRAIN_MONTHS)
    ap.add_argument("--grid", action="store_true",
                    help="search on TRAIN months, then select on VALIDATION (shortlist only); refused on val/test months")
    ap.add_argument("--config", help="frozen config JSON for a test run")
    ap.add_argument("--out", default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--robust", action="store_true",
                    help="A10: re-select the base on ALL development months (2024-11..2025-07) by the "
                         "fixed robustness rule; refused on test months")
    ap.add_argument("--secondary", default=None,
                    help="A10: a second frozen config reported beside --config on the test run (not primary)")
    ap.add_argument("--signal", default=None,
                    help="A6.3: seed-averaged STGAT mid-move signal (export_mid_signal.py). With --config, "
                         "adds S4 (base + filter) and S5 (model-led) and reports S4 - base and S5 - base.")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.robust:
        if args.grid or args.config or args.signal:
            raise SystemExit("--robust runs alone")
        if args.months == TRAIN_MONTHS:
            args.months = DEV_MONTHS
        if max(args.months) >= TEST_MONTHS[0]:
            raise SystemExit("REFUSED: A10 re-selection uses development months only (<= 2025-07).")
    if args.signal and (args.grid or not args.config):
        raise SystemExit("--signal runs S4/S5 beside the frozen base: it needs --config and no --grid.")
    global SIGNAL_PATH
    SIGNAL_PATH = args.signal
    if args.grid and max(args.months) >= FIRST_VAL_MONTH:
        raise SystemExit("REFUSED: the search runs on TRAIN months only; validation sees only the "
                         "shortlist and test sees only the frozen winner (amendment A4).")

    if args.robust:
        cfgs = list(robust_grid_configs())
        res = run_many([(c, m, args.months) for c in cfgs for m in ("pess", "strict")], args.workers)
        rows = []
        for c in cfgs:
            pm = monthly_returns(c, "pess", args.months)
            rows.append({"cfg": c, "pess": res[(c, "pess")], "strict": res[(c, "strict")],
                         "pess_active_months": sum(1 for v in pm.values() if v == v),
                         "strict_monthly_ret": monthly_returns(c, "strict", args.months)})
        win, ok = robust_select(rows, len(args.months))
        print(f"\n=== A10 ROBUST RE-SELECTION on {args.months[0]}..{args.months[-1]} "
              f"({len(cfgs)} configs): {len(ok)} qualify ===")
        for r in ok[:10]:
            npos = sum(1 for v in r["strict_monthly_ret"].values() if v == v and v > 0)
            print(f"  {r['cfg'].name()}\n      PESS {fmt(r['pess'])}\n      STRICT {fmt(r['strict'])}"
                  f"  strict>0 in {npos}/{len(args.months)} months")
        if win is None:
            print("\nNo configuration qualifies: the A6 winner stays the primary base (A10).")
        elif args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(dataclasses.asdict(win["cfg"]), indent=2))
            print(f"\nA10 WINNER (frozen as the PRIMARY base for the single test run): {win['cfg'].name()}"
                  f"\nwritten to {args.out}")
    elif args.grid:
        # 1. search on TRAIN
        cfgs = list(grid_configs())
        res = run_many([(c, m, args.months) for c in cfgs for m in ("opt", "pess")], args.workers)
        rows = [(c, {"opt": res[(c, "opt")], "pess": res[(c, "pess")]}) for c in cfgs]
        ok = [(c, r) for c, r in rows if r["pess"]["fills"] >= 300 and r["pess"]["events"] >= 30]
        ok.sort(key=lambda cr: (cr[1]["pess"]["ret"], cr[1]["pess"]["fills"]), reverse=True)
        print(f"\n=== TRAIN {args.months[0]}..{args.months[-1]}: {len(ok)} of {len(rows)} configurations met the "
              f"minimum-activity rule; {sum(1 for _, r in ok if r['pess']['ret'] > 0)} positive pessimistic ===")
        for univ in ("mece", "liquid"):
            for c, r in [(c, r) for c, r in ok if c.universe == univ][:1]:
                print(f"  best on train, universe={univ}: {c.name()}\n      PESS {fmt(r['pess'])}\n      OPT  {fmt(r['opt'])}")
        shortlist = [c for c, _ in ok[:SHORTLIST_K]]
        print(f"\n  shortlist (top {len(shortlist)} by pessimistic train return):")
        for c, r in ok[:SHORTLIST_K]:
            print(f"    {c.name()}  train PESS {r['pess']['ret']:+.2f}%")
        # 2. select on VALIDATION (shortlist only)
        vres = run_many([(c, m, VAL_MONTHS) for c in shortlist for m in ("opt", "pess")], args.workers)
        vrows = [(c, {"opt": vres[(c, "opt")], "pess": vres[(c, "pess")]}) for c in shortlist]
        vok = [(c, r) for c, r in vrows if r["pess"]["fills"] >= 100 and r["pess"]["events"] >= 10]
        vok.sort(key=lambda cr: (cr[1]["pess"]["ret"], cr[1]["pess"]["fills"]), reverse=True)
        print(f"\n=== VALIDATION {VAL_MONTHS[0]}..{VAL_MONTHS[-1]} (shortlist only; pick best pessimistic, >=100 fills, >=10 events) ===")
        for c, r in vrows:
            print(f"  {c.name()}\n      PESS {fmt(r['pess'])}\n      OPT  {fmt(r['opt'])}")
        if vok and args.out:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(json.dumps(dataclasses.asdict(vok[0][0]), indent=2))
            print(f"\nSELECTED (frozen for the single test run): {vok[0][0].name()}\nwritten to {args.out}")
    else:
        cfgs = [("S1 (pre-registered reference)", Config())]
        base = None
        if args.config:
            base = Config(**json.loads(Path(args.config).read_text()))
            cfgs.insert(0, ("PRIMARY base (frozen)", base))
        if args.secondary:
            cfgs.insert(1, ("SECONDARY base (A6 winner)", Config(**json.loads(Path(args.secondary).read_text()))))
        if args.signal:
            cfgs += [("S4 (base + STGAT filter)", dataclasses.replace(base, stgat="s4")),
                     ("S5 (STGAT-led)", S5_CONFIG)]
        res = run_many([(c, m, args.months) for _, c in cfgs for m in ("opt", "pess", "strict")], args.workers)
        for label, cfg in cfgs:
            for m in ("opt", "pess", "strict"):
                print(f"{label:<30} {m.upper():<4} {fmt(res[(cfg, m)])}")
        if args.signal:
            print("\nA6.3 comparisons against the frozen base (event-resampled, same draw for both):")
            for label, cfg in cfgs[-2:]:
                for m in ("pess", "opt", "strict"):
                    ev_s, ev_b = event_totals(cfg, m, args.months), event_totals(base, m, args.months)
                    pt, lo, hi = paired_diff_ci(ev_s, ev_b)
                    print(f"  {label:<26} - base  {m.upper():<6} {pt:+7.2f}pp  CI95 [{lo:+7.2f}, {hi:+7.2f}]  "
                          f"(k={len(set(ev_s) | set(ev_b)):,} events)")
            print("\nA9 secondary (fills from quotes at signal hours only, H on the 2 h grid):")
            for label, cfg in cfgs[-2:]:
                for m in ("pess", "opt", "strict"):
                    ev_s = event_totals(cfg, m, args.months, signal_hours_only=True)
                    ev_b = event_totals(base, m, args.months, signal_hours_only=True)
                    pt, lo, hi = paired_diff_ci(ev_s, ev_b)
                    print(f"  {label:<26} - base  {m.upper():<6} {pt:+7.2f}pp  CI95 [{lo:+7.2f}, {hi:+7.2f}]  "
                          f"(k={len(set(ev_s) | set(ev_b)):,} events)")
    print("\nexit: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
