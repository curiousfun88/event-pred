"""
offline_baselines.py

EXPLORATORY (declared in lumid-forward-test-preregistration.md after L9, before any live P&L):
the live test's baselines scored offline on L9's six walk-forward folds, beside G2-W3's recipe.

Folds 2026-04..08: A15's table (runs/tune_gbm/features.npz). Fold 2026-09-07..10-05: the A13
validation window's BROAD pessimistic fills, single-winner events (as L9).
Baselines per fold (A15's offline score: kept fills' net / capital):
  random  W3's kept share in that fold, mean of 20 seeds
  wide3   spread >= 3c
  liq     trades_24h >= the fold month's median (live rule: the hour's median)
  lin2    train_baselines.fit_lin2 refit on W3's window (all earlier months); September: frozen lin2
  mlp2    train_baselines.fit_mlp2 refit on W3's window; time holdout by month; September: frozen mlp2

USAGE (from repo root, laptop, capped):
    python stg_infra/examples/offline_baselines.py --self-test
    python stg_infra/examples/offline_baselines.py      # -> results/live/offline_baselines.json
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

OUT = _REPO / "results/live/offline_baselines.json"
L9 = _REPO / "results/live/l9_window_selection.json"
SEEDS = 20


def rows_from_X(X, feats, cats, month=None):
    """Feature-table matrix -> the row dicts train_baselines expects (13 numeric + cat; _H orders by month)."""
    import tune_gbm as tg
    fi = {f: i for i, f in enumerate(feats)}
    ci = fi["cat_i"]
    out = []
    for j, x in enumerate(X):
        r = {f: float(x[i]) for f, i in fi.items() if f != "cat_i"}
        c = int(x[ci])
        r["cat"] = cats[c] if 0 <= c < len(cats) else "?"
        if month is not None:
            r["_H"] = tg.months_index(month[j])
        out.append(r)
    return out


def rule_scores(X, feats, kept_share, seed_list=range(SEEDS)):
    """{name: [pred arrays]}: predictions > 1c mean 'post'. random has one array per seed."""
    fi = {f: i for i, f in enumerate(feats)}
    n = len(X)
    post = lambda m: np.where(m, 2.0, -np.inf)
    rnd = [post(np.random.default_rng(s).random(n) < kept_share) for s in seed_list]
    return {"random": rnd, "wide3": [post(X[:, fi["spread"]] >= 3)],
            "liq": [post(X[:, fi["trades_24h"]] >= np.median(X[:, fi["trades_24h"]]))]}


def score_all(preds, net, cap, qty):
    import tune_gbm as tg
    sc = [tg.score(p, net, cap, qty) for p in preds]
    return {"ret": float(np.mean([s["ret"] for s in sc])), "kept": int(np.mean([s["kept"] for s in sc])),
            "share": float(np.mean([s["share"] for s in sc])), "seeds": len(sc)}


def september_rows():
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
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
    return rows, *(np.asarray(x, float) for x in (net, cap, qty))


def main_run():
    import retrain_g2 as rg
    import train_baselines as tb
    import tune_gbm as tg
    l9 = json.loads(L9.read_text())
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    res = {}
    for i, tm in enumerate(tg.TEST_MONTHS):
        te, tr = D["month"] == tm, D["month"] < tm
        net, cap, qty = D["net_c"][te], D["capital_c"][te], D["qty"][te]
        w3 = l9["folds"]["W3"][i]
        row = {"W3": {"ret": w3["ret"], "kept": w3["kept"]}, "quote_all": {"ret": w3["ret_all"]}}
        for name, preds in rule_scores(D["X"][te], feats, w3["share"]).items():
            row[name] = score_all(preds, net, cap, qty)
        R_tr = rows_from_X(D["X"][tr], feats, cats, D["month"][tr])
        R_te = rows_from_X(D["X"][te], feats, cats)
        y = D["y"][tr]
        row["lin2"] = score_all([tb.predict(tb.fit_lin2(R_tr, y), R_te)], net, cap, qty)
        row["mlp2"] = score_all([tb.predict(tb.fit_mlp2(R_tr, y, log=lambda *a: None), R_te)], net, cap, qty)
        res[tm] = row
        print(json.dumps({tm: row}, default=float), flush=True)
    rows, net, cap, qty = september_rows()
    w3 = l9["folds"]["W3"][-1]
    X = rg.matrix("G2", rows, cats)      # cat_i by the table's categories, for the rule baselines
    row = {"W3": {"ret": w3["ret"], "kept": w3["kept"]}, "quote_all": {"ret": w3["ret_all"]}}
    for name, preds in rule_scores(X, rg.feats("G2"), w3["share"]).items():
        row[name] = score_all(preds, net, cap, qty)
    for a in ("lin2", "mlp2"):
        row[a] = score_all([tb.predict(pickle.loads(tb.model_path(a).read_bytes()), rows)], net, cap, qty)
    res["2026-09-07..10-05"] = row
    print(json.dumps({"2026-09-07..10-05": row}, default=float), flush=True)
    names = ["W3", "random", "wide3", "liq", "lin2", "mlp2", "quote_all"]
    summ = {n: {"mean_ret": float(np.mean([res[f][n]["ret"] for f in res])),
                "months_positive": int(sum(res[f][n]["ret"] > 0 for f in res)),
                "W3_better_months": int(sum(res[f]["W3"]["ret"] > res[f][n]["ret"] for f in res))} for n in names}
    OUT.write_text(json.dumps({"note": "exploratory, offline, pre-live", "folds": res, "summary": summ}, indent=1, default=float))
    print(json.dumps(summ, indent=1))


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    feats = ["spread", "trades_24h", "cat_i"]
    X = np.array([[2, 0, 0], [3, 5, 1], [4, 10, 1], [1, 1, -1]], float)
    r = rows_from_X(X, feats, ["Sports", "Crypto"], np.array(["2026-01"] * 4))
    check("rows: category from cat_i; unknown index -> '?'; _H from month", r[1]["cat"] == "Crypto" and r[3]["cat"] == "?"
          and r[0]["_H"] == 2026 * 12)
    sc = rule_scores(X, feats, 0.5, seed_list=range(3))
    check("wide3 posts spread >= 3 only", list(sc["wide3"][0] > 1) == [False, True, True, False])
    check("liq posts trades_24h >= the fold median (median 3)", list(sc["liq"][0] > 1) == [False, True, True, False])
    check("random: one prediction array per seed", len(sc["random"]) == 3)
    net, cap, qty = np.array([10.0, -5, 20, 0]), np.array([100.0] * 4), np.ones(4)
    s = score_all(sc["wide3"], net, cap, qty)
    check(f"score: kept fills' net / capital (wide3 keeps -5 and +20 -> +7.5%, got {s['ret']:+.2f})", abs(s["ret"] - 7.5) < 1e-9)
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
