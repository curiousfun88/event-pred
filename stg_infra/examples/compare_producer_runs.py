"""
compare_producer_runs.py

Do two producer instances (laptop and Lumid sandbox) produce the same scores for the same hour?
Plumbing check before moving the producer (no result of the forward test is read).

Joins one hour's score files (one_<H>.parquet, two_<H>.parquet) from two runs/live/scores
directories on (ticker, side, price) and reports: candidates only in one run, how often the
quotes at H agree (the two snapshots are taken seconds apart, so some legs legitimately differ),
and, where all inputs agree, whether every model's prediction agrees.

USAGE (from repo root):
    python stg_infra/examples/compare_producer_runs.py --self-test
    python stg_infra/examples/compare_producer_runs.py DIR_A DIR_B 20261011T15
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import polars as pl

KEY = ["ticker", "side", "price"]
PREDS = {"one": ["pred_g", "pred_g2"], "two": ["pred_g2p"]}
INPUTS = {"one": ["rel_price", "spread", "mid", "trades_24h", "dmid_24h", "n_legs", "n_quoted", "basket_sum",
                  "second_mid", "hour_utc", "charged"],
          "two": ["rel_price", "spread", "mid", "trades_24h", "dmid_24h", "n_legs", "n_quoted", "basket_sum",
                  "second_mid", "hour_utc", "charged", "improved", "prints_1h", "imb_1h", "dmid_1h", "dmid_3h", "ttc_h"]}


def same(a, b):
    return (a == b) | (np.isnan(a) & np.isnan(b))


def compare(A: pl.DataFrame, B: pl.DataFrame, kind: str) -> dict:
    ka = set(map(tuple, A.select(KEY).rows())); kb = set(map(tuple, B.select(KEY).rows()))
    j = A.join(B, on=KEY, suffix="_b")
    quotes = same(j["bid_c"].to_numpy().astype(float), j["bid_c_b"].to_numpy().astype(float)) & \
        same(j["ask_c"].to_numpy().astype(float), j["ask_c_b"].to_numpy().astype(float))
    inputs = quotes.copy()
    for c in INPUTS[kind]:
        inputs &= same(j[c].to_numpy().astype(float), j[c + "_b"].to_numpy().astype(float))
    out = {"only_a": len(ka - kb), "only_b": len(kb - ka), "both": j.height,
           "quotes_agree": float(quotes.mean()) if j.height else float("nan"),
           "inputs_agree": float(inputs.mean()) if j.height else float("nan")}
    for p in PREDS[kind]:
        d = np.abs(j[p].to_numpy().astype(float) - j[p + "_b"].to_numpy().astype(float))
        out[f"{p}_max_diff_when_inputs_agree"] = float(np.nanmax(d[inputs])) if inputs.any() else float("nan")
        out[f"{p}_agree_all"] = float((d < 1e-9).mean()) if j.height else float("nan")
    return out


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    base = {"ticker": ["A", "A", "B"], "side": [1, -1, 1], "price": [40, 44, 30], "bid_c": [40.0, 40.0, 30.0],
            "ask_c": [44.0, 44.0, 33.0], "pred_g": [2.0, -1.0, 0.5], "pred_g2": [1.5, 0.0, 3.0],
            **{c: [1.0, 2.0, np.nan] for c in INPUTS["one"]}}
    A = pl.DataFrame(base)
    r = compare(A, A, "one")
    check("identical runs agree fully", r["both"] == 3 and r["inputs_agree"] == 1 and r["pred_g_agree_all"] == 1
          and r["pred_g2_max_diff_when_inputs_agree"] == 0)
    B = A.with_columns(pl.when(pl.col("ticker") == "B").then(31.0).otherwise(pl.col("bid_c")).alias("bid_c"),
                       pl.when(pl.col("ticker") == "B").then(9.0).otherwise(pl.col("pred_g2")).alias("pred_g2"))
    r = compare(A, B, "one")
    check("a moved quote is excluded from the like-for-like check (2/3 agree, max diff 0)",
          abs(r["inputs_agree"] - 2 / 3) < 1e-12 and r["pred_g2_max_diff_when_inputs_agree"] == 0)
    C = A.with_columns(pl.when(pl.col("ticker") == "A").then(pl.col("pred_g") + 0.5).otherwise(pl.col("pred_g")).alias("pred_g"))
    r = compare(A, C, "one")
    check("same inputs, different prediction is caught (max diff 0.5)", abs(r["pred_g_max_diff_when_inputs_agree"] - 0.5) < 1e-12)
    r = compare(A, A.filter(pl.col("ticker") == "A"), "one")
    check("candidates in only one run are counted", r["only_a"] == 1 and r["only_b"] == 0)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    da, db, H = a.dirs
    for kind in ("one", "two"):
        A = pl.read_parquet(f"{da}/{kind}_{H}.parquet"); B = pl.read_parquet(f"{db}/{kind}_{H}.parquet")
        sa, sb = A["snap_ns"][0], B["snap_ns"][0]
        print(f"{kind}-level, hour {H}: snapshots {abs(sa - sb) / 1e9:.0f} s apart")
        for k, v in compare(A, B, kind).items():
            print(f"  {k:<36} {v:.4f}" if isinstance(v, float) else f"  {k:<36} {v:,}")


if __name__ == "__main__":
    main()
