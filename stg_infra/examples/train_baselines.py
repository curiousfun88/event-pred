"""
train_baselines.py

LIVE BASELINE MODELS lin2 (amendment L3) AND mlp2 (amendment L6): both trained on
exactly G2-W3's training fills and targets (net c/contract, pessimistic fills), on
G's 14 features, posted live if predicted > 1c, like G2.

Shared design matrix: 13 numeric features; missing dmid_24h (no two-sided quote 24h
earlier) set to 0 (no mid change) with a missing-indicator; category one-hot (the
`cat_i` slot; an unseen category is all-zero). Any NaN in another feature is an error,
never imputed silently. Columns are standardised with training mean/std (std 0 -> 1).

lin2 (L3): ridge regression, alpha 1.0.

mlp2 (L6): sklearn MLPRegressor, hidden layers (64, 32), ReLU, Adam (lr 1e-3), L2
alpha 1e-4, minibatch 1024, random_state 0, on standardised inputs and a standardised
target. Early stopping on a TIME-ORDERED holdout: the latest 10% of training rows by
quoting hour; up to 100 epochs, patience 10 (holdout MSE), the best epoch's weights kept.
The model is fitted on the earlier 90% only.

--verify-g2 refits G2-W3 from the same rows and checks the pickle's sha1 against the
pre-registered de87439617ba9476: the rows are then G2-W3's rows exactly.

USAGE (from repo root; on a Lumid batch sandbox with A13_LOCAL_DIR set):
    python stg_infra/examples/train_baselines.py --self-test
    A13_LOCAL_DIR=runs/maker/a13_local python stg_infra/examples/train_baselines.py --verify-g2
"""
from __future__ import annotations

import argparse
import copy
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

OUTDIR = _REPO / "runs/maker"
G2_W3_SHA1 = "de87439617ba9476"
G2_W3_N = 679_400
THRESHOLD_C = 1.0
ALPHA = 1.0
MLP = {"hidden_layer_sizes": (64, 32), "activation": "relu", "solver": "adam", "learning_rate_init": 1e-3,
       "alpha": 1e-4, "batch_size": 1024, "random_state": 0}
HOLDOUT, MAX_EPOCHS, PATIENCE = 0.10, 100, 10


def model_path(arm):
    return OUTDIR / f"policy_{arm}_W3_model.pkl"


def numeric_feats():
    import maker_policy as mp
    return [f for f in mp.FEATS_G if f != "cat_i"]


def design(rows, num, cats):
    """rows -> raw design matrix: numeric features, dmid_24h missing-indicator, category one-hot."""
    X = np.array([[r[f] for f in num] for r in rows], dtype=float).reshape(len(rows), len(num))
    j = num.index("dmid_24h")
    miss = np.isnan(X[:, j])
    X[miss, j] = 0.0
    bad = np.isnan(X).any(0)
    if bad.any():
        raise ValueError(f"NaN outside dmid_24h in {[f for f, b in zip(num, bad) if b]}: no imputation specified")
    C = np.array([[float(r["cat"] == c) for c in cats] for r in rows]).reshape(len(rows), len(cats))
    return np.hstack([X, miss[:, None].astype(float), C])


def _scaled(rows):
    num, cats = numeric_feats(), sorted({r["cat"] for r in rows})
    X = design(rows, num, cats)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    return (X - mu) / sd, {"mu": mu, "sd": sd, "num": num, "cats": cats}


def fit_lin2(rows, ys, alpha=None, scaled=None):
    """alpha: ridge penalty override (exploratory note 7 sensitivity only; None = lin2 exactly).
    scaled: a precomputed _scaled(rows), so a sweep builds the design matrix once."""
    from sklearn.linear_model import Ridge
    a = ALPHA if alpha is None else float(alpha)
    Z, meta = scaled if scaled is not None else _scaled(rows)
    return {**meta, "model": Ridge(alpha=a).fit(Z, np.asarray(ys, float)), "arm": "lin2", "alpha": a,
            "y_mu": 0.0, "y_sd": 1.0}


def time_split(rows, frac=HOLDOUT):
    """Indices (train, holdout): holdout = the latest `frac` of rows by quoting hour; ties by row order."""
    h = np.array([r["_H"] for r in rows])
    order = np.argsort(h, kind="stable")
    k = int(round(len(rows) * (1 - frac)))
    return np.sort(order[:k]), np.sort(order[k:])


def fit_mlp2(rows, ys, max_epochs=MAX_EPOCHS, patience=PATIENCE, log=print, hp=None):
    """hp: settings overriding MLP (exploratory note 3 sensitivity only; None = mlp2 exactly)."""
    from sklearn.neural_network import MLPRegressor
    Z, meta = _scaled(rows)
    y = np.asarray(ys, float)
    y_mu, y_sd = y.mean(), y.std() or 1.0
    t = (y - y_mu) / y_sd
    tr, ho = time_split(rows)
    m = MLPRegressor(**{**MLP, **(hp or {})})
    best, best_mse, best_ep, wait = None, np.inf, 0, 0
    for ep in range(1, max_epochs + 1):
        m.partial_fit(Z[tr], t[tr])
        mse = float(np.mean((m.predict(Z[ho]) - t[ho]) ** 2))
        if mse < best_mse - 1e-9:
            best, best_mse, best_ep, wait = copy.deepcopy(m), mse, ep, 0
        else:
            wait += 1
        log(f"  mlp2 epoch {ep:3d}  holdout mse {mse:.5f}  best {best_mse:.5f} @ {best_ep}")
        if wait >= patience:
            break
    return {**meta, "model": best, "arm": "mlp2", "mlp": {**MLP, **(hp or {})}, "best_epoch": best_ep, "holdout_mse_std": best_mse,
            "y_mu": float(y_mu), "y_sd": float(y_sd), "n_fit": int(len(tr)), "n_holdout": int(len(ho))}


def predict(blob, rows):
    """Predicted net c/contract for each candidate row (post iff > THRESHOLD_C)."""
    if not rows:
        return np.empty(0)
    Z = (design(rows, blob["num"], blob["cats"]) - blob["mu"]) / blob["sd"]
    return blob["model"].predict(Z) * blob["y_sd"] + blob["y_mu"]


def verify_g2(rows, ys):
    """Refit G2-W3 exactly as retrain_g2.train does, without writing; return its sha1 prefix."""
    import maker_policy as mp
    import retrain_g2 as rg
    from sklearn.ensemble import HistGradientBoostingRegressor
    cats = sorted({r["cat"] for r in rows})
    f = rg.feats("G2")
    m = HistGradientBoostingRegressor(**mp.HP, categorical_features=[x == "cat_i" for x in f]).fit(
        rg.matrix("G2", rows, cats), np.array(ys))
    return hashlib.sha1(pickle.dumps({"model": m, "cats": cats, "feats": f, "design": "G2"})).hexdigest()[:16]


def save(blob, rows, ys, extra):
    p = model_path(blob["arm"])
    p.write_bytes(pickle.dumps(blob))
    sha = hashlib.sha1(p.read_bytes()).hexdigest()[:16]
    pred = predict(blob, rows)
    meta = {"arm": blob["arm"], "window": "W3", "rows_from": "G2-W3", "n_train": len(ys), **extra,
            "model_sha1": sha, "threshold_c": THRESHOLD_C, "categories": blob["cats"],
            "features": blob["num"] + ["dmid_24h_missing"] + [f"cat={c}" for c in blob["cats"]],
            "train_share_posted": round(float(np.mean(pred > THRESHOLD_C)), 4),
            "train_rmse_c": round(float(np.sqrt(np.mean((pred - np.asarray(ys)) ** 2))), 4),
            **{k: blob[k] for k in ("alpha", "mlp", "best_epoch", "holdout_mse_std", "n_fit", "n_holdout") if k in blob}}
    p.with_suffix(".json").write_text(json.dumps(meta, indent=1, default=str))
    print(json.dumps(meta, default=str), flush=True)
    return sha


def main_train(arms, check_g2):
    import retrain_g2 as rg
    rows, ys = rg.training_rows("W3", "G2")
    extra = {"rows_match_n": len(ys) == G2_W3_N,
             "dmid_24h_missing_share": round(float(np.mean([np.isnan(r["dmid_24h"]) for r in rows])), 4)}
    print(f"rows: {len(ys):,} (G2-W3 recorded {G2_W3_N:,})", flush=True)
    if check_g2:
        sha = verify_g2(rows, ys)
        extra.update({"g2_w3_refit_sha1": sha, "g2_w3_refit_matches": sha == G2_W3_SHA1})
        print(f"G2-W3 refit sha1 {sha} ({'MATCHES' if sha == G2_W3_SHA1 else 'DIFFERS FROM'} {G2_W3_SHA1})", flush=True)
    for arm in arms:
        save(fit_lin2(rows, ys) if arm == "lin2" else fit_mlp2(rows, ys), rows, ys, extra)


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    num = numeric_feats()
    rng = np.random.default_rng(0)
    cats = ["Sports", "Climate and Weather", "Financials"]
    beta = rng.normal(size=len(num))
    rows, ys = [], []
    for i in range(3000):
        r = {f: float(rng.normal()) for f in num}
        r["cat"], r["_H"] = cats[i % 3], 3000 - i      # later rows have EARLIER hours
        if i % 5 == 0:
            r["dmid_24h"] = np.nan
        rows.append(r)
        x = np.array([0.0 if np.isnan(r[f]) else r[f] for f in num])
        ys.append(float(x @ beta) + 2.0 * (r["cat"] == "Sports") - 1.5 * np.isnan(r["dmid_24h"]))

    b = fit_lin2(rows, ys)
    p = predict(b, rows)
    check("lin2: planted linear target recovered (rmse < 0.01)", np.sqrt(np.mean((p - np.array(ys)) ** 2)) < 0.01)
    check("design: 13 numeric + indicator + 3 one-hot columns", b["mu"].shape == (len(num) + 1 + 3,))
    one = dict(rows[1]); one["cat"] = "Sports"; two = dict(rows[1]); two["cat"] = "Financials"
    d = predict(b, [one])[0] - predict(b, [two])[0]
    check(f"lin2: category effect recovered (+2.0c, got {d:+.3f})", abs(d - 2.0) < 0.02)
    a = dict(rows[1]); a["dmid_24h"] = 0.0; m_ = dict(rows[1]); m_["dmid_24h"] = np.nan
    d = predict(b, [m_])[0] - predict(b, [a])[0]
    check(f"lin2: missing-indicator effect recovered (-1.5c, got {d:+.3f})", abs(d + 1.5) < 0.02)
    u = dict(rows[1]); u["cat"] = "Unseen"
    check("unseen category predicts (all-zero one-hot), no error", np.isfinite(predict(b, [u])[0]))
    bad = dict(rows[1]); bad["spread"] = np.nan
    try:
        predict(b, [bad]); raised = False
    except ValueError:
        raised = True
    check("NaN outside dmid_24h raises", raised)
    check("empty input -> empty prediction", predict(b, []).shape == (0,))
    check("lin2 deterministic: refit gives identical pickle", pickle.dumps(fit_lin2(rows, ys)) == pickle.dumps(b))
    sc = _scaled(rows)
    check("alpha override: alpha=1.0 and a precomputed design give lin2 exactly",
          pickle.dumps(fit_lin2(rows, ys, alpha=ALPHA, scaled=sc)) == pickle.dumps(b))
    big_a = fit_lin2(rows, ys, alpha=1e9, scaled=sc)
    check("alpha override: alpha=1e9 shrinks every coefficient to ~0",
          np.abs(big_a["model"].coef_).max() < 1e-3 * np.abs(b["model"].coef_).max() and big_a["alpha"] == 1e9)

    tr, ho = time_split(rows)
    hs = np.array([r["_H"] for r in rows])
    check("time split: holdout is the latest 10% by quoting hour, not the last rows",
          len(ho) == 300 and hs[ho].min() > hs[tr].max() and set(ho) == set(range(300)))
    # nonlinear planted target on a larger sample: with 1024-row minibatches a tiny sample gives too few updates
    quiet = lambda *a, **k: None
    big, ynl = [], []
    for i in range(30000):
        r = {f: float(rng.normal()) for f in num}
        r["cat"], r["_H"] = cats[i % 3], i
        big.append(r)
        ynl.append(3.0 * (r[num[0]] > 0) * np.sign(r[num[1]]) + r[num[2]] ** 2)   # interaction + curvature
    mb = fit_mlp2(big, ynl, max_epochs=40, log=quiet)
    lb = fit_lin2(big, ynl)
    e_m = np.sqrt(np.mean((predict(mb, big) - np.array(ynl)) ** 2))
    e_l = np.sqrt(np.mean((predict(lb, big) - np.array(ynl)) ** 2))
    check(f"mlp2 learns a planted nonlinear target that lin2 cannot (rmse {e_m:.2f} vs {e_l:.2f})", e_m < 0.5 * e_l)
    check(f"mlp2 keeps the best holdout epoch ({mb['best_epoch']}) and fits only the earlier 90%",
          1 <= mb["best_epoch"] <= 40 and mb["n_fit"] == 27000 and mb["n_holdout"] == 3000)
    mb2 = fit_mlp2(big, ynl, max_epochs=40, log=quiet)
    check("mlp2 deterministic: refit gives identical predictions",
          np.array_equal(predict(mb, big), predict(mb2, big)))
    check("mlp2 predictions are in target units (de-standardised)", abs(predict(mb, big).mean() - np.mean(ynl)) < 0.2)
    noise = fit_mlp2(big, list(rng.normal(size=len(big))), max_epochs=40, log=quiet)
    check(f"mlp2 early stopping: pure-noise target stops early (best epoch {noise['best_epoch']}, patience 10)",
          noise["best_epoch"] <= 29)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--verify-g2", action="store_true")
    ap.add_argument("--arms", nargs="+", default=["lin2", "mlp2"], choices=["lin2", "mlp2"])
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    main_train(a.arms, a.verify_g2)


if __name__ == "__main__":
    main()
