# Usage (from repo root): python stg_infra/examples/live_tradestore_bug_effect.py <fixed trades2.pkl>
"""Amendment L2: effect of the trade-store bug on one pre-fix hour (2026-10-11 15:00 UTC, laptop).
trades_24h (and G2+'s prints_1h / imb_1h) recomputed from the fixed store, everything else as logged;
reports how many candidates' post/do-not-post decision (prediction > 1c) flips."""
import sys, pickle, numpy as np, polars as pl
sys.path[:0] = ["stg_infra", "stg_infra/examples"]
import live_signal_producer as lp, maker_policy as mp, retrain_g2 as rg, simulate_maker as s
H_NS = lp.H_NS
store = pickle.load(open(sys.argv[1], "rb"))
models = lp.load_models()
for kind, arms in (("one", [("g", "pred_g"), ("g2", "pred_g2")]), ("two", [("g2p", "pred_g2p")])):
    df = pl.read_parquet(f"runs/live/scores/{kind}_20261011T15.parquet")
    H = int(df["H_ns"][0])
    rows, fixed, cov = [], [], 0
    for r in df.iter_rows(named=True):
        r = dict(r); f = dict(r)
        st = store.get(r["ticker"])
        if st is not None:
            cov += 1
            f["trades_24h"] = s.recent_trades(st["t"], H)
            if kind == "two":
                lo, hi = np.searchsorted(st["t"], H - H_NS, "right"), np.searchsorted(st["t"], H, "right")
                tc, ts = st["c"][lo:hi], st["s"][lo:hi]
                f["prints_1h"] = float(hi - lo); f["imb_1h"] = float((tc * ts).sum() / tc.sum()) if tc.sum() > 0 else 0.0
        rows.append(r); fixed.append(f)
    print(f"{kind}-level: {df.height:,} candidates, {cov:,} with a fixed trade history "
          f"({cov / df.height:.0%}); trades_24h changed on "
          f"{np.mean([a['trades_24h'] != b['trades_24h'] for a, b in zip(rows, fixed)]):.1%}, "
          f"median correction +{np.median([b['trades_24h'] - a['trades_24h'] for a, b in zip(rows, fixed)]):.0f}")
    for arm, col in arms:
        d, blob, _ = models[arm]
        X = (lambda R: rg.matrix("G2P", R, blob["cats"]) if d == "G2P" else mp.to_matrix(R, blob["cats"]))
        p0, p1 = blob["model"].predict(X(rows)), blob["model"].predict(X(fixed))
        logged = df[col].to_numpy()
        print(f"  {arm:<4} logged preds reproduced: {np.allclose(p0, logged)} | posted (>1c) buggy {np.mean(p0 > 1):.1%} "
              f"fixed {np.mean(p1 > 1):.1%} | decisions flipped {np.mean((p0 > 1) != (p1 > 1)):.1%} "
              f"(post->skip {np.mean((p0 > 1) & (p1 <= 1)):.1%}, skip->post {np.mean((p0 <= 1) & (p1 > 1)):.1%}) "
              f"| median |pred change| {np.median(np.abs(p1 - p0)):.2f}c")
