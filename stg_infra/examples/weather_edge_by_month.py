"""Exploratory note 6: the model's weather edge month by month (2025-05..2026-09), with event-clustered CIs.

Each month in 2025-05..2026-08 is scored by G2's recipe trained only on earlier months (A15's table); 2026-09-07..10-05
by the frozen G2-W3 (L9's validation rows). For weather series (category Climate and Weather) it reports what quoting
everything earns per contract, median trades in 24 h, and what the model's picks (predicted > 1c) earn per contract
with a 95% event-cluster bootstrap CI. Descriptive only; no decision depends on it (L11 was decided by its own rule).

    python stg_infra/examples/weather_edge_by_month.py --self-test
    python stg_infra/examples/weather_edge_by_month.py
"""
import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_REPO / "stg_infra"), str(_REPO / "stg_infra/examples")]
WEATHER_CAT = "Climate and Weather"
OUT = _REPO / "results/live/weather_edge_by_month.json"


def cluster_ci(net, qty, events, n_boot=2000, seed=0):
    """Net per contract (sum net / sum qty) and its 95% CI, resampling whole events."""
    u, inv = np.unique(np.asarray(events), return_inverse=True)
    N, Q = np.bincount(inv, np.asarray(net, float)), np.bincount(inv, np.asarray(qty, float))
    rng = np.random.default_rng(seed)
    bs = [N[i].sum() / Q[i].sum() for i in (rng.integers(0, len(u), len(u)) for _ in range(n_boot))]
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return float(N.sum() / Q.sum()), float(lo), float(hi), int(len(u))


def month_row(net, qty, ev, trades, pick):
    v, lo, hi, k = cluster_ci(net[pick], qty[pick], ev[pick])
    return {"quotes": int(len(net)), "all_net_per_contract_c": float(net.sum() / qty.sum()),
            "trades_24h_median": float(np.median(trades)), "picked_share": float(pick.mean()),
            "picks_net_per_contract_c": v, "ci": [lo, hi], "events": k}


def september():
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    legs, events, charged, start, end = rg.val_data()
    events = rg.single_winner_events(legs, events)
    lookup = mp.category_lookup()
    fl = [f for f in s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, ["2026-09", "2026-10"])
          if start <= int(f[9]) < end]
    rows, net, qty, ev = [], [], [], []
    for f in fl:
        r = rg.features("G2", legs, events, charged, lookup, f[0], f[1], int(f[9]), int(f[2]), int(f[3]))
        if r is not None:
            rows.append(r); net.append(f[6]); qty.append(f[4]); ev.append(f[0])
    w3 = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    pred = w3["model"].predict(rg.matrix("G2", rows, w3["cats"]))
    w = np.array([r["cat"] == WEATHER_CAT for r in rows])
    tr = np.array([r["trades_24h"] for r in rows], float)
    net, qty, ev = np.asarray(net, float), np.asarray(qty, float), np.asarray(ev)
    return month_row(net[w], qty[w], ev[w], tr[w], pred[w] > 1.0)


def main():
    import tune_gbm as tg
    D = tg.load()
    f = list(D["feats"]); ci = f.index("cat_i"); wi = list(D["cats"]).index(WEATHER_CAT)
    out = {"note": "exploratory note 6", "months": {}}
    for tm in [m for m in sorted(set(D["month"])) if m >= "2025-05"]:
        te, trn = D["month"] == tm, D["month"] < tm
        p, _ = tg.fit_predict(tg.GRID[0], D["X"][trn], D["y"][trn], np.ones(int(trn.sum())), ci, D["X"][te], D["month"][trn])
        w = D["X"][te][:, ci] == wi
        out["months"][tm] = month_row(D["net_c"][te][w], D["qty"][te][w], D["event"][te][w],
                                      D["X"][te][w][:, f.index("trades_24h")], p[w] > 1.0)
        print(json.dumps({tm: out["months"][tm]}), flush=True)
    out["months"]["2026-09-07..10-05"] = september()
    print(json.dumps({"2026-09-07..10-05": out["months"]["2026-09-07..10-05"]}), flush=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(f"-> {OUT}")


def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    v, lo, hi, k = cluster_ci([30, 10, -20], [10, 10, 10], ["a", "a", "b"])
    check("net per contract = 20c / 30 contracts", abs(v - 20 / 30) < 1e-12 and k == 2)
    check("CI spans the two event-level values (+2c, -2c)", lo >= -2 - 1e-9 and hi <= 2 + 1e-9 and lo < v < hi)
    v1, lo1, hi1, _ = cluster_ci([5, 5, 5, 5], [1, 1, 1, 1], ["a", "b", "c", "d"])
    check("identical events -> zero-width CI", v1 == lo1 == hi1 == 5)
    r = month_row(np.array([10.0, -10, 30]), np.ones(3), np.array(["a", "b", "c"]), np.array([1.0, 2, 3]),
                  np.array([True, False, True]))
    check("month_row: all quotes 30/3, picks 40/2, median trades 2",
          r["all_net_per_contract_c"] == 10 and r["picks_net_per_contract_c"] == 20 and r["trades_24h_median"] == 2)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if self_test() else 1) if a.self_test else main()
