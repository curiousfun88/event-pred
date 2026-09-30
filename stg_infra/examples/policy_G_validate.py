"""A12 validation gate for the learned policy G: in-simulator run on 2025-06..07 (development months),
optimistic / pessimistic / strict, beside quote-everything (BROAD) and A10 on the same months.

    python stg_infra/examples/policy_G_validate.py featcheck   # shared features == offline (leak-audited) features
    python stg_infra/examples/policy_G_validate.py run
"""
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, "stg_infra"); sys.path.insert(0, "stg_infra/examples")
import simulate_maker as s
import maker_policy as mp
VAL = ["2025-06", "2025-07"]
SCORES = "runs/maker/policy_G_scores_2025-06_2025-07.parquet"


def featcheck():
    z = np.load("runs/maker/learned_policy_features_dev.npz", allow_pickle=True)
    idx, Xoff = z["idx"], z["X"]
    import learned_maker_policy as lp
    F = dict(np.load(f"runs/maker/cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
    month = np.array([s.month_of(int(h)) for h in F["hour_ns"]])
    lookup = mp.category_lookup()
    legs, events, charged = s.load(["2025-06"], "mece")
    rng = np.random.default_rng(0)
    sel = [k for k, i in enumerate(idx) if month[i] == "2025-06"]
    sel = rng.choice(sel, size=min(2000, len(sel)), replace=False)
    bad = 0
    for k in sel:
        i = idx[k]
        r = mp.quote_features(legs, events, charged, lookup, "2025-06", F["event"][i], F["ticker"][i],
                              int(F["hour_ns"][i]), int(F["side"][i]), int(F["price"][i]))
        for f in mp.FEATS_G:
            if f == "cat_i":
                continue
            off = Xoff[k, lp.FEATS.index(f)]
            new = r[f]
            if not ((np.isnan(off) and np.isnan(new)) or abs(off - new) < 1e-9):
                bad += 1; break
    print(f"  [{'PASS' if bad == 0 else 'FAIL'}] shared features == offline features on {len(sel)} sampled June fills (mismatches: {bad})")
    return bad == 0


def run():
    s.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    a10 = s.Config(**json.load(open("runs/maker/selected_a10.json")))
    broad = s.Config(**mp.BROAD)
    G = s.Config(**{**mp.BROAD, "policy": SCORES, "policy_t": 1.0})
    tasks = [(c, m, VAL) for c in (broad, G, a10) for m in ("opt", "pess", "strict")]
    res = s.run_many(tasks, workers=3)
    print("\nA12 VALIDATION GATE (in-simulator, 2025-06..07, development months)")
    meta = json.load(open(mp.META_PATH))
    print(f"  model sha1 {meta['model_sha1']}, trained on {meta['train_months'][0]}..{meta['train_months'][-1]} ({meta['n_train']:,} fills), t = 1c")
    for nm, c in (("quote everything (BROAD)", broad), ("G (learned policy)", G), ("A10 (rules)", a10)):
        for m in ("opt", "pess", "strict"):
            r = res[(c, m)]
            print(f"  {nm:<26} {m.upper():<6} ret {r['ret']:+7.2f}%  CI95 [{r['lo']:+7.2f}, {r['hi']:+7.2f}]  net ${r['net_c'] / 100:+9.2f}"
                  f"  fills {r['fills']:>7,}  events {r['events']:>5,}  markout {r['markout_c_per_contract']:+.2f}c/ct")
    g = res[(G, "pess")]
    print(f"\n  GATE (pessimistic return > 0): {'PASS -> proceed to the test months' if g['ret'] > 0 else 'FAIL -> report and stop'}")


if __name__ == "__main__":
    {"featcheck": lambda: sys.exit(0 if featcheck() else 1), "run": run}[sys.argv[1]]()
