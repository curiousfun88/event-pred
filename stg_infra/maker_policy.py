"""
maker_policy.py -- learned maker policy G (maker pre-registration, amendment A12).

One feature function (`quote_features`) is used for training, for scoring
candidate orders, and therefore by the simulator run: the simulator only
consumes the pre-computed scores (simulate_maker.Config.policy).

Commands (repo root):
  python stg_infra/maker_policy.py --self-test
  python stg_infra/maker_policy.py train      # fit G on 2024-11..2025-05 broad-config fills; save + hash
  python stg_infra/maker_policy.py score MONTH [MONTH ...]   # candidate orders -> runs/maker/policy_G_scores_<months>.parquet
  python stg_infra/maker_policy.py check MONTH  # identity checks on real data (allow-all == no policy; deny-all == no fills)
"""
from __future__ import annotations

import sys, json, pickle, hashlib, argparse
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "examples"))

TRAIN = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
BROAD = dict(sides="both", improve=1, band_lo=1, band_hi=99, min_spread=2, series="all", q=10, basket=False,
             pos_limit=50, event_limit=200, universe="mece", min_trades_24h=0, stgat="", min_ttc_h=0)
BROAD_KEY_DEV = "b85bd3c8cb9be1ee"          # cached pessimistic fills of BROAD on the 9 development months
FEATS_G = ["side", "price", "rel_price", "spread", "mid", "trades_24h", "dmid_24h", "n_legs", "n_quoted",
           "basket_sum", "second_mid", "hour_utc", "charged", "cat_i"]      # A12: no time-to-close
HP = dict(max_iter=400, learning_rate=0.03, max_leaf_nodes=31, min_samples_leaf=300, l2_regularization=1.0,
          random_state=0)
ST_COLS = ["st_mid", "st_d1", "st_d2", "st_d3", "st_d6", "st_d12"]    # A12 G+S: STGAT inputs (cents)
FEATS = {"G": FEATS_G, "GS": FEATS_G + ST_COLS}
ST_PATH = _REPO / "runs/maker/stgat_features_13mo.parquet"
ST_MAX_AGE_NS = 2 * 3_600_000_000_000                             # latest snapshot ending <= H, at most 2h old
VARIANT = "G"


def model_path(v=None):
    return _REPO / f"runs/maker/policy_{v or VARIANT}_model.pkl"


def meta_path(v=None):
    return _REPO / f"runs/maker/policy_{v or VARIANT}_model.json"


MODEL_PATH = model_path("G")
META_PATH = meta_path("G")


def load_stgat(path=ST_PATH):
    """{ticker: (end_ns sorted, values (n, 6))} from export_stgat_features.py."""
    import polars as pl
    df = pl.read_parquet(path).sort(["ticker", "end_ns"])
    return {tk: (g["end_ns"].to_numpy(), g.select(ST_COLS).to_numpy())
            for (tk,), g in df.group_by(["ticker"], maintain_order=True)}


def stgat_at(st, tk, H):
    """A12: outputs of the latest snapshot ending at or before H and at most 2h old; else all-NaN."""
    rec = st.get(tk) if st else None
    if rec is not None:
        e, v = rec
        j = np.searchsorted(e, H, side="right") - 1
        if j >= 0 and H - e[j] <= ST_MAX_AGE_NS:
            return v[j]
    return np.full(len(ST_COLS), np.nan)


def add_stgat(r, st, tk, H):
    if r is not None and VARIANT == "GS":
        r.update(dict(zip(ST_COLS, stgat_at(st, tk, H))))
    return r


def category_lookup():
    import polars as pl
    c = pl.read_parquet(_REPO / "results/data_audit/kalshi_series_categories.parquet")
    return dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))


def quote_features(legs, events, charged, lookup, month, ev, tk, H, side, price):
    """Features of one candidate order at quoting hour H (ns). Uses only quotes at H, trades in
    (H-24h, H], quotes at H-24h, the event's leg list, the fee schedule and the series category."""
    import simulate_maker as s
    from diagnose_basket_composition import category_of
    HN = s.H_NS
    L = legs[tk]
    j = np.searchsorted(L["e"], H)
    if j >= len(L["e"]) or L["e"][j] != H:
        return None
    b, a = L["bid"][j] * 100, L["ask"][j] * 100
    tks = events.get(ev, [tk])
    mids = []
    for t in tks:
        Lt = legs[t]; jt = np.searchsorted(Lt["e"], H)
        if jt < len(Lt["e"]) and Lt["e"][jt] == H and not np.isnan(Lt["bid"][jt] + Lt["ask"][jt]):
            mids.append(((Lt["bid"][jt] + Lt["ask"][jt]) * 50, t))
    others = sorted((m for m, t in mids if t != tk), reverse=True)
    j24 = np.searchsorted(L["e"], H - 24 * HN)
    dm = ((b + a) / 2 - (L["bid"][j24] + L["ask"][j24]) * 50
          if j24 < len(L["e"]) and L["e"][j24] == H - 24 * HN and not np.isnan(L["bid"][j24] + L["ask"][j24]) else np.nan)
    return dict(side=float(side), price=float(price), rel_price=float(price) - (a + b) / 2, spread=a - b,
                mid=(a + b) / 2, trades_24h=s.recent_trades(L["tt"], H) if "tt" in L else 0, dmid_24h=dm,
                n_legs=len(tks), n_quoted=len(mids), basket_sum=sum(m for m, _ in mids),
                second_mid=others[0] if others else 0.0, hour_utc=(H // HN) % 24,
                charged=float(charged(L["series"], month)), cat=category_of(L["series"], lookup))


def to_matrix(rows, cats):
    return np.array([[r[f] if f != "cat_i" else float(cats.index(r["cat"]) if r["cat"] in cats else -1)
                      for f in FEATS[VARIANT]] for r in rows], dtype=float)


def file_hash(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:16]


# ---------------------------------------------------------------- commands
def cmd_train():
    import simulate_maker as s
    from sklearn.ensemble import HistGradientBoostingRegressor
    lookup = category_lookup()
    F = dict(np.load(_REPO / f"runs/maker/cache/{BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
    month = np.array([s.month_of(int(h)) for h in F["hour_ns"]])
    st = load_stgat() if VARIANT == "GS" else None
    rows, ys = [], []
    for mo in TRAIN:
        legs, events, charged = s.load([mo], "mece")
        for i in np.where(month == mo)[0]:
            if F["ticker"][i] not in legs:
                continue
            r = quote_features(legs, events, charged, lookup, mo, F["event"][i], F["ticker"][i],
                               int(F["hour_ns"][i]), int(F["side"][i]), int(F["price"][i]))
            r = add_stgat(r, st, F["ticker"][i], int(F["hour_ns"][i]))
            if r is not None:
                rows.append(r); ys.append(F["net_c"][i] / F["qty"][i])
        print(f"  {mo}: {len(rows):,} training fills", flush=True)
    cats = sorted({r["cat"] for r in rows})
    X, y = to_matrix(rows, cats), np.array(ys)
    fe = FEATS[VARIANT]
    m = HistGradientBoostingRegressor(**HP, categorical_features=[f == "cat_i" for f in fe]).fit(X, y)
    mp_, me_ = model_path(), meta_path()
    mp_.write_bytes(pickle.dumps({"model": m, "cats": cats, "feats": fe}))
    extra = {}
    if VARIANT == "GS":
        cov = float(np.mean(~np.isnan(X[:, fe.index("st_mid")])))
        extra = {"stgat_features": str(ST_PATH.name), "stgat_sha1": file_hash(ST_PATH), "stgat_coverage_train": cov}
        print(f"  STGAT feature coverage on training fills: {cov:.1%}")
    me_.write_text(json.dumps({"amendment": "A12", "variant": VARIANT, "train_months": TRAIN, "n_train": len(y),
                               "features": fe, "hp": HP, "threshold_c": 1.0, "source_fills": BROAD_KEY_DEV,
                               "model_sha1": file_hash(mp_), **extra}, indent=1))
    print(f"trained {VARIANT} on {len(y):,} fills; saved {mp_.name} sha1 {file_hash(mp_)}")


def cmd_score(months):
    import polars as pl
    import simulate_maker as s
    blob = pickle.loads(model_path().read_bytes())
    m, cats = blob["model"], blob["cats"]
    lookup = category_lookup()
    cfg = s.Config(**BROAD)
    st = load_stgat() if VARIANT == "GS" else None
    out = []
    for mo in months:
        legs, events, charged = s.load([mo], "mece")
        cand = []
        s.simulate(cfg, "pess", legs, events, charged, [mo], record=cand)
        rows, keys = [], []
        for ev, tk, H, sd, pr, b, a in cand:
            r = quote_features(legs, events, charged, lookup, mo, ev, tk, int(H), int(sd), int(pr))
            r = add_stgat(r, st, tk, int(H))
            if r is not None:
                rows.append(r); keys.append((tk, int(H), int(sd)))
        pred = m.predict(to_matrix(rows, cats)) if rows else np.array([])
        out += [(k[0], k[1], k[2], float(p)) for k, p in zip(keys, pred)]
        print(f"  {mo}: {len(cand):,} candidate orders scored; {np.mean(pred > 1.0) if len(pred) else 0:.1%} above t=1c", flush=True)
    path = _REPO / f"runs/maker/policy_{VARIANT}_scores_{months[0]}_{months[-1]}.parquet"
    pl.DataFrame(out, schema={"ticker": pl.Utf8, "hour_ns": pl.Int64, "side": pl.Int64, "pred": pl.Float64},
                 orient="row").write_parquet(path)
    print(f"-> {path} ({len(out):,} scored orders; model sha1 {file_hash(model_path())})")


def cmd_check(month):
    """Real-data identities: every candidate allowed -> identical fills to no policy; none allowed -> no fills."""
    import simulate_maker as s
    legs, events, charged = s.load([month], "mece")
    base = s.Config(**BROAD)
    cand = []
    s.simulate(base, "pess", legs, events, charged, [month], record=cand)
    allow = {(tk, int(H), int(sd)): 1e9 for _, tk, H, sd, _, _, _ in cand}
    deny = {k: -1e9 for k in allow}
    f0 = s.simulate(base, "pess", legs, events, charged, [month])
    pol = s.Config(**{**BROAD, "policy": "x", "policy_t": 1.0})
    f_allow = s.simulate(pol, "pess", legs, events, charged, [month], policy_scores=allow)
    f_deny = s.simulate(pol, "pess", legs, events, charged, [month], policy_scores=deny)
    ok1 = f_allow == f0
    ok2 = len(f_deny) == 0
    print(f"  {month}: candidates {len(cand):,}; fills without policy {len(f0):,}")
    print(f"  [{'PASS' if ok1 else 'FAIL'}] allow-all policy reproduces the no-policy fills exactly")
    print(f"  [{'PASS' if ok2 else 'FAIL'}] deny-all policy gives zero fills ({len(f_deny)})")
    return ok1 and ok2


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (synthetic legs)")
    import simulate_maker as s
    HN = s.H_NS
    e = np.array([0, HN, 24 * HN, 25 * HN], dtype=np.int64)
    legs = {"A": {"e": e, "bid": np.array([.40, .41, .50, .52]), "ask": np.array([.44, .45, .54, .56]),
                  "tt": np.array([HN // 2, 24 * HN + 1], dtype=np.int64), "series": "KXHIGHNY", "close": None, "yes": True},
            "B": {"e": e, "bid": np.array([.50, .50, .40, .40]), "ask": np.array([.54, .54, .44, .44]),
                  "tt": np.array([], dtype=np.int64), "series": "KXHIGHNY", "close": None, "yes": False}}
    events = {"EV": ["A", "B"]}
    r = quote_features(legs, events, lambda sr, mo: False, {}, "2025-01", "EV", "A", 24 * HN, -1, 53)
    check("mid and spread at H", abs(r["mid"] - 52) < 1e-9 and abs(r["spread"] - 4) < 1e-9)
    check("24h mid change uses the quote exactly 24h earlier", abs(r["dmid_24h"] - 10) < 1e-9)
    check("trades counted in (H-24h, H] only: 0.5h in, just-after-H out", r["trades_24h"] == 1)
    check("basket context: other leg's mid, basket sum", abs(r["second_mid"] - 42) < 1e-9 and abs(r["basket_sum"] - 94) < 1e-9)
    check("order price relative to mid", abs(r["rel_price"] - 1) < 1e-9)
    check("no quote at H -> None", quote_features(legs, events, lambda sr, mo: False, {}, "2025-01", "EV", "A", 5 * HN, 1, 40) is None)
    check("no time-to-close feature (A12)", "ttc_h" not in FEATS_G)
    st = {"A": (np.array([0, 2 * HN], dtype=np.int64), np.array([[1.0] * 6, [2.0] * 6]))}
    check("STGAT: exact snapshot at H used", stgat_at(st, "A", 2 * HN)[0] == 2.0)
    check("STGAT: 1h-old snapshot used", stgat_at(st, "A", 3 * HN)[0] == 2.0)
    check("STGAT: >2h-old snapshot -> missing", np.isnan(stgat_at(st, "A", 5 * HN)[0]))
    check("STGAT: snapshot after H never used", stgat_at(st, "A", HN)[0] == 1.0)
    check("STGAT: unknown node -> missing", np.isnan(stgat_at(st, "Z", HN)).all())
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["train", "score", "check"])
    ap.add_argument("months", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--variant", choices=["G", "GS"], default="G")
    a = ap.parse_args()
    global VARIANT
    VARIANT = a.variant
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.cmd == "train":
        cmd_train()
    elif a.cmd == "score":
        cmd_score(a.months)
    elif a.cmd == "check":
        sys.exit(0 if cmd_check(a.months[0]) else 1)


if __name__ == "__main__":
    main()
