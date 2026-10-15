"""
paper_trader.py

LIVE FORWARD-TEST ENGINE (amendment L3 item 3; universe L4; arms L3/L6).

Settles each live hour's orders against Kalshi's real trade tape with simulate_maker's
own quoting, fill, fee, limit and settlement code. Nothing in the fill logic is
re-implemented: the producer's logged snapshot quotes, the trade tape and settlement
results are reshaped into simulate_maker's `legs` / `events`, and simulate() runs once
per arm with that arm's posting rule as `policy_scores` (positions carry across hours
per event, as in the backtest).

ORDER WINDOWS (L3 item 2). simulate() rests hour H's orders over (H, H+1h]. The window is
cut by removing each hour's trades up to the cut time before simulate() sees them:
  primary      cut = snap_ns          orders rest over (snap_ns, H+1h]
  sensitivity  cut = D_H (t_decided_ns; earlier hours snap_ns + secs)
An hour with D_H >= H+1h has no trades left, so no fills.

ARMS. One-level (keyed (ticker, H, side)): g, g2, rnd2, cand (L1/L3); wide3, liq (L3);
lin2 (L3), mlp2 (L6). Two-level (keyed (ticker, H, side, price), levels="both"): g2p,
rnd2p. g2_sel (L4) is g2's fills restricted to the selected categories. A score >
THRESHOLD_C posts the order (the producer's own rule).

CHECKS. In every hour the simulator must regenerate the candidates the producer logged
(one- and two-level); mismatches are counted and the run fails above MAX_MISMATCH.
Hourly and replay use this one engine; `--check-tape` refetches stored hours and compares
trade ids (L3: fills must agree exactly).

USAGE (from repo root; on a Lumid sandbox next to the producer):
    python stg_infra/paper_trader.py --self-test
    python stg_infra/paper_trader.py --fetch-tape [--since 20261011T15]   # missing complete hours
    python stg_infra/paper_trader.py --run [--since 20261011T15]          # engine -> runs/live/paper/
    python stg_infra/paper_trader.py --loop                               # hourly: tape, markets, run
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pickle
import sys
import time
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "examples"))

H_NS = 3_600_000_000_000
import os
LIVE = Path(os.environ.get("LIVE_DIR", _REPO / "runs/live"))   # the producer's live directory
PAPER = LIVE / "paper"
TAPE = PAPER / "tape"
L2_FIX = "20261011T15"
POOL = _REPO / "docs/planning/l4_candidate_pool.json"
# L7: g2_sel folds (quoting hours, UTC): (selection from, selection to, trades from, trades to)
FOLDS = (("20261011T15", "20261018T00", "20261018T00", "20261025T00"),
         ("20261018T00", "20261025T00", "20261025T00", "20261101T00"),
         ("20261025T00", "20261101T00", "20261101T00", "20261111T00"))
MIN_EVENTS = 20
ACTIVE_DAYS = 4          # L10: a ledger round recomputes events with a candidate in the last ACTIVE_DAYS days
ONE_ARMS = ("g", "g2", "rnd2", "cand", "wide3", "liq", "lin2", "mlp2", "g2w1", "g2w2")
PAIRS = (("g2", "rnd2"), ("g2p", "rnd2p"), ("g2", "g"), ("g2", "cand"), ("g2", "wide3"), ("g2", "liq"),
         ("g2", "lin2"), ("g2", "mlp2"), ("g2", "g2w1"), ("g2", "g2w2"), ("g2_sel", "g2"))   # first two: verdicts (§5)
TWO_ARMS = ("g2p", "rnd2p")
SELECTED_C, SENTINEL_C, THRESHOLD_C = 2.0, -100.0, 1.0
MAX_MISMATCH = 0.005
WINDOWS = ("primary", "sensitivity")
# pre-registration section 4: pessimistic (verdicts), optimistic and strict fills (bounds) on the primary window; L3 sensitivity: pessimistic
STREAMS = (("primary", "primary", "pess"), ("primary_opt", "primary", "opt"), ("primary_strict", "primary", "strict"),
           ("sensitivity", "sensitivity", "pess"))


def stamp_of(H: int) -> str:
    return dt.datetime.fromtimestamp(H / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H")


def ns_of(stamp: str) -> int:
    return int(dt.datetime.strptime(stamp, "%Y%m%dT%H").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9


def hour_of_trade(t):
    """Hour H whose window (H, H+1h] contains trade time t (ns); vectorised."""
    return ((np.asarray(t, np.int64) - 1) // H_NS) * H_NS


# ---------------------------------------------------------------- inputs

def load_scores(hours):
    """Logged candidates of the given hours: (one-level, two-level) polars frames."""
    import polars as pl
    one = [pl.read_parquet(LIVE / "scores" / f"one_{h}.parquet") for h in hours if (LIVE / "scores" / f"one_{h}.parquet").exists()]
    two = [pl.read_parquet(LIVE / "scores" / f"two_{h}.parquet") for h in hours if (LIVE / "scores" / f"two_{h}.parquet").exists()]
    fix = lambda d: d.with_columns(pl.col("dmid_24h").fill_null(float("nan")))
    return (fix(pl.concat(one, how="diagonal_relaxed")) if one else None,
            fix(pl.concat(two, how="diagonal_relaxed")) if two else None)


def cut_times(runs_lines):
    """{H_ns: (snap_ns, D_H)} from runs.jsonl lines; D_H = t_decided_ns, else snap_ns + secs (L3)."""
    out = {}
    for line in runs_lines:
        if not line.startswith("{"):
            continue
        d = json.loads(line)
        if "H" not in d or "events" not in d:
            continue
        H = ns_of(d["H"])
        snap = d.get("snap_ns")
        if snap is None:
            continue     # lines before 2026-10-13 lack snap_ns in runs.jsonl: taken from the scores files
        out[H] = (int(snap), int(d.get("t_decided_ns") or snap + d["secs"] * 1e9))
    return out


def cut_times_all(one, runs_lines):
    """Cut times for every scored hour: runs.jsonl where it has them, else snap_ns from the scores
    files and D_H = snap_ns + secs (L3: 'for earlier hours D_H = snap_ns + secs')."""
    import polars as pl
    secs = {}
    for line in runs_lines:
        if line.startswith("{"):
            d = json.loads(line)
            if "H" in d and "secs" in d:
                secs[ns_of(d["H"])] = float(d["secs"])
    out = cut_times(runs_lines)
    snaps = one.group_by("H_ns").agg(pl.col("snap_ns").first())
    for H, snap in zip(snaps["H_ns"].to_list(), snaps["snap_ns"].to_list()):
        if H not in out and H in secs:
            out[H] = (int(snap), int(snap + secs[H] * 1e9))
    return out


# ---------------------------------------------------------------- arms

def arm_scores(one, two, baselines=None):
    """{arm: policy_scores} from the logged candidates. One-level keys (ticker, H, side); two-level keys
    (ticker, H, side, price). Score > THRESHOLD_C posts."""
    import polars as pl
    k1 = list(zip(one["ticker"].to_list(), one["H_ns"].to_list(), [int(x) for x in one["side"].to_list()]))
    sel = lambda m: [SELECTED_C if x else SENTINEL_C for x in m]
    med = one.group_by("H_ns").agg(pl.col("trades_24h").median().alias("m"))
    liq = one.join(med, on="H_ns", how="left").select(pl.col("trades_24h") >= pl.col("m"))
    out = {"g": dict(zip(k1, one["pred_g"].to_list())), "g2": dict(zip(k1, one["pred_g2"].to_list())),
           "rnd2": dict(zip(k1, one["rnd2_c"].to_list())), "cand": dict(zip(k1, [SELECTED_C] * len(k1))),
           "wide3": dict(zip(k1, sel((one["spread"] >= 3).to_list()))),
           "liq": dict(zip(k1, sel(liq.to_series().to_list())))}
    if baselines:
        import train_baselines as tb
        rows = one.select(tb.numeric_feats() + ["cat"]).to_dicts()
        for arm, blob in baselines.items():
            if arm in ("g2w1", "g2w2"):          # L8: the A13 windows not selected, G2 design (retrain_g2.matrix)
                import retrain_g2 as rg
                out[arm] = dict(zip(k1, blob["model"].predict(rg.matrix("G2", rows, blob["cats"])).tolist()))
            else:
                out[arm] = dict(zip(k1, tb.predict(blob, rows).tolist()))
    if two is not None and len(two):
        k2 = list(zip(two["ticker"].to_list(), two["H_ns"].to_list(), [int(x) for x in two["side"].to_list()],
                      [int(x) for x in two["price"].to_list()]))
        out["g2p"] = dict(zip(k2, two["pred_g2p"].to_list()))
        out["rnd2p"] = dict(zip(k2, sel(two["rnd2p_pick"].to_list())))
    return out


# ---------------------------------------------------------------- legs

def build_legs(one, two, tape, markets, fee_types):
    """simulate_maker legs/events/charged from logged quotes, the tape {ticker: (t, price_c, count, side)}
    and markets {ticker: {"result", "close_ns"}}. Only legs that were candidates appear; quoting is per leg."""
    import polars as pl
    import retrain_g2 as rg
    q = pl.concat([d.select("ticker", "event", "H_ns", "bid_c", "ask_c") for d in (one, two) if d is not None])
    q = q.unique(["ticker", "H_ns"]).sort(["ticker", "H_ns"])
    legs, events = {}, {}
    for (tk,), g in q.group_by(["ticker"], maintain_order=True):
        ev = g["event"][0]
        m = markets.get(tk, {})
        tt, tp, tc, ts = tape.get(tk, (np.empty(0, np.int64), np.empty(0), np.empty(0), np.empty(0)))
        legs[tk] = {"event": ev, "series": ev.split("-")[0], "yes": m.get("result") == "yes",
                    "close": m.get("close_ns"), "e": g["H_ns"].to_numpy().astype(np.int64),
                    "bid": g["bid_c"].to_numpy() / 100.0, "ask": g["ask_c"].to_numpy() / 100.0,
                    "tt": tt, "tp": tp, "tc": tc, "ts": ts}
        events.setdefault(ev, []).append(tk)
    events = {e: sorted(t) for e, t in events.items()}      # fixed leg order (L3 item 3)
    return legs, events, rg.fee_charged(fee_types)


def apply_window(legs, cuts, which):
    """Copy of legs with each hour's trades at or before that hour's cut removed (L3 order windows)."""
    idx = 0 if which == "primary" else 1
    hs = np.array(sorted(cuts), np.int64)
    cv = np.array([cuts[h][idx] for h in hs], np.int64)
    out = {}
    for tk, L in legs.items():
        t = L["tt"]
        if len(t) == 0 or len(hs) == 0:
            out[tk] = L; continue
        H = hour_of_trade(t)
        j = np.searchsorted(hs, H)
        known = (j < len(hs)) & (hs[np.minimum(j, len(hs) - 1)] == H)
        cut = np.where(known, cv[np.minimum(j, len(hs) - 1)], np.iinfo(np.int64).min)
        keep = t > cut
        out[tk] = {**L, "tt": t[keep], "tp": L["tp"][keep], "tc": L["tc"][keep], "ts": L["ts"][keep]}
    return out


def regenerated(legs, events, charged, months, levels=""):
    """Candidates the simulator generates from these legs: {(ticker, H, side, price)}."""
    import maker_policy as mp
    import simulate_maker as s
    rec = []
    s.simulate(s.Config(**{**mp.BROAD, **({"levels": levels} if levels else {})}), "pess", legs, events, charged,
               months, record=rec)
    return {(tk, int(H), int(sd), int(pr)) for ev, tk, H, sd, pr, b, a in rec}


def run_arms(legs, events, charged, months, scores, arms, model="pess"):
    """{arm: fills} with simulate_maker.simulate (fill model `model`: pess | opt | strict), BROAD config, the arm's scores."""
    import maker_policy as mp
    import simulate_maker as s
    out = {}
    for arm in arms:
        if arm not in scores:
            continue
        lv = {"levels": "both"} if arm in TWO_ARMS else {}
        cfg = s.Config(**{**mp.BROAD, **lv, "policy": "live", "policy_t": THRESHOLD_C})
        out[arm] = s.simulate(cfg, model, legs, events, charged, months, policy_scores=scores[arm])
    return out


# ---------------------------------------------------------------- universes and summaries

def universes(pool, l1_tickers):
    """{name: predicate(event, ticker, series, category)}."""
    ps = {x["series"] for x in pool["series"]}
    weather = lambda se: se.startswith(("KXHIGH", "KXLOW"))
    from fetch_kalshi_api_months import SERIES_A13
    a13 = set(SERIES_A13)
    base = lambda se: se in ps or weather(se)             # L11: weather re-included in the primary universe
    return {"primary_L4": lambda tk, se, cat: base(se),
            "non_weather": lambda tk, se, cat: se in ps,           # the L4 pool as frozen (descriptive)
            "weather": lambda tk, se, cat: weather(se),            # descriptive (L11)
            "new_series": lambda tk, se, cat: (se not in ps) and not weather(se),
            "L1": lambda tk, se, cat: tk in l1_tickers and not weather(se),
            "train23": lambda tk, se, cat: base(se) and se in a13,
            "other": lambda tk, se, cat: base(se) and se not in a13}


def settled_mask(fills, legs, events):
    """True for fills in events whose every leg has a yes/no result (scored); others are reported apart."""
    done = {ev: all(legs[t]["_settled"] for t in tks) for ev, tks in events.items()}
    return [done[f[0]] for f in fills]


def by_cluster(fills, key):
    """{cluster: (net_c, capital_c)}; key = event (primary CIs) or UTC day of the order hour (L3 item 5)."""
    out = {}
    for f in fills:
        k = key(f)
        a = out.get(k, (0.0, 0.0))
        out[k] = (a[0] + float(f[6]), a[1] + float(f[7]))
    return out


DAY = lambda f: int(f[9]) // (24 * H_NS)
EVENT = lambda f: f[0]


def boot_ret(cl, n=2000, seed=0):
    """Bootstrap draws of net return (%) over clusters; the cluster_ci resampling of simulate_maker."""
    v = np.array(list(cl.values()), float).reshape(-1, 2)
    if len(v) < 2 or v[:, 1].sum() <= 0:
        return None
    idx = np.random.default_rng(seed).integers(0, len(v), (n, len(v)))
    return v[idx, 0].sum(1) / np.maximum(v[idx, 1].sum(1), 1e-9) * 100


def verdict_stats(fills):
    """Return with two-sided 95% CI and the L8 one-sided 95% lower bound, by event (primary) and by day."""
    out = {}
    for name, key in (("event", EVENT), ("day", DAY)):
        cl = by_cluster(fills, key)
        d = boot_ret(cl)
        cap = sum(c for _, c in cl.values())
        out[name] = {"ret": 100 * sum(n for n, _ in cl.values()) / cap if cap else float("nan"),
                     "clusters": len(cl),
                     "lo95": float(np.percentile(d, 2.5)) if d is not None else float("nan"),
                     "hi95": float(np.percentile(d, 97.5)) if d is not None else float("nan"),
                     "lo_one_sided": float(np.percentile(d, 5.0)) if d is not None else float("nan")}
    return out


def paired_stats(fa, fb, n=2000, seed=0):
    """ret(A) - ret(B) over the union of clusters (same draw for both), by event and by day; adds the L8
    one-sided 95% lower bound. Mirrors simulate_maker.paired_diff_ci."""
    out = {}
    for name, key in (("event", EVENT), ("day", DAY)):
        A, B = by_cluster(fa, key), by_cluster(fb, key)
        ks = sorted(set(A) | set(B), key=str)
        if len(ks) < 2:
            out[name] = {"diff": float("nan"), "lo95": float("nan"), "hi95": float("nan"), "lo_one_sided": float("nan")}
            continue
        a = np.array([A.get(k, (0.0, 0.0)) for k in ks]); b = np.array([B.get(k, (0.0, 0.0)) for k in ks])
        r = lambda x: x[..., 0].sum(-1) / np.maximum(x[..., 1].sum(-1), 1e-9) * 100
        idx = np.random.default_rng(seed).integers(0, len(ks), (n, len(ks)))
        d = r(a[idx]) - r(b[idx])
        out[name] = {"diff": float(r(a) - r(b)), "lo95": float(np.percentile(d, 2.5)),
                     "hi95": float(np.percentile(d, 97.5)), "lo_one_sided": float(np.percentile(d, 5.0))}
    return out


def summarise_by(fills, key):
    import simulate_maker as s
    groups = {}
    for f in fills:
        groups.setdefault(key(f), []).append(f)
    return {g: s.summarise(v) for g, v in sorted(groups.items())}


def event_settled_at(events, markets):
    """{event: time all its legs were settled (ns)}, None while any leg is unsettled."""
    out = {}
    for ev, tks in events.items():
        ts = [markets.get(t, {}).get("settled_ns") for t in tks]
        ok = all(markets.get(t, {}).get("result") in ("yes", "no") for t in tks) and all(x is not None for x in ts)
        out[ev] = max(ts) if ok else None
    return out


def settled_at_all(markets, fills=None):
    """{event: time all its known legs settled}: events from the markets cache (or from `fills`), so events no
    longer recomputed still count as settled."""
    legs_of = {}
    for tk, m in markets.items():
        ev = tk.rsplit("-", 1)[0]
        legs_of.setdefault(ev, []).append(tk)
    if fills is not None:
        want = {f[0] for f in fills}
        legs_of = {e: t for e, t in legs_of.items() if e in want}
    return event_settled_at(legs_of, markets)


def g2_archive_update(g2_fills, markets):
    """L10: g2's fills (all hours) kept in PAPER/g2_archive.json, so the L7 walk-forward selection sees past weeks
    when a ledger round recomputes only active events. Returns the archive as fill tuples valued at settlement."""
    import paper_ledger as pl_
    p = PAPER / "g2_archive.json"
    arch = {tuple(k) for k in json.loads(p.read_text())} if p.exists() else set()
    arch |= {pl_.fill_key(f) for f in g2_fills}
    p.write_text(json.dumps(sorted(arch)))
    return [pl_.as_fill(k, markets.get(k[1], {}).get("result")) for k in arch]


def walk_forward_selection(g2_fills, settled_at, cat_f, in_primary):
    """L7: per fold, g2's fills in the selection window (primary universe), events settled by the window's
    end only; a category is selected iff net return > 0 and >= MIN_EVENTS events with fills."""
    import simulate_maker as s
    out = []
    for sel_lo, sel_hi, tr_lo, tr_hi in FOLDS:
        lo, hi = ns_of(sel_lo), ns_of(sel_hi)
        sub = [f for f in g2_fills if lo <= int(f[9]) < hi and in_primary(f)
               and settled_at.get(f[0]) is not None and settled_at[f[0]] <= hi]
        table = {c: s.summarise(v) for c, v in sorted(_group(sub, cat_f).items())}
        sel = sorted(c for c, r in table.items() if r["events"] >= MIN_EVENTS and r["ret"] > 0)
        out.append({"selection": [sel_lo, sel_hi], "trades": [tr_lo, tr_hi], "selected": sel,
                    "table": table})
    return out


def g2_sel_fills(g2_fills, folds, cat_f, in_primary):
    """g2's fills in each fold's trading week, in that fold's selected categories (L7)."""
    out = []
    for fd in folds:
        lo, hi, sel = ns_of(fd["trades"][0]), ns_of(fd["trades"][1]), set(fd["selected"])
        out += [f for f in g2_fills if lo <= int(f[9]) < hi and in_primary(f) and cat_f(f) in sel]
    return out


def _group(fills, key):
    g = {}
    for f in fills:
        g.setdefault(key(f), []).append(f)
    return g


# ---------------------------------------------------------------- Kalshi I/O

def producer_quiet(lines, now_utc) -> bool:
    """L7 item 4: Kalshi calls only after the producer logged the current hour and before minute 58."""
    stamp = now_utc.strftime("%Y%m%dT%H")
    return now_utc.minute < 58 and any(f'"H": "{stamp}"' in ln and '"events"' in ln for ln in lines[-30:])


def quiet_kalshi(rps):
    """Kalshi client that waits for the producer's quiet minutes before every request."""
    import live_signal_producer as lp

    class Q(lp.Kalshi):
        _ok_until = 0.0

        def get(self, path, **params):
            while time.time() > self._ok_until:
                runs = LIVE / "runs.jsonl"
                lines = runs.read_text().splitlines() if runs.exists() else []
                if producer_quiet(lines, dt.datetime.now(dt.timezone.utc)):
                    self._ok_until = time.time() + 30
                    break
                time.sleep(30)
            return super().get(path, **params)
    return Q(rps=rps)


def fetch_tape_hour(k, H, tickers):
    """Every Kalshi trade in (H, H+1h] on `tickers`, from the platform-wide trades feed."""
    import polars as pl
    import smoke_test_2026 as st
    rows = []
    for tr in k.pages("markets/trades", "trades", min_ts=H // 10**9, max_ts=(H + H_NS) // 10**9 + 1, limit=1000):
        if tr["ticker"] in tickers:
            rows.append(tr)
    # every column from ONE list (2026-10-15 fix): trade_arrays re-sorts by (t, price, count, side) while ids and
    # tickers were sorted by t alone, so trades sharing a timestamp could be paired with another trade's market
    df = tape_frame([(tr["ticker"], tr["trade_id"], st.ts_ns(tr["created_time"]),
                      round(float(tr.get("yes_price_dollars", tr.get("yes_price", 0) / 100)) * 100, 6),
                      float(tr.get("count_fp", tr.get("count", 0))), 1 if tr["taker_side"] == "yes" else -1)
                     for tr in rows])
    return df.filter((pl.col("t") > H) & (pl.col("t") <= H + H_NS))


TAPE_ORDER = ["ticker", "t", "price_c", "count", "side", "trade_id"]   # ties as the backtests (trade_arrays), then id


def tape_frame(rows):
    """Tape DataFrame from (ticker, trade_id, t, price_c, count, side) rows, in TAPE_ORDER."""
    import polars as pl
    cols = list(zip(*rows)) if rows else [[]] * 6
    return pl.DataFrame({"ticker": list(cols[0]), "trade_id": list(cols[1]), "t": pl.Series(list(cols[2]), dtype=pl.Int64),
                         "price_c": pl.Series(list(cols[3]), dtype=pl.Float64), "count": pl.Series(list(cols[4]), dtype=pl.Float64),
                         "side": pl.Series(list(cols[5]), dtype=pl.Int64)}).select(
        ["ticker", "t", "price_c", "count", "side", "trade_id"]).sort(TAPE_ORDER)


def load_tape(hours):
    import polars as pl
    fs = [TAPE / f"trades_{h}.parquet" for h in hours if (TAPE / f"trades_{h}.parquet").exists()]
    if not fs:
        return {}, []
    d = pl.concat([pl.read_parquet(f) for f in fs]).unique("trade_id", keep="first", maintain_order=True).sort(TAPE_ORDER)
    out = {}
    for (tk,), g in d.group_by(["ticker"], maintain_order=True):
        out[tk] = (g["t"].to_numpy(), g["price_c"].to_numpy(), g["count"].to_numpy(), g["side"].to_numpy())
    return out, [f.stem.split("_")[1] for f in fs]


def refresh_markets(k, events, cache):
    """Settlement result and close time per ticker, for events not yet final in `cache`."""
    import smoke_test_2026 as st
    for ev in sorted(events):
        tks = events[ev]
        if all(cache.get(t, {}).get("result") in ("yes", "no") for t in tks):
            continue
        for m in k.pages("markets", "markets", event_ticker=ev, limit=1000):
            cache[m["ticker"]] = {"result": m.get("result") or "", "status": m.get("status"),
                                  "close_ns": st.ts_ns(m["close_time"]) if m.get("close_time") else None,
                                  "settled_ns": st.ts_ns(m["settlement_ts"]) if m.get("settlement_ts") else
                                  (st.ts_ns(m["close_time"]) if m.get("close_time") and m.get("result") in ("yes", "no") else None)}
    return cache


# ---------------------------------------------------------------- run

def scored_hours(since):
    hs = sorted(p.stem.split("_")[1] for p in (LIVE / "scores").glob("one_*.parquet"))
    return [h for h in hs if h >= since]


def complete(h, now_ns):
    return ns_of(h) + H_NS + 5 * 60 * 10**9 <= now_ns


def cmd_fetch_tape(since, rps):
    import polars as pl
    TAPE.mkdir(parents=True, exist_ok=True)
    k = quiet_kalshi(rps)
    for h in scored_hours(since):
        p = TAPE / f"trades_{h}.parquet"
        if p.exists() or not complete(h, time.time_ns()):
            continue
        tks = set()
        for f in (LIVE / "scores" / f"one_{h}.parquet", LIVE / "scores" / f"two_{h}.parquet"):
            if f.exists():
                tks |= set(pl.read_parquet(f, columns=["ticker"])["ticker"].to_list())
        df = fetch_tape_hour(k, ns_of(h), tks)
        df.write_parquet(p.with_suffix(".tmp")); p.with_suffix(".tmp").replace(p)
        print(json.dumps({"tape": h, "trades": len(df), "tickers": len(tks), "api_calls": k.calls}), flush=True)


def cmd_run(since, rps, write=True, check_only=False, ledger=False, pat=None, ledger_dir=None, ots=False):
    import live_signal_producer as lp
    import simulate_maker as s
    import train_baselines as tb
    hours = [h for h in scored_hours(since) if (TAPE / f"trades_{h}.parquet").exists()]
    if not hours:
        print("no hours with tape yet"); return None
    one, two = load_scores(hours)
    active = None
    if ledger and (Path(ledger_dir) if ledger_dir else PAPER / "ledger").joinpath("state.json").exists():
        import polars as pl
        lo = ns_of(hours[-1]) - ACTIVE_DAYS * 24 * H_NS
        active = set(one.filter(pl.col("H_ns") >= lo)["event"].to_list())
        if two is not None:
            active |= set(two.filter(pl.col("H_ns") >= lo)["event"].to_list())
        one = one.filter(pl.col("event").is_in(list(active)))
        two = two.filter(pl.col("event").is_in(list(active))) if two is not None else None
        print(json.dumps({"active_events": len(active)}), flush=True)
    runs = (LIVE / "runs.jsonl").read_text().splitlines() if (LIVE / "runs.jsonl").exists() else []
    cuts = cut_times_all(one, runs)
    tape, _ = load_tape(hours)
    PAPER.mkdir(parents=True, exist_ok=True)
    mpath = PAPER / "markets.pkl"
    markets = pickle.loads(mpath.read_bytes()) if mpath.exists() else {}
    k = quiet_kalshi(rps)
    evs = {}
    for d in (one, two):
        if d is not None:
            for ev, tk in zip(d["event"].to_list(), d["ticker"].to_list()):
                evs.setdefault(ev, set()).add(tk)
    markets = refresh_markets(k, {e: sorted(t) for e, t in evs.items()}, markets)
    mpath.write_bytes(pickle.dumps(markets))
    sp = LIVE / "state" / "series.pkl"
    fee_types = {se: c.get("fee_type") for se, c in (pickle.loads(sp.read_bytes()) if sp.exists() else {}).items()}
    legs, events, charged = build_legs(one, two, tape, markets, fee_types)
    for tk, L in legs.items():
        L["_settled"] = markets.get(tk, {}).get("result") in ("yes", "no")
    months = sorted({s.month_of(int(h)) for h in one["H_ns"].unique().to_list()})

    # check: the simulator regenerates the logged candidates
    logged1 = set(zip(one["ticker"].to_list(), one["H_ns"].to_list(), [int(x) for x in one["side"].to_list()],
                      [int(x) for x in one["price"].to_list()]))
    gen1 = regenerated(legs, events, charged, months)
    mm1 = len(logged1 ^ gen1) / max(1, len(logged1))
    chk = {"one_logged": len(logged1), "one_regenerated": len(gen1), "one_mismatch_share": round(mm1, 5)}
    if two is not None:
        logged2 = set(zip(two["ticker"].to_list(), two["H_ns"].to_list(), [int(x) for x in two["side"].to_list()],
                          [int(x) for x in two["price"].to_list()]))
        gen2 = regenerated(legs, events, charged, months, "both")
        chk.update({"two_logged": len(logged2), "two_regenerated": len(gen2),
                    "two_mismatch_share": round(len(logged2 ^ gen2) / max(1, len(logged2)), 5)})
    print(json.dumps({"candidate_check": chk}), flush=True)
    if max(chk.get("one_mismatch_share", 0), chk.get("two_mismatch_share", 0)) > MAX_MISMATCH:
        raise SystemExit(f"candidate regeneration mismatch above {MAX_MISMATCH:.1%}: {chk}")
    if check_only:     # no fills, no P&L: usable before the L4 selection is committed
        return {"check": chk}

    import retrain_g2 as rg
    paths = {"lin2": tb.model_path("lin2"), "mlp2": tb.model_path("mlp2"),
             "g2w1": rg.model_path("W1", "G2"), "g2w2": rg.model_path("W2", "G2")}
    missing = [a for a, pth in paths.items() if not pth.exists()]
    if missing:
        raise SystemExit(f"missing model files for arms {missing}: every pre-registered arm must run (copy them first)")
    base = {a: pickle.loads(pth.read_bytes()) for a, pth in paths.items()}
    scores = arm_scores(one, two, base)
    pool = json.loads(POOL.read_text())
    cat_of = {x["series"]: x["cat"] for x in pool["series"]}
    for se, c in zip([e.split("-")[0] for e in one["event"].to_list()], one["cat"].to_list()):
        cat_of.setdefault(se, c)
    l1 = set()
    for f in (LIVE / "payloads").glob("sent_*.json"):
        l1 |= {r["instrument_id"] for r in json.loads(f.read_text())}
    U = universes(pool, l1)
    cat_f = lambda f: cat_of.get(legs[f[1]]["series"], "?")
    in_primary = lambda f: U["primary_L4"](f[1], legs[f[1]]["series"], cat_f(f))
    cat_f_any = lambda f: cat_of.get(str(f[0]).split("-")[0], "?")             # archive fills may be outside `legs`
    in_primary_any = lambda f: U["primary_L4"](f[1], str(f[0]).split("-")[0], cat_f_any(f))
    settled_at = event_settled_at(events, markets)
    result = {"hours": [hours[0], hours[-1], len(hours)], "check": chk, "tape_hours": len(hours), "windows": {}}
    folds = None
    ledger_fills = {}
    for w, base_w, model in STREAMS:     # primary pessimistic first: the L7 selection uses its g2 fills
        Lw = apply_window(legs, cuts, base_w)
        fills = run_arms(Lw, events, charged, months, scores, ONE_ARMS + TWO_ARMS, model)
        if folds is None:
            sel_src = g2_archive_update(fills["g2"], markets) if ledger else fills["g2"]
            folds = walk_forward_selection(sel_src, settled_at_all(markets, sel_src) if ledger else settled_at, cat_f_any, in_primary_any)
            result["g2_sel_folds"] = folds
        fills["g2_sel"] = g2_sel_fills(fills["g2"], folds, cat_f, in_primary)
        ledger_fills[w] = {a: [f for f in fl if in_primary(f)] for a, fl in fills.items()}   # L10: verdict universe
        res = {}
        for arm, fl in fills.items():
            mask = settled_mask(fl, Lw, events)
            done = [f for f, m in zip(fl, mask) if m]
            open_ = [f for f, m in zip(fl, mask) if not m]
            for un, pred in U.items():
                inu = lambda f: pred(f[1], legs[f[1]]["series"], cat_of.get(legs[f[1]]["series"], "?"))
                sub = [f for f in done if inu(f)]
                res.setdefault(arm, {})[un] = {
                    "all": s.summarise(sub), "verdict_stats": verdict_stats(sub),
                    "unsettled_fills": sum(1 for f in open_ if inu(f)),
                    "by_category": summarise_by(sub, lambda f: cat_of.get(legs[f[1]]["series"], "?"))}
                res[arm][un]["_fills"] = sub
            if write:
                import polars as pl
                pl.DataFrame([{"event": f[0], "ticker": f[1], "side": int(f[2]), "price": int(f[3]), "qty": int(f[4]),
                               "fee_c": float(f[5]), "net_c": float(f[6]), "capital_c": float(f[7]),
                               "markout_c": float(f[8]), "H_ns": int(f[9]), "settled": bool(m)}
                              for f, m in zip(fl, mask)] or [{"event": ""}]).write_parquet(PAPER / f"fills_{w}_{arm}.parquet")
        pairs = {}
        for a_, b_ in PAIRS:
            if a_ in res and b_ in res:
                pairs[f"{a_}-{b_}"] = {un: paired_stats(res[a_][un]["_fills"], res[b_][un]["_fills"])
                                       for un in res[a_] if un in res[b_]}
        for arm in res:
            for un in res[arm]:
                res[arm][un].pop("_fills", None)
        res["_paired"] = pairs
        result["windows"][w] = res
    if write:
        (PAPER / "summary.json").write_text(json.dumps(result, indent=1, default=float))
    if ledger:
        result["ledger"] = ledger_round(ledger_fills, ns_of(hours[-1]), events, markets, one, two, pat, ledger_dir, ots)
    return result


def ledger_round(ledger_fills, complete_H, events, markets, one, two, pat, ledger_dir=None, ots=False):
    """L10: append this round's ledger entries (paper_ledger) and post the newest to Research Fleet."""
    import paper_ledger as pl_
    import polars as pl
    settled_at = event_settled_at(events, markets)
    settled = {ev for ev, t in settled_at.items() if t is not None}
    q = pl.concat([d.select("ticker", "H_ns", "bid_c", "ask_c") for d in (one, two) if d is not None])
    last = q.sort("H_ns").group_by("ticker").agg(pl.col("bid_c").last(), pl.col("ask_c").last())
    mids = {tk: (b + a) / 2 for tk, b, a in zip(last["ticker"].to_list(), last["bid_c"].to_list(), last["ask_c"].to_list())}

    def verdict(live, settled_now):
        w = live.get("primary", {})
        g2 = [f for f in w.get("g2", []) if f[0] in settled_now]
        rnd = [f for f in w.get("rnd2", []) if f[0] in settled_now]
        vs, ps = verdict_stats(g2), paired_stats(g2, rnd)
        return {"g2_return_settled_pct": vs["event"]["ret"], "g2_lo_one_sided": vs["event"]["lo_one_sided"],
                "g2_lo95": vs["event"]["lo95"], "g2_hi95": vs["event"]["hi95"], "g2_events": vs["event"]["clusters"],
                "g2_minus_rnd2": ps["event"]["diff"], "g2_minus_rnd2_lo_one_sided": ps["event"]["lo_one_sided"],
                "day_cluster": {"g2_lo_one_sided": vs["day"]["lo_one_sided"],
                                "g2_minus_rnd2_lo_one_sided": ps["day"]["lo_one_sided"]}}
    results = {tk: m.get("result") for tk, m in markets.items()}
    settled = settled | {ev for ev, t in settled_at_all(markets, None).items() if t is not None}
    written = pl_.round_update(Path(ledger_dir) if ledger_dir else PAPER / "ledger", ledger_fills, complete_H, settled, mids,
                               stamp_of, verdict, results=results, events=set(events))
    jobs = []
    if written and pat:
        jobs.append(pl_.post_fleet(written[-1], pat))
    stamp = None
    if written and ots:                  # L14: independent public timestamp of the ledger head
        e = written[-1]
        stamp = pl_.ots_stamp({"H": e["H"], "entry_hash": e["hash"], "prev_hash": e["prev_hash"]},
                              (Path(ledger_dir) if ledger_dir else PAPER / "ledger") / "stamps" / f"ledger_{e['H']}.json")
    info = {"entries_written": [e["H"] for e in written], "fleet_job": jobs[-1] if jobs else None, "ots": stamp,
            "verification_issues": written[0]["verification"] if written else []}
    print(json.dumps({"ledger": info}), flush=True)
    return info


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    import polars as pl
    import simulate_maker as s
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    H0 = ns_of("20261012T10")
    check("stamp/ns round trip", stamp_of(ns_of("20261012T10")) == "20261012T10")
    # 2026-10-15 fixes: tape rows stay aligned under shared timestamps; order is the same whatever the input order
    import random
    T = H0 + 600 * 10**9
    rows = [("A", "a1", T, 7.0, 11.0, 1), ("B", "b1", T, 40.0, 3.0, -1), ("A", "a2", T, 5.0, 1.0, 1),
            ("A", "a3", T, 6.0, 1.0, 1), ("B", "b0", T - 1, 41.0, 2.0, 1)]
    fr = tape_frame(rows)
    kept = {(tk, i): (p_, c_) for tk, i, p_, c_ in zip(fr["ticker"], fr["trade_id"], fr["price_c"], fr["count"])}
    check("tape: every trade keeps its own market, price and size when timestamps are shared",
          kept == {(r[0], r[1]): (r[3], r[4]) for r in rows})
    orders = set()
    for seed in range(20):
        rr = rows[:]; random.Random(seed).shuffle(rr)
        orders.add(tuple(tape_frame(rr)["trade_id"].to_list()))
    check(f"tape: one order for 20 shuffles of tied trades ({orders})", len(orders) == 1)
    check("tape: ties as the backtests (time, then price): A's trades at T in price order 5, 6, 7",
          fr.filter(pl.col("ticker") == "A")["price_c"].to_list() == [5.0, 6.0, 7.0])
    t = np.array([H0 + 1, H0 + H_NS, H0 + H_NS + 1], np.int64)
    check("trade hour: (H, H+1h] belongs to H", list(hour_of_trade(t)) == [H0, H0, H0 + H_NS])

    # planted world: one event, two legs, two hours
    mk = lambda tk, side, price, H, bid, ask, sp=4, tr=5, g=3.0, g2=3.0, rnd=SELECTED_C: {
        "side": float(side), "price": float(price), "rel_price": 0.0, "spread": float(sp), "mid": 50.0,
        "trades_24h": tr, "dmid_24h": float("nan"), "n_legs": 2, "n_quoted": 2, "basket_sum": 100.0,
        "second_mid": 50.0, "hour_utc": 10, "charged": 0.0, "cat": "Sports", "event": "KXT-E1", "ticker": tk,
        "bid_c": bid, "ask_c": ask, "pred_g": g, "pred_g2": g2, "rnd2_c": rnd, "H_ns": H, "snap_ns": H + 60 * 10**9}
    rows = [mk("KXT-E1-A", +1, 41, H0, 40, 44), mk("KXT-E1-A", -1, 43, H0, 40, 44, g2=0.5),
            mk("KXT-E1-B", +1, 51, H0, 50, 54, tr=0), mk("KXT-E1-B", -1, 53, H0, 50, 54, tr=0),
            mk("KXT-E1-A", +1, 41, H0 + H_NS, 40, 44), mk("KXT-E1-A", -1, 43, H0 + H_NS, 40, 44)]
    one = pl.DataFrame(rows)
    sc = arm_scores(one, None)
    check("arms: g2 score keyed (ticker, H, side)", sc["g2"][("KXT-E1-A", H0, -1)] == 0.5)
    check("arms: wide3 posts spread >= 3 only", all(v == SELECTED_C for v in sc["wide3"].values()))
    check("arms: liq posts trades_24h >= the hour's median (B has 0 < median 2.5 at H0)",
          sc["liq"][("KXT-E1-B", H0, 1)] == SENTINEL_C and sc["liq"][("KXT-E1-A", H0, 1)] == SELECTED_C)
    # tape: a YES seller at 40 (fills the improved bid at 41) at H0+30s (before the snap) and at H0+120s
    tape = {"KXT-E1-A": (np.array([H0 + 30 * 10**9, H0 + 120 * 10**9], np.int64), np.array([40.0, 40.0]),
                         np.array([5.0, 5.0]), np.array([-1, -1]))}
    markets = {"KXT-E1-A": {"result": "yes", "close_ns": H0 + 10 * H_NS},
               "KXT-E1-B": {"result": "no", "close_ns": H0 + 10 * H_NS}}
    legs, events, charged = build_legs(one, None, tape, markets, {"KXT": "quadratic"})
    months = [s.month_of(H0)]
    gen = regenerated(legs, events, charged, months)
    logged = set(zip(one["ticker"].to_list(), one["H_ns"].to_list(), [int(x) for x in one["side"].to_list()],
                     [int(x) for x in one["price"].to_list()]))
    check("simulator regenerates exactly the logged candidates", gen == logged)
    cuts = {H0: (H0 + 60 * 10**9, H0 + 1800 * 10**9), H0 + H_NS: (H0 + H_NS + 60 * 10**9, H0 + 2 * H_NS)}
    F = {w: run_arms(apply_window(legs, cuts, w), events, charged, months, sc, ("g2", "cand"))["g2"] for w in WINDOWS}
    check(f"primary window: trade before the snap dropped, the later one fills 5 at 41 ({[(f[1], f[3], f[4]) for f in F['primary']]})",
          [(f[1], f[2], f[3], f[4]) for f in F["primary"]] == [("KXT-E1-A", 1, 41, 5)])
    check("pnl from the simulator: YES bought at 41 settles 100 -> +59c x 5, fee 0", F["primary"][0][6] == 295.0)
    check("sensitivity window: decision at +30 min leaves no trade -> no fill", F["sensitivity"] == [])
    # a YES seller exactly AT our improved 41 fills under pess (improved order) and opt; a seller at 41 for a
    # non-improved order (join at 40 when spread < 3) would not fill under pess. Check the model is passed through:
    Fs = run_arms(apply_window(legs, cuts, "primary"), events, charged, months, sc, ("g2",), "strict")["g2"]
    check(f"strict fill model is passed through (improved 41 needs a trade below the original 40: {len(Fs)} fills)", Fs == [])
    Fo = run_arms(apply_window(legs, cuts, "primary"), events, charged, months, sc, ("g2",), "opt")["g2"]
    check("optimistic fills at least what pessimistic fills", sum(f[4] for f in Fo) >= sum(f[4] for f in F["primary"]))
    g2_raw = run_arms(legs, events, charged, months, sc, ("g2",))["g2"]
    check("without a window cut both trades fill (the look-ahead L3 removes)", sum(f[4] for f in g2_raw) == 10)
    legs2 = apply_window(legs, {**cuts, H0: (H0 + 2 * H_NS, H0 + 2 * H_NS)}, "primary")
    check("an hour whose cut is past H+1h keeps no trades", len(legs2["KXT-E1-A"]["tt"]) == 0)
    for tk, L in legs.items():
        L["_settled"] = tk != "KXT-E1-B"
    check("an event with any unsettled leg is not scored", settled_mask(F["primary"], legs, events) == [False])
    pool = {"series": [{"series": "KXT", "cat": "Sports"}]}
    U = universes(pool, {"KXT-E1-A"})
    check("universes: pool, L1 by ticker, weather never new",
          U["primary_L4"]("KXT-E1-B", "KXT", "Sports") and not U["L1"]("KXT-E1-B", "KXT", "Sports")
          and not U["new_series"]("KXHIGHNY-X", "KXHIGHNY", "Climate and Weather"))
    check("L11: weather is in the primary universe and in the weather split, not in non_weather",
          U["primary_L4"]("KXHIGHNY-X", "KXHIGHNY", "Climate and Weather") and U["weather"]("KXHIGHNY-X", "KXHIGHNY", "Climate and Weather")
          and not U["non_weather"]("KXHIGHNY-X", "KXHIGHNY", "Climate and Weather"))

    # L7 walk-forward: fold 1 selects on [10-11 15:00, 10-18), trades [10-18, 10-25)
    sel_h, tr_h, hi1 = ns_of("20261015T12"), ns_of("20261020T12"), ns_of("20261018T00")
    F, cat, settled = [], {}, {}
    def add(ev, c, net, H, settle):
        F.append((ev, ev + "-L", 1, 50, 10, 0.0, net, 500.0, 0.0, H)); cat[ev + "-L"] = c; settled[ev] = settle
    for i in range(20):
        add(f"S{i}", "Sports", +10.0, sel_h, hi1 - H_NS)            # positive, 20 events, settled in time
        add(f"C{i}", "Crypto", -10.0, sel_h, hi1 - H_NS)            # negative
        add(f"P{i}", "Politics", +50.0, sel_h, hi1 + H_NS)          # positive but settled AFTER the window
    for i in range(19):
        add(f"E{i}", "Economics", +50.0, sel_h, hi1 - H_NS)         # positive, only 19 events
    for c in ("Sports", "Crypto", "Politics", "Economics"):
        add("T" + c, c, 1.0, tr_h, None)                            # trading-week fills
    cf = lambda f: cat[f[1]]
    folds = walk_forward_selection(F, settled, cf, lambda f: True)
    check(f"walk-forward: only Sports selected in fold 1 ({folds[0]['selected']})", folds[0]["selected"] == ["Sports"])
    check("walk-forward: events settled after the selection window are not counted (purged)",
          "Politics" not in folds[0]["table"])
    check("walk-forward: 19 events < minimum 20 fails despite a positive return",
          folds[0]["table"]["Economics"]["events"] == 19 and "Economics" not in folds[0]["selected"])
    gs = g2_sel_fills(F, folds, cf, lambda f: True)
    check("g2_sel: fold 1 trades only its trading week, only selected categories",
          [f[0] for f in gs] == ["TSports"])
    check("walk-forward: later folds see no fills here and select nothing", folds[1]["selected"] == folds[2]["selected"] == [])
    m = {"A": {"result": "yes", "settled_ns": 5}, "B": {"result": "no", "settled_ns": 9}, "C": {"result": "", "settled_ns": None}}
    check("event settled at = latest leg settlement; None while any leg is open",
          event_settled_at({"E": ["A", "B"], "F": ["A", "C"]}, m) == {"E": 9, "F": None})
    lines = [json.dumps({"H": "20261013T06", "events": 1, "snap_ns": 5, "t_decided_ns": 9, "secs": 1.0}),
             json.dumps({"H": "20261013T05", "events": 1, "secs": 2.0}), '{"info": "x"}']
    # L8 statistics
    rng = np.random.default_rng(1)
    fl = [(f"E{i}", f"E{i}-L", 1, 50, 10, 0.0, float(rng.normal(20, 100)), 500.0, 0.0, H0 + (i % 7) * 24 * H_NS)
          for i in range(400)]
    vs = verdict_stats(fl)
    ev = vs["event"]
    check(f"one-sided 95% lower bound lies between the two-sided bounds' lower end and the estimate "
          f"({ev['lo95']:.2f} <= {ev['lo_one_sided']:.2f} <= {ev['ret']:.2f})", ev["lo95"] <= ev["lo_one_sided"] <= ev["ret"])
    check("event clusters = events, day clusters = UTC days of the order hour", ev["clusters"] == 400 and vs["day"]["clusters"] == 7)
    same = paired_stats(fl, fl)
    check("paired: an arm minus itself is exactly 0 with a zero-width CI",
          same["event"]["diff"] == 0 and same["event"]["lo95"] == 0 == same["event"]["hi95"])
    better = [f[:6] + (f[6] + 50.0,) + f[7:] for f in fl]
    pb = paired_stats(better, fl)["event"]
    check(f"paired: +50c per event on 500c capital = +10 points, lower bound > 0 ({pb['diff']:.2f}, {pb['lo_one_sided']:.2f})",
          abs(pb["diff"] - 10.0) < 1e-9 and pb["lo_one_sided"] > 0)

    class M:
        def predict(self, X): return X[:, 0] * 0 + 7.0
    sc2 = arm_scores(one, None, {"g2w1": {"model": M(), "cats": ["Sports"]}})
    check("W1/W2 arms scored with the G2 design matrix", set(sc2["g2w1"].values()) == {7.0} and len(sc2["g2w1"]) == len(one))

    T = dt.datetime(2026, 10, 13, 14, 40, tzinfo=dt.timezone.utc)
    logged = [json.dumps({"H": "20261013T14", "events": 3})]
    check("quiet: hour logged and minute < 58 -> calls allowed", producer_quiet(logged, T))
    check("quiet: hour not yet logged -> wait", not producer_quiet([json.dumps({"H": "20261013T13", "events": 3})], T))
    check("quiet: minute 58 or later -> wait", not producer_quiet(logged, T.replace(minute=58)))
    check("quiet: an info line for the hour is not a logged cycle",
          not producer_quiet([json.dumps({"info": "hour 20261013T14 already completed", "H": "20261013T14"})], T))
    check("cut times: t_decided_ns when logged; older lines need the scores files", cut_times(lines) == {ns_of("20261013T06"): (5, 9)})
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--fetch-tape", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--check", action="store_true", help="candidate regeneration only: never simulates fills or P&L")
    ap.add_argument("--since", default=L2_FIX)
    ap.add_argument("--rps", type=float, default=2.0, help="L7: <= 2 requests/s")
    ap.add_argument("--ledger", action="store_true", help="L10: append the live ledger each round")
    ap.add_argument("--fleet", action="store_true", help="L10: post each round's ledger summary to Research Fleet")
    ap.add_argument("--ots", action="store_true", help="L14: OpenTimestamps record of each round's ledger head")
    ap.add_argument("--pat-file", default="~/.lumid_pat")
    ap.add_argument("--blind-test", metavar="DIR", help="one engine + ledger round into DIR; prints structure, timing "
                    "and memory only (no P&L), writes no summary, posts nothing")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.fetch_tape:
        cmd_fetch_tape(a.since, a.rps)
    if a.check:
        cmd_run(a.since, a.rps, write=False, check_only=True)
    pat = Path(a.pat_file).expanduser().read_text().strip() if a.fleet else None
    if a.blind_test:
        import resource
        t0 = time.time()
        r = cmd_run(a.since, a.rps, write=False, ledger=True, pat=None, ledger_dir=a.blind_test)
        import paper_ledger as pl_
        d = Path(a.blind_test)
        ents = sorted((d / "entries").glob("*.json"))
        chain_ok, prev = True, ""
        for e in ents:
            j = json.loads(e.read_text())
            chain_ok &= j["prev_hash"] == prev and j["hash"] == pl_.sha({k: v for k, v in j.items() if k != "hash"})
            prev = j["hash"]
        print(json.dumps({"BLIND_TEST": {"secs": round(time.time() - t0, 1), "max_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024,
                          "candidate_check": r["check"], "entries": [e.stem for e in ents], "chain_ok": chain_ok,
                          "verification_issues": r["ledger"]["verification_issues"],
                          "arms": sorted(json.loads(ents[-1].read_text())["cumulative"].get("primary", {})) if ents else []}}), flush=True)
    if a.run:
        cmd_run(a.since, a.rps, ledger=a.ledger, pat=pat, ots=a.ots)
    if a.loop:
        last = None
        while True:      # one round per hour, in the producer's quiet minutes (L7 item 4), never during its cycle
            now = dt.datetime.now(dt.timezone.utc)
            runs = LIVE / "runs.jsonl"
            lines = runs.read_text().splitlines() if runs.exists() else []
            stamp = now.strftime("%Y%m%dT%H")
            if stamp != last and producer_quiet(lines, now):
                last = stamp
                t0 = time.time()
                try:
                    cmd_fetch_tape(a.since, a.rps)
                    cmd_run(a.since, a.rps, ledger=a.ledger, pat=pat, ots=a.ots)
                except Exception as e:
                    print(json.dumps({"error": repr(e)[:300], "at": time.time()}), flush=True)
                print(json.dumps({"round": stamp, "secs": round(time.time() - t0, 1)}), flush=True)
            time.sleep(60)


if __name__ == "__main__":
    main()
