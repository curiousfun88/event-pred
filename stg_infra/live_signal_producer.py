"""
live_signal_producer.py

LIVE SIGNAL PRODUCER FOR THE LEARNED MAKER POLICIES (Lumid forward test).

WHAT. Once an hour: snapshot every open Kalshi MECE basket, build the features of
every candidate maker order with the SAME code the backtest and validation used,
score them with each frozen model, and publish the scores as Lumid signals for
.lqts strategies to read (docs: lum.id/docs/lqt-signals.md). Every candidate and
every arm's score is also logged, so the live hours can be replayed through
simulate_maker afterwards (the forward test's primary channel).

MODELS (amendments A12-A14): G (2025, decay reference), G2-W3 and G2+-W3 (the
A13/A14 selections, runs/maker/policy_G2_selection.json).

SAME CODE AS THE BACKTEST. The live snapshot is reshaped into the simulator's own
`legs` / `events` structures; candidates come from simulate_maker.simulate(...,
record=...) (BROAD config; levels="both" for G2+), and features from
maker_policy.quote_features (G, G2) or retrain_g2.features (G2+).

ARMS AND SIGNALS (cents per contract; a strategy posts when its signal > 1c):
    g_bid/g_ask          G's prediction                    (one level per side)
    g2_bid/g2_ask        G2-W3's prediction                (one level per side)
    g2p_bid/g2p_ask      G2+-W3's best level per side, with g2p_bid_lvl/g2p_ask_lvl
                         (1.0 = 1c inside the touch, 0 = at the touch)
    rnd2_bid/rnd2_ask    random, at G2's share of candidates this hour
    rnd2p_bid/rnd2p_ask  random over G2+'s candidates at G2+'s share (+ _lvl signals)
    cand_bid/cand_ask    every one-level candidate (quote everything)
Selected = 2c, not selected = SENTINEL_C. A leg published last hour that is no
longer a candidate gets SENTINEL_C on every score signal. score_ticks =
round(cents * 100) (1c = 100 ticks on the x10000 scale); a level signal is 10000
(1.0) or 0.

BASKETS. An open event qualifies if Kalshi flags it mutually_exclusive, it has
3-100 legs, it is not a combo (KXMVE*), and its series has >= 3 recent settled
events, every one with exactly one YES. Checked once per day per series.

DEVIATIONS FROM THE BACKTEST (stated): quotes at H are the market listing's best
bid/ask just after the top of the hour (the backtest used the candle close at H);
earlier quotes (H-1h, H-3h, H-24h) are the hourly candle closes, as in the
backtest; the basket rule uses Kalshi's flag and recent settled history.

DATA. Kalshi public API, unauthenticated, read-only, throttled. State and logs:
  runs/live/state/        snapshot store, trade store, series cache, last published set
  runs/live/scores/       one parquet per hour: every candidate, its features, every model's prediction
  runs/live/payloads/     the exact signal batch built each hour (dry-run or sent)

PUBLISHING. Off unless --publish. Envelope per lqt-strategies.md with topic
"signal.publish" and the batch shape of lqt-signals.md. TO VERIFY on first send.

USAGE (from repo root):
    python stg_infra/live_signal_producer.py --self-test
    python stg_infra/live_signal_producer.py --once                  # dry run
    python stg_infra/live_signal_producer.py --loop                  # hourly, logging only
    python stg_infra/live_signal_producer.py --loop --publish --pat-file ~/.lumid_pat
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

API = "https://api.elections.kalshi.com/trade-api/v2"
SUBMIT_URL = "https://lum.id/lqt/submit/lqt_inbox"
LIVE_DIR = _REPO / "runs/live"
H_NS = 3_600_000_000_000
SENTINEL_C = -100.0
SELECTED_C = 2.0
THRESHOLD_C = 1.0
MIN_LEGS, MAX_LEGS = 3, 100
MIN_SETTLED = 3
SERIES_TTL_S = 24 * 3600
MAKER_FEE_TYPES = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}


# ---------------------------------------------------------------- pure pieces

def dollars(x):
    """'0.4500' -> 0.45; None/'' -> nan."""
    if x is None or x == "":
        return np.nan
    return float(x)


def iso_ns(s: str) -> int:
    """'2026-10-05T15:48:45.343262Z' -> epoch ns (UTC)."""
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    return int(d.timestamp()) * 1_000_000_000 + d.microsecond * 1000


def hour_floor(ns: int) -> int:
    return ns - ns % H_NS


def to_ticks(cents: float) -> int:
    return int(round(cents * 100))


def series_rule(settled_n_yes: list) -> bool:
    """settled_n_yes: YES counts of a series' recent settled events (None = results unknown).
    Qualifies with >= MIN_SETTLED known events, every one single-winner."""
    known = [n for n in settled_n_yes if n is not None]
    return len(known) >= MIN_SETTLED and all(n == 1 for n in known)


def event_ok(ev: dict) -> bool:
    ms = ev.get("markets") or []
    return (bool(ev.get("mutually_exclusive")) and MIN_LEGS <= len(ms) <= MAX_LEGS
            and not str(ev.get("series_ticker", "")).startswith("KXMVE"))


def build_structures(events_json, H, history, trades, series_info, now_ns):
    """Live snapshot -> the simulator's (legs, events, charged).
    events_json: open qualifying events with nested markets (listing snapshot at ~H).
    history: {ticker: [(end_ns, bid, ask), ...]} hourly candle closes before H.
    trades: {ticker: (t ns, count, side +1 taker bought YES / -1 sold)} sorted by time.
    series_info: {series: {"fee_type":..., "category":...}}."""
    legs, events = {}, {}
    for ev in events_json:
        etk, ser = ev["event_ticker"], ev["series_ticker"]
        tks = []
        for m in ev["markets"]:
            tk = m["ticker"]
            close = iso_ns(m["close_time"]) if m.get("close_time") else None
            b, a = dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars"))
            if m.get("status") not in (None, "active", "open"):
                b = a = np.nan
            hist = sorted((int(e), float(hb), float(ha)) for e, hb, ha in history.get(tk, []) if int(e) < H)
            e = [x[0] for x in hist] + [H]
            bid = [x[1] for x in hist] + [b]
            ask = [x[2] for x in hist] + [a]
            tt, tc, ts = trades.get(tk, (np.empty(0, np.int64), np.empty(0), np.empty(0)))
            legs[tk] = {"event": etk, "series": ser, "yes": False, "close": close,
                        "e": np.array(e, np.int64), "bid": np.array(bid, float), "ask": np.array(ask, float),
                        "tt": tt, "tp": np.zeros(len(tt)), "tc": np.asarray(tc, float), "ts": np.asarray(ts, float)}
            tks.append(tk)
        events[etk] = tks

    def charged(series, month):
        return series_info.get(series, {}).get("fee_type", "quadratic") in MAKER_FEE_TYPES
    return legs, events, charged


def candidates_at(legs, events, charged, H, levels=""):
    """Candidate orders at H from the simulator's own quoting logic (BROAD config; levels="both" for G2+)."""
    import simulate_maker as s
    import maker_policy as mp
    cand = []
    s.simulate(s.Config(**{**mp.BROAD, **({"levels": levels} if levels else {})}), "pess", legs, events, charged,
               [s.month_of(H)], record=cand)
    return [c for c in cand if int(c[2]) == H]


def score_design(design, blob, legs, events, charged, lookup, H, cand):
    """Features with the training code of `design` ("G" and "G2": maker_policy; "G2P": retrain_g2) and the
    model's predictions. Returns (rows, keys, pred); keys = (event, ticker, side, price, bid_c, ask_c)."""
    import simulate_maker as s
    import maker_policy as mp
    import retrain_g2 as rg
    rows, keys = [], []
    for ev, tk, Hh, sd, pr, b, a in cand:
        if design == "G2P":
            r = rg.features("G2P", legs, events, charged, lookup, ev, tk, int(Hh), int(sd), int(pr))
        else:
            r = mp.quote_features(legs, events, charged, lookup, s.month_of(int(Hh)), ev, tk, int(Hh), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((ev, tk, int(sd), int(pr), int(b), int(a)))
    if not rows:
        return rows, keys, np.array([])
    X = rg.matrix("G2P", rows, blob["cats"]) if design == "G2P" else mp.to_matrix(rows, blob["cats"])
    return rows, keys, blob["model"].predict(X)


def one_level(keys, pred):
    """{(ticker, side): (score_c, level)} for one-level candidates."""
    return {(k[1], k[2]): (float(p), float(k[3] not in (k[4], k[5]))) for k, p in zip(keys, pred)}


def best_level(keys, pred):
    """{(ticker, side): (score_c, level)}: the higher-scoring level per side (the simulator's rule; first wins ties)."""
    out = {}
    for k, p in zip(keys, pred):
        key, lvl = (k[1], k[2]), float(k[3] not in (k[4], k[5]))
        if key not in out or p > out[key][0]:
            out[key] = (float(p), lvl)
    return out


def random_arm(keys, share, H, salt, two_level):
    """Random selection at `share`, reproducible per hour and arm. Picked = SELECTED_C, else SENTINEL_C."""
    rng = np.random.default_rng([int(H // H_NS), salt])
    u = rng.random(len(keys))
    sc = np.where(u < share, SELECTED_C, SENTINEL_C)
    return best_level(keys, sc) if two_level else one_level(keys, sc)


SCORE_ARMS = ("g", "g2", "g2p", "rnd2", "rnd2p", "cand")
LEVEL_ARMS = ("g2p", "rnd2p")


def build_signals(arms, prev_published, ts_event_ns):
    """arms: {arm: {(ticker, side): (score_c, level)}}. Signal rows for this hour, plus sentinels for legs
    published last hour that are no candidate now. Returns (rows, published_tickers)."""
    rows, now = [], set()
    tks = sorted({tk for v in arms.values() for tk, _ in v})
    row = lambda nm, tk, ticks: {"signal_name": nm, "instrument_id": tk, "score_ticks": int(ticks),
                                 "confidence_bps": 10000, "ts_event_ns": int(ts_event_ns)}
    for tk in tks:
        now.add(tk)
        for sd, nm in ((1, "bid"), (-1, "ask")):
            for arm in SCORE_ARMS:
                sc, lvl = arms.get(arm, {}).get((tk, sd), (SENTINEL_C, 0.0))
                rows.append(row(f"{arm}_{nm}", tk, to_ticks(sc)))
                if arm in LEVEL_ARMS:
                    rows.append(row(f"{arm}_{nm}_lvl", tk, 10000 if lvl > 0 else 0))
    for tk in sorted(set(prev_published) - now):
        for nm in ("bid", "ask"):
            for arm in SCORE_ARMS:
                rows.append(row(f"{arm}_{nm}", tk, to_ticks(SENTINEL_C)))
    return rows, now


def envelope(rows, pat, msg_id):
    """signal.publish record in the strategy.deploy envelope shape (lqt-strategies.md §4.2). TO VERIFY."""
    return {"records": [{"msg_id": msg_id, "topic": "signal.publish",
                         "payload": {"topic": "signal.publish", "auth": {"pat": pat}, "signals": rows}}]}


# ---------------------------------------------------------------- Kalshi client

class Kalshi:
    def __init__(self, rps=8.0):
        import requests
        self.s = requests.Session()
        self.gap = 1.0 / rps
        self.last = 0.0
        self.calls = 0

    def get(self, path, **params):
        for attempt in range(12):          # backoff 1, 2, 4 .. capped at 60s: rides out ~8 min of outage
            wait = self.last + self.gap - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                r = self.s.get(f"{API}/{path}", params=params, timeout=60)
            except Exception:
                time.sleep(min(2 ** attempt, 60)); continue
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(2 ** attempt, 60)); continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError(f"Kalshi GET failed: {path} {params}")

    def pages(self, path, key, **params):
        cur = ""
        while True:
            d = self.get(path, **({**params, "cursor": cur} if cur else params))
            yield from d.get(key, [])
            cur = d.get("cursor")
            if not cur:
                return


# ---------------------------------------------------------------- state

def load_state(name, default):
    p = LIVE_DIR / "state" / name
    return pickle.loads(p.read_bytes()) if p.exists() else default


def save_state(name, obj):
    p = LIVE_DIR / "state" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps(obj))
    tmp.replace(p)


def series_meta(k: Kalshi, series_list, cache, now_s):
    """{series: {"ok", "fee_type", "category", "checked"}}, refreshed once per SERIES_TTL_S."""
    for ser in series_list:
        c = cache.get(ser)
        if c and now_s - c["checked"] < SERIES_TTL_S:
            continue
        info = k.get(f"series/{ser}").get("series", {})
        n_yes = []
        for e in k.get("events", series_ticker=ser, status="settled", with_nested_markets="true", limit=8).get("events", []):
            ms = e.get("markets") or []
            if not ms:
                ms = k.get("historical/markets", event_ticker=e["event_ticker"], limit=200).get("markets", [])
            res = [m.get("result") for m in ms]
            n_yes.append(sum(r == "yes" for r in res) if ms and all(r in ("yes", "no") for r in res) else None)
            if sum(n is not None for n in n_yes) >= 5:
                break
        cache[ser] = {"ok": series_rule(n_yes), "fee_type": info.get("fee_type"), "category": info.get("category"),
                      "n_yes": n_yes, "checked": now_s}
    return cache


def update_trades(k: Kalshi, tickers, store, H):
    """Incremental trade store (time, count, taker side): keep trades in (H-25h, H]; fetch only what is new."""
    lo = H - 25 * H_NS
    empty = {"t": np.empty(0, np.int64), "c": np.empty(0), "s": np.empty(0), "ids": set()}
    for tk in tickers:
        have = store.get(tk, empty)
        min_s = int(max(lo, int(have["t"].max()) if len(have["t"]) else lo) // 1_000_000_000) - 1
        new, ids = [], set(have["ids"])
        for tr in k.pages("markets/trades", "trades", ticker=tk, min_ts=min_s, limit=1000):
            if tr["trade_id"] in ids:
                continue
            ids.add(tr["trade_id"])
            new.append((iso_ns(tr["created_time"]), float(tr.get("count_fp", tr.get("count", 0))),
                        1.0 if tr["taker_side"] == "yes" else -1.0))
        t = np.concatenate([have["t"], np.array([x[0] for x in new], np.int64)])
        c = np.concatenate([have["c"], np.array([x[1] for x in new], float)])
        s_ = np.concatenate([have["s"], np.array([x[2] for x in new], float)])
        o = np.argsort(t, kind="stable"); t, c, s_ = t[o], c[o], s_[o]
        keep = (t > lo) & (t <= H)
        store[tk] = {"t": t[keep], "c": c[keep], "s": s_[keep], "ids": ids if len(ids) < 50_000 else set()}
    return store


def candle_history(k: Kalshi, legs_needed, H):
    """{ticker: [(end_ns, bid, ask), ...]} hourly candle closes ending in [H-26h, H), one call per leg."""
    out = {}
    s_ = H // 1_000_000_000
    for tk, ser in legs_needed:
        d = k.get(f"series/{ser}/markets/{tk}/candlesticks", start_ts=s_ - 26 * 3600, end_ts=s_ - 1, period_interval=60)
        rows = []
        for c in d.get("candlesticks", []):
            b = (c.get("yes_bid") or {}).get("close_dollars")
            a = (c.get("yes_ask") or {}).get("close_dollars")
            e = int(c["end_period_ts"]) * 1_000_000_000
            if e < H:
                rows.append((e, np.nan if b is None else float(b), np.nan if a is None else float(a)))
        out[tk] = rows
    return out


# ---------------------------------------------------------------- one run

def load_models():
    """{arm: (design, blob, sha1)} for G and the A13/A14 selections."""
    import hashlib
    import maker_policy as mp
    import retrain_g2 as rg
    sel = json.loads((_REPO / "runs/maker/policy_G2_selection.json").read_text())
    paths = {"g": ("G", mp.model_path("G")), "g2": ("G2", rg.model_path(sel["G2"]["selected"], "G2")),
             "g2p": ("G2P", rg.model_path(sel["G2P"]["selected"], "G2P"))}
    return {arm: (d, pickle.loads(p.read_bytes()), hashlib.sha1(p.read_bytes()).hexdigest()[:16])
            for arm, (d, p) in paths.items()}


def run_once(args) -> dict:
    import polars as pl
    import maker_policy as mp
    models = load_models()
    k = Kalshi(rps=args.rps)
    t0 = time.time()
    now_ns = time.time_ns()
    H = hour_floor(now_ns)

    if args.series:
        evs = [e for ser in args.series
               for e in k.pages("events", "events", series_ticker=ser, status="open", with_nested_markets="true", limit=200)]
    else:
        evs = list(k.pages("events", "events", status="open", with_nested_markets="true", limit=200))
    snap_ns = time.time_ns()
    evs = [e for e in evs if event_ok(e)]
    cache = series_meta(k, sorted({e["series_ticker"] for e in evs}), load_state("series.pkl", {}), int(time.time()))
    save_state("series.pkl", cache)
    evs = [e for e in evs if cache[e["series_ticker"]]["ok"]]
    info = {s_: {"fee_type": c["fee_type"], "category": c["category"]} for s_, c in cache.items()}

    snaps = load_state("snaps.pkl", {})
    for e in evs:
        for m in e["markets"]:
            snaps[(m["ticker"], H)] = (dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars")))
    snaps = {key: v for key, v in snaps.items() if key[1] >= H - 48 * H_NS}

    # pass 0 (listing only) finds the legs that need per-leg calls
    legs0, events0, charged = build_structures(evs, H, {}, {}, info, now_ns)
    c0 = candidates_at(legs0, events0, charged, H) + candidates_at(legs0, events0, charged, H, "both")
    need = sorted({(c[1], legs0[c[1]]["series"]) for c in c0})
    hist = candle_history(k, need, H)
    vol = {m["ticker"]: float(m.get("volume_24h_fp") or 0) for e in evs for m in e["markets"]}
    tstore = load_state("trades2.pkl", {})
    tstore = update_trades(k, [tk for tk, _ in need if vol.get(tk, 0) > 0], tstore, H)
    tstore = {tk: v for tk, v in tstore.items() if tk in legs0}
    trades = {tk: (v["t"], v["c"], v["s"]) for tk, v in tstore.items()}

    legs, events, charged = build_structures(evs, H, hist, trades, info, now_ns)
    lookup = mp.category_lookup()
    for s_, c in cache.items():
        if s_ not in lookup and c.get("category"):
            lookup[s_] = c["category"]
    cand1 = candidates_at(legs, events, charged, H)
    cand2 = candidates_at(legs, events, charged, H, "both")
    out = {}
    for arm, cand in (("g", cand1), ("g2", cand1), ("g2p", cand2)):
        d, blob, _ = models[arm]
        out[arm] = score_design(d, blob, legs, events, charged, lookup, H, cand)
    r1, k1, p_g = out["g"]
    _, k1b, p_g2 = out["g2"]
    r2, k2, p_g2p = out["g2p"]
    assert k1 == k1b
    share2 = float(np.mean(p_g2 > THRESHOLD_C)) if len(p_g2) else 0.0
    share2p = float(np.mean(p_g2p > THRESHOLD_C)) if len(p_g2p) else 0.0
    arms = {"g": one_level(k1, p_g), "g2": one_level(k1, p_g2), "g2p": best_level(k2, p_g2p),
            "rnd2": random_arm(k1, share2, H, 2, False), "rnd2p": random_arm(k2, share2p, H, 3, True),
            "cand": one_level(k1, np.full(len(k1), SELECTED_C))}

    published = load_state("published.pkl", set())
    sig, now_pub = build_signals(arms, published, snap_ns)
    stamp = dt.datetime.fromtimestamp(H / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H")
    for sub in ("scores", "payloads"):
        (LIVE_DIR / sub).mkdir(parents=True, exist_ok=True)
    rnd2 = arms["rnd2"]
    if r1:
        pl.DataFrame([{**{f: r[f] for f in mp.FEATS_G if f != "cat_i"}, "cat": r["cat"], "event": kk[0], "ticker": kk[1],
                       "bid_c": kk[4], "ask_c": kk[5], "pred_g": float(a), "pred_g2": float(b),
                       "rnd2_c": rnd2[(kk[1], kk[2])][0], "H_ns": H, "snap_ns": snap_ns}
                      for r, kk, a, b in zip(r1, k1, p_g, p_g2)]).write_parquet(LIVE_DIR / "scores" / f"one_{stamp}.parquet")
    if r2:
        import retrain_g2 as rg
        u = np.random.default_rng([int(H // H_NS), 3]).random(len(k2))
        pl.DataFrame([{**{f: r[f] for f in rg.feats("G2P") if f != "cat_i"}, "cat": r["cat"], "event": kk[0],
                       "ticker": kk[1], "bid_c": kk[4], "ask_c": kk[5], "pred_g2p": float(p),
                       "rnd2p_pick": bool(v < share2p), "H_ns": H, "snap_ns": snap_ns}
                      for r, kk, p, v in zip(r2, k2, p_g2p, u)]).write_parquet(LIVE_DIR / "scores" / f"two_{stamp}.parquet")
    (LIVE_DIR / "payloads" / f"signals_{stamp}.json").write_text(json.dumps(sig))

    sent = None
    if args.publish:
        pat = Path(args.pat_file).expanduser().read_text().strip()
        import requests
        sent = []
        for i in range(0, len(sig), args.batch):
            body = envelope(sig[i:i + args.batch], pat, f"maker-{stamp}-{i // args.batch}")
            r = requests.post(SUBMIT_URL, json=body, headers={"Authorization": f"Bearer {pat}"}, timeout=60)
            sent.append((r.status_code, r.text[:200]))
        if all(c == 200 for c, _ in sent):
            save_state("published.pkl", now_pub)
    save_state("snaps.pkl", snaps)
    save_state("trades2.pkl", tstore)

    summary = {"H": stamp, "events": len(evs), "legs": len(legs), "cand_one": len(k1), "cand_two": len(k2),
               "share_g": round(float(np.mean(p_g > THRESHOLD_C)) if len(p_g) else 0.0, 4),
               "share_g2": round(share2, 4), "share_g2p": round(share2p, 4), "signal_rows": len(sig),
               "hist_legs": len(hist), "trade_legs": len(trades), "api_calls": k.calls,
               "secs": round(time.time() - t0, 1), "models": {a: m[2] for a, m in models.items()},
               "published": sent if sent is not None else "dry-run"}
    print(json.dumps(summary), flush=True)
    with open(LIVE_DIR / "runs.jsonl", "a") as f:
        f.write(json.dumps(summary) + "\n")
    return summary


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted live snapshot)")
    import simulate_maker as s
    import maker_policy as mp
    import retrain_g2 as rg

    H = 1_791_212_400 * 1_000_000_000          # a top-of-hour, 2026-10
    close = "2026-10-06T07:59:00Z"

    def mk(tk, b, a, status="active", cl=close):
        return {"ticker": tk, "yes_bid_dollars": b, "yes_ask_dollars": a, "status": status, "close_time": cl}
    ev = {"event_ticker": "KXHIGHLAX-26OCT05", "series_ticker": "KXHIGHLAX", "mutually_exclusive": True,
          "markets": [mk("A", "0.4000", "0.4400"),        # spread 4 -> improve: bid 41, ask 43
                      mk("B", "0.3000", "0.3200"),        # spread 2 -> join: bid 30, ask 32
                      mk("C", "0.2000", "0.2100"),        # spread 1 -> no candidate
                      mk("D", "0.0000", "0.0500"),        # one-sided (bid 0) -> no candidate, still quoted
                      mk("E", "0.5000", "0.5500", cl="2026-10-05T00:00:00Z")]}   # closed before H -> none
    info = {"KXHIGHLAX": {"fee_type": "quadratic", "category": "Climate and Weather"}}
    hist = {"A": [(H - 24 * H_NS, 0.30, 0.34), (H - 3 * H_NS, 0.36, 0.40), (H - H_NS, 0.38, 0.42), (H + H_NS, 0.9, 0.95)]}
    tt = np.array([H - 25 * H_NS, H - 23 * H_NS, H - 1800 * 10**9, H - 1, H, H + 1], np.int64)
    trades = {"A": (tt, np.array([1, 1, 3, 1, 2, 9.0]), np.array([1, 1, 1, -1, -1, 1.0]))}
    legs, events, charged = build_structures([ev], H, hist, trades, info, H)
    check("history after H is never used", legs["A"]["e"].max() == H and len(legs["A"]["e"]) == 4)

    c1 = candidates_at(legs, events, charged, H)
    got = sorted((c[1], int(c[3]), int(c[4])) for c in c1)
    check(f"one-level candidates from the simulator's own logic: {got}",
          got == [("A", -1, 43), ("A", 1, 41), ("B", -1, 32), ("B", 1, 30)])
    c2 = candidates_at(legs, events, charged, H, "both")
    got2 = sorted((c[1], int(c[3]), int(c[4])) for c in c2)
    check(f"two-level candidates add the touch where spread >= 3c: {got2}",
          got2 == [("A", -1, 43), ("A", -1, 44), ("A", 1, 40), ("A", 1, 41), ("B", -1, 32), ("B", 1, 30)])

    lookup = {"KXHIGHLAX": "Climate and Weather"}
    r = mp.quote_features(legs, events, charged, lookup, s.month_of(H), "KXHIGHLAX-26OCT05", "A", H, 1, 41)
    check("mid / spread / price relative to mid", r["mid"] == 42 and r["spread"] == 4 and r["rel_price"] == -1)
    check("24h mid change from the H-24h candle (42 - 32 = 10)", abs(r["dmid_24h"] - 10) < 1e-9)
    check("trades counted in (H-24h, H] only", r["trades_24h"] == 4)
    check("basket context: 5 legs, all 5 quoted, sum and second mid",
          r["n_legs"] == 5 and r["n_quoted"] == 5 and abs(r["basket_sum"] - 148.5) < 1e-9 and abs(r["second_mid"] - 52.5) < 1e-9)
    p = rg.features("G2P", legs, events, charged, lookup, "KXHIGHLAX-26OCT05", "A", H, 1, 41)
    check(f"G2+ live features: prints 3, imbalance (3-1-2)/6, dmid_1h 2, dmid_3h 4, ttc 16.98h, improved 1",
          p["prints_1h"] == 3 and abs(p["imb_1h"] - 0.0) < 1e-9 and abs(p["dmid_1h"] - 2) < 1e-9
          and abs(p["dmid_3h"] - 4) < 1e-9 and abs(p["ttc_h"] - 16.9833333) < 1e-4 and p["improved"] == 1.0)
    check("fee status: quadratic series is taker-only (not charged)", not charged("KXHIGHLAX", "2026-10"))
    check("basket rule: 3 single-winner settled events qualify, 2 winners revoke",
          series_rule([1, 1, 1]) and not series_rule([1, 1, None]) and not series_rule([1, 1, 1, 2]))
    check("event filter: combos and 2-leg events excluded",
          not event_ok({**ev, "series_ticker": "KXMVECROSS"}) and not event_ok({**ev, "markets": ev["markets"][:2]})
          and event_ok(ev) and not event_ok({**ev, "mutually_exclusive": False}))

    models = load_models()
    check(f"selected models load (G2 {models['g2'][2]}, G2+ {models['g2p'][2]})",
          models["g2"][0] == "G2" and models["g2p"][0] == "G2P")
    _, k1, pg2 = score_design("G2", models["g2"][1], legs, events, charged, lookup, H, c1)
    _, k2, pg2p = score_design("G2P", models["g2p"][1], legs, events, charged, lookup, H, c2)
    direct = models["g2p"][1]["model"].predict(rg.matrix("G2P", [rg.features("G2P", legs, events, charged, lookup,
                                                                              c[0], c[1], int(c[2]), int(c[3]), int(c[4])) for c in c2], models["g2p"][1]["cats"]))
    check(f"G2+ live scores equal the training path's ({len(pg2p)} candidates)", np.allclose(pg2p, direct, atol=0, rtol=0))
    check("every candidate scored with a finite prediction", len(pg2) == 4 and len(pg2p) == 6 and np.isfinite(np.r_[pg2, pg2p]).all())

    keys = [("E", "A", 1, 40, 40, 44), ("E", "A", 1, 41, 40, 44), ("E", "A", -1, 44, 40, 44), ("E", "A", -1, 43, 40, 44)]
    bl = best_level(keys, np.array([3.0, 2.0, 0.5, 1.5]))
    check(f"best level per side: bid touch (3.0, lvl 0), ask inside (1.5, lvl 1): {bl}",
          bl == {("A", 1): (3.0, 0.0), ("A", -1): (1.5, 1.0)})
    ra, rb = random_arm(keys, 0.5, H, 3, True), random_arm(keys, 0.5, H, 3, True)
    check("random arm reproducible for the same hour and arm", ra == rb and random_arm(keys, 0.0, H, 3, True)[("A", 1)][0] == SENTINEL_C)
    arms = {"g2": one_level(keys[:1] + keys[3:], np.array([3.0, -2.0])), "g2p": bl}
    rows, now = build_signals(arms, {"A", "Z"}, H + 5)
    names = {x["signal_name"] for x in rows if x["instrument_id"] == "A"}
    check("16 signals per published leg (6 arms x 2 sides + 2 level arms x 2 sides)",
          len([x for x in rows if x["instrument_id"] == "A"]) == 16 and "g2p_bid_lvl" in names and "rnd2p_ask_lvl" in names)
    g = {x["signal_name"]: x["score_ticks"] for x in rows if x["instrument_id"] == "A"}
    check("score scale 3.0c -> 300 ticks; missing arm -> sentinel; level 1 -> 10000",
          g["g2_bid"] == 300 and g["g_bid"] == to_ticks(SENTINEL_C) and g["g2p_ask_lvl"] == 10000 and g["g2p_bid_lvl"] == 0)
    z = [x for x in rows if x["instrument_id"] == "Z"]
    check("a leg dropped since last hour gets the sentinel on all 12 score signals",
          len(z) == 12 and all(x["score_ticks"] == to_ticks(SENTINEL_C) for x in z))
    check("ts_event_ns is the snapshot time", all(x["ts_event_ns"] == H + 5 for x in rows))
    env = envelope(rows[:2], "PAT", "m1")
    check("envelope carries topic and the PAT owner credential",
          env["records"][0]["topic"] == "signal.publish" and env["records"][0]["payload"]["auth"]["pat"] == "PAT")
    check("time helpers", iso_ns("2026-10-05T15:48:45.5Z") % 1_000_000_000 == 500_000_000 and hour_floor(H + 5) == H)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true", help="run at minute 1 of every hour")
    ap.add_argument("--series", nargs="*", help="limit to these series (default: every open Kalshi event)")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--pat-file", default="~/.lumid_pat")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--rps", type=float, default=8.0)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.once:
        run_once(a)
    elif a.loop:
        while True:
            try:
                run_once(a)
            except Exception as e:
                print(json.dumps({"error": repr(e), "at": time.time()}), flush=True)
                # a failed cycle is retried within the same hour while there is time to finish it
                if (time.time_ns() - hour_floor(time.time_ns())) < 25 * 60 * 1_000_000_000:
                    time.sleep(180)
                    continue
            nxt = hour_floor(time.time_ns()) + H_NS + 60 * 1_000_000_000
            time.sleep(max(30, (nxt - time.time_ns()) / 1e9))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
