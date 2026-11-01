"""
validate_g2_sel.py

AMENDMENT L4 ITEM 4: the secondary arm g2_sel's category selection, on the A13
validation window, for the frozen 290-series candidate pool.

For each Kalshi category of the pool (category as logged by the live producer, from
docs/planning/l4_candidate_pool.json), G2-W3 is run exactly as in the A13 validation
(retrain_g2.validate): BROAD candidates recorded by the simulator, G2 features, post if
predicted > 1c, pessimistic fills, fills kept by quoting hour in [2026-09-07, 2026-10-05).
Data: smoke_test_2026.fetch (settled markets closing in the window, hourly candles,
trades), the same code and cache layout that built the A13 validation data.

Rule (fixed in L4 before this ran): a category is selected iff its net return > 0 AND it
has >= 20 events with fills. Categories are processed one at a time (the simulator is
per event, so results are identical to one pooled run) to bound memory.

USAGE (from repo root, on a Lumid batch sandbox; resumable, the fetch is cached per series):
    python stg_infra/examples/validate_g2_sel.py --self-test
    python stg_infra/examples/validate_g2_sel.py --rps 4
"""
from __future__ import annotations

import argparse
import datetime as dt
import gc
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

POOL = _REPO / "docs/planning/l4_candidate_pool.json"
OUT = _REPO / "results/live/l4_g2_sel_selection.json"
MIN_EVENTS, MIN_RET = 20, 0.0
REPRO = {"fills": 1725, "events": 153, "ret_pct": 6.73}   # L1: G2-W3, non-weather A13 series, pess


def passes(summary: dict) -> bool:
    return summary["fills"] > 0 and summary["events"] >= MIN_EVENTS and summary["ret"] > MIN_RET


def pool_by_category(pool: dict) -> dict:
    out = {}
    for s_ in pool["series"]:
        out.setdefault(s_["cat"], []).append(s_["series"])
    return {c: sorted(v) for c, v in sorted(out.items())}


def category_run(series, k, cache, start, end, blob, lookup, s, mp, rg, st):
    """G2-W3 on one category's series: (summary, n candidates, posted share). Mirrors retrain_g2.validate (G2)."""
    keep = [x for x in series if cache.get(x, {}).get("ok")]
    raw = st.fetch(k, keep, start, end)
    legs, events, charged = st.build(raw, {x: cache[x]["fee_type"] for x in keep})
    del raw
    months = sorted({s.month_of(int(h)) for L in legs.values() for h in L["e"] if start <= h < end})
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
    cand = []
    s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, months, record=cand)
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a in cand:
        if not (start <= int(H) < end):
            continue
        r = rg.features("G2", legs, events, charged, lookup, ev, tk, int(H), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((tk, int(H), int(sd)))
    if not rows:
        return {"ret": float("nan"), "lo": float("nan"), "hi": float("nan"), "fills": 0, "events": 0, "net_c": 0.0}, 0, 0.0, len(keep)
    pred = blob["model"].predict(rg.matrix("G2", rows, blob["cats"]))
    pol = dict(zip(keys, pred))
    fl = win(s.simulate(rg.sim_cfg("G2", policy="x", policy_t=1.0), "pess", legs, events, charged, months,
                        policy_scores=pol))
    summ = s.summarise(fl) if fl else {"ret": float("nan"), "lo": float("nan"), "hi": float("nan"), "fills": 0,
                                        "events": 0, "net_c": 0.0}
    return summ, len(keys), float(np.mean(pred > 1.0)), len(keep)


def main_run(rps):
    import live_signal_producer as lp
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import smoke_test_2026 as st
    start = int(dt.datetime.fromisoformat(rg.VAL[0]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    end = int(dt.datetime.fromisoformat(rg.VAL[1]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    pool = json.loads(POOL.read_text())
    cats = pool_by_category(pool)
    blob = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    lookup = mp.category_lookup()
    k = lp.Kalshi(rps=rps)
    allser = [x for v in cats.values() for x in v]
    cache = lp.series_meta(k, allser, lp.load_state("series.pkl", {}), int(dt.datetime.now().timestamp()))
    lp.save_state("series.pkl", cache)
    # pipeline check first: the A13 non-weather series must reproduce L1's figure exactly, or nothing is selected
    from fetch_kalshi_api_months import SERIES_A13
    a13nw = [x for x in SERIES_A13 if not x.startswith(("KXHIGH", "KXLOW"))]
    cache_a13 = lp.series_meta(k, a13nw, lp.load_state("series.pkl", {}), int(dt.datetime.now().timestamp()))
    summ, *_ = category_run(a13nw, k, cache_a13, start, end, blob, lookup, s, mp, rg, st)
    rep = {"fills": int(summ["fills"]), "events": int(summ["events"]), "ret_pct": round(summ["ret"], 2)}
    print(f"REPRODUCTION (L1: 1,725 fills, 153 events, +6.73%): {rep}", flush=True)
    if rep != REPRO:
        print("REPRODUCTION FAILED: pipeline differs from the A13 validation; no selection made", flush=True)
        sys.exit(2)
    res = json.loads(OUT.read_text()) if OUT.exists() else {"categories": {}}
    res["reproduction"] = rep
    res.update({"amendment": "L4 item 4", "window": list(rg.VAL), "model": "G2-W3", "rule":
                f"ret > {MIN_RET} and events with fills >= {MIN_EVENTS}", "pool": str(POOL.relative_to(_REPO))})
    for cat, series in cats.items():
        if cat in res["categories"]:
            print(f"{cat}: done earlier, skipped", flush=True); continue
        summ, n_cand, share, n_ok = category_run(series, k, cache, start, end, blob, lookup, s, mp, rg, st)
        row = {"series": len(series), "series_pass_basket_rule": n_ok, "candidates": n_cand,
               "posted_share": round(share, 4), "fills": int(summ["fills"]), "events": int(summ["events"]),
               "ret_pct": summ["ret"], "ci_lo": summ["lo"], "ci_hi": summ["hi"], "net_usd": summ["net_c"] / 100,
               "selected": passes(summ)}
        res["categories"][cat] = row
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(res, indent=1, default=float))
        print(json.dumps({cat: row}, default=float), flush=True)
        gc.collect()
    res["selected"] = sorted(c for c, r in res["categories"].items() if r["selected"])
    res["fallback_to_L1"] = not res["selected"]
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(f"\nSELECTED for g2_sel: {res['selected'] or 'NONE (g2_sel is empty)'}  api calls {k.calls}", flush=True)


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    S = lambda ret, ev, fills=100: {"ret": ret, "events": ev, "fills": fills}
    check("rule: positive return with 20 events passes", passes(S(0.5, 20)))
    check("rule: positive return with 19 events fails (minimum)", not passes(S(5.0, 19)))
    check("rule: zero return fails (strictly > 0)", not passes(S(0.0, 50)))
    check("rule: negative return fails", not passes(S(-0.1, 500)))
    check("rule: no fills fails (NaN return)", not passes(S(float("nan"), 0, 0)))
    pool = {"series": [{"series": "B", "cat": "Sports"}, {"series": "A", "cat": "Sports"},
                       {"series": "C", "cat": "Crypto"}]}
    check("pool grouped by logged category, sorted", pool_by_category(pool) == {"Crypto": ["C"], "Sports": ["A", "B"]})
    real = json.loads(POOL.read_text())
    g = pool_by_category(real)
    check(f"frozen pool: 290 series in {len(g)} categories, none lost", sum(map(len, g.values())) == 290 == len(real["series"]))
    import retrain_g2 as rg
    check("window is the A13 validation window", rg.VAL == ("2026-09-07", "2026-10-05"))
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--rps", type=float, default=4.0, help="Kalshi requests/s (the live producer uses 8 on the same egress)")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    main_run(a.rps)


if __name__ == "__main__":
    main()
