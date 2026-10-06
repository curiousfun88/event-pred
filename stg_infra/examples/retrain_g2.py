"""
retrain_g2.py

RETRAINED POLICIES G2 (amendment A13) AND G2+ (amendment A14): train one model per
candidate window and design, validate each on 2026-09-07..10-04, select by the fixed rule.

G2 is G with new training months: candidates from the BROAD config, features from
maker_policy.quote_features, maker_policy.HP, target = net c/contract at settlement
after fees (pessimistic fills), threshold 1c.
G2+ (design "G2P") adds, per A14: both quote levels as candidates (simulator option
levels="both"; the better-scoring level per side is posted), toxicity features
(prints and signed taker imbalance in the last hour, mid change over 1h and 3h, an
improved-level flag) and time to close for non-sports series.

DATA. 2024-11..2025-11: local data (simulate_maker.load); for G2 the cached BROAD
pessimistic fills. 2025-12..2026-08: Kalshi API compact cache
(fetch_kalshi_api_months.py). Validation: the smoke-test cache. All restricted to
the 23 A13 series; training events must have resolved with exactly one YES.

USAGE (from repo root, memory-capped):
    python stg_infra/examples/retrain_g2.py --self-test
    python stg_infra/examples/retrain_g2.py train W1 [--design G2P]   # W1 | W2 | W3
    python stg_infra/examples/retrain_g2.py validate                  # every trained model + selection
    python stg_infra/examples/retrain_g2.py timeline                  # descriptive: monthly quote-everything
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
DESIGNS = ("G2", "G2P")
PLUS = ["improved", "prints_1h", "imb_1h", "dmid_1h", "dmid_3h", "ttc_h"]
VAL = ("2026-09-07", "2026-10-05")
OUTDIR = _REPO / "runs/maker"


def model_path(w, design="G2"):
    return OUTDIR / f"policy_{design}_{w}_model.pkl"


def feats(design):
    import maker_policy as mp
    return mp.FEATS_G + (PLUS if design == "G2P" else [])


def sim_cfg(design, **extra):
    import maker_policy as mp
    import simulate_maker as s
    return s.Config(**{**mp.BROAD, **({"levels": "both"} if design == "G2P" else {}), **extra})


# ---------------------------------------------------------------- features

def _mid_at(L, H):
    j = np.searchsorted(L["e"], H)
    if j < len(L["e"]) and L["e"][j] == H and not np.isnan(L["bid"][j] + L["ask"][j]):
        return 50.0 * (L["bid"][j] + L["ask"][j])
    return np.nan


def plus_features(L, H, side, price, cat):
    """A14 additions at quoting hour H (ns): trades in (H-1h, H], quotes at H, H-1h, H-3h, close time."""
    lo = np.searchsorted(L["tt"], H - H_NS, side="right")
    hi = np.searchsorted(L["tt"], H, side="right")
    tc, ts = np.asarray(L["tc"][lo:hi], float), np.asarray(L["ts"][lo:hi], float)
    tot = tc.sum()
    j = np.searchsorted(L["e"], H)
    touch = (L["bid"][j] if side > 0 else L["ask"][j]) * 100
    m0 = _mid_at(L, H)
    return {"improved": float(abs(price - touch) > 0.5), "prints_1h": float(hi - lo),
            "imb_1h": float((tc * ts).sum() / tot) if tot > 0 else 0.0,
            "dmid_1h": m0 - _mid_at(L, H - H_NS), "dmid_3h": m0 - _mid_at(L, H - 3 * H_NS),
            "ttc_h": (L["close"] - H) / H_NS if (L["close"] is not None and cat != "Sports") else np.nan}


def features(design, legs, events, charged, lookup, ev, tk, H, side, price):
    import maker_policy as mp
    import simulate_maker as s
    r = mp.quote_features(legs, events, charged, lookup, s.month_of(H), ev, tk, H, int(side), int(price))
    if r is not None and design == "G2P":
        r.update(plus_features(legs[tk], H, side, price, r["cat"]))
    return r


def matrix(design, rows, cats):
    f = feats(design)
    return np.array([[r[x] if x != "cat_i" else float(cats.index(r["cat"]) if r["cat"] in cats else -1)
                      for x in f] for r in rows], dtype=float)


# ---------------------------------------------------------------- data

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
                                     # float32 cache -> exact cents again (0.41f32 = 0.40999..., which
                                     # would make a 2c spread read as 1.9999c)
                                     "close": int(r["close_ns"]), "e": r["e"], "bid": np.round(r["bid"].astype(float), 4),
                                     "ask": np.round(r["ask"].astype(float), 4), "tt": r["tt"],
                                     "tp": np.round(r["tp"].astype(float), 4),
                                     "tc": r["tc"].astype(float), "ts": r["ts"].astype(float)}
                events.setdefault(r["event"], []).append(r["ticker"])
    return legs, events


def local_legs(mo, series):
    import simulate_maker as s
    legs, events, charged = s.load([mo], "mece")
    keep = {t for t, L in legs.items() if L["series"] in series}
    legs = {t: L for t, L in legs.items() if t in keep}
    events = {e: [t for t in tks if t in keep] for e, tks in events.items()}
    return legs, {e: tks for e, tks in events.items() if tks}, charged


def fee_charged(series_fee):
    mfee = {"quadratic_with_maker_fees", "quadratic_with_combo_maker_fees"}
    return lambda series, month: series_fee.get(series) in mfee


def fills_to_rows(design, fl, legs, events, charged, lookup):
    """Simulator fill tuples -> (feature rows, y = net c/contract)."""
    rows, ys = [], []
    for f in fl:
        r = features(design, legs, events, charged, lookup, f[0], f[1], int(f[9]), int(f[2]), int(f[3]))
        if r is not None:
            rows.append(r); ys.append(f[6] / f[4])
    return rows, ys


# ---------------------------------------------------------------- train

def train(w, design):
    import maker_policy as mp
    import simulate_maker as s
    import live_signal_producer as lp
    from fetch_kalshi_api_months import SERIES_A13
    from sklearn.ensemble import HistGradientBoostingRegressor
    lookup = mp.category_lookup()
    months = WINDOWS[w]
    rows, ys = [], []
    loc = [m for m in months if m in LOCAL]
    if loc and design == "G2":
        from policy_G_audit import fills as cached_fills
        Fd = dict(np.load(OUTDIR / f"cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
        Ft = cached_fills(s.Config(**mp.BROAD), "pess", ["2025-08", "2025-09", "2025-10", "2025-11"])
    for mo in loc:
        legs, events, charged = local_legs(mo, SERIES_A13)
        events = single_winner_events(legs, events)
        if design == "G2":
            F = Fd if mo <= "2025-07" else Ft
            fl = [(F["event"][i], F["ticker"][i], F["side"][i], F["price"][i], F["qty"][i], F["fee_c"][i],
                   F["net_c"][i], F["capital_c"][i], F["markout_c"][i], F["hour_ns"][i])
                  for i in range(len(F["hour_ns"]))
                  if s.month_of(int(F["hour_ns"][i])) == mo and F["event"][i] in events]
        else:
            fl = s.simulate(sim_cfg(design), "pess", legs, events, charged, [mo])
        r, y = fills_to_rows(design, fl, legs, events, charged, lookup)
        rows += r; ys += y
        print(f"  {mo} (local): {len(r):,} training fills", flush=True)
    api = [m for m in months if m in API]
    if api:
        cache = lp.load_state("series.pkl", {})
        legs, events = api_legs(api, SERIES_A13)
        events = single_winner_events(legs, events)
        charged = fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES_A13})
        fl = s.simulate(sim_cfg(design), "pess", legs, events, charged, api)
        r, y = fills_to_rows(design, fl, legs, events, charged, lookup)
        rows += r; ys += y
        print(f"  {api[0]}..{api[-1]} (API): {len(r):,} training fills", flush=True)
    cats = sorted({r["cat"] for r in rows})
    f = feats(design)
    m = HistGradientBoostingRegressor(**mp.HP, categorical_features=[x == "cat_i" for x in f]).fit(
        matrix(design, rows, cats), np.array(ys))
    p = model_path(w, design)
    p.write_bytes(pickle.dumps({"model": m, "cats": cats, "feats": f, "design": design}))
    sha = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    p.with_suffix(".json").write_text(json.dumps({"amendment": "A14" if design == "G2P" else "A13", "design": design,
                                                  "window": w, "months": months, "n_train": len(ys),
                                                  "series": SERIES_A13, "features": f, "hp": mp.HP,
                                                  "threshold_c": 1.0, "model_sha1": sha}, indent=1))
    print(f"trained {design}-{w} on {len(ys):,} fills ({len(cats)} categories); sha1 {sha}")


# ---------------------------------------------------------------- validate

def val_data():
    import live_signal_producer as lp
    import smoke_test_2026 as st
    from fetch_kalshi_api_months import SERIES_A13
    start = int(dt.datetime.fromisoformat(VAL[0]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    end = int(dt.datetime.fromisoformat(VAL[1]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    cache = lp.load_state("series.pkl", {})
    raw = {x: pickle.loads((st.CACHE / f"{x}_{start}_{end}.pkl").read_bytes()) for x in SERIES_A13}
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
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
    line = lambda r: (f"ret {r['ret']:+6.2f}% CI [{r['lo']:+6.2f}, {r['hi']:+6.2f}]  fills {r['fills']:>6,}  "
                      f"events {r['events']:>4}  net ${r['net_c'] / 100:+8.2f}  markout {r['markout_c_per_contract']:+.2f}c")
    ALL = {m: win(s.simulate(s.Config(**mp.BROAD), m, legs, events, charged, months)) for m in ("pess", "opt", "strict")}
    print(f"VALIDATION {VAL[0]}..{VAL[1]} (A13/A14)")
    for m in ("pess", "opt", "strict"):
        print(f"  quote everything [{m:<6}] {line(s.summarise(ALL[m]))}")
    out = {}
    for design in DESIGNS:
        cand = []
        s.simulate(sim_cfg(design), "pess", legs, events, charged, months, record=cand)
        rows, keys = [], []
        for ev, tk, H, sd, pr, b, a in cand:
            if not (start <= int(H) < end):
                continue
            r = features(design, legs, events, charged, lookup, ev, tk, int(H), int(sd), int(pr))
            if r is not None:
                rows.append(r)
                keys.append((tk, int(H), int(sd), int(pr)) if design == "G2P" else (tk, int(H), int(sd)))
        print(f"\n== {design}: {len(keys):,} candidates")
        res = {}
        for w in (["G"] if design == "G2" else []) + list(WINDOWS):
            p = mp.model_path("G") if w == "G" else model_path(w, design)
            if not p.exists():
                print(f"  {w}: not trained"); res[w] = None; continue
            blob = pickle.loads(p.read_bytes())
            X = mp.to_matrix(rows, blob["cats"]) if w == "G" else matrix(design, rows, blob["cats"])
            pred = blob["model"].predict(X)
            pol = dict(zip(keys, pred)); share = float(np.mean(pred > 1.0))
            print(f" {design}-{w} (scores {share:.0%} of candidates above 1c)")
            for m in ("pess", "opt", "strict"):
                fl = win(s.simulate(sim_cfg(design, policy="x", policy_t=1.0), m, legs, events, charged, months,
                                    policy_scores=pol))
                r = s.summarise(fl)
                print(f"  {w:<3} [{m:<6}] {line(r)}")
                if m != "pess":
                    continue
                if w != "G":
                    res[w] = r["ret"]
                d = paired_diff_ci(fl, ALL["pess"])
                print(f"      minus quote-everything (pessimistic, event-paired): {d[0]:+.2f} pts CI [{d[1]:+.2f}, {d[2]:+.2f}]")
                rr = []
                for seed in range(5):
                    u = np.random.default_rng(seed).random(len(keys))
                    rp = {k_: (2.0 if v < share else 0.0) for k_, v in zip(keys, u)}
                    rr.append(s.summarise(win(s.simulate(sim_cfg(design, policy="random", policy_t=1.0), "pess", legs,
                                                         events, charged, months, policy_scores=rp)))["ret"])
                print(f"      random at the same share (5 seeds): mean {np.mean(rr):+.2f}%  range [{min(rr):+.2f}, {max(rr):+.2f}]")
        sel = select({k_: v for k_, v in res.items() if k_ != "G"})
        out[design] = {"selected": sel, "pess_returns": res}
        print(f"\n  A13/A14 SELECTION for {design}: {sel or 'NONE -- no window is positive'}")
    (OUTDIR / "policy_G2_selection.json").write_text(json.dumps({"val": VAL, **out}, indent=1))


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


# ---------------------------------------------------------------- self-test

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

    H = 100 * H_NS
    L = {"e": np.array([H - 3 * H_NS, H - H_NS, H], np.int64), "bid": np.array([.30, .38, .40]),
         "ask": np.array([.34, .42, .44]), "tt": np.array([H - 2 * H_NS, H - 1800 * 10**9, H - 60 * 10**9, H + 1], np.int64),
         "tc": np.array([9.0, 3.0, 1.0, 50.0]), "ts": np.array([1.0, 1.0, -1.0, -1.0]), "close": H + 5 * H_NS}
    p = plus_features(L, H, 1, 41, "Climate and Weather")
    check(f"A14 prints/imbalance use (H-1h, H] only: prints {p['prints_1h']}, imbalance {(3 - 1) / 4}",
          p["prints_1h"] == 2 and abs(p["imb_1h"] - 0.5) < 1e-9)
    check("A14 mid changes over 1h (42-40=2) and 3h (42-32=10)", abs(p["dmid_1h"] - 2) < 1e-9 and abs(p["dmid_3h"] - 10) < 1e-9)
    check("A14 improved flag: bid 41 vs touch 40 -> 1; touch -> 0",
          p["improved"] == 1.0 and plus_features(L, H, 1, 40, "x")["improved"] == 0.0)
    check("A14 ask side: touch 44 -> 0, inside 43 -> 1",
          plus_features(L, H, -1, 44, "x")["improved"] == 0.0 and plus_features(L, H, -1, 43, "x")["improved"] == 1.0)
    check("A14 time to close: 5h for non-sports, missing for Sports",
          p["ttc_h"] == 5.0 and np.isnan(plus_features(L, H, 1, 41, "Sports")["ttc_h"]))
    check("A14 no trades in the hour -> imbalance 0", plus_features({**L, "tt": np.array([H - 5 * H_NS], np.int64),
                                                                       "tc": np.array([1.0]), "ts": np.array([1.0])},
                                                                    H, 1, 41, "x")["imb_1h"] == 0.0)
    check("A14 missing quote 3h earlier -> dmid_3h missing",
          np.isnan(plus_features({**L, "e": np.array([H - 4 * H_NS, H - H_NS, H], np.int64)}, H, 1, 41, "x")["dmid_3h"]))
    import maker_policy as mp
    check("G2+ feature list = G's 14 + the 6 A14 additions", feats("G2P") == mp.FEATS_G + PLUS and feats("G2") == mp.FEATS_G)
    import tempfile, fetch_kalshi_api_months as fk
    with tempfile.TemporaryDirectory() as d:
        old = fk.OUT; fk.OUT = Path(d)
        rec = {"ticker": "Q-1", "event": "Q", "result": "yes", "close_ns": 0, "e": np.array([0], np.int64),
               "bid": np.array([0.41], np.float32), "ask": np.array([0.43], np.float32), "tt": np.empty(0, np.int64),
               "tp": np.array([41.0], np.float32), "tc": np.empty(0, np.float32), "ts": np.empty(0, np.int8)}
        (Path(d) / "KXQ_2026-06.pkl").write_bytes(pickle.dumps([rec]))
        lg, _ = api_legs(["2026-06"], ["KXQ"]); fk.OUT = old
    check("API cache prices come back as exact cents (float32 0.41/0.43 -> spread exactly 2c)",
          lg["Q-1"]["ask"][0] * 100 - lg["Q-1"]["bid"][0] * 100 == 2.0 and lg["Q-1"]["bid"][0] == 0.41)
    check("G2+ simulates both levels; G2 the BROAD config",
          sim_cfg("G2P").levels == "both" and sim_cfg("G2").levels == "")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["train", "validate", "timeline"])
    ap.add_argument("window", nargs="?", choices=list(WINDOWS))
    ap.add_argument("--design", choices=DESIGNS, default="G2")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.cmd == "train":
        train(a.window, a.design)
    elif a.cmd == "validate":
        validate()
    elif a.cmd == "timeline":
        timeline()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
