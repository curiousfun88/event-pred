"""
retrain_g2.py

RETRAINED POLICY G2 (maker pre-registration, amendment A13): train one model per
candidate window, validate each on 2026-09-07..10-04, select by the fixed rule.

Everything except the training months is G's: candidates from the BROAD config,
features from maker_policy.quote_features, maker_policy.HP, target = net
c/contract at settlement after fees (pessimistic fills), threshold 1c.

DATA. 2024-11..2025-11: the cached BROAD pessimistic fills (dev + test months)
and simulate_maker.load for features. 2025-12..2026-08: Kalshi API compact cache
(fetch_kalshi_api_months.py). Validation: the smoke-test cache. All restricted to
the 23 A13 series; training events must have resolved with exactly one YES.

USAGE (from repo root, memory-capped):
    python stg_infra/examples/retrain_g2.py --self-test
    python stg_infra/examples/retrain_g2.py train W1        # W1 | W2 | W3
    python stg_infra/examples/retrain_g2.py validate         # every trained window + selection
    python stg_infra/examples/retrain_g2.py timeline         # descriptive: monthly quote-everything 2025-12..2026-09
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

H_NS = 3_600_000_000_000
LOCAL = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
         "2025-08", "2025-09", "2025-10", "2025-11"]
API = ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
WINDOWS = {"W1": ["2026-06", "2026-07", "2026-08"],
           "W2": ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"],
           "W3": LOCAL + API}
VAL = ("2026-09-07", "2026-10-05")
OUTDIR = _REPO / "runs/maker"


def model_path(w):
    return OUTDIR / f"policy_G2_{w}_model.pkl"


def single_winner_events(legs, events):
    """Hindsight training curation: events whose legs resolved with exactly one YES."""
    return {ev: tks for ev, tks in events.items() if sum(bool(legs[t]["yes"]) for t in tks) == 1}


def api_legs(months, series):
    """Compact API cache -> simulate_maker (legs, events) for markets closing in `months`."""
    from fetch_kalshi_api_months import OUT
    legs, events = {}, {}
    for mo in months:
        for ser in series:
            p = OUT / f"{ser}_{mo}.pkl"
            if not p.exists():
                raise FileNotFoundError(f"missing API cache {p.name}: run fetch_kalshi_api_months.py")
            for r in pickle.loads(p.read_bytes()):
                legs[r["ticker"]] = {"event": r["event"], "series": ser, "yes": r["result"] == "yes",
                                     "close": int(r["close_ns"]), "e": r["e"], "bid": r["bid"].astype(float),
                                     "ask": r["ask"].astype(float), "tt": r["tt"], "tp": r["tp"].astype(float),
                                     "tc": r["tc"].astype(float), "ts": r["ts"].astype(float)}
                events.setdefault(r["event"], []).append(r["ticker"])
    return legs, events


def fee_charged(series_fee):
    mfee = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}
    return lambda series, month: series_fee.get(series) in mfee


def fills_to_rows(fl, legs, events, charged, lookup):
    """Simulator fill tuples -> (feature rows, y = net c/contract)."""
    import maker_policy as mp
    import simulate_maker as s
    rows, ys = [], []
    for f in fl:
        ev, tk, sd, pr, qty, net, H = f[0], f[1], f[2], f[3], f[4], f[6], int(f[9])
        r = mp.quote_features(legs, events, charged, lookup, s.month_of(H), ev, tk, H, int(sd), int(pr))
        if r is not None:
            rows.append(r); ys.append(net / qty)
    return rows, ys


def train(w):
    import maker_policy as mp
    import simulate_maker as s
    import live_signal_producer as lp
    from fetch_kalshi_api_months import SERIES_A13
    from sklearn.ensemble import HistGradientBoostingRegressor
    lookup = mp.category_lookup()
    months = WINDOWS[w]
    rows, ys = [], []
    loc = [m for m in months if m in LOCAL]
    if loc:
        from policy_G_audit import fills as cached_fills
        Fd = dict(np.load(OUTDIR / f"cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
        Ft = cached_fills(s.Config(**mp.BROAD), "pess", ["2025-08", "2025-09", "2025-10", "2025-11"])
        for mo in loc:
            legs, events, charged = s.load([mo], "mece")
            keep = {t for t, L in legs.items() if L["series"] in SERIES_A13}
            legs = {t: L for t, L in legs.items() if t in keep}
            events = {e: [t for t in tks if t in keep] for e, tks in events.items()}
            events = single_winner_events(legs, {e: tks for e, tks in events.items() if tks})
            F = Fd if mo <= "2025-07" else Ft
            sel = [i for i in range(len(F["hour_ns"])) if s.month_of(int(F["hour_ns"][i])) == mo
                   and F["event"][i] in events]
            fl = [(F["event"][i], F["ticker"][i], F["side"][i], F["price"][i], F["qty"][i], F["fee_c"][i],
                   F["net_c"][i], F["capital_c"][i], F["markout_c"][i], F["hour_ns"][i]) for i in sel]
            r, y = fills_to_rows(fl, legs, events, charged, lookup)
            rows += r; ys += y
            print(f"  {mo} (local): {len(r):,} training fills", flush=True)
    api = [m for m in months if m in API]
    if api:
        cache = lp.load_state("series.pkl", {})
        legs, events = api_legs(api, SERIES_A13)
        events = single_winner_events(legs, events)
        charged = fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES_A13})
        fl = s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, api)
        r, y = fills_to_rows(fl, legs, events, charged, lookup)
        rows += r; ys += y
        print(f"  {api[0]}..{api[-1]} (API): {len(r):,} training fills", flush=True)
    cats = sorted({r["cat"] for r in rows})
    X = mp.to_matrix(rows, cats)
    m = HistGradientBoostingRegressor(**mp.HP, categorical_features=[f == "cat_i" for f in mp.FEATS_G]).fit(X, np.array(ys))
    p = model_path(w)
    p.write_bytes(pickle.dumps({"model": m, "cats": cats, "feats": mp.FEATS_G}))
    sha = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    p.with_suffix(".json").write_text(json.dumps({"amendment": "A13", "window": w, "months": months, "n_train": len(ys),
                                                  "series": SERIES_A13, "hp": mp.HP, "threshold_c": 1.0,
                                                  "model_sha1": sha}, indent=1))
    print(f"trained G2-{w} on {len(ys):,} fills ({len(cats)} categories); sha1 {sha}")


def val_data():
    import live_signal_producer as lp
    import smoke_test_2026 as st
    from fetch_kalshi_api_months import SERIES_A13
    start = int(dt.datetime.fromisoformat(VAL[0]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    end = int(dt.datetime.fromisoformat(VAL[1]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    cache = lp.load_state("series.pkl", {})
    raw = {}
    for x in SERIES_A13:
        p = st.CACHE / f"{x}_{start}_{end}.pkl"
        raw[x] = pickle.loads(p.read_bytes())
    legs, events, charged = st.build(raw, {x: cache[x]["fee_type"] for x in raw})
    return legs, events, charged, start, end


def paired_diff_ci(Fa, Fb, n=2000, seed=0):
    """Return(a) - return(b) by event-cluster bootstrap over the union of events (fills of one simulation each)."""
    evs = sorted({f[0] for f in Fa} | {f[0] for f in Fb})
    ix = {e: i for i, e in enumerate(evs)}
    A = np.zeros((len(evs), 2)); B = np.zeros((len(evs), 2))
    for F, M in ((Fa, A), (Fb, B)):
        for f in F:
            M[ix[f[0]], 0] += f[6]; M[ix[f[0]], 1] += f[7]
    idx = np.random.default_rng(seed).integers(0, len(evs), (n, len(evs)))
    d = (100 * A[idx, 0].sum(1) / np.maximum(A[idx, 1].sum(1), 1e-9)
         - 100 * B[idx, 0].sum(1) / np.maximum(B[idx, 1].sum(1), 1e-9))
    pt = 100 * A[:, 0].sum() / max(A[:, 1].sum(), 1e-9) - 100 * B[:, 0].sum() / max(B[:, 1].sum(), 1e-9)
    return pt, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def select(results: dict):
    """A13 rule: highest pessimistic validation return among windows with return > 0; None if none."""
    ok = {w: r for w, r in results.items() if r is not None and r > 0}
    return max(ok, key=ok.get) if ok else None


def validate():
    import maker_policy as mp
    import simulate_maker as s
    legs, events, charged, start, end = val_data()
    months = ["2026-09", "2026-10"]
    lookup = mp.category_lookup()
    cand = []
    s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months, record=cand)
    cand = [c for c in cand if start <= int(c[2]) < end]
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a in cand:
        r = mp.quote_features(legs, events, charged, lookup, s.month_of(int(H)), ev, tk, int(H), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((tk, int(H), int(sd)))
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
    sim = lambda model, pol=None, name="x": win(s.simulate(
        s.Config(**({**mp.BROAD, "policy": name, "policy_t": 1.0} if pol is not None else mp.BROAD)),
        model, legs, events, charged, months, policy_scores=pol))
    ALL = {m: sim(m) for m in ("pess", "opt", "strict")}
    line = lambda r: (f"ret {r['ret']:+6.2f}% CI [{r['lo']:+6.2f}, {r['hi']:+6.2f}]  fills {r['fills']:>6,}  "
                      f"events {r['events']:>4}  net ${r['net_c'] / 100:+8.2f}  markout {r['markout_c_per_contract']:+.2f}c")
    print(f"VALIDATION {VAL[0]}..{VAL[1]} (A13), {len(keys):,} candidates")
    for m in ("pess", "opt", "strict"):
        print(f"  quote everything [{m:<6}] {line(s.summarise(ALL[m]))}")
    res = {}
    for w in ("G", "W1", "W2", "W3"):
        p = mp.model_path("G") if w == "G" else model_path(w)
        if not p.exists():
            print(f"  {w}: not trained"); res[w] = None; continue
        blob = pickle.loads(p.read_bytes())
        pred = blob["model"].predict(mp.to_matrix(rows, blob["cats"]))
        pol = dict(zip(keys, pred)); share = float(np.mean(pred > 1.0))
        print(f" {w} (posts {share:.0%} of candidates)")
        for m in ("pess", "opt", "strict"):
            fl = sim(m, pol)
            r = s.summarise(fl)
            print(f"  {w:<3} [{m:<6}] {line(r)}")
            if m == "pess":
                if w != "G":
                    res[w] = r["ret"]
                d = paired_diff_ci(fl, ALL["pess"])
                print(f"      minus quote-everything (pessimistic, event-paired): {d[0]:+.2f} pts CI [{d[1]:+.2f}, {d[2]:+.2f}]")
                rr = []
                for seed in range(5):
                    u = np.random.default_rng(seed).random(len(keys))
                    rr.append(s.summarise(sim("pess", {k_: (2.0 if v < share else 0.0) for k_, v in zip(keys, u)}, "random"))["ret"])
                print(f"      random at {share:.0%} (5 seeds): mean {np.mean(rr):+.2f}%  range [{min(rr):+.2f}, {max(rr):+.2f}]")
    sel = select(res)
    print(f"\nA13 SELECTION (highest pessimistic return among windows > 0): {sel or 'NONE -- no window is positive'}")
    print(f"  pessimistic returns: " + ", ".join(f"{w} {v:+.2f}%" for w, v in res.items() if v is not None))
    (OUTDIR / "policy_G2_selection.json").write_text(json.dumps({"selected": sel, "pess_returns": res, "val": VAL}, indent=1))


def timeline():
    """Descriptive (A13): quote-everything per month, 2025-12..2026-08 from the API cache."""
    import maker_policy as mp
    import simulate_maker as s
    import live_signal_producer as lp
    from fetch_kalshi_api_months import SERIES_A13
    cache = lp.load_state("series.pkl", {})
    charged = fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES_A13})
    weather = {x for x in SERIES_A13 if x.startswith("KXHIGH")}
    print("QUOTE EVERYTHING BY MONTH (pessimistic), descriptive -- A13")
    for mo in API:
        legs, events = api_legs([mo], SERIES_A13)
        fl = s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, [mo])
        for nm, sub in (("all", fl), ("weather", [f for f in fl if f[0].split("-")[0] in weather])):
            r = s.summarise(sub)
            q = sum(f[4] for f in sub) or 1
            print(f"  {mo} {nm:<8} fills {r['fills']:>6,}  ret {r['ret']:+6.2f}%  net c/contract {r['net_c'] / q:+.2f}  "
                  f"markout {r['markout_c_per_contract']:+.2f}c")


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    check("selection: highest positive window wins", select({"W1": 0.5, "W2": 1.2, "W3": -0.3}) == "W2")
    check("selection: no positive window -> None", select({"W1": -0.5, "W2": -0.1, "W3": None}) is None)
    check("selection: a zero return is not positive", select({"W1": 0.0}) is None)
    legs = {"a": {"yes": True}, "b": {"yes": False}, "c": {"yes": True}, "d": {"yes": True}, "e": {"yes": False}}
    check("training curation keeps only single-winner events",
          single_winner_events(legs, {"E1": ["a", "b"], "E2": ["c", "d"], "E3": ["e"]}) == {"E1": ["a", "b"]})
    f = lambda ev, net, cap: (ev, "t", 1, 50, 1, 0.0, net, cap, 0.0, 0)
    pt, lo, hi = paired_diff_ci([f("x", 10, 100), f("y", 10, 100)], [f("x", 0, 100), f("y", 0, 100)])
    check(f"paired difference: +10 pts when A earns 10% and B 0% on the same events ({pt:+.1f})", abs(pt - 10) < 1e-9 and lo <= pt <= hi)
    check("windows fixed by A13", WINDOWS["W1"] == ["2026-06", "2026-07", "2026-08"] and len(WINDOWS["W2"]) == 6
          and WINDOWS["W3"][0] == "2024-11" and WINDOWS["W3"][-1] == "2026-08")
    charged = fee_charged({"KXA": "quadratic_with_maker_fees", "KXB": "quadratic"})
    check("fee status from the series fee type", charged("KXA", "2026-05") and not charged("KXB", "2026-05"))
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["train", "validate", "timeline"])
    ap.add_argument("window", nargs="?", choices=list(WINDOWS))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.cmd == "train":
        train(a.window)
    elif a.cmd == "validate":
        validate()
    elif a.cmd == "timeline":
        timeline()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
