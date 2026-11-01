"""
model/quote_features.py

Amendment B1 of docs/planning/stgat-7-2-4-preregistration.md: quoted top of
book as model INPUTS (B1.1) and the next-hour quoted-mid move as an auxiliary
TARGET (B1.2).

WHY THIS IS ATTACHED AT LOAD TIME, NOT BUILT INTO THE CACHE. A cached month
already carries everything the join needs -- ``timestamps`` (window starts),
``node_ids`` (tickers) and the MECE spokes -- and the quotes are a separate,
small table (data/quotes/by_month/, ~1 MB per month). Attaching per chunk
means no month is rebuilt (a rebuild is ~20 min and ~7 GB RSS per month on
this machine) and cache_724/ stays byte-identical, so every earlier figure
read from it still reproduces.

LAYOUT. The block is inserted just BEFORE the node-type slot, so every
existing slot index (0-8, and time_to_close at 8) keeps its meaning and the
type indicator stays last, where TypeSpecificProjection routes on it.
    ticker:  q_bid q_ask q_mid q_spread q_print_minus_mid q_no_bid q_no_ask q_age_h q_has
    hub:     q_sum_mid_minus_1 q_sum_bid q_sum_ask q_share_quoted  0 0 0 0 0
Slots are shared across types with per-type meaning, as in stg/nodes/kalshi.py.

CAUSALITY. Snapshot t covers [ts, ts + WINDOW); its end is E_t = ts + WINDOW.
A candle stamped end_ts covers (end_ts - 1h, end_ts]. Inputs use the LATEST
candle with end_ts <= E_t, never a later one. The target uses the candles
ending exactly at E_t and E_t + 1h, and is never an input.

Prices are dollars in [0, 1] throughout (true_prices() divides slot 0 by 100).
One-sided books are bid == 0 or ask == 1 (verified on the fetched candles:
no nulls, never crossed).

    python stg_infra/model/quote_features.py --self-test
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

import numpy as np
import torch

QUOTE_TICKER_COLS = ("q_bid", "q_ask", "q_mid", "q_spread", "q_print_minus_mid",
                     "q_no_bid", "q_no_ask", "q_age_h", "q_has")
QUOTE_HUB_COLS = ("q_sum_mid_minus_1", "q_sum_bid", "q_sum_ask", "q_share_quoted")
N_QUOTE = len(QUOTE_TICKER_COLS)
AGE_CAP_H = 24.0
HOUR_NS = 3600 * 10**9
VOLUME_SLOT = 4       # window_volume (stg/nodes/kalshi.py)


def _ns(ts: datetime) -> int:
    return int(np.datetime64(ts, "ns").astype(np.int64))


def _shift_month(month: str, k: int) -> str:
    y, m = map(int, month.split("-"))
    m += k
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


class QuoteIndex:
    """ticker -> (end_ns sorted, bid, ask). One month's chunks need the
    previous month (latest candle at or before the first E_t) and the next
    one (the E_t + 1h target at a month's last snapshot), so
    ``for_month`` loads all three."""

    def __init__(self, table: Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]):
        self.table = table

    @classmethod
    def from_frame(cls, df) -> "QuoteIndex":
        import polars as pl
        df = (df.select("ticker", "end_ts", "bid_close", "ask_close")
                .drop_nulls()
                .with_columns(pl.col("end_ts").cast(pl.Datetime("ns")).cast(pl.Int64).alias("e"))
                .unique(["ticker", "e"], keep="last")
                .sort(["ticker", "e"]))
        table = {}
        for (tk,), g in df.group_by(["ticker"], maintain_order=True):
            table[tk] = (g["e"].to_numpy(), g["bid_close"].to_numpy().astype(np.float64),
                         g["ask_close"].to_numpy().astype(np.float64))
        return cls(table)

    @classmethod
    def for_month(cls, quotes_dir: Path, month: str) -> "QuoteIndex":
        import polars as pl
        files = [Path(quotes_dir) / f"quotes_{m}.parquet"
                 for m in (_shift_month(month, -1), month, _shift_month(month, 1))]
        files = [f for f in files if f.exists()]
        if not files:
            raise FileNotFoundError(f"no quote partitions for {month} under {quotes_dir}")
        return cls.from_frame(pl.concat([pl.read_parquet(f) for f in files]))

    def at_or_before(self, ticker: str, t_ns: np.ndarray) -> Optional[Tuple[np.ndarray, ...]]:
        """For each time: (idx or -1, bid, ask, end_ns) of the latest candle
        with end_ns <= t. None when the ticker has no candles at all."""
        rec = self.table.get(ticker)
        if rec is None:
            return None
        e, b, a = rec
        idx = np.searchsorted(e, t_ns, side="right") - 1
        ok = idx >= 0
        j = np.where(ok, idx, 0)
        return np.where(ok, idx, -1), b[j], a[j], e[j]

    def exact(self, ticker: str, t_ns: np.ndarray):
        """(found, bid, ask) of the candle ending exactly at each time."""
        rec = self.table.get(ticker)
        if rec is None:
            n = len(t_ns)
            return np.zeros(n, bool), np.zeros(n), np.zeros(n)
        e, b, a = rec
        idx = np.searchsorted(e, t_ns, side="left")
        j = np.minimum(idx, len(e) - 1)
        found = (idx < len(e)) & (e[j] == t_ns)
        return found, b[j], a[j]


def quote_block(ct: dict, qidx: QuoteIndex, window: timedelta):
    """(T, N, N_QUOTE) input block, (T, N) mid-move target and its mask, for
    one materialised chunk. Zero wherever the node is unobserved (mask False),
    as for every other input slot."""
    feats, mask = ct["features"], ct["mask"]
    T, N, _ = feats.shape
    node_ids = ct["node_ids"]
    is_hub = (feats[..., -1] == 1.0).any(dim=0).numpy()
    ends = np.array([_ns(ts + window) for ts in ct["timestamps"]], dtype=np.int64)
    nxt = ends + HOUR_NS
    last_print = (feats[..., 0] / 100.0).numpy()
    traded = (feats[..., VOLUME_SLOT] > 0).numpy()
    obs = mask.numpy()

    blk = np.zeros((T, N, N_QUOTE), dtype=np.float64)
    y = np.zeros((T, N), dtype=np.float64)
    ym = np.zeros((T, N), dtype=bool)
    for i in range(N):
        if is_hub[i]:
            continue
        tk = str(node_ids[i])
        r = qidx.at_or_before(tk, ends)
        if r is not None:
            idx, b, a, e = r
            has = idx >= 0
            mid = (b + a) / 2.0
            age = np.minimum((ends - e) / HOUR_NS, AGE_CAP_H)
            col = np.stack([b, a, mid, a - b,
                            np.where(traded[:, i], last_print[:, i] - mid, 0.0),
                            (b == 0.0).astype(float), (a == 1.0).astype(float),
                            age, np.ones(T)], axis=1)
            blk[:, i, :] = np.where(has[:, None], col, 0.0)
        f0, b0, a0 = qidx.exact(tk, ends)
        f1, b1, a1 = qidx.exact(tk, nxt)
        two0 = f0 & (b0 > 0.0) & (a0 < 1.0)
        two1 = f1 & (b1 > 0.0) & (a1 < 1.0)
        ok = two0 & two1 & obs[:, i]
        y[:, i] = np.where(ok, (b1 + a1) / 2.0 - (b0 + a0) / 2.0, 0.0)
        ym[:, i] = ok

    # Hubs: causal aggregates over the legs linked THIS snapshot.
    spokes = ct["adjacency_by_type"].get("mece_leg_to_basket")
    if spokes is not None:
        for t in range(T):
            ei = spokes[t].edge_index
            if ei.numel() == 0:
                continue
            legs, hubs = ei[0].numpy(), ei[1].numpy()
            q_has = blk[t, legs, 8]
            n_linked = np.bincount(hubs, minlength=N).astype(float)
            n_quoted = np.bincount(hubs, weights=q_has, minlength=N)
            s_mid = np.bincount(hubs, weights=blk[t, legs, 2] * q_has, minlength=N)
            s_bid = np.bincount(hubs, weights=blk[t, legs, 0] * q_has, minlength=N)
            s_ask = np.bincount(hubs, weights=blk[t, legs, 1] * q_has, minlength=N)
            for h in np.unique(hubs):
                if n_quoted[h] > 0:
                    blk[t, h, :4] = (s_mid[h] - 1.0, s_bid[h], s_ask[h], n_quoted[h] / n_linked[h])

    blk *= obs[..., None]
    return (torch.from_numpy(blk).to(feats.dtype), torch.from_numpy(y).to(feats.dtype),
            torch.from_numpy(ym))


def prev_move(ct: dict, qidx: QuoteIndex, window: timedelta) -> torch.Tensor:
    """(T, N) previous-hour quoted-mid move, mid(E_t) - mid(E_t - 1h), from
    candles ending exactly at those times and both two-sided; 0 otherwise.

    SCORING ONLY: the regressor of the one-parameter shrinkage oracle the
    mid-move head is compared against (y_hat = alpha * x, alpha fitted on the
    scored split). Uses nothing after E_t, but it is never a model input."""
    T, N, _ = ct["features"].shape
    ends = np.array([_ns(ts + window) for ts in ct["timestamps"]], dtype=np.int64)
    x = np.zeros((T, N), dtype=np.float64)
    for i, nid in enumerate(ct["node_ids"]):
        f0, b0, a0 = qidx.exact(str(nid), ends)
        if not f0.any():
            continue
        fp, bp, ap = qidx.exact(str(nid), ends - HOUR_NS)
        ok = f0 & (b0 > 0.0) & (a0 < 1.0) & fp & (bp > 0.0) & (ap < 1.0)
        x[:, i] = np.where(ok, (b0 + a0) / 2.0 - (bp + ap) / 2.0, 0.0)
    return torch.from_numpy(x).to(ct["features"].dtype)


def attach(ct: dict, qidx: QuoteIndex, window: timedelta, with_inputs: bool,
           with_prev: bool = False) -> dict:
    """Adds ``mid_target``/``mid_mask`` to a chunk and, when ``with_inputs``,
    inserts the quote block before the type slot. ``with_prev`` (scoring
    only) adds ``mid_prev`` for the shrinkage oracle. Returns a new dict."""
    blk, y, ym = quote_block(ct, qidx, window)
    out = dict(ct)
    if with_inputs:
        f = ct["features"]
        out["features"] = torch.cat([f[..., :-1], blk, f[..., -1:]], dim=-1)
    out["mid_target"], out["mid_mask"] = y, ym
    if with_prev:
        out["mid_prev"] = prev_move(ct, qidx, window)
    return out


class QuoteAttacher:
    """Wraps a MonthlyBundleStore's materialize_chunk. Holds one month's
    QuoteIndex at a time, matching the store's one-month residency."""

    def __init__(self, store, quotes_dir: Path, window: timedelta, with_inputs: bool,
                 with_prev: bool = False):
        self.store, self.quotes_dir = store, Path(quotes_dir)
        self.window, self.with_inputs, self.with_prev = window, with_inputs, with_prev
        self._month, self._qidx = None, None

    @property
    def feature_width(self) -> int:
        return self.store.feature_width + (N_QUOTE if self.with_inputs else 0)

    def materialize_chunk(self, chunk) -> dict:
        month = self.store.month_of(chunk)
        if month != self._month:
            self._qidx = QuoteIndex.for_month(self.quotes_dir, month)
            self._month = month
        return attach(self.store.materialize_chunk(chunk), self._qidx, self.window,
                      self.with_inputs, self.with_prev)


# ----------------------------------------------------------------- self-test

def self_test() -> int:
    import polars as pl

    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    W = timedelta(hours=2)
    ts0 = datetime(2025, 8, 1, 10)          # window [10:00, 12:00), E = 12:00
    E = ts0 + W

    def chunk(n_snap=1, vol=5.0, price=50.0):
        f = torch.zeros(n_snap, 3, 10)
        f[:, 0, 0], f[:, 0, VOLUME_SLOT] = price, vol    # ticker A
        f[:, 1, 0], f[:, 1, VOLUME_SLOT] = 30.0, 0.0     # ticker B, no trade
        f[:, 2, -1] = 1.0                                # hub H
        from types import SimpleNamespace
        spokes = [SimpleNamespace(edge_index=torch.tensor([[0, 1], [2, 2]])) for _ in range(n_snap)]
        return {"features": f, "mask": torch.ones(n_snap, 3, dtype=torch.bool),
                "timestamps": [ts0 + k * W for k in range(n_snap)],
                "node_ids": ["A", "B", "H"], "adjacency_by_type": {"mece_leg_to_basket": spokes}}

    def frame(rows):
        return pl.DataFrame(rows, schema=["ticker", "end_ts", "bid_close", "ask_close"], orient="row")

    planted = [("A", E - timedelta(hours=1), 0.40, 0.44),
               ("A", E, 0.45, 0.49),
               ("A", E + timedelta(hours=1), 0.60, 0.64)]

    print("B1.1 known-answer test (pre-registered):")
    blk, y, ym = quote_block(chunk(), QuoteIndex.from_frame(frame(planted)), W)
    a = blk[0, 0].double()
    check("uses the candle ending AT E_t (bid 0.45, ask 0.49)",
          abs(a[0] - 0.45) < 1e-6 and abs(a[1] - 0.49) < 1e-6)
    check("age 0h at E_t", abs(a[7]) < 1e-6)
    check("mid and spread", abs(a[2] - 0.47) < 1e-6 and abs(a[3] - 0.04) < 1e-6)
    check("print minus mid = 0.50 - 0.47", abs(a[4] - 0.03) < 1e-6)

    blk2, _, _ = quote_block(chunk(), QuoteIndex.from_frame(frame([planted[0], planted[2]])), W)
    a2 = blk2[0, 0].double()
    check("E_t candle removed -> uses E_t - 1h (bid 0.40)", abs(a2[0] - 0.40) < 1e-6)
    check("... with age 1h", abs(a2[7] - 1.0) < 1e-6)

    blk3, _, _ = quote_block(chunk(), QuoteIndex.from_frame(frame([planted[2]])), W)
    check("never uses E_t + 1h (only a future candle -> q_has 0, all zero)",
          float(blk3[0, 0].abs().sum()) == 0.0)

    print("B1.2 target:")
    check("y = mid(E+1h) - mid(E) = 0.62 - 0.47", bool(ym[0, 0]) and abs(float(y[0, 0]) - 0.15) < 1e-6)
    _, _, ym2 = quote_block(chunk(), QuoteIndex.from_frame(frame([planted[0], planted[2]])), W)
    check("masked without the exact E_t candle (no 'at or before' fallback)", not bool(ym2[0, 0]))
    one = [("A", E, 0.0, 0.49), ("A", E + timedelta(hours=1), 0.60, 0.64)]
    _, _, ym3 = quote_block(chunk(), QuoteIndex.from_frame(frame(one)), W)
    check("masked when a candle is one-sided (bid 0)", not bool(ym3[0, 0]))
    check("hub never gets a target", not bool(ym[0, 2]))

    print("one-sided flags, print side, age cap:")
    old = [("A", E, 0.0, 1.0), ("B", E - timedelta(hours=40), 0.20, 0.30)]
    blk4, _, _ = quote_block(chunk(), QuoteIndex.from_frame(frame(old)), W)
    check("q_no_bid and q_no_ask set", float(blk4[0, 0, 5]) == 1.0 and float(blk4[0, 0, 6]) == 1.0)
    check("age capped at 24h", abs(float(blk4[0, 1, 7]) - AGE_CAP_H) < 1e-6)
    check("print minus mid = 0 without a trade in the window", float(blk4[0, 1, 4]) == 0.0)

    print("hub aggregates:")
    both = planted[:2] + [("B", E, 0.50, 0.56)]
    blk5, _, _ = quote_block(chunk(), QuoteIndex.from_frame(frame(both)), W)
    h = blk5[0, 2].double()
    check("sum mid - 1 = 0.47 + 0.53 - 1", abs(h[0] - 0.0) < 1e-6)
    check("sum bid, sum ask", abs(h[1] - 0.95) < 1e-6 and abs(h[2] - 1.05) < 1e-6)
    check("share quoted 1.0", abs(h[3] - 1.0) < 1e-6)
    blk6, _, _ = quote_block(chunk(), QuoteIndex.from_frame(frame(planted[:2])), W)
    check("share quoted 0.5 when one leg has no candle", abs(float(blk6[0, 2, 3]) - 0.5) < 1e-6)

    print("masking and layout:")
    c = chunk()
    c["mask"][0, 0] = False
    blk7, _, ym7 = quote_block(c, QuoteIndex.from_frame(frame(planted)), W)
    check("unobserved position -> zero block, no target", float(blk7[0, 0].abs().sum()) == 0.0 and not bool(ym7[0, 0]))
    out = attach(chunk(), QuoteIndex.from_frame(frame(planted)), W, with_inputs=True)
    f = out["features"]
    check(f"width 10 -> {10 + N_QUOTE}, type slot still last",
          f.shape[-1] == 10 + N_QUOTE and float(f[0, 2, -1]) == 1.0 and float(f[0, 0, -1]) == 0.0)
    check("existing slots 0-8 unchanged", torch.equal(f[..., :9], chunk()["features"][..., :9]))
    out2 = attach(chunk(), QuoteIndex.from_frame(frame(planted)), W, with_inputs=False)
    check("with_inputs=False leaves features untouched, still adds the target",
          torch.equal(out2["features"], chunk()["features"]) and bool(out2["mid_mask"][0, 0]))

    print("second snapshot (window 12:00-14:00, E=14:00):")
    blk8, _, ym8 = quote_block(chunk(n_snap=2), QuoteIndex.from_frame(frame(planted)), W)
    check("latest candle <= 14:00 is 13:00 (age 1h)",
          abs(float(blk8[1, 0, 0]) - 0.60) < 1e-6 and abs(float(blk8[1, 0, 7]) - 1.0) < 1e-6)
    check("no target without candles at 14:00 and 15:00", not bool(ym8[1, 0]))

    print("previous-hour move (scoring only, shrinkage-oracle regressor):")
    prev = [("A", E - timedelta(hours=1), 0.40, 0.44), ("A", E, 0.45, 0.49)]
    x = prev_move(chunk(), QuoteIndex.from_frame(frame(prev)), W)
    check("x = mid(E) - mid(E-1h) = 0.47 - 0.42", abs(float(x[0, 0]) - 0.05) < 1e-6)
    x2 = prev_move(chunk(), QuoteIndex.from_frame(frame([prev[1]])), W)
    check("x = 0 without the E-1h candle", float(x2[0, 0]) == 0.0)
    x3 = prev_move(chunk(), QuoteIndex.from_frame(frame([("A", E - timedelta(hours=1), 0.0, 0.44), prev[1]])), W)
    check("x = 0 when the E-1h candle is one-sided", float(x3[0, 0]) == 0.0)
    x4 = prev_move(chunk(), QuoteIndex.from_frame(frame(planted)), W)
    check("x never reads E+1h (same as with the E+1h candle absent)",
          torch.equal(x4, prev_move(chunk(), QuoteIndex.from_frame(frame(planted[:2])), W)))
    out3 = attach(chunk(), QuoteIndex.from_frame(frame(planted)), W, with_inputs=True)
    check("training path (with_prev False) adds no mid_prev", "mid_prev" not in out3)

    print(f"\n{'ALL PASS' if fails == 0 else f'{fails} FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    print(__doc__)
