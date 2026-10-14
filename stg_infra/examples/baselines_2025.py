"""
baselines_2025.py

AMENDMENT A16 (maker-simulator-preregistration.md): the live test's baselines on G's 2025
test months (2025-08..11), descriptive. G is unchanged; nothing is selected.

Phase `train`: the lin2 and mlp2 designs (train_baselines.fit_lin2 / fit_mlp2, defaults)
on exactly G's training rows (maker_policy.cmd_train's assembly: BROAD pessimistic fills,
2024-11..2025-05), saved with sha1 before any test month is read.
Phase `test`: all four test months in one load (as A12's test run); BROAD candidates;
scores for G (frozen e39cc4ca97bbebd4), lin2-2025, mlp2-2025, wide3, liq (hourly median),
random at G's share (5 seeds); one pessimistic simulation each; gate: G must reproduce A12
(+3.55%, 34,086 fills, 1,325 events).

USAGE (from repo root, laptop, capped):
    python stg_infra/examples/baselines_2025.py --self-test
    python stg_infra/examples/baselines_2025.py train
    python stg_infra/examples/baselines_2025.py test
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

TEST = ["2025-08", "2025-09", "2025-10", "2025-11"]
OUT = _REPO / "results/maker/a16_baselines_2025.json"
MODELS = {"lin2": _REPO / "runs/maker/policy_lin2_2025_model.pkl", "mlp2": _REPO / "runs/maker/policy_mlp2_2025_model.pkl"}
G_SHA = "e39cc4ca97bbebd4"
A12 = {"ret": 3.55, "fills": 34086, "events": 1325}


def sha16(p):
    return hashlib.sha1(Path(p).read_bytes()).hexdigest()[:16]


def g_training_rows():
    """Exactly maker_policy.cmd_train's rows and targets (variant G), plus _H for mlp2's time holdout."""
    import maker_policy as mp
    import simulate_maker as s
    lookup = mp.category_lookup()
    F = dict(np.load(_REPO / f"runs/maker/cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
    month = np.array([s.month_of(int(h)) for h in F["hour_ns"]])
    rows, ys = [], []
    for mo in mp.TRAIN:
        legs, events, charged = s.load([mo], "mece")
        for i in np.where(month == mo)[0]:
            if F["ticker"][i] not in legs:
                continue
            r = mp.quote_features(legs, events, charged, lookup, mo, F["event"][i], F["ticker"][i],
                                  int(F["hour_ns"][i]), int(F["side"][i]), int(F["price"][i]))
            if r is not None:
                r["_H"] = int(F["hour_ns"][i])
                rows.append(r); ys.append(F["net_c"][i] / F["qty"][i])
        print(f"  {mo}: {len(rows):,} training rows", flush=True)
        del legs, events, charged
    return rows, ys


def cmd_train():
    import train_baselines as tb
    rows, ys = g_training_rows()
    meta = {"amendment": "A16", "n_train": len(ys), "train_months": "2024-11..2025-05 (G's rows)"}
    for arm, fit in (("lin2", tb.fit_lin2), ("mlp2", lambda r, y: tb.fit_mlp2(r, y, log=lambda *a: None))):
        blob = fit(rows, ys)
        MODELS[arm].write_bytes(pickle.dumps(blob))
        meta[f"{arm}_2025_sha1"] = sha16(MODELS[arm])
        meta[f"{arm}_2025_train_share_posted"] = round(float(np.mean(tb.predict(blob, rows) > 1.0)), 4)
        if arm == "mlp2":
            meta["mlp2_2025_best_epoch"] = blob["best_epoch"]
        print(json.dumps({arm: meta[f"{arm}_2025_sha1"]}), flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"train": meta}, indent=1))
    print(json.dumps(meta, indent=1))


def liq_flags(trades_24h, hours):
    """trades_24h >= that hour's median over the hour's candidates (the live rule)."""
    t, h = np.asarray(trades_24h, float), np.asarray(hours)
    med = {x: np.median(t[h == x]) for x in np.unique(h)}
    return t >= np.array([med[x] for x in h])


def cmd_test():
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    import train_baselines as tb
    res = json.loads(OUT.read_text())
    assert all(MODELS[a].exists() for a in MODELS), "run `train` first"
    assert sha16(mp.model_path("G")) == G_SHA, "G model hash differs from A12"
    legs, events, charged = s.load(TEST, "mece")
    lookup = mp.category_lookup()
    cand = []
    s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, TEST, record=cand)
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a in cand:
        r = mp.quote_features(legs, events, charged, lookup, s.month_of(int(H)), ev, tk, int(H), int(sd), int(pr))
        if r is not None:
            rows.append(r); keys.append((tk, int(H), int(sd)))
    print(f"candidates {len(cand):,}; scored {len(rows):,}", flush=True)
    G = pickle.loads(mp.model_path("G").read_bytes())
    pg = G["model"].predict(mp.to_matrix(rows, G["cats"]))
    share = float(np.mean(pg > 1.0))
    post = lambda m: np.where(m, 2.0, -np.inf)
    scores = {"G": pg,
              "lin2-2025": tb.predict(pickle.loads(MODELS["lin2"].read_bytes()), rows),
              "mlp2-2025": tb.predict(pickle.loads(MODELS["mlp2"].read_bytes()), rows),
              "wide3": post(np.array([r["spread"] for r in rows]) >= 3),
              "liq": post(liq_flags([r["trades_24h"] for r in rows], [k[1] for k in keys]))}
    for seed in range(5):
        scores[f"random_s{seed}"] = post(np.random.default_rng(seed).random(len(keys)) < share)
    del rows
    cfg = s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0})
    fills, out = {}, {"G_share": share, "candidates": len(keys)}
    for name, sc in scores.items():
        fills[name] = s.simulate(cfg, "pess", legs, events, charged, TEST, policy_scores=dict(zip(keys, sc)))
        r = s.summarise(fills[name])
        out[name] = {k: r[k] for k in ("ret", "lo", "hi", "fills", "events", "net_c")} | {"posted_share": float(np.mean(sc > 1.0))}
        print(json.dumps({name: out[name]}, default=float), flush=True)
        if name == "G":
            rep = {"ret": round(r["ret"], 2), "fills": r["fills"], "events": r["events"]}
            out["reproduction"] = {"got": rep, "A12": A12, "ok": rep == A12}
            print(json.dumps({"REPRODUCTION": out["reproduction"]}), flush=True)
            if rep != A12:
                res["test"] = out
                OUT.write_text(json.dumps(res, indent=1, default=float))
                raise SystemExit("A16 gate: G does not reproduce A12; nothing reported as a result")
    out["paired_G_minus"] = {n: rg.paired_diff_ci(fills["G"], fills[n]) for n in scores if n != "G"}
    out["random_mean_ret"] = float(np.mean([out[f"random_s{i}"]["ret"] for i in range(5)]))
    res["test"] = out
    OUT.write_text(json.dumps(res, indent=1, default=float))
    print(json.dumps({k: v for k, v in out.items() if k in ("paired_G_minus", "random_mean_ret")}, default=float, indent=1))


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    t = [0, 5, 10, 1, 1, 9]
    h = [1, 1, 1, 2, 2, 2]
    check("liq: >= the hour's median, per hour (H1 median 5; H2 median 1)", list(liq_flags(t, h)) == [False, True, True, True, True, True])
    check("test months and A12 gate as pre-registered", TEST == ["2025-08", "2025-09", "2025-10", "2025-11"]
          and A12 == {"ret": 3.55, "fills": 34086, "events": 1325})
    import maker_policy as mp
    check("G's frozen model hash is A12's", sha16(mp.model_path("G")) == G_SHA)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["train", "test"])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    {"train": cmd_train, "test": cmd_test}[a.cmd]()


if __name__ == "__main__":
    main()
