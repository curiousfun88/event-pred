"""Exploratory (development months only): a LEARNED market-making policy.

Instead of A10's hand-set filters, learn where maker quotes pay. Training data:
the fills of the broadest cached maker configuration on the development
months (both sides, improve 1c, 1-99c, spread >= 2c, all series, inventory
50, pessimistic fills). Target: net P&L per contract AT SETTLEMENT, after
fees. Posting costs nothing unless filled, so "post if predicted P&L of a
fill > t" is the decision rule.

Fit on TRAIN months, evaluated on VALIDATION months against (a) keeping every
fill (quote everything) and (b) A10's own fills in the same months.

Approximation (stated): fills are scored from the broad run, so inventory
interactions from posting fewer quotes are ignored. A pre-registered version
must run the policy inside simulate_maker.

    python stg_infra/examples/learned_maker_policy.py --self-test
    python stg_infra/examples/learned_maker_policy.py
"""
import sys, json, argparse
import numpy as np

sys.path.insert(0, "stg_infra")
TRAIN = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL = ["2025-06", "2025-07"]
DEV = TRAIN + VAL
BROAD_KEY = "b85bd3c8cb9be1ee"
FEATS = ["side", "price", "rel_price", "spread", "mid", "ttc_h", "trades_24h", "dmid_24h", "n_legs",
         "n_quoted", "basket_sum", "second_mid", "hour_utc", "charged", "cat_i"]


def features_for_month(mo, fills_idx, F, lookup):
    """Quote-time features for the fills (indices) whose quoting hour falls in month mo."""
    import simulate_maker as s
    from diagnose_basket_composition import category_of
    legs, events, charged = s.load([mo], "mece")
    H = s.H_NS
    out = {}
    for i in fills_idx:
        tk, Hh, ev = F["ticker"][i], int(F["hour_ns"][i]), F["event"][i]
        L = legs.get(tk)
        if L is None:
            continue
        j = np.searchsorted(L["e"], Hh)
        if j >= len(L["e"]) or L["e"][j] != Hh:
            continue
        b, a = L["bid"][j] * 100, L["ask"][j] * 100
        tks = events.get(ev, [tk])
        mids = []
        for t in tks:
            Lt = legs[t]; jt = np.searchsorted(Lt["e"], Hh)
            if jt < len(Lt["e"]) and Lt["e"][jt] == Hh and not np.isnan(Lt["bid"][jt] + Lt["ask"][jt]):
                mids.append(((Lt["bid"][jt] + Lt["ask"][jt]) * 50, t))
        others = sorted((m for m, t in mids if t != tk), reverse=True)
        j24 = np.searchsorted(L["e"], Hh - 24 * H)
        dm = ((b + a) / 2 - (L["bid"][j24] + L["ask"][j24]) * 50
              if j24 < len(L["e"]) and L["e"][j24] == Hh - 24 * H and not np.isnan(L["bid"][j24] + L["ask"][j24]) else np.nan)
        out[i] = dict(side=float(F["side"][i]), price=float(F["price"][i]), rel_price=float(F["price"][i]) - (a + b) / 2,
                      spread=a - b, mid=(a + b) / 2,
                      ttc_h=(L["close"] - Hh) / H if L["close"] is not None else np.nan,
                      trades_24h=s.recent_trades(L["tt"], Hh) if "tt" in L else 0, dmid_24h=dm, n_legs=len(tks),
                      n_quoted=len(mids), basket_sum=sum(m for m, _ in mids), second_mid=others[0] if others else 0.0,
                      hour_utc=(Hh // H) % 24, charged=float(charged(L["series"], mo)),
                      cat=category_of(L["series"], lookup))
    return out


def cluster_mean_ci(v, g, n_boot=2000, seed=0):
    _, inv = np.unique(g, return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k); c = np.bincount(inv, minlength=k).astype(float)
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    return v.mean(), tuple(np.percentile(s[idx].sum(1) / c[idx].sum(1), [2.5, 97.5])), k


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted policy)")
    from sklearn.ensemble import HistGradientBoostingRegressor
    rng = np.random.default_rng(0)
    n = 20000
    X = rng.normal(size=(n, 4))
    y = np.where(X[:, 2] > 0.5, 3.0, -1.0) + rng.normal(0, 8, n)        # profitable pocket in one feature
    tr, te = np.arange(n) < 14000, np.arange(n) >= 14000
    m = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, min_samples_leaf=200, random_state=0).fit(X[tr], y[tr])
    p = m.predict(X[te])
    check(f"policy keeps the planted pocket: mean kept {y[te][p > 0].mean():+.2f} > all {y[te].mean():+.2f}",
          y[te][p > 0].mean() > y[te].mean() + 1.0)
    y0 = rng.normal(0, 8, n) - 0.5
    m0 = HistGradientBoostingRegressor(max_iter=200, learning_rate=0.05, min_samples_leaf=200, random_state=0).fit(X[tr], y0[tr])
    p0 = m0.predict(X[te])
    kept = y0[te][p0 > 0]
    check(f"no signal: policy keeps few fills or no better than all ({len(kept)} kept)",
          len(kept) < 300 or kept.mean() < y0[te].mean() + 0.8)
    mm, (lo, hi), k = cluster_mean_ci(np.array([1., 1, 5, 5]), np.array(["a", "a", "b", "b"]))
    check("cluster CI brackets mean", lo <= mm <= hi and k == 2)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    import simulate_maker as s
    from sklearn.ensemble import HistGradientBoostingRegressor
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    F = dict(np.load(f"runs/maker/cache/{BROAD_KEY}.fills.npz", allow_pickle=True))
    month = np.array([s.month_of(int(h)) for h in F["hour_ns"]])
    feats = {}
    for mo in DEV:
        feats.update(features_for_month(mo, np.where(month == mo)[0], F, lookup))
        print(f"  {mo}: features for {len(feats):,} fills", flush=True)
    idx = np.array(sorted(feats))
    cats = sorted({feats[i]["cat"] for i in idx})
    X = np.array([[feats[i][f] if f != "cat_i" else float(cats.index(feats[i]["cat"])) for f in FEATS] for i in idx])
    y = F["net_c"][idx] / F["qty"][idx]                      # cents per contract at settlement, after fees
    ev = F["event"][idx]; mo_ = month[idx]; net = F["net_c"][idx]; qty = F["qty"][idx]; cap = F["capital_c"][idx]
    tr, va = np.isin(mo_, TRAIN), np.isin(mo_, VAL)
    print(f"\nDEVELOPMENT MONTHS ONLY. broad-config fills with features: train {tr.sum():,}, validation {va.sum():,}")
    m = HistGradientBoostingRegressor(max_iter=400, learning_rate=0.03, max_leaf_nodes=31, min_samples_leaf=300,
                                      l2_regularization=1.0, random_state=0,
                                      categorical_features=[f == "cat_i" for f in FEATS]).fit(X[tr], y[tr])
    p = m.predict(X[va])
    yv, evv, netv, qv, capv = y[va], ev[va], net[va], qty[va], cap[va]
    print(f"\nVALIDATION (Jun-Jul 2025): policy = keep fills with predicted P&L per contract > t")
    print(f"  {'policy':<26}{'fills':>8}{'events':>8}{'net $':>10}{'ret on cap':>11}{'c/contract':>11}   CI95 (c/contract, by event)")
    def row(nm, sel):
        mm, (lo, hi), k = cluster_mean_ci(yv[sel], evv[sel])
        print(f"  {nm:<26}{sel.sum():>8,}{k:>8,}{netv[sel].sum() / 100:>+10.2f}{netv[sel].sum() / max(capv[sel].sum(), 1):>+11.2%}"
              f"{mm:>+11.2f}   [{lo:+.2f}, {hi:+.2f}]")
    row("quote everything (broad)", np.ones(len(yv), bool))
    for t in (0, 1, 2, 3, 5):
        sel = p > t
        if sel.sum() >= 30:
            row(f"learned policy, t={t}c", sel)
    # A10 on the same validation months, from its own cached run
    cfg = s.Config(**json.load(open("runs/maker/selected_a10.json")))
    A = dict(np.load(f"runs/maker/cache/{s.cache_key(cfg, 'pess', DEV)}.fills.npz", allow_pickle=True))
    am = np.array([s.month_of(int(h)) for h in A["hour_ns"]]); sel = np.isin(am, VAL)
    ya = A["net_c"][sel] / A["qty"][sel]
    mm, (lo, hi), k = cluster_mean_ci(ya, A["event"][sel])
    print(f"  {'A10 (hand-set rules)':<26}{sel.sum():>8,}{k:>8,}{A['net_c'][sel].sum() / 100:>+10.2f}"
          f"{A['net_c'][sel].sum() / max(A['capital_c'][sel].sum(), 1):>+11.2%}{mm:>+11.2f}   [{lo:+.2f}, {hi:+.2f}]")
    print("\n  feature importance proxy: validation c/contract of kept fills by side (t=1):")
    for sd, nm in ((1, "bid (buy YES)"), (-1, "ask (sell YES)")):
        s2 = (p > 1) & (X[va][:, 0] == sd)
        if s2.sum():
            print(f"    {nm:<16} kept {s2.sum():>6,}  mean {yv[s2].mean():+.2f}c")


if __name__ == "__main__":
    main()
