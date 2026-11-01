"""
diagnose_ladder_timing.py

IS LADDER REPRICING TIMING UNFORECASTABLE, OR WAS IT HIDDEN FROM THE MODEL?

`ladder-conclusion-overturned.md` closed the ladder on one mechanism: the
model learns the SIZE of a correction but cannot tell WHICH pairs are about
to reprice, so learned reversion bleeds onto the ~85-90% of pairs that stay
frozen. It concluded "whether a leg reprices is not in the features in any
form the model can exploit".

Two properties of the experimental setup make that true by construction,
independently of the market:

  1. STALENESS IS ERASED. When a tracked leg does not trade in a window,
     KalshiTickerNodes replays its whole previous feature vector (volume,
     trade intensity, net flow included); only time_to_close (slot 8) is
     recomputed. There is no time-since-last-trade feature. A leg that last
     traded ten hours ago is indistinguishable from one that traded this
     window.
  2. THE GRID IS COARSER THAN THE CONTRACTS. ~79% of validated ladder legs
     (KXINXU, KXNASDAQ100U, KXBTCD, KXETHD) live one hour, open to close.
     The graph snapshots every 2h and the objective forecasts h = 1..12
     snapshots (2h..24h) ahead, so most of those contracts are closed before
     the first horizon.

This script measures whether (1) and (2) matter, on exactly the population
the forecast objective scores:

  - pair-snapshots selected as model/forecast_objective.py:_ladder_terms
    selects them (both legs present at t and t+h, after apply_validity),
    "moved" defined with the same MOVE_EPS;
  - each leg's AGE = snapshots since its last FRESH window, recovered by
    detecting replayed feature vectors (slots 0-7 identical to the previous
    snapshot);
  - AUC for predicting "moved" from the hidden age, against what the model
    could see (replayed window volume, time to close);
  - everything split by contract lifetime (hourly / daily / longer), from
    open_time..close_time in the markets files.

  - PAST-CLOSE legs flagged. run_real_training.py builds each month from
    market rows CREATED in that month, so a contract created in the previous
    month but still trading has no close_time in KalshiTickerNodes and is
    carried forward, frozen at its last print, until the 14-day
    max_staleness fallback. Close times here come from the neighbouring
    months' markets files too, and every table is repeated on LIVE pairs
    only (both legs before their close at t+h).

If the hidden age separates movers from frozen pairs where the visible
features do not, the ladder closure tested an information set, not the
market, and a retest with a staleness feature is warranted. If it does not,
the closure stands on firmer ground.

SPLIT DISCIPLINE. Defaults to train+val months (2025-05..2025-08). The test
month is refused unless --allow-test is passed, because this diagnostic may
motivate a retrain and must not be informed by test data.

Scores months independently; a pair spanning a month boundary is dropped,
and the first snapshot of each month counts every present leg as fresh.
Training chunks cut at the same boundaries, so this matches training.

USAGE (from the repo root)
    python stg_infra/diagnose_ladder_timing.py --self-test
    python stg_infra/diagnose_ladder_timing.py                       # h=1, May-Aug
    python stg_infra/diagnose_ladder_timing.py --horizons 1 3 12 --months 2025-07 2025-08
"""

from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import polars as pl
import torch

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_THIS_DIR / "examples"))

from data_windows import split_for  # noqa: E402
from model.data_validation import apply_validity  # noqa: E402
from model.forecast_objective import MOVE_EPS  # noqa: E402
from model.month_store import build_month_paths  # noqa: E402

LADDER_KEY = "ladder_monotonic"
N_STATE_SLOTS = 8          # slots 0-7 describe the window's trades; 8 = time_to_close (refreshed on replay)
AGE_BUCKETS = [(0, 0, "0 (traded this window)"), (1, 1, "1"), (2, 2, "2"),
               (3, 5, "3-5"), (6, 11, "6-11"), (12, 10**9, "12+")]


# ---------------------------------------------------------------------------
# Core computation (pure numpy; exercised by --self-test)
# ---------------------------------------------------------------------------

def leg_age(features: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(T,N,F), (T,N) -> (T,N) int: snapshots since the leg's last FRESH
    window; -1 where the leg is absent. A window is fresh when the leg is
    present and either absent at t-1 or its trade-state slots changed. A
    carried-forward replay reproduces slots 0-7 exactly, so identical slots
    at consecutive present snapshots mean 'no trade this window'."""
    T, N, _ = features.shape
    age = np.full((T, N), -1, dtype=np.int64)
    state = features[:, :, :N_STATE_SLOTS]
    for t in range(T):
        present = mask[t]
        if t == 0:
            age[t, present] = 0
            continue
        changed = np.any(state[t] != state[t - 1], axis=1)
        fresh = present & (~mask[t - 1] | changed)
        carried = present & ~fresh
        age[t, fresh] = 0
        prev = age[t - 1]
        age[t, carried] = np.where(prev[carried] >= 0, prev[carried] + 1, 0)
    return age


def scored_pairs(features: np.ndarray, mask: np.ndarray, edges_per_t: List[Optional[np.ndarray]],
                 h: int) -> Dict[str, np.ndarray]:
    """Replicates _ladder_terms' selection for one horizon and returns one
    row per scored pair-snapshot, plus the count of pairs present at t but
    dropped because a leg is absent at t+h."""
    T = features.shape[0]
    prices = features[:, :, 0] / 100.0
    age = leg_age(features, mask)
    cols = {k: [] for k in ("t", "a", "b", "moved", "age_min", "age_max",
                            "vol_visible", "ttc_min")}
    present_now = 0
    for t in range(T - h):
        e = edges_per_t[t]
        if e is None or e.size == 0:
            continue
        a, b = e[0], e[1]
        now = mask[t, a] & mask[t, b]
        ok = now & mask[t + h, a] & mask[t + h, b]
        present_now += int(now.sum())
        if not ok.any():
            continue
        a, b = a[ok], b[ok]
        mv = ((np.abs(prices[t + h, a] - prices[t, a]) > MOVE_EPS) |
              (np.abs(prices[t + h, b] - prices[t, b]) > MOVE_EPS))
        cols["t"].append(np.full(a.size, t))
        cols["a"].append(a)
        cols["b"].append(b)
        cols["moved"].append(mv)
        cols["age_min"].append(np.minimum(age[t, a], age[t, b]))
        cols["age_max"].append(np.maximum(age[t, a], age[t, b]))
        cols["vol_visible"].append(features[t, a, 4] + features[t, b, 4])
        cols["ttc_min"].append(np.minimum(features[t, a, 8], features[t, b, 8]))
    out = {k: (np.concatenate(v) if v else np.array([])) for k, v in cols.items()}
    out["present_now"] = np.array(present_now)
    return out


def auc(score: np.ndarray, label: np.ndarray) -> float:
    """Mann-Whitney AUC with average ranks for ties. 0.5 = no information."""
    label = label.astype(bool)
    n_pos, n_neg = int(label.sum()), int((~label).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    ranks = pl.Series(score.astype(np.float64)).rank("average").to_numpy()
    return float((ranks[label].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def life_class(hours: Optional[float]) -> str:
    if hours is None or not np.isfinite(hours):
        return "unknown"
    if hours <= 1.5:
        return "hourly (<=1.5h)"
    if hours <= 26:
        return "daily (<=26h)"
    return "longer (>26h)"


# ---------------------------------------------------------------------------
# Real data
# ---------------------------------------------------------------------------

def _neighbours(months: List[str]) -> List[str]:
    """The requested months plus one either side, so contracts created in
    the previous month (the ones the per-month build loses) are covered."""
    out = set(months)
    for m in months:
        y, mo = (int(x) for x in m.split("-"))
        out.add(f"{y - (mo == 1):04d}-{12 if mo == 1 else mo - 1:02d}")
        out.add(f"{y + (mo == 12):04d}-{1 if mo == 12 else mo + 1:02d}")
    return sorted(out)


def ticker_meta(months: List[str], repo_root: Path):
    """ticker -> (lifetime in hours, close_time as naive UTC)."""
    files = []
    for m in _neighbours(months):
        files += glob.glob(str(repo_root / f"data/markets/markets_kalshi_*/markets_{m}.parquet"))
    if not files:
        raise SystemExit(f"no markets files found for {months} under data/markets/")
    lf = pl.concat([pl.scan_parquet(f).select(["ticker", "open_time", "close_time"]) for f in files])
    df = (lf.with_columns(pl.col("close_time").dt.replace_time_zone(None).alias("close_naive"),
                          ((pl.col("close_time").cast(pl.Datetime) - pl.col("open_time").cast(pl.Datetime))
                           .dt.total_seconds() / 3600.0).alias("life_h"))
            .group_by("ticker").agg(pl.col("life_h").max(), pl.col("close_naive").max()).collect())
    tk = df["ticker"].to_list()
    return dict(zip(tk, df["life_h"].to_list())), dict(zip(tk, df["close_naive"].to_list()))


def past_close(timestamps, node_close, mask: np.ndarray) -> np.ndarray:
    """(T,N) bool: leg present in a window that STARTS at or after its close.
    Such a leg cannot trade; any presence is a carry-forward replay."""
    ts = np.array([np.datetime64(getattr(t, "replace")(tzinfo=None) if getattr(t, "tzinfo", None) else t, "s")
                   for t in timestamps])
    cl = np.array([np.datetime64(c, "s") if c is not None else np.datetime64("NaT") for c in node_close])
    return mask & (ts[:, None] >= cl[None, :])


def load_month(path: Path):
    bundle = torch.load(path, map_location="cpu", weights_only=False)
    feats, mask, adj, _ = apply_validity(bundle.features, bundle.mask, bundle.adjacency_by_type)
    edges = [None if e is None or e.edge_index.numel() == 0 else e.edge_index.numpy()
             for e in adj.get(LADDER_KEY, [])]
    return feats.numpy(), mask.numpy(), edges, [str(n) for n in bundle.node_ids], list(bundle.timestamps)


def summarise(rows: pl.DataFrame, title: str) -> pl.DataFrame:
    print(f"\n{title}")
    print(f"  {'lifetime class':18s} {'pair-snaps':>11s} {'pairs k':>9s} {'series':>7s} "
          f"{'moved':>7s} {'AUC age':>8s} {'AUC vol':>8s} {'AUC ttc':>8s}")
    out = []
    for cls in sorted(rows["life_class"].unique().to_list()) + ["ALL"]:
        r = rows if cls == "ALL" else rows.filter(pl.col("life_class") == cls)
        if r.height == 0:
            continue
        mv = r["moved"].to_numpy()
        a_age = auc(-r["age_min"].to_numpy(), mv)        # fresher -> more likely to move
        a_vol = auc(r["vol_visible"].to_numpy(), mv)
        a_ttc = auc(-r["ttc_min"].to_numpy(), mv)        # closer to expiry -> more likely to move
        k = r.select(pl.struct("a_id", "b_id").n_unique()).item()
        ns = r["series"].n_unique()
        print(f"  {cls:18s} {r.height:>11,d} {k:>9,d} {ns:>7d} {mv.mean():>7.1%} "
              f"{a_age:>8.3f} {a_vol:>8.3f} {a_ttc:>8.3f}")
        out.append({"life_class": cls, "pair_snapshots": r.height, "pairs": k, "series": ns,
                    "moved_share": float(mv.mean()), "auc_hidden_age": a_age,
                    "auc_visible_volume": a_vol, "auc_visible_ttc": a_ttc})
    print("\n  moved share by the fresher leg's age (snapshots since its last trade):")
    hdr = "  " + f"{'':18s}" + "".join(f"{lab:>24s}" for _, _, lab in AGE_BUCKETS)
    print(hdr)
    for cls in sorted(rows["life_class"].unique().to_list()) + ["ALL"]:
        r = rows if cls == "ALL" else rows.filter(pl.col("life_class") == cls)
        cells = []
        for lo, hi, _ in AGE_BUCKETS:
            s = r.filter((pl.col("age_min") >= lo) & (pl.col("age_min") <= hi))
            cells.append(f"{s['moved'].mean():>7.1%} (n={s.height:>9,d})" if s.height else f"{'-':>24s}")
        print("  " + f"{cls:18s}" + "".join(f"{c:>24s}" for c in cells))
    return pl.DataFrame(out)


def run(args) -> None:
    repo_root = _THIS_DIR.parent
    months = args.months
    test_months = [m for m in months if split_for(m) == "test"]
    if test_months and not args.allow_test:
        raise SystemExit(f"refusing test month(s) {test_months}: this diagnostic may motivate a "
                         f"retrain. Pass --allow-test only for a final, pre-registered look.")
    print(f"months: {months}  (splits: {[split_for(m) for m in months]})  horizons: {args.horizons}")
    lifetimes, closes = ticker_meta(months, repo_root)
    paths = build_month_paths(months, repo_root / args.cache)
    per_h: Dict[int, List[pl.DataFrame]] = {h: [] for h in args.horizons}
    dropped: Dict[int, List[tuple]] = {h: [] for h in args.horizons}
    for m in months:
        feats, mask, edges, node_ids, stamps = load_month(paths[m])
        dead = past_close(stamps, [closes.get(n) for n in node_ids], mask)
        cls_of = np.array([life_class(lifetimes.get(n)) for n in node_ids], dtype=object)
        series_of = np.array([n.split("-")[0] for n in node_ids], dtype=object)
        ids = np.array(node_ids, dtype=object)
        for h in args.horizons:
            r = scored_pairs(feats, mask, edges, h)
            n = r["moved"].size
            dropped[h].append((int(r["present_now"]), n))
            if n == 0:
                continue
            a, b = r["a"], r["b"]
            # a pair's class is its SHORTER-lived leg's class
            cls = np.where(cls_of[a] == "hourly (<=1.5h)", cls_of[a], cls_of[b])
            per_h[h].append(pl.DataFrame({
                "month": [m] * n, "a_id": ids[a], "b_id": ids[b], "series": series_of[a],
                "life_class": cls, "moved": r["moved"], "age_min": r["age_min"],
                "age_max": r["age_max"], "vol_visible": r["vol_visible"], "ttc_min": r["ttc_min"],
                "past_close": dead[r["t"] + h, a] | dead[r["t"] + h, b],
            }))
        print(f"  {m}: loaded, T={feats.shape[0]} N={feats.shape[1]}")
        del feats, mask, edges

    summaries = []
    for h in args.horizons:
        rows = pl.concat(per_h[h]) if per_h[h] else pl.DataFrame()
        pres = sum(p for p, _ in dropped[h]); sc = sum(s for _, s in dropped[h])
        print("\n" + "=" * 110)
        print(f"h={h} ({2 * h}h ahead) -- scored exactly as _ladder_terms selects pairs")
        print(f"  ladder pair-snapshots with both legs present at t: {pres:,d}; "
              f"still both present at t+h (scored): {sc:,d} ({sc / max(pres, 1):.1%})")
        if rows.height == 0:
            continue
        print(f"  frozen share of scored pairs: {1 - rows['moved'].mean():.1%} "
              f"(reported in ladder-conclusion-overturned.md for val h=1: 89.8%)")
        pc = rows["past_close"]
        print(f"  PAST-CLOSE: {pc.mean():.1%} of scored pair-snapshots have a leg already closed by t+h "
              f"(moved among them: {rows.filter(pc)['moved'].mean() if pc.any() else float('nan'):.1%}) -- "
              f"carry-forward replays of contracts whose close_time the per-month build never saw")
        s = summarise(rows, "  ALL SCORED PAIRS (as the objective saw them). AUC for 'moved' -- 0.5 = no "
                            "information. 'age' is HIDDEN from the model; 'vol' and 'ttc' are what it saw.")
        summaries.append(s.with_columns(pl.lit(h).alias("h"), pl.lit("all_scored").alias("population")))
        live = rows.filter(~pl.col("past_close"))
        print(f"\n  LIVE PAIRS ONLY: {live.height:,d} pair-snapshots, frozen share {1 - live['moved'].mean():.1%}")
        s = summarise(live, "  LIVE PAIRS ONLY. Same columns.")
        summaries.append(s.with_columns(pl.lit(h).alias("h"), pl.lit("live_only").alias("population")))
    if summaries and args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        pl.concat(summaries).write_parquet(out)
        print(f"\nsaved summary to {out}")


# ---------------------------------------------------------------------------
# Self-test: planted cases with known answers
# ---------------------------------------------------------------------------

def _synthetic(T: int, schedule: Dict[int, int], seed: int = 0, closes: Optional[Dict[int, int]] = None):
    """Nodes trade every `schedule[n]` snapshots; between trades their
    features are replayed exactly (slot 8 still changes), as the real
    carry-forward does. `closes[n] = t` makes node n absent from t on."""
    rng = np.random.default_rng(seed)
    N = len(schedule)
    F = 10
    feats = np.zeros((T, N, F), dtype=np.float32)
    mask = np.ones((T, N), dtype=bool)
    for n, every in schedule.items():
        cur = rng.uniform(10, 90, F).astype(np.float32)
        for t in range(T):
            if t % every == 0:
                cur = rng.uniform(10, 90, F).astype(np.float32)
                cur[0] = round(float(rng.uniform(10, 90)))
            feats[t, n] = cur
            feats[t, n, 8] = 1000.0 - t          # time_to_close always refreshed
            feats[t, n, 9] = 0.0
        if closes and n in closes:
            mask[closes[n]:, n] = False
    return feats, mask


def self_test() -> None:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        failures += 0 if cond else 1

    # 1. Age recovery: node 0 trades every snapshot, node 1 every 4th.
    f, m = _synthetic(12, {0: 1, 1: 4})
    age = leg_age(f, m)
    check("age is 0 for a leg that trades every window", (age[:, 0] == 0).all(), str(age[:, 0]))
    check("age counts replayed windows 0,1,2,3,0,...", list(age[:8, 1]) == [0, 1, 2, 3, 0, 1, 2, 3],
          str(list(age[:8, 1])))
    check("refreshed time_to_close alone does not count as a trade", age[1, 1] == 1)

    # 2. Absent legs: age -1, and re-appearance counts as fresh.
    m2 = m.copy(); m2[5, 1] = False
    age2 = leg_age(f, m2)
    check("absent leg has age -1", age2[5, 1] == -1)
    check("re-appearing leg is fresh", age2[6, 1] == 0)

    # 3. Pair selection mirrors _ladder_terms: a leg absent at t+h drops the pair.
    f3, m3 = _synthetic(10, {0: 1, 1: 1, 2: 1}, closes={2: 5})
    e = np.array([[0, 0], [1, 2]])
    r = scored_pairs(f3, m3, [e] * 10, h=1)
    t_for_02 = r["t"][r["b"] == 2]
    check("pair with a leg closed at t+h is not scored", t_for_02.max() == 3, f"last t={t_for_02.max()}")
    check("present-at-t count includes the dropped pair", int(r["present_now"]) == 9 + 5)

    # 4. Moved uses MOVE_EPS on prices in dollars: a replayed pair never moves.
    f4, m4 = _synthetic(20, {0: 5, 1: 5})
    r4 = scored_pairs(f4, m4, [np.array([[0], [1]])] * 20, h=1)
    replay_rows = r4["age_min"][r4["t"] % 5 != 4]  # t+1 still inside the replay run
    check("frozen pairs (both legs replayed through t+1) never count as moved",
          not r4["moved"][r4["t"] % 5 != 4].any(), f"n={replay_rows.size}")

    # 5. Planted hazard: movers are exactly the fresh pairs -> AUC(age) ~ 1; null -> ~0.5.
    rng = np.random.default_rng(1)
    ages = rng.integers(0, 12, 20000)
    planted = rng.random(20000) < np.where(ages == 0, 0.8, 0.05)
    a_hi = auc(-ages, planted)
    # Analytic value: movers at age 0 outrank almost every frozen pair; movers
    # at ages 1-11 carry no information against frozen pairs at those ages.
    p0, q = 0.8 / 12, 0.05 * 11 / 12
    pos0, neg0 = p0 / (p0 + q), (0.2 / 12) / (0.2 / 12 + 0.95 * 11 / 12)
    expected = pos0 * ((1 - neg0) + 0.5 * neg0) + (1 - pos0) * 0.5 * (1 - neg0)
    check("planted age hazard is detected at its analytic AUC", abs(a_hi - expected) < 0.02,
          f"AUC={a_hi:.3f}, expected {expected:.3f}")
    steep = rng.random(20000) < np.exp(-0.7 * ages)
    check("a hazard decaying with age reads far above 0.5", auc(-ages, steep) > 0.85,
          f"AUC={auc(-ages, steep):.3f}")
    null = rng.random(20000) < 0.2
    a_null = auc(-ages, null)
    check("no hazard reads as ~0.5", abs(a_null - 0.5) < 0.02, f"AUC={a_null:.3f}")
    check("constant score reads as exactly 0.5", abs(auc(np.zeros(1000), rng.random(1000) < 0.3) - 0.5) < 1e-9)

    # 6. Mutation: if replay detection looked at slot 8 too, every window would read fresh.
    state_with_ttc = f[:, :, :9]
    changed = np.any(state_with_ttc[1:] != state_with_ttc[:-1], axis=2)
    check("mutation caught: including slot 8 would mark replays as fresh", changed[:, 1].all())

    # 7. Past-close flag: present in a window starting at/after close.
    from datetime import datetime as _dt
    stamps = [_dt(2025, 7, 1, 2 * i) for i in range(6)]
    pmask = np.ones((6, 2), dtype=bool)
    flag = past_close(stamps, [_dt(2025, 7, 1, 5), None], pmask)
    check("leg is past close from the first window starting at/after close", list(flag[:, 0]) == [False, False, False, True, True, True],
          str(list(flag[:, 0])))
    check("unknown close_time is never flagged", not flag[:, 1].any())
    check("neighbouring months span year ends", _neighbours(["2025-01"]) == ["2024-12", "2025-01", "2025-02"])

    check("lifetime classes", life_class(1.0).startswith("hourly") and life_class(24.0).startswith("daily")
          and life_class(100.0).startswith("longer") and life_class(None) == "unknown")

    print(f"\nself-test: {'all passed' if failures == 0 else f'{failures} FAILED'}")
    if failures:
        raise SystemExit(1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1] if __doc__ else None)
    ap.add_argument("--self-test", action="store_true", help="run planted cases and exit")
    ap.add_argument("--months", nargs="+", default=["2025-05", "2025-06", "2025-07", "2025-08"])
    ap.add_argument("--horizons", type=int, nargs="+", default=[1],
                    help="in snapshots; the grid is 2h, so h=1 is 2h and h=12 is 24h")
    ap.add_argument("--cache", default="cache")
    ap.add_argument("--allow-test", action="store_true")
    ap.add_argument("--out", default="results/ladder/ladder_timing_check.parquet")
    args = ap.parse_args()
    if args.self_test:
        self_test()
        return
    run(args)


if __name__ == "__main__":
    main()
