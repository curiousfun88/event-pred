"""
tune_gbm.py

WALK-FORWARD HYPERPARAMETER SENSITIVITY FOR THE G2 MAKER POLICY.
Training months only (2024-11..2026-08). The September 2026 validation window and every
forward-test hour are never read. The grid, folds and selection rule below are pre-registered
as amendment A15 (docs/planning/maker-simulator-preregistration.md); `fit` refuses to score
real folds while AMENDMENT is unset.

Model: G2's own model, scikit-learn's HistGradientBoostingRegressor (CPU). "hgb_a12" is G2
exactly (maker_policy.HP); every other hgb row changes one thing from it. "xgb_a12" is a
library benchmark only: XGBoost with the A12 settings matched as closely as it allows,
runnable on CPU or GPU (--device cuda). It is not a candidate for selection.

Offline scoring: per fold, train on every month before the test month, predict the test
month's candidate fills (BROAD config, pessimistic, quote-everything), keep those predicted
above 1c (A12 threshold) and score return = net / capital over the kept fills. This
ignores the inventory interaction the full simulator has. The top settings are re-checked
in the simulator afterwards.

USAGE (from repo root):
    python stg_infra/examples/tune_gbm.py --self-test
    python stg_infra/examples/tune_gbm.py bench [--device cuda]       # synthetic data, timing only
    python stg_infra/examples/tune_gbm.py build                       # laptop, memory-capped, ~3 min
    python stg_infra/examples/tune_gbm.py fit --task 7 [--device cuda]
    python stg_infra/examples/tune_gbm.py summarise
On the cluster: sbatch --array=0-<n_tasks-1> cluster/tune_gbm.sbatch (n_tasks: `tasks`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

AMENDMENT = "A15"         # maker-simulator-preregistration.md, 2026-10-11
OUT = _REPO / "runs/tune_gbm"
FEATURES = OUT / "features.npz"
TEST_MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
THRESHOLD_C = 1.0           # A12
MIN_KEPT = 200              # a setting keeping fewer fills than this in any fold is ineligible

GRID = [{"name": "hgb_a12"},                                   # G2 itself
        {"name": "leaf100", "hp": {"min_samples_leaf": 100}},
        {"name": "leaf1000", "hp": {"min_samples_leaf": 1000}},
        {"name": "leaves15", "hp": {"max_leaf_nodes": 15}},
        {"name": "leaves63", "hp": {"max_leaf_nodes": 63}},
        {"name": "lr0.1_iter120", "hp": {"learning_rate": 0.1, "max_iter": 120}},
        {"name": "iter800", "hp": {"max_iter": 800}},
        {"name": "l2_10", "hp": {"l2_regularization": 10.0}},
        {"name": "features0.8", "hp": {"max_features": 0.8}},
        {"name": "early_stop_last_month", "early_stop": True},
        {"name": "recency_hl3", "half_life_m": 3},
        {"name": "recency_hl6", "half_life_m": 6},
        {"name": "abs_error", "hp": {"loss": "absolute_error"}},
        {"name": "bag5", "bag": 5},
        {"name": "xgb_a12", "model": "xgb"}]                    # library benchmark, not selectable
BENCHMARKS = {"xgb_a12"}
XGB_A12 = dict(eta=0.03, rounds=400, max_leaves=31, min_child_weight=300, reg_lambda=1.0)


def tasks():
    return [(g, f) for g in range(len(GRID)) for f in range(len(TEST_MONTHS))]


def months_index(m):
    y, mo = m.split("-")
    return int(y) * 12 + int(mo) - 1


# ---------------------------------------------------------------- folds, weights, scoring

def fold(month, test_month):
    """Strictly forward: train on months before the test month, score the test month."""
    return month < test_month, month == test_month


def recency_weights(month, test_month, half_life_m):
    if half_life_m is None:
        return np.ones(len(month))
    age = months_index(test_month) - np.array([months_index(m) for m in month])
    return 0.5 ** ((age - 1) / half_life_m)


def score(pred, net_c, capital_c, qty):
    keep = pred > THRESHOLD_C
    cap = capital_c[keep].sum()
    return {"kept": int(keep.sum()), "share": float(keep.mean()) if len(keep) else 0.0,
            "ret": float(100 * net_c[keep].sum() / cap) if cap > 0 else float("nan"),
            "ret_all": float(100 * net_c.sum() / max(capital_c.sum(), 1e-9)),
            "net_c_per_contract": float(net_c[keep].sum() / max(qty[keep].sum(), 1e-9))}


def select(table):
    """table: {name: [fold results]}. Highest worst-fold return among settings that keep at
    least MIN_KEPT fills in every fold; None if none qualifies. Benchmarks are never selected."""
    ok = {n: min(r["ret"] for r in rs) for n, rs in table.items()
          if n not in BENCHMARKS and rs and all(r["kept"] >= MIN_KEPT and r["ret"] == r["ret"] for r in rs)}
    return max(ok, key=ok.get) if ok else None


# ---------------------------------------------------------------- models

def fit_predict(g, X, y, w, cat_col, X_test, month_tr, device="cpu", threads=None, seed=0):
    if g.get("model") == "xgb":
        return _xgb(X, y, w, cat_col, X_test, device, threads, seed), {}
    if device != "cpu":
        raise SystemExit(f"{g['name']} is scikit-learn's model: CPU only.")
    import maker_policy as mp
    from sklearn.ensemble import HistGradientBoostingRegressor
    hp = {**mp.HP, **g.get("hp", {})}
    cats = [i == cat_col for i in range(X.shape[1])]
    if g.get("early_stop"):
        # stop on the LAST training month (time-ordered), not A12's random 10% holdout
        last = max(month_tr)
        es, tr = month_tr == last, month_tr != last
        m = HistGradientBoostingRegressor(**{**hp, "max_iter": 2000, "early_stopping": False},
                                          categorical_features=cats).fit(X[tr], y[tr], sample_weight=w[tr])
        mse = [np.average((p - y[es]) ** 2, weights=w[es]) for p in m.staged_predict(X[es])]
        n = int(np.argmin(mse)) + 1
        return next(p for i, p in enumerate(m.staged_predict(X_test), 1) if i == n), {"best_iter": n}
    preds = []
    for b in range(g.get("bag", 1)):
        if g.get("bag", 1) > 1:     # bootstrap rows, one seed per member
            ix = np.random.default_rng(seed + b).integers(0, len(y), len(y))
            Xb, yb, wb, rs = X[ix], y[ix], w[ix], seed + b
        else:
            Xb, yb, wb, rs = X, y, w, hp["random_state"]
        m = HistGradientBoostingRegressor(**{**hp, "random_state": rs}, categorical_features=cats)
        preds.append(m.fit(Xb, yb, sample_weight=None if g.get("half_life_m") is None else wb).predict(X_test))
    return np.mean(preds, axis=0), {}


def _xgb(X, y, w, cat_col, X_test, device, threads, seed):
    import xgboost as xgb
    ftypes = ["c" if i == cat_col else "q" for i in range(X.shape[1])]

    def dm(A, b=None, ww=None):
        A = A.copy(); A[:, cat_col] = np.where(A[:, cat_col] < 0, np.nan, A[:, cat_col])
        return xgb.DMatrix(A, label=b, weight=ww, feature_types=ftypes, enable_categorical=True,
                           nthread=threads or -1)
    g = XGB_A12
    params = {"tree_method": "hist", "device": device, "eta": g["eta"], "grow_policy": "lossguide",
              "max_depth": 0, "max_leaves": g["max_leaves"], "min_child_weight": g["min_child_weight"],
              "lambda": g["reg_lambda"], "objective": "reg:squarederror", "nthread": threads or 0, "seed": seed}
    return xgb.train(params, dm(X, y, w), g["rounds"]).predict(dm(X_test))


# ---------------------------------------------------------------- commands

def build():
    """Every G2 training fill 2024-11..2026-08 with its features, month, event, net and capital,
    assembled exactly as retrain_g2.train("W3", "G2") assembles them."""
    import maker_policy as mp
    import simulate_maker as s
    import live_signal_producer as lp
    import retrain_g2 as rg
    from fetch_kalshi_api_months import SERIES_A13
    from policy_G_audit import fills as cached_fills
    lookup = mp.category_lookup()
    rows, extra = [], []

    def add(fl, legs, events, charged):
        for f in fl:
            r = rg.features("G2", legs, events, charged, lookup, f[0], f[1], int(f[9]), int(f[2]), int(f[3]))
            if r is not None:
                rows.append(r); extra.append((s.month_of(int(f[9])), f[0], f[6] / f[4], f[6], f[7], f[4]))
    Fd = dict(np.load(rg.OUTDIR / f"cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
    Ft = cached_fills(s.Config(**mp.BROAD), "pess", ["2025-08", "2025-09", "2025-10", "2025-11"])
    for mo in rg.LOCAL:
        legs, events, charged = rg.local_legs(mo, SERIES_A13)
        events = rg.single_winner_events(legs, events)
        F = Fd if mo <= "2025-07" else Ft
        fl = [(F["event"][i], F["ticker"][i], F["side"][i], F["price"][i], F["qty"][i], F["fee_c"][i],
               F["net_c"][i], F["capital_c"][i], F["markout_c"][i], F["hour_ns"][i])
              for i in range(len(F["hour_ns"])) if s.month_of(int(F["hour_ns"][i])) == mo and F["event"][i] in events]
        n0 = len(rows); add(fl, legs, events, charged)
        print(f"  {mo} (local): {len(rows) - n0:,} fills", flush=True)
    cache = lp.load_state("series.pkl", {})
    legs, events = rg.api_legs(rg.API, SERIES_A13)
    events = rg.single_winner_events(legs, events)
    charged = rg.fee_charged({x: cache.get(x, {}).get("fee_type") for x in SERIES_A13})
    n0 = len(rows); add(s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, rg.API), legs, events, charged)
    print(f"  {rg.API[0]}..{rg.API[-1]} (API): {len(rows) - n0:,} fills", flush=True)
    cats = sorted({r["cat"] for r in rows})
    f = rg.feats("G2")
    month, event, y, net, cap, qty = (np.array(c) for c in zip(*extra))
    OUT.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(FEATURES, X=rg.matrix("G2", rows, cats), y=y.astype(float),
                        month=month.astype("U7"), event=event.astype(str), net_c=net.astype(float),
                        capital_c=cap.astype(float), qty=qty.astype(float), feats=np.array(f), cats=np.array(cats))
    print(f"wrote {FEATURES} : {len(y):,} rows, {len(f)} features, months {min(month)}..{max(month)}")


def load():
    D = dict(np.load(FEATURES))
    if max(D["month"]) >= "2026-09":
        raise SystemExit("feature table reaches the validation window: rebuild it")
    return D


def fit(task, device, threads):
    if AMENDMENT is None:
        raise SystemExit("AMENDMENT is not set: pre-register the grid, folds and rule before scoring real folds.")
    gi, fi = tasks()[task]
    g, tm = GRID[gi], TEST_MONTHS[fi]
    D = load()
    tr, te = fold(D["month"], tm)
    cat_col = list(D["feats"]).index("cat_i")
    w = recency_weights(D["month"][tr], tm, g.get("half_life_m"))
    t0 = time.time()
    pred, info = fit_predict(g, D["X"][tr], D["y"][tr], w, cat_col, D["X"][te], D["month"][tr], device, threads)
    res = {"amendment": AMENDMENT, "task": task, "setting": g["name"], "test_month": tm, "device": device,
           "n_train": int(tr.sum()), "n_test": int(te.sum()), "fit_s": round(time.time() - t0, 1), **info,
           **score(pred, D["net_c"][te], D["capital_c"][te], D["qty"][te])}
    (OUT / "results").mkdir(parents=True, exist_ok=True)
    (OUT / "results" / f"task_{task:03d}.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res))


def summarise():
    rs = [json.loads(p.read_text()) for p in sorted((OUT / "results").glob("task_*.json"))]
    table = {}
    for r in rs:
        table.setdefault(r["setting"], {})[r["test_month"]] = r
    print(f"{len(rs)}/{len(tasks())} tasks done\n{'setting':<22}" + "".join(f"{m:>10}" for m in TEST_MONTHS)
          + f"{'worst':>9}{'mean':>8}")
    full = {}
    for g in GRID:
        row = table.get(g["name"], {})
        rets = [row[m]["ret"] for m in TEST_MONTHS if m in row]
        print(f"{g['name']:<22}" + "".join(f"{row[m]['ret']:>+9.2f}%" if m in row else f"{'-':>10}" for m in TEST_MONTHS)
              + (f"{min(rets):>+8.2f}%{np.mean(rets):>+7.2f}%" if rets else ""))
        if len(row) == len(TEST_MONTHS):
            full[g["name"]] = [row[m] for m in TEST_MONTHS]
    any_r = next(iter(table.values()), {})
    print(f"{'quote everything':<22}" + "".join(f"{any_r[m]['ret_all']:>+9.2f}%" if m in any_r else f"{'-':>10}"
                                                 for m in TEST_MONTHS))
    if len(full) == len(GRID):
        print(f"\nSELECTED (highest worst-fold return, >= {MIN_KEPT} kept fills every fold): {select(full)}")
    else:
        print("\nselection waits for every setting to finish all folds")


def bench(device, threads, n=680_000):
    """Timing only, on synthetic data the size of the W3 training set. Reads no real data."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(n, 14)).astype(np.float32); X[:, 13] = rng.integers(0, 12, n)
    y = (X[:, 0] + rng.normal(scale=20, size=n)).astype(np.float32)
    month = np.array(["2026-01"] * (n // 2) + ["2026-02"] * (n - n // 2))
    for g, dev in ((GRID[0], "cpu"), (GRID[-1], device)):
        t0 = time.time()
        fit_predict(g, X, y, np.ones(n), 13, X[:100_000], month, dev, threads)
        print(f"{g['name']:<10} on {dev}: {time.time() - t0:6.1f} s  ({n:,} rows x 14)", flush=True)


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    tr, te = fold(np.array(["2026-03", "2026-04", "2026-05"]), "2026-04")
    check("fold is strictly forward: train 2026-03 only, test 2026-04 only", list(tr) == [True, False, False]
          and list(te) == [False, True, False])
    check("no test month is in or after the validation window", max(TEST_MONTHS) < "2026-09")
    w = recency_weights(np.array(["2026-03", "2026-02", "2025-12"]), "2026-04", 3)
    check(f"recency: last month weight 1, 3 months older 0.5 ({w.round(3)})", abs(w[0] - 1) < 1e-12 and abs(w[2] - 0.5) < 1e-12)
    r = score(np.array([5.0, 0.5, 2.0]), np.array([10.0, -50.0, -2.0]), np.array([100.0, 100.0, 100.0]), np.ones(3))
    check(f"score keeps pred > 1c only: (10-2)/200 = 4% ({r['ret']:.2f}%), all 3 = -14%",
          r["kept"] == 2 and abs(r["ret"] - 4) < 1e-12 and abs(r["ret_all"] + 14) < 1e-12)
    fr = lambda ret, kept=500: {"ret": ret, "kept": kept}
    check("selection: best worst-fold wins (A worst -1 beats B worst -3 despite B's higher mean)",
          select({"A": [fr(1), fr(-1)], "B": [fr(9), fr(-3)]}) == "A")
    check("selection: too few kept fills in one fold -> ineligible",
          select({"A": [fr(5), fr(5, 10)], "B": [fr(1), fr(1)]}) == "B")
    check("selection: none eligible -> None", select({"A": [fr(5, 10)]}) is None)
    check("tasks cover every (setting, fold) once", len(set(tasks())) == len(GRID) * len(TEST_MONTHS) == len(tasks()))
    check("setting 0 is G2 itself (no overrides); xgb_a12 is a benchmark",
          GRID[0] == {"name": "hgb_a12"} and GRID[-1]["name"] in BENCHMARKS)
    check("benchmark is never selected", select({"xgb_a12": [fr(50), fr(50)], "A": [fr(1), fr(1)]}) == "A")
    check("every hgb row changes one thing from G2 (lr0.1_iter120: rate and trees together, by design)",
          all(len([k for k in g if k != "name"]) == 1
              and len(g.get("hp", {"x": 0})) == (2 if g["name"] == "lr0.1_iter120" else 1) for g in GRID[1:-1]))
    # planted signal: y = +20c when x0 > 0 (and category 2), else -20c; a fitted model keeps the good half
    rng = np.random.default_rng(1)
    n = 20_000
    X = rng.normal(size=(n, 3)).astype(np.float32); X[:, 2] = rng.integers(-1, 4, n)
    good = (X[:, 0] > 0) | (X[:, 2] == 2)
    y = np.where(good, 20.0, -20.0).astype(np.float32)
    month = np.array(["2026-01"] * (n // 2) + ["2026-02"] * (n - n // 2))
    import maker_policy as mp
    from sklearn.ensemble import HistGradientBoostingRegressor
    ref = HistGradientBoostingRegressor(**mp.HP, categorical_features=[False, False, True]).fit(
        X[:15_000], y[:15_000]).predict(X[15_000:])
    mine, _ = fit_predict(GRID[0], X[:15_000], y[:15_000], np.ones(15_000), 2, X[15_000:], month[:15_000])
    check("hgb_a12 is bit-identical to G2's model (maker_policy.HP)", np.array_equal(ref, mine))
    for gi in (0, 8, 9, 10, 12, 13, len(GRID) - 1):
        g = GRID[gi]
        pred, info = fit_predict(g, X[:15_000], y[:15_000], np.ones(15_000), 2, X[15_000:], month[:15_000])
        r = score(pred, y[15_000:].astype(float), np.full(n - 15_000, 100.0), np.ones(n - 15_000))
        check(f"{g['name']}: learns a planted rule incl. the categorical column (kept ret {r['ret']:+.1f}%, "
              f"all {r['ret_all']:+.1f}%)", r["ret"] > 19 and r["kept"] > 0.4 * (n - 15_000))
    if AMENDMENT is None:
        try:
            fit(0, "cpu", 1); refused = False
        except SystemExit:
            refused = True
        check("fit refuses real folds while AMENDMENT is unset", refused)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["build", "fit", "summarise", "bench", "tasks"])
    ap.add_argument("--task", type=int, default=None, help="task index; default $SLURM_ARRAY_TASK_ID")
    ap.add_argument("--device", default="cpu", help="cpu (default) or cuda; only the xgb_a12 benchmark can use a GPU")
    ap.add_argument("--threads", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 0)) or None)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.cmd == "build":
        build()
    elif a.cmd == "fit":
        task = a.task if a.task is not None else int(os.environ["SLURM_ARRAY_TASK_ID"])
        g = GRID[tasks()[task][0]]
        fit(task, a.device if g.get("model") == "xgb" else "cpu", a.threads)
    elif a.cmd == "summarise":
        summarise()
    elif a.cmd == "bench":
        bench(a.device, a.threads)
    elif a.cmd == "tasks":
        print(f"{len(tasks())} tasks: {len(GRID)} settings x {len(TEST_MONTHS)} folds (array 0-{len(tasks()) - 1})")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
