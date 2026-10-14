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
    import polars as pl
    lookup = mp.category_lookup()
    rows, keys = [], []
    for mo in TEST:          # features month by month, exactly as A12's maker_policy.cmd_score
        lg, ev_, ch = s.load([mo], "mece")
        cand = []
        s.simulate(s.Config(**mp.BROAD), "pess", lg, ev_, ch, [mo], record=cand)
        for ev, tk, H, sd, pr, b, a in cand:
            r = mp.quote_features(lg, ev_, ch, lookup, mo, ev, tk, int(H), int(sd), int(pr))
            if r is not None:
                rows.append(r); keys.append((tk, int(H), int(sd)))
        print(f"  {mo}: {len(cand):,} candidates", flush=True)
        del lg, ev_, ch
    G = pickle.loads(mp.model_path("G").read_bytes())
    pg = G["model"].predict(mp.to_matrix(rows, G["cats"]))
    ref = pl.read_parquet(_REPO / "runs/maker/policy_G_scores_2025-08_2025-11.parquet")
    refd = dict(zip(zip(ref["ticker"].to_list(), ref["hour_ns"].to_list(), ref["side"].to_list()), ref["pred"].to_list()))
    same = len(refd) == len(keys) and all(abs(refd.get(k, np.inf) - p) < 1e-9 for k, p in zip(keys, pg))
    print(f"scored {len(rows):,}; G scores identical to A12's saved scores: {same}", flush=True)
    if not same:
        raise SystemExit("A16 gate: G's scores differ from A12's saved scores; nothing reported")
    legs, events, charged = s.load(TEST, "mece")      # simulation over all four months, as A12's test run
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


def cmd_metrics():
    """A16 addendum: risk and behaviour metrics on 2025-08..11 for G and every baseline (same run as `test`,
    fills and scores kept). Gated on reproducing A12 exactly."""
    import datetime as dt
    import polars as pl
    import maker_policy as mp
    import simulate_maker as s
    import train_baselines as tb
    sys.path.insert(0, str(_REPO / "stg_infra"))
    import cut_report as cr
    lookup = mp.category_lookup()
    rows, keys = [], []
    for mo in TEST:                                   # features month by month, as A12
        lg, ev_, ch = s.load([mo], "mece")
        cand = []
        s.simulate(s.Config(**mp.BROAD), "pess", lg, ev_, ch, [mo], record=cand)
        for ev, tk, H, sd, pr, b, a in cand:
            r = mp.quote_features(lg, ev_, ch, lookup, mo, ev, tk, int(H), int(sd), int(pr))
            if r is not None:
                rows.append(r); keys.append((tk, int(H), int(sd)))
        del lg, ev_, ch
    G = pickle.loads(mp.model_path("G").read_bytes())
    pg = G["model"].predict(mp.to_matrix(rows, G["cats"]))
    ref = pl.read_parquet(_REPO / "runs/maker/policy_G_scores_2025-08_2025-11.parquet")
    refd = dict(zip(zip(ref["ticker"].to_list(), ref["hour_ns"].to_list(), ref["side"].to_list()), ref["pred"].to_list()))
    assert len(refd) == len(keys) and all(abs(refd[k] - v) < 1e-9 for k, v in zip(keys, pg)), "G scores differ from A12"
    share = float(np.mean(pg > 1.0))
    post = lambda m: np.where(m, 2.0, -np.inf)
    scores = {"G": pg, "lin2-2025": tb.predict(pickle.loads(MODELS["lin2"].read_bytes()), rows),
              "mlp2-2025": tb.predict(pickle.loads(MODELS["mlp2"].read_bytes()), rows),
              "wide3": post(np.array([r["spread"] for r in rows]) >= 3),
              "liq": post(liq_flags([r["trades_24h"] for r in rows], [k[1] for k in keys])),
              "random_s0": post(np.random.default_rng(0).random(len(keys)) < share)}
    del rows
    legs, events, charged = s.load(TEST, "mece")
    settle = {ev: max((legs[t]["close"] or 0) for t in tks) or None for ev, tks in events.items()}
    def mid_at(tk, H):
        L = legs.get(tk)
        if L is None:
            return None
        j = np.searchsorted(L["e"], H)
        if j < len(L["e"]) and L["e"][j] == H and not np.isnan(L["bid"][j] + L["ask"][j]):
            return 50.0 * (L["bid"][j] + L["ask"][j])
        return None
    cfg = s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0})
    lo, hi = dt.date(2025, 8, 1), dt.date(2025, 11, 30)
    bm = cr.fetch_spy_and_tbill(lo, hi)
    spy = bm.pop("spy_close", {})
    sd_ = sorted(spy)
    spy_ret = {sd_[i]: spy[sd_[i]] / spy[sd_[i - 1]] - 1 for i in range(1, len(sd_))}
    out = {"amendment": "A16 addendum", "months": TEST, "benchmarks": bm, "arms": {}}
    for name, sc in scores.items():
        pol = dict(zip(keys, sc))
        F = s.simulate(cfg, "pess", legs, events, charged, TEST, policy_scores=pol)
        r = s.summarise(F)
        if name == "G":
            rep = {"ret": round(r["ret"], 2), "fills": r["fills"], "events": r["events"]}
            assert rep == A12, f"A16 gate: {rep} != {A12}"
        day_ends, cum = cr.tradedate_series(F)
        fkeys = [(f[0], f[1], f[2], f[3], f[4], f[5], f[7], f[9]) for f in F]
        cap = cr.peak_open_capital(fkeys, settle, day_ends)
        dd = np.diff(np.concatenate([[0.0], cum]))
        dates = [dt.datetime.fromtimestamp((de - cr.DAY_NS) / 1e9, dt.timezone.utc).date().isoformat() for de in day_ends]
        both = [(spy_ret[d_], v / cap) for d_, v in zip(dates, dd) if d_ in spy_ret and cap]
        risk = cr.risk_metrics(cum, cap, bm.get("tbill_rate_pct", 0.0) / 100 if bm.get("tbill_rate_pct") else None,
                               ([x for x, _ in both], [y for _, y in both]) if both else None)
        pred = [pol[(f[1], int(f[9]), int(f[2]))] for f in F] if name in ("G", "lin2-2025", "mlp2-2025") else None
        out["arms"][name] = {"ret_pct": r["ret"], "ci": [r["lo"], r["hi"]], "fills": r["fills"], "events": r["events"],
                             "net_usd": r["net_c"] / 100, "peak_open_capital_usd": cap,
                             "max_drawdown_usd": cr.max_drawdown(cum),
                             "max_drawdown_pct_of_peak_capital": 100 * cr.max_drawdown(cum) / cap if cap else float("nan"),
                             "risk": risk, "behaviour": cr.behaviour_metrics(F, pred, mid_at, settle)}
        print(json.dumps({name: {k: out["arms"][name][k] for k in ("ret_pct", "net_usd", "max_drawdown_usd")} | {"sharpe": risk.get("sharpe")}}, default=float), flush=True)
    p_ = _REPO / "results/maker/a16_metrics_2025.json"
    p_.write_text(json.dumps(out, indent=1, default=float))
    print(f"-> {p_}")


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
    ap.add_argument("cmd", nargs="?", choices=["train", "test", "metrics"])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    {"train": cmd_train, "test": cmd_test, "metrics": cmd_metrics}[a.cmd]()


if __name__ == "__main__":
    main()
