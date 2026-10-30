"""
live_matched_share.py

EXPLORATORY NOTE 10 (lumid-forward-test-preregistration.md, committed 2026-10-29 06:49 UTC, before the interim cut
report was computed): live matched-share comparison of g2, g2p (G2 two-level) and lin2, as note 2 did offline.

Main result (L18: 23 series, quoting hours from 2026-10-16 T17 to the cut), primary order window, pessimistic fills.
From quote-everything's live fills (`cand`, as recorded in the ledger, with its corrections, as the cut report reads them), each model keeps its top-ranked candidate
fills by its own hourly score at fixed shares; return and net P&L are pooled over the events settled by the cut's
settle-by, beside each model's own 1c rule. Scores: g2 and g2p as logged by the producer; lin2 recomputed from the
logged features with the frozen model, exactly as the paper trader does (paper_trader.arm_scores). The fill set is
checked against the cut report's own quote-everything figure before anything is ranked.

USAGE (from repo root; LIVE_DIR = a copy of runs/live after `paper_trader.py --run`, as for cut_report.py):
    python stg_infra/examples/live_matched_share.py --self-test
    LIVE_DIR=<copy> python stg_infra/examples/live_matched_share.py --cut 2026-10-28T00 --settle-by 2026-10-30T00 \
        --check-json results/live/cut_interim.json --out results/live/note10_matched_share_interim.json
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(_THIS))

SHARES = (2, 5, 10, 15, 20, 25, 30, 40)
MAIN = "train23 (L18 main result, hours from 2026-10-16 17:00 UTC)"


def matched(score, net, cap, shares=SHARES, threshold=1.0):
    """Keep each model's top-ranked fills at fixed shares of all candidate fills (ties broken by order), and at its own
    rule (score > threshold). Fills without a score never rank. Returns {label: {share, fills, net_usd, return_pct}}."""
    score, net, cap = (np.asarray(x, float) for x in (score, net, cap))
    n = len(score)
    order = np.argsort(-np.nan_to_num(score, nan=-np.inf), kind="stable")
    out = {}

    def row(idx):
        c = cap[idx].sum()
        return {"share": 100 * len(idx) / n if n else 0.0, "fills": int(len(idx)), "net_usd": float(net[idx].sum() / 100),
                "return_pct": float(100 * net[idx].sum() / c) if c else float("nan")}

    for s in shares:
        k = int(round(n * s / 100))
        out[f"top {s}%"] = row(order[:k][~np.isnan(score[order[:k]])])
    out["own 1c rule"] = row(np.where(np.nan_to_num(score, nan=-np.inf) > threshold)[0])
    return out


def run(cut, settle_by, check_json, out):
    import polars as pl
    import cut_report as cr
    import paper_trader as pt
    import train_baselines as tb
    from fetch_kalshi_api_months import SERIES_A13

    live = pt.LIVE
    cut_ns, settle_ns, main_from = cr.ns_of(cut), cr.ns_of(settle_by), cr.ns_of(cr.MAIN_FROM)
    import paper_ledger as pl_
    markets = pickle.loads((live / "paper" / "markets.pkl").read_bytes())
    results = {t: m.get("result") for t, m in markets.items()}
    settled_at = cr.settle_times(markets)
    _, fills, _ = cr.read_ledger(cr.LEDGER)                 # the recorded fills, as the cut report reads them
    cr.apply_corrections(cr.LEDGER, fills)
    keys = [k for k in fills[("primary", "cand")]
            if cr.is_train23_key(k) and main_from <= int(k[7]) < cut_ns
            and settled_at.get(k[0]) is not None and settled_at[k[0]] <= settle_ns]
    F = [pl_.as_fill(k, results.get(k[1])) for k in keys]   # (ev, tk, side, price, qty, fee, net, cap, mk, H)
    f = pl.DataFrame({"ticker": [x[1] for x in F], "H_ns": [int(x[9]) for x in F], "side": [int(x[2]) for x in F],
                      "price": [int(x[3]) for x in F], "net_c": [float(x[6]) for x in F],
                      "capital_c": [float(x[7]) for x in F]})

    ref = json.loads(Path(check_json).read_text())["headline"]["primary"][MAIN]["arms"]["cand"]
    got = (round(f["net_c"].sum() / 100, 2), f.height)
    print(f"check against the cut report's quote everything: here ${got[0]:+.2f} over {got[1]:,} settled fills, "
          f"cut report ${ref['net_usd']:+.2f} over {ref['settled_fills']:,}")
    if abs(got[0] - ref["net_usd"]) > 0.01 or got[1] != ref["settled_fills"]:
        raise SystemExit("fill set does not match the cut report; nothing ranked")

    hours = sorted({h for h in f["H_ns"].to_list()})
    stamps = [pt.stamp_of(h) for h in hours] if hasattr(pt, "stamp_of") else None
    one, two = pt.load_scores(stamps if stamps else [cr.dt.datetime.fromtimestamp(h / 1e9, cr.dt.timezone.utc).strftime("%Y%m%dT%H") for h in hours])
    base = {"lin2": pickle.loads(tb.model_path("lin2").read_bytes())}
    sc = pt.arm_scores(one, two, base)
    tk, H, sd, pr = (f[c].to_list() for c in ("ticker", "H_ns", "side", "price"))
    k1 = list(zip(tk, H, [int(x) for x in sd]))
    k2 = list(zip(tk, H, [int(x) for x in sd], [int(x) for x in pr]))
    score = {"g2": [sc["g2"].get(k, np.nan) for k in k1], "lin2": [sc["lin2"].get(k, np.nan) for k in k1],
             "g2p": [sc["g2p"].get(k, np.nan) for k in k2]}
    net, cap = f["net_c"].to_numpy(), f["capital_c"].to_numpy()
    res = {"note": "exploratory note 10; descriptive, no verdict", "cut": cut, "settle_by": settle_by,
           "candidate_fills": f.height, "scored_share": {m: float(np.mean(~np.isnan(v))) for m, v in score.items()},
           "models": {m: matched(v, net, cap) for m, v in score.items()}}
    Path(out).write_text(json.dumps(res, indent=1))
    print(f"\n{f.height:,} candidate fills; scored: " + ", ".join(f"{m} {100 * s:.1f}%" for m, s in res["scored_share"].items()))
    print(f"{'':<12}" + "".join(f"{m:>22}" for m in score))
    for lab in list(res["models"]["g2"]):
        print(f"{lab:<12}" + "".join(f"{res['models'][m][lab]['return_pct']:>+9.2f}% ${res['models'][m][lab]['net_usd']:>+9.2f} "
                                     for m in score))


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    net = [100, 50, -20, -80, 10]
    cap = [1000, 1000, 1000, 1000, 1000]
    good = [5, 4, 3, 2, 1]          # ranks the profitable fills first
    r = matched(good, net, cap, shares=(20, 40))
    check("top 20% keeps the single best fill", r["top 20%"]["fills"] == 1 and r["top 20%"]["net_usd"] == 1.0)
    check("top 40% keeps the best two: +150c on 2000c", r["top 40%"]["net_usd"] == 1.5 and r["top 40%"]["return_pct"] == 7.5)
    check("own 1c rule keeps scores above 1 (four fills)", r["own 1c rule"]["fills"] == 4)
    r2 = matched([np.nan, 4, 3, 2, 1], net, cap, shares=(40,))
    check("an unscored fill never ranks: the best-paid fill (unscored) is skipped, top 2 = +50c, -20c",
          r2["top 40%"]["fills"] == 2 and abs(r2["top 40%"]["net_usd"] - 0.3) < 1e-9)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cut", default="2026-10-28T00")
    ap.add_argument("--settle-by", default="2026-10-30T00")
    ap.add_argument("--check-json", default="results/live/cut_interim.json")
    ap.add_argument("--out", default="results/live/note10_matched_share_interim.json")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.cut.replace("-", "").replace(":", ""), a.settle_by.replace("-", "").replace(":", ""), a.check_json, a.out)


if __name__ == "__main__":
    main()
