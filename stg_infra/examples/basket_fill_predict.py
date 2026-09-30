"""Exploratory (development months only): can features known at quoting hour
H predict which whole-basket maker attempts complete (every leg filled)? If a
gradient-boosted model cannot, an STGAT fill predictor is unlikely to either.

Input: results/mece/basket_explore_*.npy (explore_basket_maker.py, 20 columns).
Label: full = every leg filled in (H, H+1h]. Out-of-fold predictions via
GroupKFold by EVENT. Reported: AUC vs base rate; the full-fill share and the
'cond' P&L (cents per 1-contract basket attempt) of the top-scored attempts
vs all attempts and vs the trivial rule "3-leg baskets only"; CIs resample
events.

    python stg_infra/examples/basket_fill_predict.py --self-test
    python stg_infra/examples/basket_fill_predict.py results/mece/basket_explore_2024-11_2025-07.npy
"""
import sys, argparse
import numpy as np

sys.path.insert(0, "stg_infra")
FEATS = ["side", "n_legs", "liquid", "edge", "hour_utc", "ttc_h", "min_tr3", "mean_tr3", "sum_spread", "max_price"]


def frame(a):
    ev = a[:, 0].astype(str)
    X = np.c_[a[:, 2].astype(float), a[:, 3].astype(float), a[:, 4].astype(float), a[:, 5].astype(float),
              a[:, 14].astype(float), a[:, 15].astype(float), a[:, 16].astype(float), a[:, 17].astype(float),
              a[:, 18].astype(float), a[:, 19].astype(float)]
    full = (a[:, 6].astype(int) == a[:, 3].astype(int)).astype(int)
    cond = a[:, 10].astype(float)
    series = a[:, 11].astype(str)
    return ev, X, full, cond, series


def oof_scores(X, y, groups, cats, n_splits=5, seed=0):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.model_selection import GroupKFold
    Xc = np.c_[X, cats]
    cat_mask = [False] * X.shape[1] + [True]
    p = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=n_splits).split(Xc, y, groups):
        m = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, max_leaf_nodes=15,
                                           categorical_features=cat_mask, random_state=seed)
        m.fit(Xc[tr], y[tr])
        p[te] = m.predict_proba(Xc[te])[:, 1]
    return p


def auc(y, s):
    from sklearn.metrics import roc_auc_score
    return roc_auc_score(y, s) if 0 < y.mean() < 1 else np.nan


def mean_ci(v, g, n_boot=2000, seed=0):
    if len(v) == 0:
        return np.nan, (np.nan, np.nan), 0
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
    print("SELF-TEST (planted)")
    rng = np.random.default_rng(0)
    n, ev = 4000, np.repeat(np.arange(400), 10).astype(str)
    X = rng.normal(size=(n, len(FEATS)))
    cats = rng.integers(0, 3, n).astype(float)
    y_sig = (X[:, 6] + 0.3 * rng.normal(size=n) > 1.0).astype(int)
    y_noise = (rng.random(n) < y_sig.mean()).astype(int)
    a_sig = auc(y_sig, oof_scores(X, y_sig, ev, cats))
    a_noise = auc(y_noise, oof_scores(X, y_noise, ev, cats))
    check(f"planted signal in one feature -> high AUC ({a_sig:.2f})", a_sig > 0.9)
    check(f"pure noise label -> AUC ~0.5 ({a_noise:.2f})", 0.44 < a_noise < 0.56)
    m, (lo, hi), k = mean_ci(np.array([1., 1, 5, 5]), np.array(["a", "a", "b", "b"]))
    check("cluster CI brackets the mean", lo <= m <= hi and k == 2)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npy", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    a_ = ap.parse_args()
    if a_.self_test:
        sys.exit(0 if self_test() else 1)
    a = np.load(a_.npy, allow_pickle=True)
    if a.shape[1] < 20:
        raise SystemExit("needs the 20-column file (rerun explore_basket_maker.py)")
    ev, X, full, cond, series = frame(a)
    from diagnose_basket_composition import category_of
    import polars as pl
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    cat_names = np.array([category_of(s, lookup) for s in series])
    _, cats = np.unique(cat_names, return_inverse=True)
    print(f"DEVELOPMENT MONTHS ONLY: {len(full):,} basket attempts, {len(np.unique(ev)):,} events; "
          f"full-fill base rate {full.mean():.2%}")
    p = oof_scores(X, full, ev, cats.astype(float))
    print(f"out-of-fold AUC (event-grouped 5-fold): {auc(full, p):.3f}")
    three = X[:, 1] == 3
    print(f"trivial rule '3-leg baskets only': full rate {full[three].mean():.2%} on {three.sum():,} attempts; "
          f"AUC of -n_legs {auc(full, -X[:, 1]):.3f}")
    print(f"\n{'selection':<34}{'attempts':>9}{'events':>7}{'full rate':>10}{'cond P&L c/attempt':>20}   CI95")
    rows = [("all attempts", np.ones(len(full), bool)), ("3-leg only (trivial rule)", three)]
    for q in (0.5, 0.8, 0.9, 0.95):
        rows.append((f"model top {100 - int(q * 100)}%", p >= np.quantile(p, q)))
        rows.append((f"model top {100 - int(q * 100)}% within 3-leg", three & (p >= np.quantile(p[three], q))))
    for nm, sel in rows:
        m, (lo, hi), k = mean_ci(cond[sel], ev[sel])
        print(f"{nm:<34}{sel.sum():>9,}{k:>7,}{full[sel].mean():>10.1%}{m:>+20.2f}   [{lo:+.2f}, {hi:+.2f}]")
    from sklearn.inspection import permutation_importance  # noqa: F401  (kept light: report simple correlations)
    print("\nfull-fill rate by feature quartile (at-H features):")
    for j, f in enumerate(FEATS):
        x = X[:, j]
        if np.nanstd(x) == 0:
            continue
        qs = np.nanquantile(x, [0.25, 0.5, 0.75])
        b = np.digitize(x, qs)
        print(f"  {f:<11}" + "  ".join(f"Q{i + 1} {full[b == i].mean():5.1%}" for i in range(4)))


if __name__ == "__main__":
    main()
