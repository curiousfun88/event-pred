"""
train_lin2.py

BASELINE ARM lin2 (amendment L3): ridge regression on G's 14 features, trained on
exactly G2-W3's training fills and targets (net c/contract, pessimistic fills).
Posted live if predicted > 1c, like G2.

Spec (L3): alpha 1.0; standardised features; category one-hot (the `cat_i` slot);
missing dmid_24h set to 0 with a missing-indicator. Order used here: the raw
dmid_24h is set to 0 (no mid change) and flagged, then every column is standardised
with training mean/std (std 0 -> 1). An unseen category at prediction time is all-zero
one-hot. Any NaN in another feature is an error, never imputed silently.

--verify-g2 refits G2-W3 from the same rows and checks the pickle's sha1 against the
pre-registered de87439617ba9476: the rows are then G2-W3's rows exactly.

USAGE (from repo root; on a Lumid batch sandbox with A13_LOCAL_DIR set):
    python stg_infra/examples/train_lin2.py --self-test
    A13_LOCAL_DIR=runs/maker/a13_local python stg_infra/examples/train_lin2.py [--verify-g2]
"""
from __future__ import annotations

import argparse
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

OUT = _REPO / "runs/maker/policy_lin2_W3_model.pkl"
G2_W3_SHA1 = "de87439617ba9476"
ALPHA = 1.0
THRESHOLD_C = 1.0


def numeric_feats():
    import maker_policy as mp
    return [f for f in mp.FEATS_G if f != "cat_i"]


def design(rows, num, cats):
    """rows -> raw design matrix: numeric features, dmid_24h missing-indicator, category one-hot."""
    X = np.array([[r[f] for f in num] for r in rows], dtype=float)
    j = num.index("dmid_24h")
    miss = np.isnan(X[:, j])
    X[miss, j] = 0.0
    bad = np.isnan(X).any(0)
    if bad.any():
        raise ValueError(f"NaN outside dmid_24h in {[f for f, b in zip(num, bad) if b]}: L3 specifies no imputation")
    C = np.array([[float(r["cat"] == c) for c in cats] for r in rows]).reshape(len(rows), len(cats))
    return np.hstack([X, miss[:, None].astype(float), C])


def fit(rows, ys):
    from sklearn.linear_model import Ridge
    num, cats = numeric_feats(), sorted({r["cat"] for r in rows})
    X = design(rows, num, cats)
    mu, sd = X.mean(0), X.std(0)
    sd[sd == 0] = 1.0
    m = Ridge(alpha=ALPHA).fit((X - mu) / sd, np.asarray(ys, float))
    return {"model": m, "mu": mu, "sd": sd, "num": num, "cats": cats, "design": "lin2", "alpha": ALPHA}


def predict(blob, rows):
    if not rows:
        return np.empty(0)
    return blob["model"].predict((design(rows, blob["num"], blob["cats"]) - blob["mu"]) / blob["sd"])


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


def main_train(check_g2):
    import retrain_g2 as rg
    rows, ys = rg.training_rows("W3", "G2")
    print(f"rows: {len(ys):,} (G2-W3 recorded 679,400)", flush=True)
    meta = {"amendment": "L3", "arm": "lin2", "window": "W3", "rows_from": "G2-W3", "n_train": len(ys),
            "rows_match_n": len(ys) == 679_400}
    if check_g2:
        sha = verify_g2(rows, ys)
        meta["g2_w3_refit_sha1"] = sha
        meta["g2_w3_refit_matches"] = sha == G2_W3_SHA1
        print(f"G2-W3 refit sha1 {sha} ({'MATCHES' if sha == G2_W3_SHA1 else 'DIFFERS FROM'} {G2_W3_SHA1})", flush=True)
    blob = fit(rows, ys)
    OUT.write_bytes(pickle.dumps(blob))
    sha = hashlib.sha1(OUT.read_bytes()).hexdigest()[:16]
    p = predict(blob, rows)
    meta.update({"model_sha1": sha, "alpha": ALPHA, "threshold_c": THRESHOLD_C, "categories": blob["cats"],
                 "features": blob["num"] + ["dmid_24h_missing"] + [f"cat={c}" for c in blob["cats"]],
                 "dmid_24h_missing_share": round(float(np.mean([np.isnan(r["dmid_24h"]) for r in rows])), 4),
                 "train_share_posted": round(float(np.mean(p > THRESHOLD_C)), 4),
                 "train_rmse_c": round(float(np.sqrt(np.mean((p - np.asarray(ys)) ** 2))), 4)})
    OUT.with_suffix(".json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta), flush=True)


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
        r["cat"] = cats[i % 3]
        if i % 5 == 0:
            r["dmid_24h"] = np.nan
        rows.append(r)
        x = np.array([0.0 if np.isnan(r[f]) else r[f] for f in num])
        ys.append(float(x @ beta) + 2.0 * (r["cat"] == "Sports") - 1.5 * np.isnan(r["dmid_24h"]))
    b = fit(rows, ys)
    p = predict(b, rows)
    check("planted linear target recovered (rmse < 0.01)", np.sqrt(np.mean((p - np.array(ys)) ** 2)) < 0.01)
    check("design: 13 numeric + indicator + 3 one-hot columns", b["mu"].shape == (len(num) + 1 + 3,))
    one = dict(rows[1]); one["cat"] = "Sports"; two = dict(rows[1]); two["cat"] = "Financials"
    d = predict(b, [one])[0] - predict(b, [two])[0]
    check(f"category effect recovered (+2.0c, got {d:+.3f})", abs(d - 2.0) < 0.02)
    a = dict(rows[1]); a["dmid_24h"] = 0.0; m_ = dict(rows[1]); m_["dmid_24h"] = np.nan
    d = predict(b, [m_])[0] - predict(b, [a])[0]
    check(f"missing-indicator effect recovered (-1.5c, got {d:+.3f})", abs(d + 1.5) < 0.02)
    u = dict(rows[1]); u["cat"] = "Unseen"
    check("unseen category predicts (all-zero one-hot), no error", np.isfinite(predict(b, [u])[0]))
    bad = dict(rows[1]); bad["spread"] = np.nan
    try:
        predict(b, [bad]); raised = False
    except ValueError:
        raised = True
    check("NaN outside dmid_24h raises", raised)
    check("empty input -> empty prediction", predict(b, []).shape == (0,))
    check("deterministic: refit gives identical pickle", pickle.dumps(fit(rows, ys)) == pickle.dumps(b))
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--verify-g2", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    main_train(a.verify_g2)


if __name__ == "__main__":
    main()
