"""
export_mid_signal.py

Amendment A6.3 (maker pre-registration) / B1.5 (7/2/4 pre-registration):
the STGAT signal S4 and S5 trade on. For every observed ticker node and
snapshot, the next-hour quoted-mid-move head's prediction m_hat, in CENTS,
AVERAGED OVER THE FINAL SEEDS, keyed by the snapshot's window end E_t.

simulate_maker.py --signal reads this file and, at quoting hour H, uses the
latest snapshot with E_t <= H (signal_at). Nothing here reads prices after
E_t: the backbone's temporal attention is causal and the quote inputs use
candles ending at or before E_t (model/quote_features.py).

Predictions only -- no target, no score is computed or printed, so running
this on the test months reveals nothing about the result.

    python stg_infra/export_mid_signal.py --self-test
    python stg_infra/export_mid_signal.py --checkpoints runs/tune/final_*_s{0..3}/best.pt \
        --cache cache_724 --months 2025-08 2025-09 2025-10 2025-11 --split test \
        --out runs/maker/stgat_signal_test.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_THIS_DIR / "examples"))


def chunk_rows(m_hat_c, mask, is_hub, node_ids, end_ns):
    """(ticker, end_ns, m_hat_c) for observed ticker positions of one chunk.
    m_hat_c, mask: (T, N); is_hub: (N,); end_ns: (T,)."""
    keep = np.asarray(mask) & ~np.asarray(is_hub)[None, :]
    t, i = np.nonzero(keep)
    ids = np.asarray([str(n) for n in node_ids], dtype=object)
    return ids[i], np.asarray(end_ns, dtype=np.int64)[t], np.asarray(m_hat_c, dtype=np.float64)[t, i]


def average_seeds(per_seed):
    """Mean m_hat over seeds. per_seed: list of (tickers, end_ns, m_hat_c).
    Every seed must cover exactly the same (ticker, end_ns) positions -- they
    are the same data and the same split -- so a mismatch is an error, not
    something to paper over with a partial average."""
    import polars as pl
    frames = []
    for k, (tk, e, m) in enumerate(per_seed):
        df = pl.DataFrame({"ticker": list(tk), "end_ns": e, f"m{k}": m})
        if df.select(["ticker", "end_ns"]).is_duplicated().any():
            raise ValueError(f"seed {k}: duplicate (ticker, end_ns) rows")
        frames.append(df)
    out = frames[0]
    for k, df in enumerate(frames[1:], start=1):
        if df.height != out.height:
            raise ValueError(f"seed {k} covers {df.height} positions, seed 0 covers {out.height}")
        out = out.join(df, on=["ticker", "end_ns"], how="inner")
        if out.height != df.height:
            raise ValueError(f"seed {k} covers different positions from seed 0")
    cols = [f"m{k}" for k in range(len(frames))]
    return (out.with_columns(pl.mean_horizontal(cols).alias("m_hat_c"))
               .select("ticker", "end_ns", "m_hat_c").sort(["ticker", "end_ns"]))


def predict_checkpoint(ck_path: Path, cache: Path, months, split: str, quotes_dir: Path,
                       exclude_prefixes=()):
    from model.chunking import build_split_ranges, chunk_ranges
    from model.forecast_head import MidMoveHead
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.quote_features import QuoteAttacher, _ns
    from model.train import STGATBackbone
    from train_forecast import WINDOW

    ck = torch.load(ck_path, weights_only=False, map_location="cpu")
    if ck.get("mid_head") is None:
        raise SystemExit(f"{ck_path}: no mid-move head (trained with --w-mid 0?)")
    if ck.get("split"):
        from data_windows import set_split
        set_split(*ck["split"])
    cfg = ck["config"]
    store = MonthlyBundleStore(build_month_paths(months, cache), verbose=False,
                               exclude_prefixes=exclude_prefixes)
    src = QuoteAttacher(store, quotes_dir, WINDOW, with_inputs=bool(ck.get("quote_features")))
    if ck.get("feature_width") is not None and ck["feature_width"] != src.feature_width:
        raise SystemExit(f"feature width {src.feature_width} != checkpoint's {ck['feature_width']}")
    chunks = [c for c in chunk_ranges(build_split_ranges(store.timestamps), chunk_len=cfg.chunk_len,
                                      min_chunk_len=4) if c.split == split]
    if not chunks:
        raise SystemExit(f"no '{split}' chunks in {months}")

    model = STGATBackbone(padded_feature_width=src.feature_width,
                          zero_input_slots=getattr(cfg, "zero_input_slots", ()),
                          zero_ladder_edge_features=getattr(cfg, "zero_ladder_edge_features", False),
                          embed_dim=cfg.embed_dim, n_heads=cfg.n_heads, max_len=cfg.chunk_len)
    model.load_state_dict(ck["model"], strict=True)
    model.drop_edges = tuple(ck.get("drop_edges") or ())
    head = MidMoveHead(cfg.embed_dim)
    head.load_state_dict(ck["mid_head"], strict=True)
    model.eval()
    head.eval()

    parts = []
    with torch.no_grad():
        for pos, c in enumerate(chunks):
            ct = src.materialize_chunk(c)
            f, mask = ct["features"], ct["mask"]
            m_hat_c = (head(model(f, mask, ct["adjacency_by_type"])) * 100.0).numpy()
            is_hub = (f[..., -1] == 1.0).any(dim=0).numpy()
            ends = [_ns(ts + WINDOW) for ts in ct["timestamps"]]
            parts.append(chunk_rows(m_hat_c, mask.numpy(), is_hub, ct["node_ids"], ends))
            print(f"  {ck_path.parent.name}: chunk {pos + 1}/{len(chunks)}", flush=True)
            del ct
    return (np.concatenate([p[0] for p in parts]), np.concatenate([p[1] for p in parts]),
            np.concatenate([p[2] for p in parts]))


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    m = np.array([[1.0, 2.0, 9.0], [3.0, 4.0, 9.0]])
    mask = np.array([[True, False, True], [True, True, True]])
    tk, e, v = chunk_rows(m, mask, np.array([False, False, True]), ["A", "B", "H"], [10, 20])
    check("unobserved positions dropped, hub dropped",
          list(zip(tk, e, v)) == [("A", 10, 1.0), ("A", 20, 3.0), ("B", 20, 4.0)])
    s0 = (np.array(["A", "B"], object), np.array([10, 10]), np.array([2.0, -4.0]))
    s1 = (np.array(["B", "A"], object), np.array([10, 10]), np.array([0.0, 4.0]))
    avg = average_seeds([s0, s1])
    check("seed average joins on (ticker, end) regardless of row order",
          avg["m_hat_c"].to_list() == [3.0, -2.0] and avg["ticker"].to_list() == ["A", "B"])
    try:
        average_seeds([s0, (np.array(["A"], object), np.array([10]), np.array([1.0]))])
        check("mismatched seed coverage is an error", False)
    except ValueError:
        check("mismatched seed coverage is an error", True)
    try:
        average_seeds([s0, (np.array(["A", "C"], object), np.array([10, 10]), np.array([1.0, 1.0]))])
        check("same count but different positions is an error", False)
    except ValueError:
        check("same count but different positions is an error", True)
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--checkpoints", nargs="+")
    ap.add_argument("--cache", default="cache_724")
    ap.add_argument("--exclude-series-prefix", nargs="*", default=[], help="drop nodes whose ticker starts with any of these prefixes (e.g. KXMVE, Kalshi's multivariate parlays, absent before 2025-10). Default: none. An excluded node with an edge is an error.")
    ap.add_argument("--months", nargs="+")
    ap.add_argument("--split", choices=["train", "val", "test"], default="test")
    ap.add_argument("--quotes-dir", default="data/quotes/by_month")
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not (args.checkpoints and args.months and args.out):
        raise SystemExit("--checkpoints, --months and --out are required")
    root = lambda p: Path(p) if Path(p).is_absolute() else _REPO_ROOT / p
    if args.exclude_series_prefix:
        print(f"EXCLUDED node prefixes: {args.exclude_series_prefix}")
    per_seed = [predict_checkpoint(root(c), root(args.cache), args.months, args.split, root(args.quotes_dir),
                                   args.exclude_series_prefix)
                for c in args.checkpoints]
    out = average_seeds(per_seed)
    Path(root(args.out)).parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(root(args.out))
    print(f"{out.height:,} (ticker, snapshot) signals, averaged over {len(per_seed)} seed(s) -> {args.out}")
    print("exit: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
