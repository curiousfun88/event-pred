"""
cut_report.py

FORWARD-TEST CUT REPORT (pre-registration section 6 metrics, plus descriptive market-making metrics).

Reads the live ledger (runs/live/paper/ledger/entries), the settlement cache (runs/live/paper/markets.pkl)
and the logged hourly scores, and for a cut (fills quoted before `--cut`, events settled by `--settle-by`)
reports for every arm and fill stream:

  verdict figures   net P&L after fees (settled events), return on capital, event-cluster 95% CI and
                    one-sided lower bound, net c/contract, fills, events, fees paid
  risk (section 6)  daily series from the ledger's total P&L (realised + marked) at each UTC day's end,
                    divided by peak capital in open positions; annualised return and volatility (365 days),
                    Sharpe over the 3-month T-bill (FRED DTB3), maximum drawdown of the hourly total-P&L curve,
                    correlation with SPY daily returns; SPY and T-bill returns over the same dates
  market making     fill rate (filled orders / posted orders), hit rate (share of settled fills with
                    positive net), profit concentration (share of net from the 10 best events), peak capital,
                    1-hour markout per contract (mid one hour later vs fill price)

All P&L is net of Kalshi maker fees. Live hours only (>= the ledger's live start). Descriptive except the
verdict figures, which follow sections 5 and L8.

USAGE (from repo root; LIVE_DIR may point at a copy of the sandbox's runs/live):
    python stg_infra/cut_report.py --self-test
    python stg_infra/cut_report.py --cut 2026-10-28T00 --settle-by 2026-10-30T00 [--out results/live/cut_interim.json]
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import os
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
sys.path.insert(0, str(_THIS))

H_NS = 3_600_000_000_000
DAY_NS = 24 * H_NS
LIVE = Path(os.environ.get("LIVE_DIR", _REPO / "runs/live"))
LEDGER = LIVE / "paper" / "ledger"
STREAMS = ("primary", "primary_opt", "primary_strict", "sensitivity")


def ns_of(stamp: str) -> int:
    return int(dt.datetime.strptime(stamp, "%Y%m%dT%H").replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9


# ---------------------------------------------------------------- ledger reading

def read_ledger(d: Path):
    """(live_start_ns, {(stream, arm): [fill keys]}, [(H_ns, {stream: {arm: total_usd}})]) from the entries."""
    fills, curve = {}, []
    st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
    start = st.get("start_H")
    for p in sorted((d / "entries").glob("*.json")):
        e = json.loads(p.read_text())
        start = start or ns_of(e["live_start"])
        for w, arms in e.get("new_fills", {}).items():
            for a, rows in arms.items():
                fills.setdefault((w, a), []).extend(tuple(r) for r in rows)
        curve.append((int(e["H_ns"]), {w: {a: c["total_usd"] for a, c in arms.items()} for w, arms in e["cumulative"].items()}))
    return start, fills, curve


# ---------------------------------------------------------------- metrics (pure, self-tested)

def settle_times(markets: dict) -> dict:
    """{event: time all its legs settled (ns) or None}, from the settlement cache."""
    by_ev = {}
    for tk, m in markets.items():
        by_ev.setdefault(tk.rsplit("-", 1)[0], []).append(m)
    out = {}
    for ev, ms in by_ev.items():
        ok = all(m.get("result") in ("yes", "no") and m.get("settled_ns") for m in ms)
        out[ev] = max(m["settled_ns"] for m in ms) if ok else None
    return out


def is_weather_key(k) -> bool:
    """Weather series (`KXHIGH*`/`KXLOW*`), from the ledger key's event ticker."""
    return str(k[0]).split("-")[0].startswith(("KXHIGH", "KXLOW"))


def universe_splits(keys, results, settled_at, settle_by, mid_next):
    """L11: verdict figures for the weather and non-weather parts of the primary universe (descriptive only)."""
    out = {}
    for name, keep in (("non_weather", lambda k: not is_weather_key(k)), ("weather", is_weather_key)):
        m = fill_metrics([k for k in keys if keep(k)], results, settled_at, settle_by, mid_next)
        m.pop("_done", None)
        out[name] = m
    return out


def fill_metrics(keys, results: dict, settled_at: dict, settle_by: int, mid_next: dict):
    """Verdict and market-making figures from ledger fill keys (event, ticker, side, price, qty, fee, capital, H)."""
    import paper_ledger as pl_
    import paper_trader as pt
    F = [pl_.as_fill(k, results.get(k[1])) for k in keys]
    done = [f for f in F if settled_at.get(f[0]) is not None and settled_at[f[0]] <= settle_by]
    net = sum(f[6] for f in done); cap = sum(f[7] for f in done); qty = sum(f[4] for f in done)
    by_ev = {}
    for f in done:
        by_ev[f[0]] = by_ev.get(f[0], 0.0) + f[6]
    top10 = sum(sorted(by_ev.values(), reverse=True)[:10])
    mk = [(int(f[2]) * (mid_next[(f[1], int(f[9]))] - int(f[3])) * int(f[4]), int(f[4])) for f in F if (f[1], int(f[9])) in mid_next]
    vs = pt.verdict_stats(done)
    return {"fills": len(F), "settled_fills": len(done), "events": len(by_ev), "net_usd": net / 100,
            "capital_usd": cap / 100, "return_pct": 100 * net / cap if cap else float("nan"),
            "net_c_per_contract": net / qty if qty else float("nan"), "fees_usd": sum(f[5] for f in F) / 100,
            "hit_rate": float(np.mean([f[6] > 0 for f in done])) if done else float("nan"),
            "top10_event_share": top10 / net if net > 0 else float("nan"),
            "markout_c_per_contract": sum(m for m, _ in mk) / sum(q for _, q in mk) if mk else float("nan"),
            "ci": vs["event"], "ci_day_clusters": vs["day"], "_done": done}


def peak_open_capital(keys, settled_at: dict, days) -> float:
    """Largest capital (USD) in open positions at any day end: fills quoted by then, events not yet settled."""
    best = 0.0
    for d_end in days:
        cap = sum(float(k[6]) for k in keys if int(k[7]) < d_end and (settled_at.get(k[0]) is None or settled_at[k[0]] > d_end))
        best = max(best, cap)
    return best / 100


def daily_series(curve, stream, arm, start, cut):
    """End-of-day total P&L (USD) per UTC day from the hourly ledger curve, live hours before the cut."""
    pts = [(H, c.get(stream, {}).get(arm)) for H, c in curve if start <= H < cut and c.get(stream, {}).get(arm) is not None]
    days = {}
    for H, v in pts:
        days[(H + H_NS) // DAY_NS] = v          # value recorded for hour H is known at H+1h
    ks = sorted(days)
    return [k * DAY_NS + DAY_NS for k in ks], [days[k] for k in ks]


def max_drawdown(values):
    """Largest fall (USD) from a running peak of a P&L curve (peak starts at 0)."""
    peak, mdd = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        mdd = max(mdd, peak - v)
    return mdd


def risk_metrics(day_totals, capital, rf_annual=None, spy_daily=None):
    """Daily returns = change in total P&L / capital. Annualised over 365 days (Kalshi trades every day)."""
    tot = np.asarray(day_totals, float)
    if len(tot) < 2 or not capital:
        return {"days": len(tot)}
    r = np.diff(np.concatenate([[0.0], tot])) / capital
    out = {"days": len(r), "ann_return_pct": 100 * r.mean() * 365, "ann_vol_pct": 100 * r.std(ddof=1) * np.sqrt(365)}
    rf = (rf_annual or 0.0) / 365
    sd = r.std(ddof=1)
    out["sharpe"] = float((r.mean() - rf) / sd * np.sqrt(365)) if sd > 0 else float("nan")
    out["short_sample_warning"] = len(r) < 60
    if spy_daily is not None:
        a, b = np.asarray(spy_daily[0], float), np.asarray(spy_daily[1], float)
        if len(a) >= 3 and np.std(a) > 0 and np.std(b) > 0:
            out["corr_spy"] = float(np.corrcoef(a, b)[0, 1])
    return out


PRICE_BANDS = ((1, 15), (15, 50), (50, 85), (85, 99))
PRED_BUCKETS = ((-1e9, 1.0), (1.0, 2.0), (2.0, 4.0), (4.0, 8.0), (8.0, 1e9))


def _rank(x):
    x = np.asarray(x, float)
    r = np.empty(len(x)); r[np.argsort(x, kind="stable")] = np.arange(len(x))
    return r


def behaviour_metrics(F, pred=None, mid_at=None, settle_ns=None):
    """Descriptive market-making and model metrics from valued fill tuples
    (event, ticker, side, price, qty, fee, net, capital, markout, H). Settled fills only for P&L items (pass them in);
    pred: predicted net c/contract per fill (model arms); mid_at(ticker, H) -> mid (cents) or None;
    settle_ns: {event: ns}. All c/contract figures are contract-weighted."""
    out = {}
    if not F:
        return out
    qty = np.array([f[4] for f in F], float)
    net_pc = np.array([f[6] / f[4] for f in F], float)
    wins = [f[6] for f in F if f[6] > 0]; losses = [-f[6] for f in F if f[6] < 0]
    out["profit_factor"] = sum(wins) / sum(losses) if losses else float("inf")
    out["avg_win_usd"] = float(np.mean(wins)) / 100 if wins else 0.0
    out["avg_loss_usd"] = float(np.mean(losses)) / 100 if losses else 0.0
    out["hit_rate"] = len(wins) / len(F)
    bands = {}
    for lo, hi in PRICE_BANDS:
        sub = [f for f in F if lo <= f[3] < hi or (hi == 99 and f[3] == 99)]
        cap = sum(f[7] for f in sub)
        bands[f"{lo}-{hi}c"] = {"fills": len(sub), "net_usd": sum(f[6] for f in sub) / 100,
                                "return_pct": 100 * sum(f[6] for f in sub) / cap if cap else float("nan")}
    out["by_price_band"] = bands
    if pred is not None and len(pred) == len(F):
        pr = np.asarray(pred, float)
        cal = []
        for lo, hi in PRED_BUCKETS:
            m = (pr > lo) & (pr <= hi)
            if m.any():
                cal.append({"pred_range_c": [lo, hi], "fills": int(m.sum()), "mean_pred_c": float(np.average(pr[m], weights=qty[m])),
                            "mean_realised_c": float(np.average(net_pc[m], weights=qty[m]))})
        out["calibration"] = cal
        out["rank_corr_pred_realised"] = float(np.corrcoef(_rank(pr), _rank(net_pc))[0, 1]) if len(F) > 2 and pr.std() > 0 else float("nan")
    # settlement markout = gross c/contract at settlement (net + fee): the price move from fill to payoff
    out["markout_settlement_c"] = float(np.average([(f[6] + f[5]) / f[4] for f in F], weights=qty))
    if mid_at is not None:
        def mk(h):
            v = [(f[2] * (m - f[3]), f[4]) for f in F for m in [mid_at(f[1], int(f[9]) + h)] if m is not None]
            return float(np.average([a for a, _ in v], weights=[b for _, b in v])) if v else float("nan")
        out["spread_capture_c"] = mk(0)          # mid at the quoting hour minus fill price, signed by side
        out["markout_1h_c"] = mk(H_NS)
        out["markout_24h_c"] = mk(24 * H_NS)
    if settle_ns is not None:
        hp = [(settle_ns[f[0]] - int(f[9])) / H_NS for f in F if settle_ns.get(f[0])]
        out["holding_hours_median"] = float(np.median(hp)) if hp else float("nan")
    days = {}
    for f in F:
        d = int(f[9]) // DAY_NS
        days[d] = days.get(d, 0.0) + f[6]
    vals = [days[k] for k in sorted(days)]
    out["profitable_days_share"] = float(np.mean([v > 0 for v in vals])) if vals else float("nan")
    streak = best = 0
    for v in vals:
        streak = streak + 1 if v < 0 else 0
        best = max(best, streak)
    out["longest_losing_streak_days"] = best
    out["tradedate_days"] = len(vals)
    return out


def mean_abs_position(F, settle_ns, t0, t1):
    """MAP (contracts): time-average over [t0, t1) of the summed absolute inventory across legs. A fill adds
    side*qty to its leg from its quoting hour until its event settles (or t1 if unsettled). Market-making
    convention (Spooner et al. 2018), summed over the many legs traded."""
    if t1 <= t0:
        return float("nan")
    changes = {}
    for f in F:
        a = max(int(f[9]), t0)
        b = min(settle_ns.get(f[0]) or t1, t1)
        if b <= a:
            continue
        changes.setdefault(f[1], []).extend([(a, int(f[2]) * int(f[4])), (b, -int(f[2]) * int(f[4]))])
    area = 0.0
    for ch in changes.values():
        ch.sort()
        pos, last = 0, ch[0][0]
        for t, d in ch:
            area += abs(pos) * (t - last)
            pos += d; last = t
    return area / (t1 - t0)


def conventional_metrics(F, settle_ns, spread_at, t0, t1):
    """Conventional market-making metrics: MAP, PnL-to-MAP (USD per contract of average inventory) and
    normalised daily PnL (each day's net P&L / mean quoted spread of that day's fills, averaged over days)."""
    out = {"map_contracts": mean_abs_position(F, settle_ns, t0, t1)}
    net = sum(f[6] for f in F) / 100
    out["pnl_to_map_usd"] = net / out["map_contracts"] if out["map_contracts"] and out["map_contracts"] == out["map_contracts"] else float("nan")
    days = {}
    for f in F:
        sp = spread_at(f[1], int(f[9])) if spread_at else None
        d = days.setdefault(int(f[9]) // DAY_NS, [0.0, []])
        d[0] += f[6]
        if sp:
            d[1].append(sp)
    npnl = [v / np.mean(sp) for v, sp in days.values() if sp]
    out["normalised_daily_pnl_spreads"] = float(np.mean(npnl)) if npnl else float("nan")
    return out


def tradedate_series(F):
    """(day_end_ns list, cumulative net USD) by trade date: each fill's final net on the day it was quoted."""
    days = {}
    for f in F:
        d = int(f[9]) // DAY_NS
        days[d] = days.get(d, 0.0) + f[6] / 100
    ks = sorted(days)
    return [k * DAY_NS + DAY_NS for k in ks], list(np.cumsum([days[k] for k in ks]))


# ---------------------------------------------------------------- benchmarks

def fetch_spy_and_tbill(lo: dt.date, hi: dt.date):
    """SPY daily closes (Stooq, split-adjusted close) and the mean 3-month T-bill rate (FRED DTB3) over [lo, hi]."""
    import requests
    out = {}
    try:
        t = requests.get("https://stooq.com/q/d/l/?s=spy.us&i=d", timeout=60, headers={"User-Agent": "fyp-cut-report"}).text
        rows = [l.split(",") for l in t.strip().splitlines()[1:]]
        px = {dt.date.fromisoformat(r[0]): float(r[4]) for r in rows if len(r) > 4 and r[4]}
        days = sorted(d for d in px if lo <= d <= hi)
        out["spy_close"] = {d.isoformat(): px[d] for d in days}
        if len(days) >= 2:
            out["spy_return_pct"] = 100 * (px[days[-1]] / px[days[0]] - 1)
    except Exception as e:
        out["spy_error"] = repr(e)[:200]
    if "spy_close" not in out or len(out["spy_close"]) < 2:
        try:    # fallback: FRED's S&P 500 price index (no dividends; about 0.1 pt/month below SPY's total return)
            t = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=SP500", timeout=60).text
            rows = [l.split(",") for l in t.strip().splitlines()[1:]]
            px = {dt.date.fromisoformat(r[0]): float(r[1]) for r in rows if len(r) > 1 and r[1] not in (".", "")}
            days = sorted(d for d in px if lo <= d <= hi)
            out["spy_close"] = {d.isoformat(): px[d] for d in days}
            out["index_source"] = "FRED SP500 (price index, no dividends)"
            out.pop("spy_error", None)
            if len(days) >= 2:
                out["spy_return_pct"] = 100 * (px[days[-1]] / px[days[0]] - 1)
        except Exception as e:
            out["spy_error"] = repr(e)[:200]
    else:
        out["index_source"] = "Stooq SPY close"
    try:
        t = requests.get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3", timeout=60).text
        vals = [float(r.split(",")[1]) for r in t.strip().splitlines()[1:]
                if r.split(",")[1] not in (".", "") and lo <= dt.date.fromisoformat(r.split(",")[0]) <= hi]
        if vals:
            out["tbill_rate_pct"] = float(np.mean(vals))
            out["tbill_return_pct"] = out["tbill_rate_pct"] * (hi - lo).days / 365
    except Exception as e:
        out["tbill_error"] = repr(e)[:200]
    return out


# ---------------------------------------------------------------- report

def mids_next_hour(hours):
    """{(ticker, H): mid one hour after H (cents)} from the logged scores (both candidate files)."""
    import paper_trader as pt
    one, two = pt.load_scores(hours)
    out = {}
    for d in (one, two):
        if d is None:
            continue
        for tk, H, b, a in zip(d["ticker"].to_list(), d["H_ns"].to_list(), d["bid_c"].to_list(), d["ask_c"].to_list()):
            out[(tk, int(H) - H_NS)] = (b + a) / 2
    return out


def arm_score_maps(hours):
    """{arm: {order key: score}} for every arm in the given hours (the paper trader's own arm_scores)."""
    import paper_trader as pt
    import train_baselines as tb
    import retrain_g2 as rg
    one, two = pt.load_scores(hours)
    base = {"lin2": pickle.loads(tb.model_path("lin2").read_bytes()), "mlp2": pickle.loads(tb.model_path("mlp2").read_bytes()),
            "g2w1": pickle.loads(rg.model_path("W1", "G2").read_bytes()), "g2w2": pickle.loads(rg.model_path("W2", "G2").read_bytes())}
    return pt.arm_scores(one, two, base)


MODEL_ARMS = ("g", "g2", "g2p", "lin2", "mlp2", "g2w1", "g2w2", "g2_sel")


def posted_orders(hours):
    """{arm: number of posted orders (ticker, H, side[, price])} in the given hours, from the logged scores."""
    import paper_trader as pt
    import train_baselines as tb
    import retrain_g2 as rg
    one, two = pt.load_scores(hours)
    base = {"lin2": pickle.loads(tb.model_path("lin2").read_bytes()), "mlp2": pickle.loads(tb.model_path("mlp2").read_bytes()),
            "g2w1": pickle.loads(rg.model_path("W1", "G2").read_bytes()), "g2w2": pickle.loads(rg.model_path("W2", "G2").read_bytes())}
    sc = pt.arm_scores(one, two, base)
    return {a: int(sum(1 for v in s.values() if v > pt.THRESHOLD_C)) for a, s in sc.items()}


def build(cut: str, settle_by: str, bench=True):
    import paper_trader as pt
    start, fills, curve = read_ledger(LEDGER)
    if start is None:
        raise SystemExit("no ledger entries: the live test has not started")
    cut_ns, settle_ns = ns_of(cut), ns_of(settle_by)
    markets = pickle.loads((LIVE / "paper" / "markets.pkl").read_bytes())
    results = {tk: m.get("result") for tk, m in markets.items()}
    settled_at = settle_times(markets)
    hours = [h for h in pt.scored_hours(dt.datetime.fromtimestamp(start / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H"))
             if ns_of(h) < cut_ns]
    mid_next = mids_next_hour(hours + [dt.datetime.fromtimestamp(cut_ns / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H")])
    smaps = arm_score_maps(hours)
    posted = {a: int(sum(1 for v in m.values() if v > pt.THRESHOLD_C)) for a, m in smaps.items()}
    later = [dt.datetime.fromtimestamp((ns_of(h) + k * H_NS) / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H")
             for h in hours[-1:] for k in range(1, 26)]
    one_all, two_all = pt.load_scores(sorted(set(hours) | {h for h in later if (pt.LIVE / "scores" / f"one_{h}.parquet").exists()}))
    mid_tab = {}
    for d in (one_all, two_all):
        if d is not None:
            for tk, H, b_, a_ in zip(d["ticker"].to_list(), d["H_ns"].to_list(), d["bid_c"].to_list(), d["ask_c"].to_list()):
                mid_tab[(tk, int(H))] = (b_ + a_) / 2
    mid_at = lambda tk, H: mid_tab.get((tk, H))
    spr_tab = {}
    for d in (one_all, two_all):
        if d is not None:
            for tk, H, b_, a_ in zip(d["ticker"].to_list(), d["H_ns"].to_list(), d["bid_c"].to_list(), d["ask_c"].to_list()):
                spr_tab[(tk, int(H))] = a_ - b_
    spread_at = lambda tk, H: spr_tab.get((tk, H))
    lo, hi = dt.datetime.fromtimestamp(start / 1e9, dt.timezone.utc).date(), dt.datetime.fromtimestamp(cut_ns / 1e9, dt.timezone.utc).date()
    bm = fetch_spy_and_tbill(lo, hi) if bench else {}
    spy = bm.get("spy_close", {})
    spy_days = sorted(spy)
    spy_ret = {spy_days[i]: spy[spy_days[i]] / spy[spy_days[i - 1]] - 1 for i in range(1, len(spy_days))}
    rep = {"cut": cut, "settle_by": settle_by, "live_start": dt.datetime.fromtimestamp(start / 1e9, dt.timezone.utc).isoformat(),
           "hours": len(hours), "benchmarks": {k: v for k, v in bm.items() if k != "spy_close"}, "arms": {}}
    for (w, a), keys in sorted(fills.items()):
        keys = [k for k in keys if start <= int(k[7]) < cut_ns]
        m = fill_metrics(keys, results, settled_at, settle_ns, mid_next)
        done = m.pop("_done")
        smap = smaps.get("g2" if a == "g2_sel" else a, {})
        pred = None
        if a in MODEL_ARMS and smap:
            two_level = a in ("g2p",)
            pred = [smap.get((f[1], int(f[9]), int(f[2]), int(f[3])) if two_level else (f[1], int(f[9]), int(f[2])), np.nan) for f in done]
            pred = None if np.isnan(pred).any() else pred
        m["behaviour"] = behaviour_metrics(done, pred, mid_at, settled_at)
        import paper_ledger as pl_
        allf = [pl_.as_fill(k, results.get(k[1])) for k in keys]
        m["conventional"] = conventional_metrics(allf, {e: t for e, t in settled_at.items() if t is not None},
                                                 spread_at, start, cut_ns)
        m["conventional"]["pnl_to_map_usd"] = m["net_usd"] / m["conventional"]["map_contracts"] if m["conventional"]["map_contracts"] else float("nan")
        m["conventional"]["normalised_daily_pnl_spreads"] = conventional_metrics(done, {}, spread_at, start, cut_ns)["normalised_daily_pnl_spreads"]
        filled_orders = len({(k[1], k[7], k[2], k[3]) for k in keys})
        if w == "primary" and posted.get(a):
            m["fill_rate"] = filled_orders / posted[a]
            m["posted_orders"] = posted[a]
        day_ends, totals = daily_series(curve, w, a, start, cut_ns)
        cap = peak_open_capital(keys, settled_at, day_ends)
        m["peak_open_capital_usd"] = cap
        m["max_drawdown_usd"] = max_drawdown([c.get(w, {}).get(a, 0.0) for H, c in curve if start <= H < cut_ns])
        m["max_drawdown_pct_of_peak_capital"] = 100 * m["max_drawdown_usd"] / cap if cap else float("nan")
        pair = None
        if spy_ret:
            dates = [dt.datetime.fromtimestamp((de - DAY_NS) / 1e9, dt.timezone.utc).date().isoformat() for de in day_ends]
            dd = np.diff(np.concatenate([[0.0], totals]))
            both = [(spy_ret[d_], v / cap) for d_, v in zip(dates, dd) if d_ in spy_ret and cap]
            pair = ([x for x, _ in both], [y for _, y in both]) if both else None
        m["risk"] = risk_metrics(totals, cap, bm.get("tbill_rate_pct", 0.0) / 100 if bm.get("tbill_rate_pct") else None, pair)
        td_ends, td_cum = tradedate_series(done)          # L11: same daily definition as the 2025 results
        m["risk_tradedate"] = risk_metrics(td_cum, cap, bm.get("tbill_rate_pct", 0.0) / 100 if bm.get("tbill_rate_pct") else None)
        m["max_drawdown_tradedate_usd"] = max_drawdown(td_cum)
        m["splits"] = universe_splits(keys, results, settled_at, settle_ns, mid_next)   # L11: descriptive
        rep["arms"].setdefault(w, {})[a] = m
    return rep


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    import tempfile
    import paper_ledger as pl_
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    check("max drawdown: peak 5 then down to 1 -> 4", max_drawdown([1, 5, 3, 1, 4]) == 4)
    check("max drawdown of a curve that only falls from 0", max_drawdown([-2, -3]) == 3)
    r = risk_metrics([1.0, 2.0, 3.0, 4.0], 100.0, rf_annual=0.0)
    check("constant daily gain: zero volatility -> Sharpe undefined, return 1%/day x 365", np.isnan(r["sharpe"]) and abs(r["ann_return_pct"] - 365) < 1e-9)
    r2 = risk_metrics([1.0, 0.0, 2.0, 1.0, 3.0], 100.0, rf_annual=0.05)
    check("Sharpe subtracts the T-bill and annualises with sqrt(365); short-sample flagged",
          abs(r2["sharpe"] - ((np.mean([1, -1, 2, -1, 2]) / 100 - 0.05 / 365) / (np.std([1, -1, 2, -1, 2], ddof=1) / 100) * np.sqrt(365))) < 1e-9
          and r2["short_sample_warning"])
    H0 = ns_of("20261020T10")
    curve = [(H0, {"primary": {"g2": 1.0}}), (H0 + 5 * H_NS, {"primary": {"g2": 3.0}}), (H0 + 20 * H_NS, {"primary": {"g2": 2.0}})]
    de, tot = daily_series(curve, "primary", "g2", H0, H0 + 30 * H_NS)
    check("daily series: last value of each UTC day (20 Oct ends at 3.0, 21 Oct at 2.0)", tot == [3.0, 2.0] and len(de) == 2)
    keys = [("E1", "E1-A", 1, 40, 10, 2.0, 400.0, H0), ("E2", "E2-A", -1, 70, 10, 0.0, 300.0, H0),
            ("E3", "E3-A", 1, 50, 10, 0.0, 500.0, H0 + H_NS)]
    res = {"E1-A": "yes", "E2-A": "yes", "E3-A": None}
    st = {"E1": H0 + 2 * H_NS, "E2": H0 + 3 * H_NS, "E3": None}
    m = fill_metrics(keys, res, st, H0 + 10 * H_NS, {("E1-A", H0): 45.0})
    # E1: bought YES 40, settles YES: +600 - 2 = 598; E2: sold YES 70, settles YES: -300; E3 open
    check(f"net after fees over settled events only (+$2.98, got {m['net_usd']:.2f})", abs(m["net_usd"] - 2.98) < 1e-9)
    check("hit rate = share of settled fills with positive net (1 of 2)", m["hit_rate"] == 0.5)
    check("fees summed over all fills ($0.02)", abs(m["fees_usd"] - 0.02) < 1e-9)
    check("markout: +1 x (45 - 40) = +5c per contract over the fill with a next-hour mid", m["markout_c_per_contract"] == 5.0)
    check("concentration: top events' share of net", abs(m["top10_event_share"] - 1.0) < 1e-9)
    kw = keys + [("KXHIGHNY-26OCT20", "KXHIGHNY-26OCT20-B70", 1, 30, 10, 1.0, 300.0, H0)]
    resw, stw = {**res, "KXHIGHNY-26OCT20-B70": "no"}, {**st, "KXHIGHNY-26OCT20": H0 + 4 * H_NS}
    sp = universe_splits(kw, resw, stw, H0 + 10 * H_NS, {})
    check("L11 splits: weather = the KXHIGH fill only (-$3.01), non-weather = the rest (+$2.98)",
          abs(sp["weather"]["net_usd"] + 3.01) < 1e-9 and abs(sp["non_weather"]["net_usd"] - 2.98) < 1e-9
          and is_weather_key(kw[-1]) and not is_weather_key(kw[0]))
    cap = peak_open_capital(keys, st, [H0 + 2 * H_NS + 1, H0 + 4 * H_NS])
    check("peak open capital: E2 and E3 open after E1 settles ($8.00)", abs(cap - 8.0) < 1e-9)
    # behaviour metrics on planted fills: (event, ticker, side, price, qty, fee, net, capital, markout, H)
    Fb = [("E1", "A", 1, 40, 10, 0.0, 600.0, 400.0, 0.0, H0), ("E2", "B", -1, 90, 10, 10.0, -1010.0, 100.0, 0.0, H0 + DAY_NS),
          ("E3", "C", 1, 10, 10, 0.0, -100.0, 100.0, 0.0, H0 + 2 * DAY_NS)]
    mids = {("A", H0): 42.0, ("A", H0 + H_NS): 50.0, ("B", H0 + DAY_NS): 88.0}
    bm = behaviour_metrics(Fb, pred=[3.0, 1.5, 9.0], mid_at=lambda tk, H: mids.get((tk, H)), settle_ns={"E1": H0 + 5 * H_NS})
    check(f"profit factor = 600 / (1010 + 100) ({bm['profit_factor']:.3f})", abs(bm["profit_factor"] - 600 / 1110) < 1e-9)
    check("hit rate and average win/loss", bm["hit_rate"] == 1 / 3 and bm["avg_win_usd"] == 6.0 and abs(bm["avg_loss_usd"] - 5.55) < 1e-9)
    check("price bands: 85-99c holds the favourite sold at 90", bm["by_price_band"]["85-99c"]["fills"] == 1
          and bm["by_price_band"]["1-15c"]["fills"] == 1)
    check("spread capture: buy at 40 under a 42 mid (+2), sell at 90 over an 88 mid (+2)", bm["spread_capture_c"] == 2.0)
    check("1-hour markout uses the mid one hour later (+10 on A only)", bm["markout_1h_c"] == 10.0)
    check("settlement markout = gross c/contract ((600 - 1000 - 100) / 30)", abs(bm["markout_settlement_c"] - (600 - 1000 - 100) / 30) < 1e-9)
    check("holding period from fill to settlement (5 h)", bm["holding_hours_median"] == 5.0)
    check("profitable days 1 of 3, longest losing streak 2 days", abs(bm["profitable_days_share"] - 1 / 3) < 1e-9
          and bm["longest_losing_streak_days"] == 2)
    check("calibration buckets and rank correlation present", len(bm["calibration"]) == 3 and abs(bm["rank_corr_pred_realised"] - 0.5) < 1e-9)
    de2, cum = tradedate_series(Fb)
    check("trade-date series: cumulative net by quote day ($6, -$4.10, -$5.10)", np.allclose(cum, [6.0, -4.1, -5.1]))
    # conventional metrics: leg A long 10 for 2 h, leg B short 10 for 4 h, over an 8 h window
    Fc = [("E1", "A", 1, 40, 10, 0.0, 300.0, 400.0, 0.0, H0), ("E2", "B", -1, 60, 10, 0.0, -100.0, 400.0, 0.0, H0)]
    st_c = {"E1": H0 + 2 * H_NS, "E2": H0 + 4 * H_NS}
    check("MAP: (10 x 2 h + 10 x 4 h) / 8 h = 7.5 contracts", abs(mean_abs_position(Fc, st_c, H0, H0 + 8 * H_NS) - 7.5) < 1e-9)
    check("offsetting fills on one leg net to zero inventory",
          mean_abs_position([("E", "A", 1, 40, 10, 0, 0, 0, 0, H0), ("E", "A", -1, 45, 10, 0, 0, 0, 0, H0)], {"E": H0 + H_NS}, H0, H0 + H_NS) == 0)
    cm = conventional_metrics(Fc, st_c, lambda tk, H: 4.0, H0, H0 + 8 * H_NS)
    check("PnL-to-MAP = $2.00 / 7.5 contracts", abs(cm["pnl_to_map_usd"] - 2.0 / 7.5) < 1e-9)
    check("normalised daily PnL = 200c / 4c spread = 50 spreads", cm["normalised_daily_pnl_spreads"] == 50.0)
    mk = {"T1-A": {"result": "yes", "settled_ns": 5}, "T1-B": {"result": "no", "settled_ns": 9}, "T2-A": {"result": "", "settled_ns": None}}
    check("settle times by event from the cache", settle_times(mk) == {"T1": 9, "T2": None})
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        pl_.round_update(d, {"primary": {"g2": [pl_.as_fill(k, None) for k in keys[:2]]}}, H0, set(), {}, lambda H: dt.datetime.fromtimestamp(H / 1e9, dt.timezone.utc).strftime("%Y%m%dT%H"),
                         lambda live, s: {}, results={})
        s0, fl, cv = read_ledger(d)
        check("ledger reader recovers the live start, fills and curve", s0 == H0 and len(fl[("primary", "g2")]) == 2 and len(cv) == 1)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cut", help="first hour NOT included, YYYYmmddTHH (UTC)")
    ap.add_argument("--settle-by", help="events settled by this hour count, YYYYmmddTHH (UTC)")
    ap.add_argument("--no-benchmarks", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    rep = build(a.cut.replace("-", "").replace(":", ""), a.settle_by.replace("-", "").replace(":", ""), not a.no_benchmarks)
    txt = json.dumps(rep, indent=1, default=float)
    if a.out:
        Path(a.out).write_text(txt)
    print(txt)


if __name__ == "__main__":
    main()
