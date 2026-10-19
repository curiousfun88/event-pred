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
Sensitivity checks (nothing selected): --mlp-sens (note 3), --lin-sens (note 7, ridge alpha over LIN_GRID).

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


def dollars(pred, net, cap, qty):
    keep = pred > 1.0
    return {"net_usd": float(net[keep].sum() / 100), "capital_usd": float(cap[keep].sum() / 100),
            "contracts": int(qty[keep].sum()), "kept": int(keep.sum())}


def main_dollars():
    """Total net P&L and capital (USD) per fold for W3, lin2 and random at W3's share (mean of 20 seeds)."""
    import retrain_g2 as rg
    import train_baselines as tb
    import tune_gbm as tg
    l9 = json.loads(L9.read_text())
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    cat_col = feats.index("cat_i")
    res = {}

    def rnd(n, share, net, cap, qty):
        ds = [dollars(np.where(np.random.default_rng(s_).random(n) < share, 2.0, -np.inf), net, cap, qty) for s_ in range(SEEDS)]
        return {k: float(np.mean([d[k] for d in ds])) for k in ds[0]}
    for i, tm in enumerate(tg.TEST_MONTHS):
        te, tr = D["month"] == tm, D["month"] < tm
        net, cap, qty = D["net_c"][te], D["capital_c"][te], D["qty"][te]
        p3, _ = tg.fit_predict(tg.GRID[0], D["X"][tr], D["y"][tr], np.ones(int(tr.sum())), cat_col, D["X"][te], D["month"][tr])
        pl = tb.predict(tb.fit_lin2(rows_from_X(D["X"][tr], feats, cats), D["y"][tr]), rows_from_X(D["X"][te], feats, cats))
        res[tm] = {"W3": dollars(p3, net, cap, qty), "lin2": dollars(pl, net, cap, qty),
                   "random": rnd(int(te.sum()), l9["folds"]["W3"][i]["share"], net, cap, qty),
                   "quote_all": dollars(np.full(int(te.sum()), 2.0), net, cap, qty)}
        print(json.dumps({tm: res[tm]}), flush=True)
    rows, net, cap, qty = september_rows()
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    p3 = w3["model"].predict(rg.matrix("G2", rows, w3["cats"]))
    pl = tb.predict(pickle.loads(tb.model_path("lin2").read_bytes()), rows)
    res["2026-09-07..10-05"] = {"W3": dollars(p3, net, cap, qty), "lin2": dollars(pl, net, cap, qty),
                                "random": rnd(len(rows), l9["folds"]["W3"][-1]["share"], net, cap, qty),
                                "quote_all": dollars(np.full(len(rows), 2.0), net, cap, qty)}
    print(json.dumps({"2026-09-07..10-05": res["2026-09-07..10-05"]}), flush=True)
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    d["dollars"] = res
    OUT.write_text(json.dumps(d, indent=1, default=float))


def main_sep_sim():
    """A13's September validation in the full simulator (inventory and limits), exactly as retrain_g2.validate
    runs G2, for every live baseline. G2-W3 must reproduce A13's +1.41%."""
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import train_baselines as tb
    legs, events, charged, start, end = rg.val_data()
    months = ["2026-09", "2026-10"]
    lookup = mp.category_lookup()
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
    cand = []
    s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, months, record=cand)
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a in cand:
        if start <= int(H) < end:
            r = rg.features("G2", legs, events, charged, lookup, ev, tk, int(H), int(sd), int(pr))
            if r is not None:
                rows.append(r); keys.append((tk, int(H), int(sd)))
    hours = np.array([k[1] for k in keys])
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    p3 = w3["model"].predict(rg.matrix("G2", rows, w3["cats"]))
    share = float(np.mean(p3 > 1.0))
    tr24 = np.array([r["trades_24h"] for r in rows], float)
    med = {h: np.median(tr24[hours == h]) for h in np.unique(hours)}
    post = lambda m: np.where(m, 2.0, -np.inf)
    arms = {"G2-W3": p3,
            "lin2": tb.predict(pickle.loads(tb.model_path("lin2").read_bytes()), rows),
            "mlp2": tb.predict(pickle.loads(tb.model_path("mlp2").read_bytes()), rows),
            "wide3": post(np.array([r["spread"] for r in rows]) >= 3),
            "liq": post(tr24 >= np.array([med[h] for h in hours]))}
    for seed in range(5):                       # A13's random arm: 5 seeds at G2's share
        arms[f"random_s{seed}"] = post(np.random.default_rng(seed).random(len(keys)) < share)
    ALL = win(s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months))
    out = {"quote_all": {**s.summarise(ALL)}, "g2_share": share, "candidates": len(keys)}
    fills = {}
    for name, pred in arms.items():
        fl = win(s.simulate(rg.sim_cfg("G2", policy="x", policy_t=1.0), "pess", legs, events, charged, months,
                            policy_scores=dict(zip(keys, pred))))
        fills[name] = fl
        out[name] = {**s.summarise(fl), "posted_share": float(np.mean(pred > 1.0))}
        print(json.dumps({name: {k: out[name][k] for k in ("ret", "lo", "hi", "fills", "events", "net_c", "posted_share")}},
                         default=float), flush=True)
    for name in ("lin2", "mlp2", "wide3", "liq", "random_s0"):
        out[f"G2-W3 minus {name}"] = rg.paired_diff_ci(fills["G2-W3"], fills[name])
    out["random_mean_ret"] = float(np.mean([out[f"random_s{i}"]["ret"] for i in range(5)]))
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    d["september_full_simulator"] = out
    OUT.write_text(json.dumps(d, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if "minus" in k or k == "random_mean_ret"}, default=float))


SHARES = (0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40)


def top_share(pred, share):
    """Predictions turned into 'post the top `share` by score' (ties broken by order)."""
    k = int(round(share * len(pred)))
    out = np.full(len(pred), -np.inf)
    if k > 0:
        out[np.argsort(-pred, kind="stable")[:k]] = 2.0
    return out


def main_curve():
    """Volume-matched G2-W3 vs lin2 on the six L9 folds (exploratory note 2)."""
    import retrain_g2 as rg
    import train_baselines as tb
    import tune_gbm as tg
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    cat_col = feats.index("cat_i")
    acc = {m: {sh: [0.0, 0.0] for sh in SHARES + ("own_1c",)} for m in ("G2-W3", "lin2")}

    def add(model, pred, net, cap):
        for sh in SHARES:
            keep = top_share(pred, sh) > 1
            acc[model][sh][0] += net[keep].sum(); acc[model][sh][1] += cap[keep].sum()
        keep = pred > 1.0
        acc[model]["own_1c"][0] += net[keep].sum(); acc[model]["own_1c"][1] += cap[keep].sum()
    for tm in tg.TEST_MONTHS:
        te, tr = D["month"] == tm, D["month"] < tm
        net, cap = D["net_c"][te], D["capital_c"][te]
        p3, _ = tg.fit_predict(tg.GRID[0], D["X"][tr], D["y"][tr], np.ones(int(tr.sum())), cat_col, D["X"][te], D["month"][tr])
        pl = tb.predict(tb.fit_lin2(rows_from_X(D["X"][tr], feats, cats), D["y"][tr]), rows_from_X(D["X"][te], feats, cats))
        add("G2-W3", p3, net, cap); add("lin2", pl, net, cap)
        print(json.dumps({"fold": tm, "done": True}), flush=True)
    rows, net, cap, qty = september_rows()
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    add("G2-W3", w3["model"].predict(rg.matrix("G2", rows, w3["cats"])), net, cap)
    add("lin2", tb.predict(pickle.loads(tb.model_path("lin2").read_bytes()), rows), net, cap)
    curve = {m: {str(sh): {"ret": 100 * a[0] / a[1] if a[1] else float("nan"), "net_usd": a[0] / 100, "capital_usd": a[1] / 100}
                 for sh, a in v.items()} for m, v in acc.items()}
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    d["volume_matched_curve"] = curve
    OUT.write_text(json.dumps(d, indent=1, default=float))
    print(json.dumps(curve, indent=1, default=float))


MLP_GRID = [("mlp2", {}), ("hidden_32", {"hidden_layer_sizes": (32,)}), ("hidden_128_64", {"hidden_layer_sizes": (128, 64)}),
            ("hidden_64_32_16", {"hidden_layer_sizes": (64, 32, 16)}), ("l2_1e-3", {"alpha": 1e-3}), ("l2_1e-2", {"alpha": 1e-2}),
            ("lr_3e-4", {"learning_rate_init": 3e-4}), ("tanh", {"activation": "tanh"})]
SENS = _REPO / "results/live/mlp_sensitivity.json"


def main_mlp_sensitivity():
    """Exploratory note 3: each MLP_GRID setting on the six L9 folds (resumable; nothing selected)."""
    import train_baselines as tb
    import tune_gbm as tg
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    done = json.loads(SENS.read_text()) if SENS.exists() else {}
    sep = None
    for name, hp in MLP_GRID:
        for tm in tg.TEST_MONTHS + ["2026-09-07..10-05"]:
            key = f"{name}|{tm}"
            if key in done:
                continue
            if tm.startswith("2026-09"):
                if sep is None:
                    sep = september_rows()
                tr = np.ones(len(D["month"]), bool)
                R_te, (net, cap, qty) = sep[0], sep[1:]
            else:
                tr, te = D["month"] < tm, D["month"] == tm
                R_te, net, cap, qty = rows_from_X(D["X"][te], feats, cats), D["net_c"][te], D["capital_c"][te], D["qty"][te]
            blob = tb.fit_mlp2(rows_from_X(D["X"][tr], feats, cats, D["month"][tr]), D["y"][tr], log=lambda *a: None, hp=hp)
            sc = tg.score(tb.predict(blob, R_te), net, cap, qty)
            done[key] = {"setting": name, "fold": tm, "best_epoch": blob["best_epoch"], **sc}
            SENS.write_text(json.dumps(done, indent=1, default=float))
            print(json.dumps(done[key], default=float), flush=True)
    summ = {}
    for name, _ in MLP_GRID:
        rs = [done[f"{name}|{tm}"]["ret"] for tm in tg.TEST_MONTHS + ["2026-09-07..10-05"]]
        summ[name] = {"mean_ret": float(np.mean(rs)), "worst_ret": float(min(rs)), "months_positive": int(sum(r > 0 for r in rs))}
    SENS.write_text(json.dumps({"note": "exploratory note 3; nothing selected", "folds": done, "summary": summ}, indent=1, default=float))
    print(json.dumps(summ, indent=1))


LIN_GRID = (0.01, 1.0, 100.0, 1e4, 1e5)          # ridge alpha; 1.0 = lin2 as frozen in L3
LIN_SENS = _REPO / "results/live/lin_sensitivity.json"


def coef_shift(ref, other):
    """Largest coefficient change relative to the reference fit's largest coefficient (0 = identical)."""
    a, b = ref["model"].coef_, other["model"].coef_
    return float(np.abs(b - a).max() / max(np.abs(a).max(), 1e-12))


def pick_overlap(p_ref, p_other):
    """Jaccard overlap of the two fits' posted sets at the 1c rule (1.0 = same orders)."""
    a, b = p_ref > 1.0, p_other > 1.0
    u = int((a | b).sum())
    return float((a & b).sum() / u) if u else 1.0


def lin_summary(done, folds):
    return {f"alpha_{a:g}": {"mean_ret": float(np.mean([done[f"{a:g}|{tm}"]["ret"] for tm in folds])),
                             "worst_ret": float(min(done[f"{a:g}|{tm}"]["ret"] for tm in folds)),
                             "months_positive": int(sum(done[f"{a:g}|{tm}"]["ret"] > 0 for tm in folds)),
                             "mean_share": float(np.mean([done[f"{a:g}|{tm}"]["share"] for tm in folds])),
                             "max_coef_shift": float(max(done[f"{a:g}|{tm}"]["coef_shift"] for tm in folds)),
                             "min_pick_overlap": float(min(done[f"{a:g}|{tm}"]["pick_overlap"] for tm in folds))}
            for a in LIN_GRID}


def main_lin_sensitivity():
    """Exploratory note 7: lin2's ridge alpha over LIN_GRID on the six L9 folds (resumable; nothing selected).
    Gate: alpha 1.0 must reproduce offline_baselines.json's lin2 on the five A15-table folds exactly."""
    import train_baselines as tb
    import tune_gbm as tg
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    ref_ret = json.loads(OUT.read_text())["folds"]
    folds = tg.TEST_MONTHS + ["2026-09-07..10-05"]
    done = json.loads(LIN_SENS.read_text()).get("folds", {}) if LIN_SENS.exists() else {}
    for tm in folds:
        if all(f"{a:g}|{tm}" in done for a in LIN_GRID):
            continue
        if tm.startswith("2026-09"):        # as note 3: trained on every month through 2026-08
            tr = np.ones(len(D["month"]), bool)
            R_te, net, cap, qty = september_rows()
        else:
            tr, te = D["month"] < tm, D["month"] == tm
            R_te, net, cap, qty = rows_from_X(D["X"][te], feats, cats), D["net_c"][te], D["capital_c"][te], D["qty"][te]
        R_tr, y = rows_from_X(D["X"][tr], feats, cats), D["y"][tr]
        sc = tb._scaled(R_tr)
        fits = {a: tb.fit_lin2(R_tr, y, alpha=a, scaled=sc) for a in LIN_GRID}
        preds = {a: tb.predict(b, R_te) for a, b in fits.items()}
        for a in LIN_GRID:
            done[f"{a:g}|{tm}"] = {"alpha": a, "fold": tm, "n_train": int(tr.sum()), **tg.score(preds[a], net, cap, qty),
                                   "coef_shift": coef_shift(fits[1.0], fits[a]), "pick_overlap": pick_overlap(preds[1.0], preds[a])}
            print(json.dumps(done[f"{a:g}|{tm}"], default=float), flush=True)
        if not tm.startswith("2026-09"):
            got, want = done[f"1|{tm}"]["ret"], ref_ret[tm]["lin2"]["ret"]
            if abs(got - want) > 1e-9:
                raise SystemExit(f"REPRODUCTION GATE FAILED {tm}: alpha 1.0 gives {got!r}, offline_baselines lin2 {want!r}")
        LIN_SENS.write_text(json.dumps({"folds": done}, indent=1, default=float))
        del R_tr, sc, fits
    summ = lin_summary(done, folds)
    LIN_SENS.write_text(json.dumps({"note": "exploratory note 7; nothing selected", "folds": done, "summary": summ},
                                   indent=1, default=float))
    print(json.dumps(summ, indent=1))


SHARES4 = (0.02, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50)


def _acc_add(acc, model, pred, net, cap):
    for sh in SHARES4:
        keep = top_share(pred, sh) > 1
        a = acc.setdefault(model, {}).setdefault(str(sh), [0.0, 0.0])
        a[0] += float(net[keep].sum()); a[1] += float(cap[keep].sum())
    keep = pred > 1.0
    a = acc[model].setdefault("own_1c", [0.0, 0.0])
    a[0] += float(net[keep].sum()); a[1] += float(cap[keep].sum())


def _acc_out(acc):
    return {m: {sh: {"ret": 100 * a[0] / a[1] if a[1] else float("nan"), "net_usd": a[0] / 100} for sh, a in v.items()}
            for m, v in acc.items()}


def _ov_add(ov, ref, other, name, preds):
    """Fraction of the reference model's top-share picks that `other` also picks (counts pooled)."""
    for sh in SHARES4:
        a = top_share(preds[ref], sh) > 1
        b = top_share(preds[other], sh) > 1
        o = ov.setdefault(name, {}).setdefault(str(sh), [0, 0])
        o[0] += int((a & b).sum()); o[1] += int(a.sum())


def main_curves_full(overlap_only=False):
    """Exploratory note 4 (and note 5 with overlap_only): matched shares, 2026 folds and 2025 test months."""
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import train_baselines as tb
    import tune_gbm as tg
    out, ov26, ov25 = {}, {}, {}
    # ---- 2026: L9 folds, models refit per fold (September: frozen models)
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    cat_col = feats.index("cat_i")
    acc = {}
    for tm in tg.TEST_MONTHS:
        te, tr = D["month"] == tm, D["month"] < tm
        net, cap = D["net_c"][te], D["capital_c"][te]
        R_tr, R_te = rows_from_X(D["X"][tr], feats, cats, D["month"][tr]), rows_from_X(D["X"][te], feats, cats)
        p3, _ = tg.fit_predict(tg.GRID[0], D["X"][tr], D["y"][tr], np.ones(int(tr.sum())), cat_col, D["X"][te], D["month"][tr])
        pr = {"G2": p3, "Linear": tb.predict(tb.fit_lin2(R_tr, D["y"][tr]), R_te),
              "Neural": tb.predict(tb.fit_mlp2(R_tr, D["y"][tr], log=lambda *a: None), R_te)}
        for m_, p_ in pr.items():
            _acc_add(acc, m_, p_, net, cap)
        _ov_add(ov26, "G2", "Linear", "G2&Linear", pr); _ov_add(ov26, "G2", "Neural", "G2&Neural", pr)
        print(json.dumps({"2026 fold": tm}), flush=True)
    rows, net, cap, qty = september_rows()
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    pr = {"G2": w3["model"].predict(rg.matrix("G2", rows, w3["cats"])),
          "Linear": tb.predict(pickle.loads(tb.model_path("lin2").read_bytes()), rows),
          "Neural": tb.predict(pickle.loads(tb.model_path("mlp2").read_bytes()), rows)}
    for m_, p_ in pr.items():
        _acc_add(acc, m_, p_, net, cap)
    _ov_add(ov26, "G2", "Linear", "G2&Linear", pr); _ov_add(ov26, "G2", "Neural", "G2&Neural", pr)
    out["2026"] = _acc_out(acc)
    del D, rows
    # ---- 2025: G's test months, frozen models, features month by month (A12)
    import baselines_2025 as b25
    F = dict(np.load(_REPO / "runs/maker/cache/b0b6c1550b3b8345.fills.npz", allow_pickle=True))
    month = np.array([s.month_of(int(h)) for h in F["hour_ns"]])
    G = pickle.loads(mp.model_path("G").read_bytes())
    L = pickle.loads(b25.MODELS["lin2"].read_bytes()); N = pickle.loads(b25.MODELS["mlp2"].read_bytes())
    lookup = mp.category_lookup()
    acc = {}
    for mo in b25.TEST:
        legs, events, charged = s.load([mo], "mece")
        rows, net, cap = [], [], []
        for i in np.where(month == mo)[0]:
            if F["ticker"][i] not in legs:
                continue
            r = mp.quote_features(legs, events, charged, lookup, mo, F["event"][i], F["ticker"][i],
                                  int(F["hour_ns"][i]), int(F["side"][i]), int(F["price"][i]))
            if r is not None:
                rows.append(r); net.append(F["net_c"][i]); cap.append(F["capital_c"][i])
        net, cap = np.asarray(net, float), np.asarray(cap, float)
        pr = {"G": G["model"].predict(mp.to_matrix(rows, G["cats"])), "Linear": tb.predict(L, rows), "Neural": tb.predict(N, rows)}
        for m_, p_ in pr.items():
            _acc_add(acc, m_, p_, net, cap)
        _ov_add(ov25, "G", "Linear", "G&Linear", pr); _ov_add(ov25, "G", "Neural", "G&Neural", pr)
        print(json.dumps({"2025 month": mo, "fills": len(rows)}), flush=True)
        del legs, events, charged, rows
    out["2025"] = _acc_out(acc)
    ovo = {yr: {k: {sh: c[0] / c[1] if c[1] else float("nan") for sh, c in v.items()} for k, v in ov.items()}
           for yr, ov in (("2026", ov26), ("2025", ov25))}
    d = json.loads(OUT.read_text()) if OUT.exists() else {}
    d["pick_overlap"] = ovo
    print(json.dumps(ovo, indent=1))
    if overlap_only:
        OUT.write_text(json.dumps(d, indent=1, default=float))
        return
    d["volume_curves_full"] = out
    OUT.write_text(json.dumps(d, indent=1, default=float))
    for yr, v in out.items():
        print(yr)
        for sh in [str(x) for x in SHARES4] + ["own_1c"]:
            print(f"  {sh:>7}  " + "  ".join(f"{m} {v[m][sh]['ret']:+6.2f}% {v[m][sh]['net_usd']:+8.0f}" for m in v))


WEATHER_CAT = "Climate and Weather"


def main_weather_split():
    """L11: G2-W3's recipe on the six L9 folds, weather vs non-weather, A15's offline score; the rule decides."""
    import retrain_g2 as rg
    import tune_gbm as tg
    D = tg.load()
    feats, cats = list(D["feats"]), list(D["cats"])
    cat_col = feats.index("cat_i")
    wi = cats.index(WEATHER_CAT)
    res = {"weather": [], "non_weather": []}
    for tm in tg.TEST_MONTHS:
        te, tr = D["month"] == tm, D["month"] < tm
        p3, _ = tg.fit_predict(tg.GRID[0], D["X"][tr], D["y"][tr], np.ones(int(tr.sum())), cat_col, D["X"][te], D["month"][tr])
        w = D["X"][te][:, cat_col] == wi
        for name, m in (("weather", w), ("non_weather", ~w)):
            sc = tg.score(p3[m], D["net_c"][te][m], D["capital_c"][te][m], D["qty"][te][m])
            res[name].append({"fold": tm, **sc})
        print(json.dumps({tm: {k: round(v[-1]["ret"], 3) for k, v in res.items()}}), flush=True)
    rows, net, cap, qty = september_rows()
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    pr = w3["model"].predict(rg.matrix("G2", rows, w3["cats"]))
    w = np.array([r["cat"] == WEATHER_CAT for r in rows])
    for name, m in (("weather", w), ("non_weather", ~w)):
        res[name].append({"fold": "2026-09-07..10-05", **tg.score(pr[m], net[m], cap[m], qty[m])})
    mean = {k: float(np.mean([f["ret"] for f in v])) for k, v in res.items()}
    decision = "re-include weather" if mean["weather"] > 0 else "exclusion stands"
    out = {"amendment": "L11", "folds": res, "mean_ret": mean,
           "months_positive": {k: int(sum(f["ret"] > 0 for f in v)) for k, v in res.items()}, "decision": decision}
    p_ = _REPO / "results/live/l11_weather_split.json"
    p_.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({"mean_ret": mean, "months_positive": out["months_positive"], "DECISION": decision}))


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
    dd = dollars(np.array([2.0, 0.0, 2.0, 2.0]), net, cap, qty)
    check("dollars: kept net and capital in USD", dd == {"net_usd": 0.3, "capital_usd": 3.0, "contracts": 3, "kept": 3})
    check("top_share: posts exactly the top k by score", list(top_share(np.array([0.1, 5.0, -2.0, 3.0]), 0.5) > 1) == [False, True, False, True])
    check(f"score: kept fills' net / capital (wide3 keeps -5 and +20 -> +7.5%, got {s['ret']:+.2f})", abs(s["ret"] - 7.5) < 1e-9)

    class _M:
        def __init__(self, c):
            self.coef_ = np.asarray(c, float)
    shift = coef_shift({"model": _M([2.0, -4.0])}, {"model": _M([2.0, -3.0])})
    check(f"coef_shift: largest change / largest reference coefficient (1/4, got {shift})", abs(shift - 0.25) < 1e-12)
    check("pick_overlap: Jaccard of posted sets ({0,1} vs {1,2} -> 1/3)",
          abs(pick_overlap(np.array([2.0, 2, 0, 0]), np.array([0.0, 2, 2, 0])) - 1 / 3) < 1e-12)
    check("pick_overlap: neither posts anything -> 1.0", pick_overlap(np.zeros(3), np.zeros(3)) == 1.0)
    planted = {f"{a:g}|{tm}": {"ret": r, "share": 0.1, "coef_shift": cs, "pick_overlap": po}
               for a in LIN_GRID for tm, r, cs, po in (("f1", 2.0 if a < 1e4 else -1.0, 0.0 if a == 1.0 else 0.5, 0.9),
                                                       ("f2", 4.0, 0.1, 0.8))}
    ls = lin_summary(planted, ["f1", "f2"])
    check("lin_summary: mean, worst, months positive, max shift, min overlap per alpha",
          ls["alpha_1"] == {"mean_ret": 3.0, "worst_ret": 2.0, "months_positive": 2, "mean_share": 0.1,
                            "max_coef_shift": 0.1, "min_pick_overlap": 0.8}
          and ls["alpha_100000"]["mean_ret"] == 1.5 and ls["alpha_100000"]["months_positive"] == 1)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dollars", action="store_true", help="total net P&L and capital per fold (W3, lin2, random)")
    ap.add_argument("--sep-sim", action="store_true", help="September validation in the full simulator, every baseline")
    ap.add_argument("--curve", action="store_true", help="volume-matched G2-W3 vs lin2 (exploratory note 2)")
    ap.add_argument("--mlp-sens", action="store_true", help="neural-baseline sensitivity analysis (exploratory note 3)")
    ap.add_argument("--lin-sens", action="store_true", help="linear-baseline ridge-alpha sensitivity (exploratory note 7)")
    ap.add_argument("--curves-full", action="store_true", help="volume-matched curves, both baselines, both years (note 4)")
    ap.add_argument("--overlap", action="store_true", help="pick overlap at matched shares (note 5)")
    ap.add_argument("--weather-split", action="store_true", help="L11 weather decision on the six walk-forward folds")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.weather_split:
        main_weather_split()
    elif a.overlap:
        main_curves_full(overlap_only=True)
    elif a.curves_full:
        main_curves_full()
    elif a.mlp_sens:
        main_mlp_sensitivity()
    elif a.lin_sens:
        main_lin_sensitivity()
    elif a.curve:
        main_curve()
    elif a.sep_sim:
        main_sep_sim()
    elif a.dollars:
        main_dollars()
    else:
        main_run()


if __name__ == "__main__":
    main()
