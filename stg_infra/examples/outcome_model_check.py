"""Exploratory (development months only): can outcomes of MECE favourites be
predicted better than their price says? This is the target a model would
need to improve A10 (a2 diagnosis: A10's P&L is decided at settlement).

Population: every MECE leg (causal membership) with a two-sided quote whose
mid is in 85-99c, more than 24h before close. One row per leg per UTC day
(first qualifying hour). Label: settles YES. Features known at H only.
Fit on TRAIN months, scored on VALIDATION months only.

Reported (validation):
  - log-loss: price, isotonic calibration of price (fitted on train), GBM
  - upset AUC (predicting NO): price alone vs GBM
  - within-price-band AUC: AUC inside 2c mid bands, pooled -- the skill
    beyond what the price already says. A10 needs roughly 0.65-0.70 to
    gain (logs/v2_forecast/a10_outcome_filter_ceiling.log).
CIs resample events.

    python stg_infra/examples/outcome_model_check.py --self-test
    python stg_infra/examples/outcome_model_check.py
"""
import sys, argparse
import numpy as np

sys.path.insert(0, "stg_infra")
TRAIN = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL = ["2025-06", "2025-07"]
FEATS = ["mid", "spread", "ttc_h", "n_legs", "second_mid", "basket_sum", "trades_24h", "dmid_24h",
         "hour_utc", "charged", "cat_i"]


def rows_for_month(mo, lookup):
    import simulate_maker as s
    from diagnose_basket_composition import category_of
    legs, events, charged = s.load([mo], "mece")
    H = s.H_NS
    out, seen = [], set()
    for ev, tks in events.items():
        hours = sorted({int(e) for tk in tks for e in legs[tk]["e"]})
        for Hh in hours:
            if s.month_of(Hh) != mo:
                continue
            q = {}
            for tk in tks:
                L = legs[tk]; j = np.searchsorted(L["e"], Hh)
                if j < len(L["e"]) and L["e"][j] == Hh and not (np.isnan(L["bid"][j]) or np.isnan(L["ask"][j])):
                    b, a = int(round(L["bid"][j] * 100)), int(round(L["ask"][j] * 100))
                    if 0 < b < a < 100:
                        q[tk] = (b, a)
            for tk, (b, a) in q.items():
                L = legs[tk]; mid = (a + b) / 2
                if not (85 <= mid <= 99) or L["close"] is None or Hh >= L["close"] or L["close"] - Hh < 24 * H:
                    continue
                key = (tk, Hh // (24 * H))
                if key in seen:
                    continue
                seen.add(key)
                others = sorted(((x[0] + x[1]) / 2 for t, x in q.items() if t != tk), reverse=True)
                j24 = np.searchsorted(L["e"], Hh - 24 * H)
                dm = (mid - (L["bid"][j24] + L["ask"][j24]) * 50
                      if j24 < len(L["e"]) and L["e"][j24] == Hh - 24 * H and not np.isnan(L["bid"][j24] + L["ask"][j24])
                      else np.nan)
                out.append(dict(event=ev, month=mo, y=int(bool(L["yes"])), mid=mid, spread=a - b,
                                ttc_h=(L["close"] - Hh) / H, n_legs=len(tks), second_mid=others[0] if others else 0.0,
                                basket_sum=mid + sum(others), trades_24h=s.recent_trades(L["tt"], Hh) if "tt" in L else 0,
                                dmid_24h=dm, hour_utc=(Hh // H) % 24, charged=float(charged(L["series"], mo)),
                                cat=category_of(L["series"], lookup)))
    return out


def band_auc(y_upset, score, mid, width=2.0):
    """AUC for upsets computed inside mid bands and pooled (weighted by pairs): skill beyond price."""
    from sklearn.metrics import roc_auc_score
    num = den = 0.0
    for lo in np.arange(85, 99, width):
        sel = (mid >= lo) & (mid < lo + width)
        pos, neg = y_upset[sel].sum(), (1 - y_upset[sel]).sum()
        if pos >= 3 and neg >= 3:
            w = pos * neg
            num += w * roc_auc_score(y_upset[sel], score[sel]); den += w
    return num / den if den else np.nan


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    rng = np.random.default_rng(0)
    n = 20000
    mid = rng.uniform(85, 99, n); z = rng.normal(size=n)
    y_up_price_only = (rng.random(n) > mid / 100).astype(int)
    a0 = band_auc(y_up_price_only, rng.normal(size=n), mid)
    check(f"random score: within-band AUC ~0.5 ({a0:.3f})", 0.46 < a0 < 0.54)
    a_mid = band_auc(y_up_price_only, -mid, mid)
    check(f"price itself has little within-band AUC ({a_mid:.3f})", a_mid < 0.56)
    p_up = np.clip((1 - mid / 100) * np.exp(0.8 * z), 0, 1)
    y_up = (rng.random(n) < p_up).astype(int)
    a1 = band_auc(y_up, z, mid)
    check(f"planted feature beyond price: within-band AUC high ({a1:.3f})", a1 > 0.65)
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
    from sklearn.metrics import roc_auc_score
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    rows = []
    for mo in TRAIN + VAL:                      # one month at a time keeps memory low
        rows += rows_for_month(mo, lookup)
        print(f"  {mo}: {len(rows):,} rows so far", flush=True)
    df = pl.DataFrame(rows)
    cats = sorted(df["cat"].unique().to_list())
    df = df.with_columns(pl.col("cat").map_elements(lambda x: float(cats.index(x)), return_dtype=pl.Float64).alias("cat_i"))
    tr, va = df.filter(pl.col("month").is_in(TRAIN)), df.filter(pl.col("month").is_in(VAL))
    Xtr, Xva = tr.select(FEATS).to_numpy().astype(float), va.select(FEATS).to_numpy().astype(float)
    ytr, yva = tr["y"].to_numpy(), va["y"].to_numpy()
    mid_va = va["mid"].to_numpy(); ev = va["event"].to_numpy()
    print(f"\nDEVELOPMENT MONTHS ONLY. MECE legs at 85-99c, >24h to close, one row per leg-day:")
    print(f"  train {tr.height:,} rows / {tr['event'].n_unique():,} events; validation {va.height:,} / {va['event'].n_unique():,}")
    print(f"  upset rate (settles NO): train {1 - ytr.mean():.1%}, validation {1 - yva.mean():.1%}; "
          f"mean implied upset (100-mid): validation {100 - mid_va.mean():.1f}%")
    gbm = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=100,
                                         l2_regularization=1.0, random_state=0,
                                         categorical_features=[f == "cat_i" for f in FEATS]).fit(Xtr, ytr)
    p_gbm = gbm.predict_proba(Xva)[:, 1]
    p_iso = IsotonicRegression(y_min=1e-3, y_max=1 - 1e-3, out_of_bounds="clip").fit(tr["mid"].to_numpy(), ytr).predict(mid_va)
    ll = lambda p: -(yva * np.log(np.clip(p, 1e-4, 1)) + (1 - yva) * np.log(np.clip(1 - p, 1e-4, 1)))
    print("\nVALIDATION log-loss (lower is better):")
    for nm, p in (("price (mid)", mid_va / 100), ("isotonic calibration of price", p_iso), ("GBM on features", p_gbm)):
        print(f"  {nm:<31}: {ll(p).mean():.4f}")
    d = ll(p_gbm) - ll(p_iso)
    _, inv = np.unique(ev, return_inverse=True); k = inv.max() + 1
    s_ = np.bincount(inv, weights=d, minlength=k); cn = np.bincount(inv, minlength=k)
    b = np.random.default_rng(0).integers(0, k, size=(2000, k))
    lo, hi = np.percentile(s_[b].sum(1) / cn[b].sum(1), [2.5, 97.5])
    print(f"  GBM - isotonic: {d.mean():+.4f}  CI95 [{lo:+.4f}, {hi:+.4f}]  (k={k}; negative = features add information)")
    up = 1 - yva
    print("\nVALIDATION upset AUC (predicting settles NO):")
    print(f"  price alone         : {roc_auc_score(up, -mid_va):.3f}")
    print(f"  GBM                 : {roc_auc_score(up, 1 - p_gbm):.3f}")
    print(f"  WITHIN 2c price bands (skill beyond price): GBM {band_auc(up, 1 - p_gbm, mid_va):.3f}   "
          f"price {band_auc(up, -mid_va, mid_va):.3f}   <- A10 needs ~0.65-0.70")


if __name__ == "__main__":
    main()
