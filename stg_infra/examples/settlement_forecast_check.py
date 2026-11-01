"""Exploratory (development months only): can a settlement forecast beat the
market price on MECE legs? Pre-check before building an STGAT settlement head.

Population: every MECE leg (causal membership) with a two-sided quote, any
mid in 1-99c, one row per leg per UTC day (first quoted hour). Label: the leg
settles YES. Features at H only; time-to-close excluded (sports close_time is
the actual match end).

Forecasts compared on VALIDATION (fit on TRAIN months only):
  price      : mid / 100
  price+iso  : isotonic calibration of mid (fitted on train)
  basket     : mid / sum of the basket's mids (the sum-to-$1 constraint alone), isotonic-calibrated
  GBM        : gradient boosting on price, basket context and market features
Reported: log-loss and Brier (lower is better), GBM minus the best baseline
with an event-cluster CI, and upset AUC within 5c price bands (skill beyond price).

    python stg_infra/examples/settlement_forecast_check.py --self-test
    python stg_infra/examples/settlement_forecast_check.py
"""
import sys, argparse
import numpy as np

sys.path.insert(0, "stg_infra")
TRAIN = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL = ["2025-06", "2025-07"]
FEATS = ["mid", "p_basket", "spread", "n_legs", "n_quoted", "basket_sum", "rank_in_basket", "second_mid",
         "trades_24h", "dmid_24h", "hour_utc", "charged", "cat_i"]


def rows_for_month(mo, lookup):
    import simulate_maker as s
    from diagnose_basket_composition import category_of
    legs, events, charged = s.load([mo], "mece")
    HN = s.H_NS
    out, seen = [], set()
    for ev, tks in events.items():
        hours = sorted({int(e) for tk in tks for e in legs[tk]["e"]})
        for H in hours:
            if s.month_of(H) != mo:
                continue
            q = {}
            for tk in tks:
                L = legs[tk]; j = np.searchsorted(L["e"], H)
                if j < len(L["e"]) and L["e"][j] == H and not (np.isnan(L["bid"][j]) or np.isnan(L["ask"][j])):
                    b, a = L["bid"][j] * 100, L["ask"][j] * 100
                    if 0 < b < a < 100 and (L["close"] is None or H < L["close"]):
                        q[tk] = (b, a)
            if not q:
                continue
            mids = {t: (x[0] + x[1]) / 2 for t, x in q.items()}
            bsum = sum(mids.values())
            order = sorted(mids, key=lambda t: -mids[t])
            for tk, (b, a) in q.items():
                key = (tk, H // (24 * HN))
                if key in seen:
                    continue
                seen.add(key)
                L = legs[tk]; mid = mids[tk]
                others = [mids[t] for t in order if t != tk]
                j24 = np.searchsorted(L["e"], H - 24 * HN)
                dm = (mid - (L["bid"][j24] + L["ask"][j24]) * 50
                      if j24 < len(L["e"]) and L["e"][j24] == H - 24 * HN and not np.isnan(L["bid"][j24] + L["ask"][j24]) else np.nan)
                out.append(dict(event=ev, month=mo, y=int(bool(L["yes"])), mid=mid, p_basket=mid / bsum if bsum > 0 else np.nan,
                                spread=a - b, n_legs=len(tks), n_quoted=len(q), basket_sum=bsum,
                                rank_in_basket=order.index(tk), second_mid=others[0] if others else 0.0,
                                trades_24h=s.recent_trades(L["tt"], H) if "tt" in L else 0, dmid_24h=dm,
                                hour_utc=(H // HN) % 24, charged=float(charged(L["series"], mo)),
                                cat=category_of(L["series"], lookup)))
    return out


def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def band_auc(y_up, score, mid, width=5.0):
    from sklearn.metrics import roc_auc_score
    num = den = 0.0
    for lo in np.arange(0, 100, width):
        sel = (mid >= lo) & (mid < lo + width)
        pos, neg = y_up[sel].sum(), (1 - y_up[sel]).sum()
        if pos >= 5 and neg >= 5:
            w = pos * neg; num += w * roc_auc_score(y_up[sel], score[sel]); den += w
    return num / den if den else np.nan


def event_ci(d, ev, n_boot=2000, seed=0):
    _, inv = np.unique(ev, return_inverse=True); k = inv.max() + 1
    s = np.bincount(inv, weights=d, minlength=k); c = np.bincount(inv, minlength=k).astype(float)
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    return d.mean(), tuple(np.percentile(s[idx].sum(1) / c[idx].sum(1), [2.5, 97.5])), k


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c); print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    rng = np.random.default_rng(0)
    n = 20000
    mid = rng.uniform(5, 95, n)
    y = (rng.random(n) < mid / 100).astype(int)
    check("calibrated price: log-loss of mid/100 near entropy", abs(logloss(y, mid / 100).mean() - 0.54) < 0.05)
    check("random score has ~0.5 within-band AUC", 0.45 < band_auc(1 - y, rng.normal(size=n), mid) < 0.55)
    m, (lo, hi), k = event_ci(np.array([1., 1, 3, 3]), np.array(["a", "a", "b", "b"]))
    check("event CI brackets mean", lo <= m <= hi and k == 2)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    rows = []
    for mo in TRAIN + VAL:
        rows += rows_for_month(mo, lookup); print(f"  {mo}: {len(rows):,} rows", flush=True)
    df = pl.DataFrame(rows)
    cats = sorted(df["cat"].unique().to_list())
    df = df.with_columns(pl.col("cat").map_elements(lambda x: float(cats.index(x)), return_dtype=pl.Float64).alias("cat_i"))
    tr, va = df.filter(pl.col("month").is_in(TRAIN)), df.filter(pl.col("month").is_in(VAL))
    ytr, yva = tr["y"].to_numpy(), va["y"].to_numpy(); ev = va["event"].to_numpy()
    iso = lambda col: IsotonicRegression(y_min=1e-3, y_max=1 - 1e-3, out_of_bounds="clip").fit(
        tr[col].fill_nan(0).to_numpy(), ytr).predict(va[col].fill_nan(0).to_numpy())
    p_price = va["mid"].to_numpy() / 100
    p_iso, p_bask = iso("mid"), iso("p_basket")
    gbm = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.03, max_leaf_nodes=31, min_samples_leaf=300,
                                         l2_regularization=1.0, random_state=0,
                                         categorical_features=[f == "cat_i" for f in FEATS]).fit(tr.select(FEATS).to_numpy(), ytr)
    p_gbm = gbm.predict_proba(va.select(FEATS).to_numpy())[:, 1]
    print(f"\nDEVELOPMENT MONTHS ONLY. MECE legs, one row per leg-day: train {tr.height:,} ({tr['event'].n_unique():,} events), "
          f"validation {va.height:,} ({va['event'].n_unique():,} events); YES rate val {yva.mean():.1%}")
    print(f"\nVALIDATION  {'log-loss':>9} {'Brier':>8}")
    res = {}
    for nm, p in (("price (mid/100)", p_price), ("price + isotonic", p_iso), ("basket-normalised + isotonic", p_bask), ("GBM", p_gbm)):
        res[nm] = logloss(yva, p)
        print(f"  {nm:<30}{res[nm].mean():>9.4f} {np.mean((p - yva) ** 2):>8.4f}")
    best = min(("price + isotonic", "basket-normalised + isotonic"), key=lambda k: res[k].mean())
    m, (lo, hi), k = event_ci(res["GBM"] - res[best], ev)
    print(f"\n  GBM minus best baseline ({best}): {m:+.4f}  CI95 [{lo:+.4f}, {hi:+.4f}]  (k={k}; negative = GBM better)")
    up = 1 - yva; mid = va["mid"].to_numpy()
    print(f"  within-5c-band upset AUC (skill beyond price): GBM {band_auc(up, 1 - p_gbm, mid):.3f}   "
          f"basket-normalised {band_auc(up, 1 - p_bask, mid):.3f}   price {band_auc(up, -mid, mid):.3f}")


if __name__ == "__main__":
    main()
