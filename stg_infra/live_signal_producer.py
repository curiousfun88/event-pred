"""
live_signal_producer.py

LIVE SIGNAL PRODUCER FOR THE LEARNED MAKER POLICY G (Lumid forward test).

WHAT. Once an hour: snapshot every open Kalshi MECE basket, build the 14
features of every candidate maker order with the SAME code the backtest used,
score them with the frozen G model, and publish the scores as Lumid signals
for .lqts strategies to read (docs: lum.id/docs/lqt-signals.md).

SAME CODE AS THE BACKTEST. The live snapshot is reshaped into the simulator's
own `legs` / `events` structures, then
  * candidates come from simulate_maker.simulate(..., record=...)   (spread >= 2c,
    improve 1c when spread >= 3c, 1-99c band, both sides, not after close), and
  * features come from maker_policy.quote_features,
so a live score is computed exactly as a test-month score was. The model file
and its sha1 are the frozen ones (runs/maker/policy_G_model.json).

THREE ARMS, ONE STRATEGY SHAPE. Every arm publishes a bid and an ask signal in
CENTS PER CONTRACT, and every strategy posts when its signal > 1c:
    gbt_bid / gbt_ask   G's predicted net P&L per contract at settlement
    rnd_bid / rnd_ask   random selection, same share of candidates as G posts this hour
    cand_bid / cand_ask every candidate (the "quote everything" baseline)
Selected = 2c, not selected = SENTINEL_C. A leg that was published last hour
and is no longer a candidate gets SENTINEL_C on every signal, so a strategy
never acts on a stale score. Scale: score_ticks = round(cents * 100)
(1c = $0.01 = 100 ticks on the x10000 scale).

BASKETS (live analogue of build_mece_membership's causal rule). An open event
qualifies if Kalshi flags it mutually_exclusive, it has 3-100 legs, it is not
a combo (KXMVE*), and its series has >= 3 settled events among its most recent
ones, every one with exactly one YES. Checked once per day per series.

DEVIATIONS FROM THE BACKTEST (stated, not hidden):
  * quotes at H are the market listing's best bid/ask taken just after the top
    of the hour; the backtest used the hourly candle close at H.
  * the quote 24h earlier comes from this producer's own snapshot store, or the
    candle ending at H-24h when the store has none.
  * the basket rule uses Kalshi's mutually_exclusive flag plus recent settled
    history, not the full-history family scan.

DATA. Kalshi public API, unauthenticated, read-only, throttled. State and logs:
  runs/live/state/        snapshot store, trade store, series cache, last published set
  runs/live/scores/       one parquet per hour: every candidate, its features, all arm scores
  runs/live/payloads/     the exact signal batch built each hour (dry-run or sent)

PUBLISHING. Off unless --publish. The envelope follows the strategy.deploy
example in lqt-strategies.md with topic "signal.publish" and the batch shape
from lqt-signals.md. TO VERIFY on the first live send (the docs give no
complete signal.publish envelope).

USAGE (from repo root):
    python stg_infra/live_signal_producer.py --self-test
    python stg_infra/live_signal_producer.py --once                  # dry run, writes logs + payload
    python stg_infra/live_signal_producer.py --once --series KXHIGHLAX KXMLSGAME
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
ARMS = ("gbt", "rnd", "cand")
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


def build_structures(events_json, H, prev_quotes, trades, series_info, now_ns):
    """Live snapshot -> the simulator's (legs, events, charged).
    events_json: open qualifying events with nested markets (listing snapshot at ~H).
    prev_quotes: {ticker: (bid, ask)} dollars at H-24h, if known.
    trades: {ticker: sorted int64 ns array of trade times}.
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
            e, bid, ask = [], [], []
            if tk in prev_quotes:
                e.append(H - 24 * H_NS); bid.append(prev_quotes[tk][0]); ask.append(prev_quotes[tk][1])
            e.append(H); bid.append(b); ask.append(a)
            tt = trades.get(tk, np.empty(0, np.int64))
            legs[tk] = {"event": etk, "series": ser, "yes": False, "close": close,
                        "e": np.array(e, np.int64), "bid": np.array(bid, float), "ask": np.array(ask, float),
                        "tt": tt, "tp": np.zeros(len(tt)), "tc": np.zeros(len(tt)), "ts": np.zeros(len(tt))}
            tks.append(tk)
        events[etk] = tks

    def charged(series, month):
        return series_info.get(series, {}).get("fee_type", "quadratic") in MAKER_FEE_TYPES
    return legs, events, charged


def candidates_at(legs, events, charged, H):
    """Candidate orders at H from the simulator's own quoting logic (BROAD config of policy G)."""
    import simulate_maker as s
    import maker_policy as mp
    cand = []
    s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, [s.month_of(H)], record=cand)
    return [c for c in cand if int(c[2]) == H]


def score_rows(legs, events, charged, lookup, H, cand, model, cats):
    """Features (maker_policy.quote_features, unchanged) and G predictions for candidates at H."""
    import simulate_maker as s
    import maker_policy as mp
    mo = s.month_of(H)
    rows, keys = [], []
    for ev, tk, Hh, sd, pr, b, a in cand:
        r = mp.quote_features(legs, events, charged, lookup, mo, ev, tk, int(Hh), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((ev, tk, int(sd), int(pr), int(b), int(a)))
    pred = model.predict(mp.to_matrix(rows, cats)) if rows else np.array([])
    return rows, keys, pred


def arm_scores(keys, pred, H):
    """{(tk, side): {"gbt":c, "rnd":c, "cand":c}}. Random arm posts the same share as G this hour,
    seeded by the hour so a rerun reproduces it."""
    share = float(np.mean(pred > THRESHOLD_C)) if len(pred) else 0.0
    rng = np.random.default_rng(int(H // H_NS))
    pick = rng.random(len(keys)) < share
    out = {}
    for (ev, tk, sd, pr, b, a), p, rp in zip(keys, pred, pick):
        out[(tk, sd)] = {"gbt": float(p), "rnd": SELECTED_C if rp else SENTINEL_C, "cand": SELECTED_C}
    return out, share


def build_signals(scores, prev_published, ts_event_ns):
    """Signal rows for this hour, plus sentinels for legs published last hour that are no longer candidates.
    Returns (rows, published_tickers)."""
    rows, now = [], set()
    by_tk = {}
    for (tk, sd), v in scores.items():
        by_tk.setdefault(tk, {})[sd] = v
    for tk, sides in by_tk.items():
        now.add(tk)
        for sd, nm in ((1, "bid"), (-1, "ask")):
            v = sides.get(sd, {a: SENTINEL_C for a in ARMS})
            for arm in ARMS:
                rows.append({"signal_name": f"{arm}_{nm}", "instrument_id": tk,
                             "score_ticks": to_ticks(v[arm]), "confidence_bps": 10000, "ts_event_ns": int(ts_event_ns)})
    for tk in sorted(set(prev_published) - now):
        for nm in ("bid", "ask"):
            for arm in ARMS:
                rows.append({"signal_name": f"{arm}_{nm}", "instrument_id": tk,
                             "score_ticks": to_ticks(SENTINEL_C), "confidence_bps": 10000, "ts_event_ns": int(ts_event_ns)})
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
    """Incremental trade-time store: keep trades in (H-25h, H]; fetch only what is new."""
    lo = H - 25 * H_NS
    for tk in tickers:
        have = store.get(tk, {"t": np.empty(0, np.int64), "ids": set()})
        min_s = int(max(lo, int(have["t"].max()) if len(have["t"]) else lo) // 1_000_000_000) - 1
        new_t, ids = [], set(have["ids"])
        for tr in k.pages("markets/trades", "trades", ticker=tk, min_ts=min_s, limit=1000):
            if tr["trade_id"] in ids:
                continue
            ids.add(tr["trade_id"]); new_t.append(iso_ns(tr["created_time"]))
        t = np.sort(np.concatenate([have["t"], np.array(new_t, np.int64)]))
        keep = (t > lo) & (t <= H)
        store[tk] = {"t": t[keep], "ids": ids if len(ids) < 50_000 else set()}
    return store


def quote_24h(k: Kalshi, legs_needed, snaps, H):
    """{ticker: (bid, ask)} at H-24h from the snapshot store, else the candle ending at H-24h."""
    want = H - 24 * H_NS
    out = {}
    for tk, ser in legs_needed:
        if (tk, want) in snaps:
            out[tk] = snaps[(tk, want)]; continue
        s_ = want // 1_000_000_000
        d = k.get(f"series/{ser}/markets/{tk}/candlesticks", start_ts=s_ - 3600, end_ts=s_, period_interval=60)
        for c in d.get("candlesticks", []):
            if int(c["end_period_ts"]) == s_:
                b = (c.get("yes_bid") or {}).get("close_dollars")
                a = (c.get("yes_ask") or {}).get("close_dollars")
                if b is not None and a is not None:
                    out[tk] = (float(b), float(a))
    return out


# ---------------------------------------------------------------- one run

def run_once(args) -> dict:
    import polars as pl
    import maker_policy as mp
    blob = pickle.loads(mp.model_path("G").read_bytes())
    model, cats = blob["model"], blob["cats"]
    meta = json.loads(mp.meta_path("G").read_text())
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

    snaps = load_state("snaps.pkl", {})
    for e in evs:
        for m in e["markets"]:
            snaps[(m["ticker"], H)] = (dollars(m.get("yes_bid_dollars")), dollars(m.get("yes_ask_dollars")))
    snaps = {key: v for key, v in snaps.items() if key[1] >= H - 48 * H_NS}

    # cheap pass: candidates with no 24h quote and no trades, to know which legs need per-leg calls
    info = {s_: {"fee_type": c["fee_type"], "category": c["category"]} for s_, c in cache.items()}
    legs0, events0, charged = build_structures(evs, H, {}, {}, info, now_ns)
    cand0 = candidates_at(legs0, events0, charged, H)
    cand_legs = sorted({(c[1], legs0[c[1]]["series"]) for c in cand0})
    prev_q = quote_24h(k, cand_legs, snaps, H)
    vol = {m["ticker"]: float(m.get("volume_24h_fp") or 0) for e in evs for m in e["markets"]}
    tstore = load_state("trades.pkl", {})
    tstore = update_trades(k, [tk for tk, _ in cand_legs if vol.get(tk, 0) > 0], tstore, H)
    tstore = {tk: v for tk, v in tstore.items() if tk in legs0}
    trades = {tk: v["t"] for tk, v in tstore.items()}

    legs, events, charged = build_structures(evs, H, prev_q, trades, info, now_ns)
    lookup = mp.category_lookup()
    for s_, c in cache.items():
        if s_ not in lookup and c.get("category"):
            lookup[s_] = c["category"]
    cand = candidates_at(legs, events, charged, H)
    rows, keys, pred = score_rows(legs, events, charged, lookup, H, cand, model, cats)
    scores, share = arm_scores(keys, pred, H)

    published = load_state("published.pkl", set())
    sig, now_pub = build_signals(scores, published, snap_ns)
    stamp = dt.datetime.fromtimestamp(H / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H")
    (LIVE_DIR / "scores").mkdir(parents=True, exist_ok=True)
    (LIVE_DIR / "payloads").mkdir(parents=True, exist_ok=True)
    if rows:
        df = pl.DataFrame([{**{f: r[f] for f in mp.FEATS_G if f != "cat_i"}, "cat": r["cat"], "event": kk[0],
                            "ticker": kk[1], "bid_c": kk[4], "ask_c": kk[5], "pred_c": float(p),
                            "rnd_c": scores[(kk[1], kk[2])]["rnd"], "H_ns": H, "snap_ns": snap_ns}
                           for r, kk, p in zip(rows, keys, pred)])
        df.write_parquet(LIVE_DIR / "scores" / f"scores_{stamp}.parquet")
    (LIVE_DIR / "payloads" / f"signals_{stamp}.json").write_text(json.dumps(sig))

    sent = None
    if args.publish:
        pat = Path(args.pat_file).expanduser().read_text().strip()
        import requests
        sent = []
        for i in range(0, len(sig), args.batch):
            body = envelope(sig[i:i + args.batch], pat, f"gbt-{stamp}-{i // args.batch}")
            r = requests.post(SUBMIT_URL, json=body, headers={"Authorization": f"Bearer {pat}"}, timeout=60)
            sent.append((r.status_code, r.text[:200]))
        if all(c == 200 for c, _ in sent):
            save_state("published.pkl", now_pub)
    save_state("snaps.pkl", snaps)
    save_state("trades.pkl", tstore)

    n_sel = int(np.sum(pred > THRESHOLD_C)) if len(pred) else 0
    summary = {"H": stamp, "events": len(evs), "legs": len(legs), "candidates": len(cand), "scored": len(rows),
               "gbt_selected": n_sel, "share": round(share, 4), "signal_rows": len(sig),
               "q24h_known": len(prev_q), "trade_legs": len(trades), "api_calls": k.calls,
               "secs": round(time.time() - t0, 1), "model_sha1": meta.get("model_sha1"),
               "published": sent if sent is not None else "dry-run"}
    print(json.dumps(summary))
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
    tt = np.array([H - 25 * H_NS, H - 23 * H_NS, H - 1, H, H + 1], np.int64)
    legs, events, charged = build_structures([ev], H, {"A": (0.30, 0.34)}, {"A": tt}, info, H)

    cand = candidates_at(legs, events, charged, H)
    got = sorted((c[1], int(c[3]), int(c[4])) for c in cand)
    check(f"candidates from the simulator's own logic: {got}",
          got == [("A", -1, 43), ("A", 1, 41), ("B", -1, 32), ("B", 1, 30)])

    lookup = {"KXHIGHLAX": "Climate and Weather"}
    r = mp.quote_features(legs, events, charged, lookup, s.month_of(H), "KXHIGHLAX-26OCT05", "A", H, 1, 41)
    check("mid / spread / price relative to mid", r["mid"] == 42 and r["spread"] == 4 and r["rel_price"] == -1)
    check("24h mid change from the stored H-24h quote (42 - 32 = 10)", abs(r["dmid_24h"] - 10) < 1e-9)
    check("trades counted in (H-24h, H] only", r["trades_24h"] == 3)
    check("basket context: 5 legs, all 5 quoted (D's one-sided book counts), sum and second mid",
          r["n_legs"] == 5 and r["n_quoted"] == 5 and abs(r["basket_sum"] - 148.5) < 1e-9
          and abs(r["second_mid"] - 52.5) < 1e-9)
    check("no 24h quote stored -> dmid missing (as in the backtest)",
          np.isnan(mp.quote_features(legs, events, charged, lookup, s.month_of(H), "KXHIGHLAX-26OCT05", "B", H, 1, 30)["dmid_24h"]))
    check("fee status: quadratic series is taker-only (not charged)", not charged("KXHIGHLAX", "2026-10"))
    _, _, ch2 = build_structures([ev], H, {}, {}, {"KXHIGHLAX": {"fee_type": "quadratic_with_maker_fees"}}, H)
    check("fee status: maker-fee series is charged", ch2("KXHIGHLAX", "2026-10"))

    check("basket rule: 3 single-winner settled events qualify", series_rule([1, 1, 1]))
    check("basket rule: only 2 known events do not", not series_rule([1, 1, None]))
    check("basket rule: any event with 2 winners revokes", not series_rule([1, 1, 1, 2]))
    check("basket rule: any event with 0 winners revokes", not series_rule([1, 0, 1, 1]))
    check("event filter: combos and 2-leg events excluded",
          not event_ok({**ev, "series_ticker": "KXMVECROSS"}) and not event_ok({**ev, "markets": ev["markets"][:2]})
          and event_ok(ev) and not event_ok({**ev, "mutually_exclusive": False}))

    keys = [("E1", "A", 1, 41, 40, 44), ("E1", "A", -1, 43, 40, 44), ("E1", "B", 1, 30, 30, 32), ("E1", "B", -1, 32, 30, 32)]
    sc, share = arm_scores(keys, np.array([3.0, -2.0, 0.5, 1.5]), H)
    check("random arm uses G's posting share this hour (2 of 4 = 0.5)", share == 0.5)
    sc2, _ = arm_scores(keys, np.array([3.0, -2.0, 0.5, 1.5]), H)
    check("random arm is reproducible for the same hour", sc == sc2)
    check("quote-everything arm selects every candidate", all(v["cand"] == SELECTED_C for v in sc.values()))
    rows, now = build_signals(sc, {"A", "Z"}, H + 5)
    z = [r for r in rows if r["instrument_id"] == "Z"]
    check("a leg dropped since last hour gets the sentinel on all 6 signals",
          len(z) == 6 and all(r["score_ticks"] == to_ticks(SENTINEL_C) for r in z))
    g = {r["signal_name"]: r["score_ticks"] for r in rows if r["instrument_id"] == "A"}
    check("score scale: 3.0c -> 300 ticks; -2.0c -> -200", g["gbt_bid"] == 300 and g["gbt_ask"] == -200)
    check("ts_event_ns is the snapshot time, not the scoring time", all(r["ts_event_ns"] == H + 5 for r in rows))
    check("6 signals per published leg", len(rows) == 6 * 3)
    env = envelope(rows[:2], "PAT", "m1")
    check("envelope carries topic and the PAT owner credential",
          env["records"][0]["topic"] == "signal.publish" and env["records"][0]["payload"]["auth"]["pat"] == "PAT")

    blob = pickle.loads(mp.model_path("G").read_bytes())
    rr, kk, pp = score_rows(legs, events, charged, lookup, H, cand, blob["model"], blob["cats"])
    check(f"frozen G scores every candidate with a finite prediction ({len(pp)})", len(pp) == 4 and np.isfinite(pp).all())
    check("unknown category maps to -1, as in the test-month scoring",
          mp.to_matrix([{**rr[0], "cat": "Economics"}], blob["cats"])[0, -1] == -1)
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
            nxt = hour_floor(time.time_ns()) + H_NS + 60 * 1_000_000_000
            time.sleep(max(30, (nxt - time.time_ns()) / 1e9))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
