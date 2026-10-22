"""
report_figures_ch4.py

Figures for Chapter 4 of the report (measuring apparent mispricing), written as PDFs into the report's figures/.

  fig_basket_sums.pdf   basket deviations d = sum - $1 (cents) at last print, mid, bid and ask, two-sided vs one-sided baskets
                        (quoted top of book, test month Sep 2025 of the Jul-Sep fetch; data from
                        diagnose_quote_candles.py --split test --save-baskets results/mece/quote_basket_sums_test.parquet)
  fig_overround.pdf     measured mean last-print deviation by number of legs, with the order-flow prediction
                        N x h(2p-1) (h = 2.8c, p = 0.687) stated before measuring
                        (data: results/mece/mece_spread_artefact_check.parquet, 4,891 basket-days)

Every figure reproduces its reported numbers first (gates below) and stops if they do not match.

USAGE (from repo root):
    python stg_infra/examples/report_figures_ch4.py --self-test
    python stg_infra/examples/report_figures_ch4.py --out ../fyp-report/figures
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
QUOTES = REPO / "results/mece/quote_basket_sums_test.parquet"
TRADES = REPO / "results/mece/mece_spread_artefact_check.parquet"
H_CENTS, ASK_SHARE = 2.8, 0.687                    # the prediction's inputs (spread-artefact-finding.md s.2)
PER_LEG = H_CENTS * (2 * ASK_SHARE - 1)            # 1.05c above mid per leg
TEXT_W = 6.27                                      # A4 with 1in margins, inches
MIN_N = 100                                        # basket sizes with fewer baskets are pooled as "7+"


def style():
    import matplotlib as mpl
    mpl.rcParams.update({"font.family": "serif", "font.serif": ["Nimbus Roman", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "font.size": 9, "axes.titlesize": 9, "axes.labelsize": 9,
                         "legend.fontsize": 8, "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.spines.top": False,
                         "axes.spines.right": False, "pdf.fonttype": 42})


def gate(name, got, want, tol):
    if abs(got - want) > tol:
        sys.exit(f"GATE FAILED {name}: got {got:.4f}, reported {want} (tolerance {tol})")
    print(f"  gate ok  {name}: {got:.4f} (reported {want})")


def size_groups(n_legs, dev, min_n=MIN_N, rng=None, reps=2000):
    """Per basket size: (label, mean N, n, mean dev, CI low, CI high, share above $1). Sizes with < min_n baskets
    are pooled as one group '7+' (each basket-day is one observation, so a plain bootstrap is the cluster bootstrap)."""
    rng = rng or np.random.default_rng(0)
    sizes = sorted(set(n_legs.tolist()))
    big = [s for s in sizes if (n_legs == s).sum() >= min_n]
    groups = [(str(s), n_legs == s) for s in big]
    rest = ~np.isin(n_legs, big)
    if rest.any():
        groups.append((f"{min(n_legs[rest])}+", rest))
    out = []
    for label, m in groups:
        d = dev[m]
        boots = rng.choice(d, size=(reps, len(d))).mean(axis=1)
        lo, hi = np.percentile(boots, [2.5, 97.5])
        out.append((label, float(n_legs[m].mean()), int(m.sum()), float(d.mean()), float(lo), float(hi), float((d > 0).mean())))
    return out


def fig_overround(out_dir: Path):
    import polars as pl
    import matplotlib.pyplot as plt
    d = pl.read_parquet(TRADES)
    dev = (d["sum_last"].to_numpy() - 100).astype(float)          # cents (sums are in cents)
    n = d["n_legs"].to_numpy()
    gate("trade baskets", len(dev), 4891, 0)
    gate("mean deviation (c)", dev.mean(), 5.25, 0.005)
    gate("share above $1", (dev > 0).mean(), 0.925, 0.0005)
    g = size_groups(n, dev)
    for label, mn, k, m, lo, hi, sh in g:
        print(f"  legs {label:>3}: n={k:5d}  measured {m:+6.2f}c [{lo:+.2f}, {hi:+.2f}]  predicted {mn * PER_LEG:+5.2f}c  above $1 {sh:.1%}")
    style()
    fig, ax = plt.subplots(figsize=(TEXT_W * 0.62, 2.6))
    xs = np.arange(len(g))
    ax.errorbar(xs, [x[3] for x in g], yerr=[[x[3] - x[4] for x in g], [x[5] - x[3] for x in g]], fmt="o", color="black",
                capsize=3, ms=4, label="measured mean, 95% CI")
    ax.scatter(xs, [x[1] * PER_LEG for x in g], marker="_", s=260, color="#c0392b", linewidths=2,
               label=r"predicted $N\,h\,(2p-1)$", zorder=3)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_xticks(xs, [f"{x[0]}\n(n={x[2]:,})" for x in g])
    ax.set_xlabel("legs per basket")
    ax.set_ylabel("basket sum $-$ \\$1 at last prints (cents)")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    p = out_dir / "fig_overround.pdf"
    fig.savefig(p)
    plt.close(fig)
    print(f"wrote {p}")
    return g


def fig_basket_sums(out_dir: Path):
    import polars as pl
    import matplotlib.pyplot as plt
    q = pl.read_parquet(QUOTES)
    gate("quote basket-snapshots", q.height, 7532, 0)
    gate("mean last-print sum", q["sum_last"].mean(), 1.0405, 0.00005)
    gate("mean mid sum", q["sum_mid"].mean(), 1.0185, 0.00005)
    two = q.filter(pl.col("two_sided"))
    gate("two-sided share", two.height / q.height, 0.69, 0.005)
    gate("two-sided mid gap (c)", 100 * (two["sum_mid"].mean() - 1), 0.34, 0.005)
    one = q.filter(~pl.col("two_sided"))
    gate("one-sided bid sum", one["sum_bid"].mean(), 0.8930, 0.00005)
    gate("one-sided ask sum", one["sum_ask"].mean(), 1.2107, 0.00005)
    gate("two-sided bid sum", two["sum_bid"].mean(), 0.9674, 0.00005)
    gate("two-sided ask sum", two["sum_ask"].mean(), 1.0393, 0.00005)
    style()
    fig, axes = plt.subplots(1, 2, figsize=(TEXT_W, 2.6), sharey=True)
    cols = (("sum_bid", "bid", "#2471a3"), ("sum_mid", "mid", "black"), ("sum_last", "last print", "#7f8c8d"),
            ("sum_ask", "ask", "#c0392b"))
    bins = np.arange(-30, 40 + 1e-9, 1.0)                # deviation d = sum - $1, cents (2026-10-23: was sums in $)
    for ax, (flag, title) in zip(axes, ((True, "every leg two-sided"), (False, "some leg one-sided"))):
        sub = q.filter(pl.col("two_sided") == flag)
        for col, lab, c in cols:
            raw = 100.0 * (sub[col].to_numpy() - 1.0)
            v = np.clip(raw, bins[0], bins[-1] - 1e-9)          # values beyond the axis land in the end bins
            w = np.full(len(v), 100.0 / len(v))
            ax.hist(v, bins=bins, weights=w, histtype="step", color=c, lw=1.4 if lab == "mid" else 1.0,
                    label=f"{lab} (mean " + f"{raw.mean():+.2f}".replace("-", "\u2212") + "\u00a2)")    # mean of the raw deviations, not the clipped ones
        ax.axvline(0.0, color="grey", lw=0.8, ls="--")
        ax.set_title(f"{title} (n={sub.height:,})")
        ax.set_xlabel("basket deviation $d$ (cents)")
        ax.legend(frameon=False, loc="upper right", fontsize=7)
    axes[0].set_ylabel("share of basket-snapshots (%)")
    fig.tight_layout()
    p = out_dir / "fig_basket_sums.pdf"
    fig.savefig(p)
    plt.close(fig)
    print(f"wrote {p}")


def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    check("per-leg prediction 2.8 x (2 x 0.687 - 1) = 1.05c", abs(PER_LEG - 1.0472) < 1e-3)
    check("six legs predict +6.3c (the stated prediction)", round(6 * PER_LEG, 1) == 6.3)
    n = np.array([3] * 200 + [6] * 150 + [20] * 3 + [41] * 2)
    dev = np.array([2.0] * 200 + [8.0] * 150 + [20.0] * 3 + [40.0] * 2)
    g = size_groups(n, dev, min_n=100)
    check("groups: sizes with >= 100 baskets kept, the rest pooled as '20+'", [x[0] for x in g] == ["3", "6", "20+"])
    check("group means and counts", [(x[2], x[3]) for x in g] == [(200, 2.0), (150, 8.0), (5, 28.0)])
    check("a constant group has a zero-width CI", g[0][4] == g[0][5] == 2.0)
    check("pooled group's mean N is the mean of its sizes", abs(g[2][1] - (3 * 20 + 2 * 41) / 5) < 1e-9)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default="../fyp-report/figures")
    ap.add_argument("--only", choices=["overround", "basket_sums"])
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.only in (None, "overround"):
        fig_overround(out)
    if a.only in (None, "basket_sums"):
        fig_basket_sums(out)


if __name__ == "__main__":
    main()
