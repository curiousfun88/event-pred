"""Exploratory (development months only): per-category breakdown of the
whole-basket maker attempts written by explore_basket_maker.py.

Every attempt is labelled by what filled in (H, H+1h]:
  none    : no leg filled -> P&L 0
  partial : some legs filled -> naked (hold), complete (taker the rest at H+1h),
            or cond (complete only if the locked-in value at H+1h is >= 0)
  full    : every leg filled -> the $1 structure is complete as a maker
P&L is cents per 1-contract basket, net of maker and taker fees, settled on the
realised outcome (no filter on whether the listed legs were a true partition).

Break-even full-fill share: among attempts with >= 1 fill, the share of full
fills f* at which f* x mean(full) + (1 - f*) x mean(partial) = 0, holding each
label's mean fixed. Defined only when mean(full) > 0 > mean(partial).

CIs resample events (baskets) as clusters.

    .venv/bin/python stg_infra/examples/summarise_basket_explore.py \
        results/mece/basket_explore_2024-11_2025-07.npy
    .venv/bin/python stg_infra/examples/summarise_basket_explore.py --self-test
"""
import sys, argparse
from pathlib import Path
import numpy as np
import polars as pl

sys.path.insert(0, "stg_infra")
from diagnose_basket_composition import category_of  # noqa: E402

COLS = ["event", "month", "side", "n_legs", "liquid", "edge", "n_filled", "n_winners",
        "naked", "complete", "cond", "series", "can_complete", "lock"]
CAT_PATH = Path("results/data_audit/kalshi_series_categories.parquet")


def to_frame(rows, lookup) -> pl.DataFrame:
    df = pl.DataFrame([list(r) for r in rows], schema=COLS, orient="row", strict=False)
    df = df.with_columns(
        pl.col("series").map_elements(lambda s: category_of(s, lookup), return_dtype=pl.Utf8).alias("category"),
        pl.when(pl.col("n_filled") == 0).then(pl.lit("none"))
          .when(pl.col("n_filled") == pl.col("n_legs")).then(pl.lit("full"))
          .otherwise(pl.lit("partial")).alias("label"),
        pl.when(pl.col("side") < 0).then(pl.lit("sell")).otherwise(pl.lit("buy")).alias("side_name"))
    return df


def cluster_ci(values, clusters, n_boot=2000, seed=0):
    """95% CI of the mean, resampling clusters with replacement."""
    v = np.asarray(values, float)
    if len(v) == 0:
        return (np.nan, np.nan)
    _, inv = np.unique(np.asarray(clusters), return_inverse=True)
    k = inv.max() + 1
    s = np.bincount(inv, weights=v, minlength=k)
    c = np.bincount(inv, minlength=k).astype(float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, k, size=(n_boot, k))
    means = s[idx].sum(1) / c[idx].sum(1)
    return tuple(np.percentile(means, [2.5, 97.5]))


def break_even(full_mean, partial_mean):
    if not (full_mean > 0 > partial_mean):
        return np.nan
    return -partial_mean / (full_mean - partial_mean)


def summarise(df: pl.DataFrame, by):
    out = []
    for key, g in df.group_by(by, maintain_order=True):
        n = g.height
        filled = g.filter(pl.col("label") != "none")
        full = g.filter(pl.col("label") == "full")
        part = g.filter(pl.col("label") == "partial")
        row = dict(zip(by, key if isinstance(key, tuple) else (key,)))
        row.update(
            attempts=n, events=g["event"].n_unique(),
            none=(g["label"] == "none").mean(), partial=part.height / n, full=full.height / n,
            full_of_filled=full.height / filled.height if filled.height else np.nan,
            can_complete=part["can_complete"].mean() if part.height else np.nan,
            full_pnl=full["complete"].mean() if full.height else np.nan,
            partial_naked=part["naked"].mean() if part.height else np.nan,
            partial_complete=part["complete"].mean() if part.height else np.nan,
            partial_cond=part["cond"].mean() if part.height else np.nan)
        for m in ("naked", "complete", "cond"):
            row[m] = g[m].mean()
        lo, hi = cluster_ci(g["cond"].to_numpy(), g["event"].to_numpy())
        row["cond_lo"], row["cond_hi"] = lo, hi
        pc = part["cond"].mean() if part.height else np.nan
        row["breakeven_full"] = break_even(row["full_pnl"], pc) if full.height and part.height else np.nan
        out.append(row)
    return pl.DataFrame(out).sort("attempts", descending=True)


def show(t: pl.DataFrame, by, title):
    print(f"\n{title}")
    hdr = (f"  {'/'.join(by):<28}{'att':>7}{'ev':>6}{'none':>6}{'part':>6}{'full':>6}{'full|fill':>10}"
           f"{'full¢':>7}{'part¢':>7}{'naked¢':>8}{'compl¢':>8}{'cond¢':>7}  cond CI95        {'BE full':>8}")
    print(hdr)
    for r in t.iter_rows(named=True):
        name = "/".join(str(r[b]) for b in by)
        print(f"  {name[:27]:<28}{r['attempts']:>7,}{r['events']:>6,}{r['none']:>6.0%}{r['partial']:>6.0%}"
              f"{r['full']:>6.1%}{r['full_of_filled']:>10.1%}{r['full_pnl']:>7.1f}{r['partial_cond']:>7.1f}"
              f"{r['naked']:>8.2f}{r['complete']:>8.2f}{r['cond']:>7.2f}  [{r['cond_lo']:>6.2f},{r['cond_hi']:>6.2f}]"
              f"{r['breakeven_full']:>8.0%}")


def self_test():
    ok = True

    def check(msg, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {msg}")
    print("SELF-TEST (planted attempts)")
    rows = [
        # event, month, side, n_legs, liquid, edge, n_filled, n_winners, naked, complete, cond, series, can, lock
        ("E1", "2025-01", -1, 3, True, 2, 3, 1, 2.0, 2.0, 2.0, "KXHIGHNY", True, np.nan),     # full, weather
        ("E1", "2025-01", +1, 3, True, 1, 0, 1, 0.0, 0.0, 0.0, "KXHIGHNY", True, np.nan),     # none
        ("E2", "2025-01", -1, 2, True, 1, 1, 1, -30.0, -6.0, -6.0, "KXHIGHNY", True, -6.0),   # partial
        ("E3", "2025-02", -1, 2, False, 0, 1, 1, 10.0, -4.0, 10.0, "KXBTCD", False, np.nan),  # partial, crypto
    ]
    df = to_frame(rows, None)
    check("labels full/none/partial/partial", df["label"].to_list() == ["full", "none", "partial", "partial"])
    check("categories from the prefix fallback", df["category"].to_list() == ["weather"] * 3 + ["crypto"])
    t = summarise(df, ["category"])
    w = t.filter(pl.col("category") == "weather").row(0, named=True)
    check("weather: 3 attempts, 2 events", w["attempts"] == 3 and w["events"] == 2)
    check("weather: full share 1/3, full|fill 1/2", abs(w["full"] - 1 / 3) < 1e-9 and abs(w["full_of_filled"] - 0.5) < 1e-9)
    check("weather: cond mean (2+0-6)/3", abs(w["cond"] - (-4 / 3)) < 1e-9)
    check("break-even full share: 2f - 6(1-f) = 0 -> 0.75", abs(w["breakeven_full"] - 0.75) < 1e-9)
    check("break-even undefined when partial is not negative", np.isnan(break_even(2.0, 1.0)))
    lo, hi = cluster_ci([1, 1, 5, 5], ["a", "a", "b", "b"])
    check(f"cluster CI [{lo:.1f},{hi:.1f}] within [1,5] and brackets 3", 1 <= lo <= 3 <= hi <= 5)
    lo, hi = cluster_ci([2, 2, 2], ["a", "b", "c"])
    check("constant values -> degenerate CI at the value", lo == hi == 2)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("npy", nargs="?")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--min-attempts", type=int, default=200, help="categories below this are pooled as 'small'")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if not a.npy:
        ap.error("npy path required (or --self-test)")
    lookup = None
    if CAT_PATH.exists():
        c = pl.read_parquet(CAT_PATH)
        lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    rows = np.load(a.npy, allow_pickle=True)
    if rows.shape[1] < len(COLS):
        raise SystemExit(f"{a.npy} has {rows.shape[1]} columns; rerun explore_basket_maker.py (needs {len(COLS)})")
    df = to_frame(rows.tolist(), lookup)
    counts = df.group_by("category").len()
    small = set(counts.filter(pl.col("len") < a.min_attempts)["category"].to_list())
    df = df.with_columns(pl.when(pl.col("category").is_in(list(small))).then(pl.lit("small (<%d)" % a.min_attempts))
                         .otherwise(pl.col("category")).alias("category"))
    print(f"{a.npy}: {df.height:,} attempts, {df['event'].n_unique():,} events, months "
          f"{df['month'].min()}..{df['month'].max()} (development only)")
    print("P&L in cents per 1-contract basket, net of fees; cond CI resamples events.")
    print("full¢ = mean on full fills; part¢ = mean on partial fills under 'cond'; "
          "BE full = full share of filled attempts needed to break even")
    for sub, name in ((df, "ALL ATTEMPTS"),
                      (df.filter(pl.col("liquid") & (pl.col("edge") >= 0)),
                       "LIQUID (every leg traded in the last 3h) AND QUOTED EDGE >= 0")):
        print("\n" + "=" * 150 + f"\n{name}: {sub.height:,} attempts\n" + "=" * 150)
        show(summarise(sub, ["side_name"]), ["side_name"], "by side")
        show(summarise(sub, ["category", "side_name"]), ["category", "side_name"], "by category x side")
        show(summarise(sub, ["n_legs"]).sort("n_legs"), ["n_legs"], "by basket size")


if __name__ == "__main__":
    main()
