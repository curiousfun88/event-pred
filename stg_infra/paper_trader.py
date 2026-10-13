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
SEL = _REPO / "results/live/l4_g2_sel_selection.json"
ONE_ARMS = ("g", "g2", "rnd2", "cand", "wide3", "liq", "lin2", "mlp2")
TWO_ARMS = ("g2p", "rnd2p")
SELECTED_C, SENTINEL_C, THRESHOLD_C = 2.0, -100.0, 1.0
MAX_MISMATCH = 0.005
WINDOWS = ("primary", "sensitivity")


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


def run_arms(legs, events, charged, months, scores, arms):
    """{arm: fills} with simulate_maker.simulate, pessimistic fills, BROAD config, the arm's scores."""
    import maker_policy as mp
    import simulate_maker as s
    out = {}
    for arm in arms:
        if arm not in scores:
            continue
        lv = {"levels": "both"} if arm in TWO_ARMS else {}
        cfg = s.Config(**{**mp.BROAD, **lv, "policy": "live", "policy_t": THRESHOLD_C})
        out[arm] = s.simulate(cfg, "pess", legs, events, charged, months, policy_scores=scores[arm])
    return out


# ---------------------------------------------------------------- universes and summaries

def universes(pool, l1_tickers, selected_cats):
    """{name: predicate(event, ticker, series, category)}."""
    ps = {x["series"] for x in pool["series"]}
    weather = lambda se: se.startswith(("KXHIGH", "KXLOW"))
    from fetch_kalshi_api_months import SERIES_A13
    a13 = set(SERIES_A13)
    return {"primary_L4": lambda tk, se, cat: se in ps,
            "new_series": lambda tk, se, cat: (se not in ps) and not weather(se),
            "L1": lambda tk, se, cat: tk in l1_tickers and not weather(se),
            "g2_sel": lambda tk, se, cat: se in ps and cat in selected_cats,
            "train23": lambda tk, se, cat: se in ps and se in a13,
            "other": lambda tk, se, cat: se in ps and se not in a13}


def settled_mask(fills, legs, events):
    """True for fills in events whose every leg has a yes/no result (scored); others are reported apart."""
    done = {ev: all(legs[t]["_settled"] for t in tks) for ev, tks in events.items()}
    return [done[f[0]] for f in fills]


def summarise_by(fills, key):
    import simulate_maker as s
    groups = {}
    for f in fills:
        groups.setdefault(key(f), []).append(f)
    return {g: s.summarise(v) for g, v in sorted(groups.items())}


# ---------------------------------------------------------------- Kalshi I/O

def fetch_tape_hour(k, H, tickers):
    """Every Kalshi trade in (H, H+1h] on `tickers`, from the platform-wide trades feed."""
    import polars as pl
    import smoke_test_2026 as st
    rows = []
    for tr in k.pages("markets/trades", "trades", min_ts=H // 10**9, max_ts=(H + H_NS) // 10**9 + 1, limit=1000):
        if tr["ticker"] in tickers:
            rows.append(tr)
    t, p, c, s_ = st.trade_arrays(rows)
    ids = [tr["trade_id"] for tr in sorted(rows, key=lambda tr: st.ts_ns(tr["created_time"]))]
    tk = [tr["ticker"] for tr in sorted(rows, key=lambda tr: st.ts_ns(tr["created_time"]))]
    df = pl.DataFrame({"ticker": tk, "t": t, "price_c": p, "count": c, "side": s_, "trade_id": ids})
    return df.filter((pl.col("t") > H) & (pl.col("t") <= H + H_NS))


def load_tape(hours):
    import polars as pl
    fs = [TAPE / f"trades_{h}.parquet" for h in hours if (TAPE / f"trades_{h}.parquet").exists()]
    if not fs:
        return {}, []
    d = pl.concat([pl.read_parquet(f) for f in fs]).unique("trade_id").sort(["ticker", "t"])
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
                                  "close_ns": st.ts_ns(m["close_time"]) if m.get("close_time") else None}
    return cache


# ---------------------------------------------------------------- run

def scored_hours(since):
    hs = sorted(p.stem.split("_")[1] for p in (LIVE / "scores").glob("one_*.parquet"))
    return [h for h in hs if h >= since]


def complete(h, now_ns):
    return ns_of(h) + H_NS + 5 * 60 * 10**9 <= now_ns


def cmd_fetch_tape(since, rps):
    import live_signal_producer as lp
    import polars as pl
    TAPE.mkdir(parents=True, exist_ok=True)
    k = lp.Kalshi(rps=rps)
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


def cmd_run(since, rps, write=True, check_only=False):
    import live_signal_producer as lp
    import simulate_maker as s
    import train_baselines as tb
    hours = [h for h in scored_hours(since) if (TAPE / f"trades_{h}.parquet").exists()]
    if not hours:
        print("no hours with tape yet"); return None
    one, two = load_scores(hours)
    runs = (LIVE / "runs.jsonl").read_text().splitlines() if (LIVE / "runs.jsonl").exists() else []
    cuts = cut_times_all(one, runs)
    tape, _ = load_tape(hours)
    PAPER.mkdir(parents=True, exist_ok=True)
    mpath = PAPER / "markets.pkl"
    markets = pickle.loads(mpath.read_bytes()) if mpath.exists() else {}
    k = lp.Kalshi(rps=rps)
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

    base = {a: pickle.loads(tb.model_path(a).read_bytes()) for a in ("lin2", "mlp2") if tb.model_path(a).exists()}
    scores = arm_scores(one, two, base)
    pool = json.loads(POOL.read_text())
    cat_of = {x["series"]: x["cat"] for x in pool["series"]}
    for se, c in zip([e.split("-")[0] for e in one["event"].to_list()], one["cat"].to_list()):
        cat_of.setdefault(se, c)
    l1 = set()
    for f in (LIVE / "payloads").glob("sent_*.json"):
        l1 |= {r["instrument_id"] for r in json.loads(f.read_text())}
    sel = json.loads(SEL.read_text()).get("selected", []) if SEL.exists() else []
    U = universes(pool, l1, set(sel))
    result = {"hours": [hours[0], hours[-1], len(hours)], "check": chk, "g2_sel_categories": sel,
              "tape_hours": len(hours), "windows": {}}
    for w in WINDOWS:
        Lw = apply_window(legs, cuts, w)
        fills = run_arms(Lw, events, charged, months, scores, ONE_ARMS + TWO_ARMS)
        res = {}
        for arm, fl in fills.items():
            mask = settled_mask(fl, Lw, events)
            done = [f for f, m in zip(fl, mask) if m]
            open_ = [f for f, m in zip(fl, mask) if not m]
            for un, pred in U.items():
                inu = lambda f: pred(f[1], legs[f[1]]["series"], cat_of.get(legs[f[1]]["series"], "?"))
                sub = [f for f in done if inu(f)]
                res.setdefault(arm, {})[un] = {
                    "all": s.summarise(sub), "unsettled_fills": sum(1 for f in open_ if inu(f)),
                    "by_category": summarise_by(sub, lambda f: cat_of.get(legs[f[1]]["series"], "?"))}
            if write:
                import polars as pl
                pl.DataFrame([{"event": f[0], "ticker": f[1], "side": int(f[2]), "price": int(f[3]), "qty": int(f[4]),
                               "fee_c": float(f[5]), "net_c": float(f[6]), "capital_c": float(f[7]),
                               "markout_c": float(f[8]), "H_ns": int(f[9]), "settled": bool(m)}
                              for f, m in zip(fl, mask)] or [{"event": ""}]).write_parquet(PAPER / f"fills_{w}_{arm}.parquet")
        result["windows"][w] = res
    if write:
        (PAPER / "summary.json").write_text(json.dumps(result, indent=1, default=float))
    return result


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
    g2_raw = run_arms(legs, events, charged, months, sc, ("g2",))["g2"]
    check("without a window cut both trades fill (the look-ahead L3 removes)", sum(f[4] for f in g2_raw) == 10)
    legs2 = apply_window(legs, {**cuts, H0: (H0 + 2 * H_NS, H0 + 2 * H_NS)}, "primary")
    check("an hour whose cut is past H+1h keeps no trades", len(legs2["KXT-E1-A"]["tt"]) == 0)
    for tk, L in legs.items():
        L["_settled"] = tk != "KXT-E1-B"
    check("an event with any unsettled leg is not scored", settled_mask(F["primary"], legs, events) == [False])
    pool = {"series": [{"series": "KXT", "cat": "Sports"}]}
    U = universes(pool, {"KXT-E1-A"}, {"Sports"})
    check("universes: pool, L1 by ticker, g2_sel by category",
          U["primary_L4"]("KXT-E1-B", "KXT", "Sports") and not U["L1"]("KXT-E1-B", "KXT", "Sports")
          and U["g2_sel"]("KXT-E1-A", "KXT", "Sports") and not U["g2_sel"]("KXT-E1-A", "KXT", "Crypto")
          and not U["new_series"]("KXHIGHNY-X", "KXHIGHNY", "Climate and Weather"))
    lines = [json.dumps({"H": "20261013T06", "events": 1, "snap_ns": 5, "t_decided_ns": 9, "secs": 1.0}),
             json.dumps({"H": "20261013T05", "events": 1, "secs": 2.0}), '{"info": "x"}']
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
    ap.add_argument("--rps", type=float, default=4.0)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.fetch_tape:
        cmd_fetch_tape(a.since, a.rps)
    if a.check:
        cmd_run(a.since, a.rps, write=False, check_only=True)
    if a.run:
        if not SEL.exists():
            raise SystemExit("L4: the g2_sel selection must be committed before any live P&L is computed")
        cmd_run(a.since, a.rps)
    if a.loop:
        while True:
            try:
                cmd_fetch_tape(a.since, a.rps)
                if SEL.exists():
                    cmd_run(a.since, a.rps)
            except Exception as e:
                print(json.dumps({"error": repr(e)[:300], "at": time.time()}), flush=True)
            now = dt.datetime.now(dt.timezone.utc)
            time.sleep(max(60, (70 - now.minute) % 60 * 60 - now.second))   # next run at ~HH:10


if __name__ == "__main__":
    main()
