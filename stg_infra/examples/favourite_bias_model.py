"""Exploratory (development months only): is the favourite-longshot mispricing
among A10's quote candidates PREDICTABLE, and stable from train to validation?

Candidates replicate A10's filters (runs/maker/selected_a10.json): MECE legs,
two-sided quote at hour H, H more than 24h before close, taker-only series,
spread >= 4c, and an improved order price (bid+1 or ask-1) inside 85-99c.
One row per leg per UTC day (the first qualifying hour) to limit dependence.

Label: the leg settles YES. Baselines: price-implied probability (mid) and an
isotonic calibration curve on mid (fitted on train). Model: gradient boosting
on features known at H. Fit on TRAIN months, scored on VALIDATION months only.

Economic view (necessary condition only; ignores which quotes would fill):
value if filled of the bid order (buy YES at bid+1) and ask order (sell YES
at ask-1), by model decile of (model_p - mid).

    python stg_infra/examples/favourite_bias_model.py --self-test
    python stg_infra/examples/favourite_bias_model.py
"""
import sys, math, argparse
import numpy as np

sys.path.insert(0, "stg_infra")
TRAIN = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL = ["2025-06", "2025-07"]
FEATS = ["mid", "spread", "ttc_h", "n_legs", "n_quoted", "second_mid", "trades_24h", "dmid_24h", "hour_utc", "cat"]


def logloss(y, p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def event_ci(v, g, n_boot=2000, seed=0):
    _, inv = np.unique(g, return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k); c = np.bincount(inv, minlength=k).astype(float)
    idx = np.random.default_rng(seed).integers(0, k, size=(n_boot, k))
    return v.mean(), tuple(np.percentile(s[idx].sum(1) / c[idx].sum(1), [2.5, 97.5])), k


def candidates(months):
    import simulate_maker as s
    from diagnose_basket_composition import category_of
    import polars as pl
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    legs, events, charged = s.load(months, "mece")
    H = s.H_NS
    rows, seen = [], set()
    for ev, tks in events.items():
        hours = sorted({int(e) for tk in tks for e in legs[tk]["e"]})
        for Hh in hours:
            mo = s.month_of(Hh)
            if mo not in months or charged(legs[tks[0]]["series"], mo):
                continue
            mids = {}
            for tk in tks:
                L = legs[tk]; j = np.searchsorted(L["e"], Hh)
                if j < len(L["e"]) and L["e"][j] == Hh and not (np.isnan(L["bid"][j]) or np.isnan(L["ask"][j])):
                    b, a = int(round(L["bid"][j] * 100)), int(round(L["ask"][j] * 100))
                    if 0 < b < a < 100:
                        mids[tk] = (b, a, j)
            for tk, (b, a, j) in mids.items():
                L = legs[tk]
                if L["close"] is None or Hh >= L["close"] or L["close"] - Hh < 24 * H or a - b < 4:
                    continue
                bid_o, ask_o = b + 1, a - 1                     # spread >= 4 -> A10 improves by 1c
                if not (85 <= bid_o <= 99 or 85 <= ask_o <= 99):
                    continue
                day = (tk, Hh // (24 * H))
                if day in seen:
                    continue
                seen.add(day)
                others = sorted(((x[0] + x[1]) / 2 for t, x in mids.items() if t != tk), reverse=True)
                j24 = np.searchsorted(L["e"], Hh - 24 * H)
                dm = ((b + a) / 2 - (L["bid"][j24] + L["ask"][j24]) * 50
                      if j24 < len(L["e"]) and L["e"][j24] == Hh - 24 * H and not np.isnan(L["bid"][j24] + L["ask"][j24])
                      else np.nan)
                rows.append(dict(event=ev, month=mo, y=int(bool(L["yes"])), mid=(b + a) / 2, spread=a - b,
                                 ttc_h=(L["close"] - Hh) / H, n_legs=len(tks), n_quoted=len(mids),
                                 second_mid=others[0] if others else 0.0,
                                 trades_24h=s.recent_trades(L["tt"], Hh) if "tt" in L else 0,
                                 dmid_24h=dm, hour_utc=(Hh // H) % 24,
                                 cat=category_of(L["series"], lookup), bid_o=bid_o, ask_o=ask_o))
    return rows


def fit_predict(Xtr, ytr, Xte, cat_col):
    from sklearn.ensemble import HistGradientBoostingClassifier
    mask = [i == cat_col for i in range(Xtr.shape[1])]
    m = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.03, max_leaf_nodes=15, min_samples_leaf=50,
                                       l2_regularization=1.0, categorical_features=mask, random_state=0)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def isotonic(x_tr, y_tr, x_te):
    from sklearn.isotonic import IsotonicRegression
    return IsotonicRegression(y_min=1e-3, y_max=1 - 1e-3, out_of_bounds="clip").fit(x_tr, y_tr).predict(x_te)


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted)")
    rng = np.random.default_rng(0)
    n = 20000
    mid = rng.uniform(85, 98, n); z = rng.normal(size=n); cat = rng.integers(0, 3, n)
    # planted: true win prob = price + 8c when z > 0 (underpriced), price - 8c otherwise
    # (favourites lose rarely, so a small planted effect needs a large sample to be learnable)
    p_true = np.clip(mid / 100 + np.where(z > 0, 0.08, -0.08), 0.01, 0.999)
    y = (rng.random(n) < p_true).astype(int)
    X = np.c_[mid, z, cat]
    tr, te = np.arange(n) < 14000, np.arange(n) >= 14000
    pm = fit_predict(X[tr], y[tr], X[te], 2)
    ll_m, ll_p = logloss(y[te], pm).mean(), logloss(y[te], mid[te] / 100).mean()
    check(f"planted heterogeneity: model log-loss {ll_m:.4f} < price {ll_p:.4f}", ll_m < ll_p)
    y0 = (rng.random(n) < mid / 100).astype(int)
    pm0 = fit_predict(X[tr], y0[tr], X[te], 2)
    iso0 = isotonic(mid[tr], y0[tr], mid[te])
    check("no heterogeneity: model does not beat isotonic by > 1%",
          logloss(y0[te], pm0).mean() > 0.99 * logloss(y0[te], iso0).mean())
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
    rows = candidates(TRAIN + VAL)
    df = pl.DataFrame(rows)
    cats = sorted(df["cat"].unique().to_list())
    df = df.with_columns(pl.col("cat").map_elements(lambda c: float(cats.index(c)), return_dtype=pl.Float64).alias("cat_i"))
    tr = df.filter(pl.col("month").is_in(TRAIN)); va = df.filter(pl.col("month").is_in(VAL))
    cols = [f if f != "cat" else "cat_i" for f in FEATS]
    Xtr, Xva = tr.select(cols).to_numpy().astype(float), va.select(cols).to_numpy().astype(float)
    ytr, yva = tr["y"].to_numpy(), va["y"].to_numpy()
    print(f"DEVELOPMENT MONTHS ONLY. A10 candidates, one row per leg-day: train {tr.height:,} "
          f"({tr['event'].n_unique():,} events), validation {va.height:,} ({va['event'].n_unique():,} events)")
    print(f"favourite bias (win rate - mid): train {ytr.mean() * 100 - tr['mid'].mean():+.2f}c, "
          f"validation {yva.mean() * 100 - va['mid'].mean():+.2f}c")
    p_price = va["mid"].to_numpy() / 100
    p_iso = isotonic(tr["mid"].to_numpy(), ytr, va["mid"].to_numpy())
    p_gbm = fit_predict(Xtr, ytr, Xva, cols.index("cat_i"))
    ev = va["event"].to_numpy()
    print("\nVALIDATION log-loss (lower is better):")
    base = logloss(yva, p_iso)
    for nm, p in (("price (mid)", p_price), ("isotonic calibration on price", p_iso), ("GBM on features", p_gbm)):
        print(f"  {nm:<32}: {logloss(yva, p).mean():.4f}")
    d = logloss(yva, p_gbm) - base
    m, (lo, hi), k = event_ci(d, ev)
    print(f"  GBM - isotonic: {m:+.4f}  CI95 [{lo:+.4f}, {hi:+.4f}]  (k={k} events; negative = features add information)")
    edge = p_gbm * 100 - va["mid"].to_numpy()
    print("\nVALIDATION value IF FILLED, cents/contract, by model edge decile (model_p - mid):")
    print(f"  {'decile':>6} {'n':>6} {'mean edge':>10} {'win rate - mid':>15} {'buy@bid+1':>11} {'sell@ask-1':>11}")
    bid_o, ask_o, mid = va["bid_o"].to_numpy(), va["ask_o"].to_numpy(), va["mid"].to_numpy()
    buy = np.where((bid_o >= 85) & (bid_o <= 99), yva * 100 - bid_o, np.nan)
    sell = np.where((ask_o >= 85) & (ask_o <= 99), ask_o - yva * 100, np.nan)
    qs = np.quantile(edge, np.linspace(0, 1, 11))
    for i in range(10):
        s_ = (edge >= qs[i]) & (edge <= qs[i + 1]) if i == 9 else (edge >= qs[i]) & (edge < qs[i + 1])
        print(f"  {i + 1:>6} {s_.sum():>6} {edge[s_].mean():>+10.2f} {yva[s_].mean() * 100 - mid[s_].mean():>+15.2f}"
              f" {np.nanmean(buy[s_]):>+11.2f} {np.nanmean(sell[s_]):>+11.2f}")
    top = edge >= np.quantile(edge, 0.7); bot = edge <= np.quantile(edge, 0.3)
    for nm, sel, v in (("buy, model top 30%", top, buy), ("buy, all", np.ones_like(top), buy),
                       ("sell, model bottom 30%", bot, sell), ("sell, all", np.ones_like(bot), sell)):
        ok_ = sel & ~np.isnan(v)
        m, (lo, hi), k = event_ci(v[ok_], ev[ok_])
        print(f"  {nm:<24}: {m:+.2f}c  CI95 [{lo:+.2f}, {hi:+.2f}]  (n={ok_.sum()}, k={k})")


if __name__ == "__main__":
    main()
