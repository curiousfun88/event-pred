"""
export_stgat_features.py -- STGAT inputs for the learned maker policy G+S
(maker pre-registration, amendment A12).

For every observed ticker node and snapshot (window end E), the seed-averaged
Model A outputs: next-hour mid-move head (cents) and the forecast head's
predicted change at each horizon (predicted level minus the current price,
cents). Predictions only: no target is read or scored. The backbone is causal
and inputs end at E, so nothing after E is used.

    python stg_infra/export_stgat_features.py --self-test
    python stg_infra/export_stgat_features.py --out runs/maker/stgat_features_13mo.parquet
"""
from __future__ import annotations

import argparse, json, sys
from pathlib import Path

import numpy as np
import torch

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "examples"))

MONTHS = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-06", "2025-07",
          "2025-08", "2025-09", "2025-10", "2025-11"]
COLS = ["st_mid", "st_d1", "st_d2", "st_d3", "st_d6", "st_d12"]


def node_rows(values, mask, is_hub, node_ids, end_ns):
    """values: (T, N, K) -> (tickers, end_ns, (n, K)) for observed non-hub positions."""
    keep = np.asarray(mask) & ~np.asarray(is_hub)[None, :]
    t, i = np.nonzero(keep)
    ids = np.asarray([str(n) for n in node_ids], dtype=object)
    return ids[i], np.asarray(end_ns, dtype=np.int64)[t], np.asarray(values)[t, i, :]


def average(per_seed):
    """Mean over seeds, joined on (ticker, end_ns). Seeds must cover identical positions."""
    import polars as pl
    frames = []
    for k, (tk, e, v) in enumerate(per_seed):
        d = {"ticker": list(tk), "end_ns": e}
        for j, c in enumerate(COLS):
            d[f"{c}_{k}"] = v[:, j]
        frames.append(pl.DataFrame(d))
    out = frames[0]
    for f in frames[1:]:
        if f.height != out.height:
            raise ValueError("seeds cover different numbers of positions")
        out = out.join(f, on=["ticker", "end_ns"], how="inner")
    if out.height != frames[0].height:
        raise ValueError("seeds cover different positions")
    n = len(per_seed)
    return out.select("ticker", "end_ns", *[(sum(pl.col(f"{c}_{k}") for k in range(n)) / n).alias(c) for c in COLS]).sort(["ticker", "end_ns"])


def predict(ck_path, split, exclude):
    from model.chunking import build_split_ranges, chunk_ranges
    from model.forecast_head import MidMoveHead, ResidualForecastHead
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.quote_features import QuoteAttacher, _ns
    from model.train import STGATBackbone, true_prices
    from train_forecast import WINDOW
    ck = torch.load(ck_path, weights_only=False, map_location="cpu")
    if ck.get("split"):
        from data_windows import set_split
        set_split(*ck["split"])
    cfg = ck["config"]
    store = MonthlyBundleStore(build_month_paths(MONTHS, _REPO / "cache_724"), verbose=False, exclude_prefixes=exclude)
    src = QuoteAttacher(store, _REPO / "data/quotes/by_month", WINDOW, with_inputs=bool(ck.get("quote_features")))
    chunks = [c for c in chunk_ranges(build_split_ranges(store.timestamps), chunk_len=cfg.chunk_len, min_chunk_len=4)
              if c.split == split]
    model = STGATBackbone(padded_feature_width=src.feature_width, zero_input_slots=getattr(cfg, "zero_input_slots", ()),
                          zero_ladder_edge_features=getattr(cfg, "zero_ladder_edge_features", False),
                          embed_dim=cfg.embed_dim, n_heads=cfg.n_heads, max_len=cfg.chunk_len)
    model.load_state_dict(ck["model"], strict=True)
    model.drop_edges = tuple(ck.get("drop_edges") or ())
    head = ResidualForecastHead(embed_dim=cfg.embed_dim, horizons=(1, 2, 3, 6, 12))
    head.load_state_dict(ck["head"], strict=True)
    mid = MidMoveHead(cfg.embed_dim); mid.load_state_dict(ck["mid_head"], strict=True)
    model.eval(); head.eval(); mid.eval()
    parts = []
    with torch.no_grad():
        for pos, c in enumerate(chunks):
            ct = src.materialize_chunk(c)
            f, mask = ct["features"], ct["mask"]
            h = model(f, mask, ct["adjacency_by_type"])
            prices = true_prices(f)
            d = (head(h, prices) - prices[..., None]) * 100.0          # (T, N, 5) predicted change, cents
            m = mid(h)[..., None] * 100.0                               # (T, N, 1)
            vals = torch.cat([m, d], dim=-1).numpy()
            is_hub = (f[..., -1] == 1.0).any(dim=0).numpy()
            parts.append(node_rows(vals, mask.numpy(), is_hub, ct["node_ids"], [_ns(ts + WINDOW) for ts in ct["timestamps"]]))
            print(f"  {Path(ck_path).parent.name} {split}: chunk {pos + 1}/{len(chunks)}", flush=True)
            del ct
    return (np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts]),
            np.concatenate([p[2] for p in parts]))


def self_test():
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}"); fails += 0 if ok else 1
    v = np.arange(2 * 3 * 6, dtype=float).reshape(2, 3, 6)
    mask = np.array([[True, False, True], [True, True, True]])
    tk, e, x = node_rows(v, mask, np.array([False, False, True]), ["A", "B", "H"], [10, 20])
    check("unobserved and hub positions dropped", list(zip(tk, e)) == [("A", 10), ("A", 20), ("B", 20)])
    check("all 6 outputs kept per position", x.shape == (3, 6) and x[0, 0] == 0 and x[2, 5] == v[1, 1, 5])
    s0 = (np.array(["A", "B"], object), np.array([1, 1]), np.ones((2, 6)))
    s1 = (np.array(["B", "A"], object), np.array([1, 1]), 3 * np.ones((2, 6)))
    avg = average([s0, s1])
    check("seed average joins on (ticker, end) regardless of order", avg["st_mid"].to_list() == [2.0, 2.0])
    try:
        average([s0, (np.array(["A", "C"], object), np.array([1, 1]), np.ones((2, 6)))]); check("coverage mismatch is an error", False)
    except ValueError:
        check("coverage mismatch is an error", True)
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default="runs/maker/stgat_features_13mo.parquet")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(1 if self_test() else 0)
    import polars as pl
    cks = json.load(open(_REPO / "runs/tune/signal_model.json"))["checkpoints"]      # Model A, 4 final seeds
    frames = []
    for split in ("train", "val", "test"):
        per_seed = [predict(_REPO / c, split, ("KXMVE",)) for c in cks]
        frames.append(average(per_seed))
        print(f"{split}: {frames[-1].height:,} (ticker, snapshot) rows", flush=True)
    out = pl.concat(frames).sort(["ticker", "end_ns"])
    out.write_parquet(_REPO / a.out)
    print(f"{out.height:,} rows -> {a.out} (Model A: {len(cks)} seeds averaged)")


if __name__ == "__main__":
    main()
