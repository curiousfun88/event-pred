"""
ablate_g2.py

FEATURE-GROUP ABLATION AND POSTING-THRESHOLD SENSITIVITY FOR THE G2 MAKER POLICY.
Offline, on A15's five walk-forward folds (test months 2026-04..08, each trained on every month
before it; runs/tune_gbm/features.npz, G2-W3's exact training rows). The September 2026
validation window and every forward-test hour are never read. Nothing here is selected or
deployed: the live G2 is unchanged.

Model: G2 exactly (tune_gbm GRID[0] "hgb_a12", maker_policy.HP). The full model reproduces A15's
hgb_a12 fold returns.

1. Ablation: retrain with one feature group removed (groups as in the report's feature table:
   order, market, basket, context) and score at G2's 1c rule. Reported per fold, mean and worst,
   and full minus variant on the mean of the fold returns with a 95% bootstrap interval
   (events resampled within each fold, paired: the same draw for both models).
2. Threshold: the full model's predictions scored at thresholds 0, 0.5, 1, 2, 4c (1c is G2's
   fixed rule; descriptive only).

USAGE (from repo root):
    python stg_infra/examples/ablate_g2.py --self-test
    python stg_infra/examples/ablate_g2.py run      # ~3 min on the laptop
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

import tune_gbm as tg  # noqa: E402

OUT = _REPO / "results/maker/ablation_g2_2026.json"
GROUPS = {"order": ["side", "price", "rel_price"],
          "market": ["spread", "mid", "trades_24h", "dmid_24h"],
          "basket": ["n_legs", "n_quoted", "basket_sum", "second_mid"],
          "context": ["hour_utc", "charged", "cat_i"]}
THRESHOLDS = [0.0, 0.5, 1.0, 2.0, 4.0]
N_BOOT = 2000


def score_at(pred, net_c, capital_c, thr):
    keep = pred > thr
    cap = capital_c[keep].sum()
    return {"kept": int(keep.sum()), "share": float(keep.mean()),
            "ret": float(100 * net_c[keep].sum() / cap) if cap > 0 else float("nan"),
            "net_usd": float(net_c[keep].sum() / 100)}


def event_sums(event, keep, net_c, capital_c):
    """Per-event kept net and capital, on a shared event index."""
    u, inv = np.unique(event, return_inverse=True)
    return (np.bincount(inv, weights=np.where(keep, net_c, 0.0), minlength=len(u)),
            np.bincount(inv, weights=np.where(keep, capital_c, 0.0), minlength=len(u)))


def paired_boot(folds, n_boot=N_BOOT, seed=0):
    """folds: list of (net_a, cap_a, net_b, cap_b) per-event arrays. Returns the mean-of-fold
    return difference a - b and its 95% interval, resampling events within each fold."""
    rng = np.random.default_rng(seed)
    diff = np.mean([100 * (na.sum() / ca.sum() - nb.sum() / cb.sum()) for na, ca, nb, cb in folds])
    draws = np.zeros(n_boot)
    for na, ca, nb, cb in folds:
        W = rng.multinomial(len(na), np.full(len(na), 1 / len(na)), size=n_boot)
        draws += 100 * ((W @ na) / (W @ ca) - (W @ nb) / (W @ cb))
    draws /= len(folds)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(diff), float(lo), float(hi)


def fit_fold(D, cols, tm):
    tr, te = tg.fold(D["month"], tm)
    feats = list(D["feats"])
    X = D["X"][:, cols]
    cat_col = cols.index(feats.index("cat_i")) if feats.index("cat_i") in cols else -1
    pred, _ = tg.fit_predict(tg.GRID[0], X[tr], D["y"][tr], np.ones(int(tr.sum())), cat_col, X[te], D["month"][tr])
    return pred, te


def run():
    D = tg.load()
    feats = list(D["feats"])
    assert sorted(sum(GROUPS.values(), [])) == sorted(feats), "groups must partition the features"
    variants = {"full": list(range(len(feats)))}
    for g, fs in GROUPS.items():
        variants[f"no_{g}"] = [i for i, f in enumerate(feats) if f not in fs]
    preds, res = {}, {"note": "offline, A15 folds 2026-04..08, G2 model; descriptive, nothing selected",
                      "groups": GROUPS, "ablation": {}, "threshold": {}}
    for name, cols in variants.items():
        rows = []
        for tm in tg.TEST_MONTHS:
            pred, te = fit_fold(D, cols, tm)
            preds[(name, tm)] = (pred, te)
            r = score_at(pred, D["net_c"][te], D["capital_c"][te], tg.THRESHOLD_C)
            rows.append({"test_month": tm, **r})
            print(f"  {name:<11} {tm}: {r['ret']:+6.2f}%  kept {r['kept']:>6,} ({100 * r['share']:4.1f}%)", flush=True)
        rets = [r["ret"] for r in rows]
        res["ablation"][name] = {"folds": rows, "mean_ret": float(np.mean(rets)), "worst_ret": float(min(rets)),
                                 "mean_share": float(np.mean([r["share"] for r in rows])),
                                 "net_usd": float(sum(r["net_usd"] for r in rows))}
    for name in variants:
        if name == "full":
            continue
        folds = []
        for tm in tg.TEST_MONTHS:
            (pa, te), (pb, _) = preds[("full", tm)], preds[(name, tm)]
            ev, net, cap = D["event"][te], D["net_c"][te], D["capital_c"][te]
            folds.append((*event_sums(ev, pa > tg.THRESHOLD_C, net, cap), *event_sums(ev, pb > tg.THRESHOLD_C, net, cap)))
        d, lo, hi = paired_boot(folds)
        res["ablation"][name]["full_minus"] = {"diff_pp": d, "lo": lo, "hi": hi}
    for thr in THRESHOLDS:
        rows = []
        for tm in tg.TEST_MONTHS:
            pred, te = preds[("full", tm)]
            rows.append({"test_month": tm, **score_at(pred, D["net_c"][te], D["capital_c"][te], thr)})
        rets = [r["ret"] for r in rows]
        res["threshold"][f"{thr:g}"] = {"folds": rows, "mean_ret": float(np.mean(rets)), "worst_ret": float(min(rets)),
                                        "mean_share": float(np.mean([r["share"] for r in rows])),
                                        "net_usd": float(sum(r["net_usd"] for r in rows))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(res, indent=1))
    print(f"\nABLATION (1c rule; mean and worst of {len(tg.TEST_MONTHS)} folds; full minus variant, 95% interval)")
    for name, r in res["ablation"].items():
        fm = r.get("full_minus")
        print(f"  {name:<11} mean {r['mean_ret']:+6.2f}%  worst {r['worst_ret']:+6.2f}%  share {100 * r['mean_share']:5.1f}%"
              f"  net ${r['net_usd']:>+9,.0f}" + (f"  full-minus {fm['diff_pp']:+5.2f} [{fm['lo']:+5.2f}, {fm['hi']:+5.2f}]" if fm else ""))
    print("\nTHRESHOLD (full model)")
    for t, r in res["threshold"].items():
        print(f"  >{t:>4}c  mean {r['mean_ret']:+6.2f}%  worst {r['worst_ret']:+6.2f}%  share {100 * r['mean_share']:5.1f}%"
              f"  net ${r['net_usd']:>+9,.0f}")
    print(f"\nwrote {OUT}")


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    check("groups match the report's 14 features, no overlap",
          len(sum(GROUPS.values(), [])) == 14 == len(set(sum(GROUPS.values(), []))))
    r = score_at(np.array([5.0, 0.5, 2.0]), np.array([10.0, -50.0, -2.0]), np.full(3, 100.0), 1.0)
    check(f"score_at keeps pred > thr: (10-2)/200 = 4% ({r['ret']:.2f}%), net $0.08",
          r["kept"] == 2 and abs(r["ret"] - 4) < 1e-12 and abs(r["net_usd"] - 0.08) < 1e-12)
    check("threshold 0 keeps every positive prediction",
          score_at(np.array([0.1, -0.1]), np.ones(2), np.ones(2), 0.0)["kept"] == 1)
    n, c = event_sums(np.array(["b", "a", "b"]), np.array([True, True, False]), np.array([1.0, 2.0, 4.0]), np.ones(3))
    check(f"event_sums groups by event and drops unkept fills (a: 2, b: 1) {n}", list(n) == [2.0, 1.0] and list(c) == [1.0, 1.0])
    # identical models -> difference 0 with a degenerate interval
    rng = np.random.default_rng(2)
    net, cap = rng.normal(1, 5, 300), np.full(300, 100.0)
    d, lo, hi = paired_boot([(net, cap, net, cap)] * 2, n_boot=200)
    check(f"paired bootstrap: same model -> 0 [0, 0] ({d:.3f} [{lo:.3f}, {hi:.3f}])", d == 0 and lo == 0 and hi == 0)
    # planted gap: a earns +2% per event, b 0% -> diff +2 inside a tight interval
    d, lo, hi = paired_boot([(np.full(400, 2.0) + rng.normal(0, .1, 400), cap.repeat(2)[:400],
                              rng.normal(0, .1, 400), cap.repeat(2)[:400])], n_boot=300)
    check(f"paired bootstrap recovers a planted +2 pp gap ({d:+.2f} [{lo:+.2f}, {hi:+.2f}])", 1.9 < lo < d < hi < 2.1)
    # planted signal in one group: dropping it destroys the model, dropping another does not
    n = 20_000
    X = rng.normal(size=(n, 3)).astype(np.float32); X[:, 2] = rng.integers(0, 4, n)
    y = np.where(X[:, 0] > 0, 20.0, -20.0)
    month = np.array(["2026-03"] * 15_000 + ["2026-04"] * 5_000)
    D = {"X": X, "y": y, "month": month, "feats": np.array(["price", "spread", "cat_i"])}
    for cols, want, msg in (([0, 1, 2], True, "all features"), ([1, 2], False, "signal column dropped"),
                            ([0, 1], True, "categorical dropped (cat_col -> -1)")):
        pred, te = fit_fold(D, cols, "2026-04")
        r = score_at(pred, y[te], np.full(int(te.sum()), 100.0), 1.0)
        good = r["kept"] > 0 and r["ret"] > 19
        check(f"planted rule, {msg}: kept ret {r['ret']:+.1f}% -> {'learns' if want else 'cannot learn'}", good == want)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["run"])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.cmd == "run":
        run()
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
