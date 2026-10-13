"""
select_g2_window.py

AMENDMENT L9 (lumid-forward-test-preregistration.md): choose G2's headline training window
(W1 3 months, W2 6 months, W3 all history) on a six-month walk-forward instead of one month.

Folds 2026-04..08: A15's table (runs/tune_gbm/features.npz, G2-W3's exact training rows,
single-winner events); each recipe is refit with G2's model and settings on its window of
months before the test month (W1: 3, W2: 6, W3: all) and scored with A15's offline score.
Fold 2026-09-07..10-05: the frozen G2-W1/W2/W3 models (these recipes trained through
2026-08) on that window's BROAD pessimistic fills of the 23 A13 series, single-winner events.

Selection: highest mean return over the six folds among recipes keeping >= 200 fills in
every fold (A15's MIN_KEPT).

USAGE (from repo root, laptop, memory-capped):
    python stg_infra/examples/select_g2_window.py --self-test
    python stg_infra/examples/select_g2_window.py        # -> runs/tune_gbm/l9_window_selection.json
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

RECIPES = {"W1": 3, "W2": 6, "W3": None}          # months of history before the test month (None = all)
OUT = _REPO / "runs/tune_gbm/l9_window_selection.json"


def window_mask(month, test_month, k):
    """Training rows for a recipe: the k calendar months before test_month (all earlier months if k is None)."""
    import tune_gbm as tg
    mi = np.array([tg.months_index(m) for m in month])
    t = tg.months_index(test_month)
    return (mi < t) if k is None else ((mi < t) & (mi >= t - k))


def select(folds):
    """folds: {recipe: [fold scores]}. Highest mean return among recipes with >= MIN_KEPT kept fills in every fold."""
    import tune_gbm as tg
    ok = {r: float(np.mean([f["ret"] for f in fs])) for r, fs in folds.items()
          if fs and all(f["kept"] >= tg.MIN_KEPT and f["ret"] == f["ret"] for f in fs)}
    return (max(ok, key=ok.get) if ok else None), ok


def september_fold():
    """{recipe: score} for 2026-09-07..10-05 with the frozen G2-W1/W2/W3 models."""
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import tune_gbm as tg
    legs, events, charged, start, end = rg.val_data()
    events = rg.single_winner_events(legs, events)
    lookup = mp.category_lookup()
    fl = [f for f in s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, ["2026-09", "2026-10"])
          if start <= int(f[9]) < end]
    rows, net, cap, qty = [], [], [], []
    for f in fl:
        r = rg.features("G2", legs, events, charged, lookup, f[0], f[1], int(f[9]), int(f[2]), int(f[3]))
        if r is not None:
            rows.append(r); net.append(f[6]); cap.append(f[7]); qty.append(f[4])
    net, cap, qty = (np.asarray(x, float) for x in (net, cap, qty))
    out = {}
    for w in RECIPES:
        blob = pickle.loads(rg.model_path(w, "G2").read_bytes())
        out[w] = tg.score(blob["model"].predict(rg.matrix("G2", rows, blob["cats"])), net, cap, qty)
    return out, len(rows)


def main_run():
    import tune_gbm as tg
    D = tg.load()
    cat_col = list(D["feats"]).index("cat_i")
    folds = {w: [] for w in RECIPES}
    for tm in tg.TEST_MONTHS:
        te = D["month"] == tm
        for w, k in RECIPES.items():
            tr = window_mask(D["month"], tm, k)
            pred, _ = tg.fit_predict(tg.GRID[0], D["X"][tr], D["y"][tr], np.ones(int(tr.sum())), cat_col,
                                     D["X"][te], D["month"][tr])
            sc = {"fold": tm, "n_train": int(tr.sum()), **tg.score(pred, D["net_c"][te], D["capital_c"][te], D["qty"][te])}
            folds[w].append(sc)
            print(json.dumps({"recipe": w, **sc}), flush=True)
    sep, n_sep = september_fold()
    for w in RECIPES:
        folds[w].append({"fold": "2026-09-07..10-05", "n_test": n_sep, **sep[w]})
        print(json.dumps({"recipe": w, **folds[w][-1]}), flush=True)
    chosen, means = select(folds)
    res = {"amendment": "L9", "recipes": {w: k for w, k in RECIPES.items()}, "folds": folds,
           "mean_ret": means, "worst_ret": {w: min(f["ret"] for f in fs) for w, fs in folds.items()},
           "selected": chosen, "headline_changes": chosen not in (None, "W3")}
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(f"\nL9 SELECTED: {chosen}   means {json.dumps({w: round(v, 2) for w, v in means.items()})}")


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    month = np.array(["2025-12", "2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"])
    check("W1 recipe: the 3 months before 2026-05 (Feb, Mar, Apr)",
          list(month[window_mask(month, "2026-05", 3)]) == ["2026-02", "2026-03", "2026-04"])
    check("W2 recipe across a year boundary: 6 months before 2026-05 (Dec..Apr)",
          list(month[window_mask(month, "2026-05", 6)]) == ["2025-12", "2026-01", "2026-02", "2026-03", "2026-04"])
    check("W3 recipe: every month before, never the test month or later",
          list(month[window_mask(month, "2026-05", None)]) == list(month[:5]))
    F = lambda *rs, kept=500: [{"ret": r, "kept": kept} for r in rs]
    check("select: highest mean wins", select({"W1": F(5, -3), "W2": F(1, 1), "W3": F(2, 2.5)})[0] == "W3")
    check("select: a recipe below 200 kept fills in any fold is ineligible",
          select({"W1": F(9, 9, kept=150), "W3": F(1, 1)})[0] == "W3")
    check("select: none eligible -> None", select({"W1": F(1, kept=10)})[0] is None)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    main_run()


if __name__ == "__main__":
    main()
