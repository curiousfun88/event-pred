"""
Case study 1 (exploratory, 2026-10-27): G on the worst days for makers in its 2025 test (Aug--Nov 2025).

The days are chosen by the data, not by hand: the trading days on which quoting every candidate lost most (net, booked
on the day each fill was quoted, as cut_report.tradedate_series). On each, G is compared with quoting everything and
with random quoting at G's share (mean of the five A16 seeds), on the same candidates. Two days are then examined
event by event: the clearest day on which G stayed positive and the worst day on which G lost.

Inputs (no new data):
  G            runs/maker/cache/6563435c72a50713.fills.npz   (A12 test run, reproduces +3.55%, 34,086 fills)
  quote all    runs/maker/cache/b0b6c1550b3b8345.fills.npz   (net -$1,133.38, 110,867 fills)
  random s0-4  re-simulated here with A16's exact procedure; each seed must reproduce A16's fills and return
               (results/maker/a16_baselines_2025.json) or nothing is written. Saved to runs/maker/case_study/.

    python stg_infra/examples/case_study_2025.py --self-test
    python stg_infra/examples/case_study_2025.py --simulate-random     # heavy: run under systemd-run caps
    python stg_infra/examples/case_study_2025.py --report [--fig-out ../fyp-report/figures]

Writes results/maker/case_study_2025.json and figures/fig_case_study_2025.pdf.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve()
_REPO = _THIS.parents[2]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS.parent))

TEST = ["2025-08", "2025-09", "2025-10", "2025-11"]
CACHE = _REPO / "runs/maker/cache"
RUNS = {"G": CACHE / "6563435c72a50713.fills.npz", "Quote all": CACHE / "b0b6c1550b3b8345.fills.npz"}
RAND_DIR = _REPO / "runs/maker/case_study"
A16 = _REPO / "results/maker/a16_baselines_2025.json"
OUT = _REPO / "results/maker/case_study_2025.json"
SCORES = _REPO / "runs/maker/policy_G_scores_2025-08_2025-11.parquet"
N_WORST = 6
TEXT_W = 6.27
DAY_NS = 86_400 * 10**9


def load_fills(p: Path) -> dict:
    z = np.load(p, allow_pickle=True)
    return {k: z[k] for k in z.files}


def daily(F: dict) -> dict:
    """{date: (net_usd, capital_usd)} with each fill booked on the UTC day it was quoted."""
    out = defaultdict(lambda: [0.0, 0.0])
    for t, n, c in zip(F["hour_ns"], F["net_c"], F["capital_c"]):
        d = dt.datetime.fromtimestamp(int(t) // DAY_NS * 86_400, dt.timezone.utc).date()
        out[d][0] += n / 100
        out[d][1] += c / 100
    return {d: tuple(v) for d, v in out.items()}


def worst_days(base: dict, n: int) -> list:
    """The n days with the lowest net for the baseline, worst first."""
    return sorted(base, key=lambda d: base[d][0])[:n]


def by_event(F: dict, day) -> dict:
    """{event: [net_usd, capital_usd, fills, contracts]} for fills quoted on `day`."""
    out = defaultdict(lambda: [0.0, 0.0, 0, 0])
    for e, t, n, c, q in zip(F["event"], F["hour_ns"], F["net_c"], F["capital_c"], F["qty"]):
        if dt.datetime.fromtimestamp(int(t) // DAY_NS * 86_400, dt.timezone.utc).date() == day:
            a = out[str(e)]
            a[0] += n / 100; a[1] += c / 100; a[2] += 1; a[3] += int(q)
    return dict(out)


def legs_detail(F: dict, day, event: str) -> list:
    """Per (ticker, side): contracts, mean price (c), net (USD) for one event's fills quoted on `day`."""
    acc = defaultdict(lambda: [0, 0.0, 0.0])
    for e, tk, sd, pr, q, t, n in zip(F["event"], F["ticker"], F["side"], F["price"], F["qty"], F["hour_ns"], F["net_c"]):
        if str(e) == event and dt.datetime.fromtimestamp(int(t) // DAY_NS * 86_400, dt.timezone.utc).date() == day:
            a = acc[(str(tk), "buy YES" if sd == 1 else "sell YES")]
            a[0] += int(q); a[1] += int(pr) * int(q); a[2] += n / 100
    return [{"ticker": k[0], "side": k[1], "contracts": v[0], "mean_price_c": round(v[1] / v[0], 1), "net_usd": round(v[2], 2)}
            for k, v in sorted(acc.items())]


def pct(v):
    return 100 * v[0] / v[1] if v and v[1] else float("nan")


# ---------------------------------------------------------------- random seeds (A16 procedure)

def cmd_simulate_random():
    import polars as pl
    import maker_policy as mp
    import simulate_maker as s
    ref = json.loads(A16.read_text())["test"]
    sc = pl.read_parquet(SCORES)
    keys = list(zip(sc["ticker"].to_list(), [int(x) for x in sc["hour_ns"].to_list()], [int(x) for x in sc["side"].to_list()]))
    pg = sc["pred"].to_numpy()
    share = float(np.mean(pg > 1.0))
    print(f"{len(keys):,} candidates, G's share {share:.4f} (A16: {ref['G_share']:.4f})", flush=True)
    assert abs(share - ref["G_share"]) < 1e-12 and len(keys) == ref["candidates"], "candidate set differs from A16"
    legs, events, charged = s.load(TEST, "mece")
    cfg = s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0})
    RAND_DIR.mkdir(parents=True, exist_ok=True)
    for seed in range(5):
        post = np.where(np.random.default_rng(seed).random(len(keys)) < share, 2.0, -np.inf)
        F = s.simulate(cfg, "pess", legs, events, charged, TEST, policy_scores=dict(zip(keys, post)))
        r = s.summarise(F)
        want = ref[f"random_s{seed}"]
        ok = r["fills"] == want["fills"] and abs(r["ret"] - want["ret"]) < 1e-9
        print(json.dumps({"seed": seed, "fills": r["fills"], "ret": r["ret"], "A16": [want["fills"], want["ret"]], "reproduces": ok}), flush=True)
        if not ok:
            raise SystemExit(f"seed {seed} does not reproduce A16: nothing saved")
        cols = list(zip(*F))
        np.savez_compressed(RAND_DIR / f"random_s{seed}.fills.npz", event=np.array(cols[0], dtype=object),
                            ticker=np.array(cols[1], dtype=object), side=np.array(cols[2]), price=np.array(cols[3]),
                            qty=np.array(cols[4]), fee_c=np.array(cols[5]), net_c=np.array(cols[6]),
                            capital_c=np.array(cols[7]), markout_c=np.array(cols[8], dtype=float),
                            hour_ns=np.array(cols[9], dtype=np.int64))
    print("all five seeds reproduce A16; saved to", RAND_DIR)


# ---------------------------------------------------------------- report

def cmd_report(fig_out: Path):
    F = {k: load_fills(p) for k, p in RUNS.items()}
    rand = [load_fills(RAND_DIR / f"random_s{i}.fills.npz") for i in range(5)]
    D = {k: daily(v) for k, v in F.items()}
    Dr = [daily(r) for r in rand]
    days = worst_days(D["Quote all"], N_WORST)
    rows = []
    for d in days:
        rv = [Dr[i].get(d, (0.0, 0.0)) for i in range(5)]
        rows.append({"day": d.isoformat(), "quote_all": D["Quote all"][d], "random_mean": (float(np.mean([v[0] for v in rv])),
                     float(np.mean([v[1] for v in rv]))), "random_seeds_net": [v[0] for v in rv],
                     "G": D["G"].get(d, (0.0, 0.0))})
    g_pos = [r for r in rows if r["G"][0] > 0]
    g_neg = [r for r in rows if r["G"][0] <= 0]
    best = max(g_pos, key=lambda r: pct(r["G"]) - pct(r["quote_all"]))["day"] if g_pos else None
    worst = min(g_neg, key=lambda r: r["G"][0])["day"] if g_neg else None
    detail = {}
    for label, ds in (("success", best), ("failure", worst)):
        if ds is None:
            continue
        d = dt.date.fromisoformat(ds)
        qa, g = by_event(F["Quote all"], d), by_event(F["G"], d)
        top = sorted(qa, key=lambda e: qa[e][0])[:4]                     # where quoting everything lost most
        g_loss = sorted(g, key=lambda e: g[e][0])[:3]                    # G's own worst events that day
        detail[label] = {"day": ds,
                         "quote_all_worst_events": [{"event": e, "quote_all": qa[e], "G": g.get(e, [0.0, 0.0, 0, 0]),
                                                     "G_legs": legs_detail(F["G"], d, e)} for e in top],
                         "G_worst_events": [{"event": e, "G": g[e], "quote_all": qa.get(e), "G_legs": legs_detail(F["G"], d, e)}
                                            for e in g_loss]}
    out = {"note": "exploratory case study (not pre-registered); days chosen by quote-all's daily net", "worst_days": rows,
           "G_positive_on": len(g_pos), "of": len(rows), "success_day": best, "failure_day": worst, "detail": detail}
    OUT.write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps({"worst_days": [(r["day"], round(r["quote_all"][0], 2), round(r["random_mean"][0], 2), round(r["G"][0], 2))
                                     for r in rows], "success": best, "failure": worst}, indent=1))
    figure(D, Dr, days, best, worst, fig_out)


def figure(D, Dr, days, best, worst, fig_out: Path):
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt
    mpl.rcParams.update({"font.family": "serif", "font.serif": ["Nimbus Roman", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "font.size": 9, "axes.labelsize": 9, "legend.fontsize": 8,
                         "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})
    allday = sorted(set(D["G"]) | set(D["Quote all"]))
    cum = lambda dd: np.cumsum([dd.get(d, (0.0, 0.0))[0] for d in allday])
    rc = np.array([cum(r) for r in Dr])
    fig, ax = plt.subplots(figsize=(TEXT_W, 2.7))
    x = [dt.datetime.combine(d, dt.time()) for d in allday]
    for d in days:
        ax.axvspan(dt.datetime.combine(d, dt.time()), dt.datetime.combine(d, dt.time()) + dt.timedelta(days=1),
                   color="#d9d9d9", lw=0)
    ax.fill_between(x, rc.min(0), rc.max(0), color="#9ecae1", alpha=0.5, lw=0, label="Random at G's share (5 seeds, range)")
    ax.plot(x, rc.mean(0), color="#3182bd", lw=1.0, label="Random at G's share (mean)")
    ax.plot(x, cum(D["Quote all"]), color="#636363", lw=1.0, ls="--", label="Quote everything")
    ax.plot(x, cum(D["G"]), color="black", lw=1.6, label="G")
    for ds, lab in ((best, "a"), (worst, "b")):
        if ds:
            d = dt.date.fromisoformat(ds)
            ax.annotate(f"({lab})", (dt.datetime.combine(d, dt.time()) + dt.timedelta(hours=12), ax.get_ylim()[1]),
                        ha="center", va="top", fontsize=8)
    ax.axhline(0, color="grey", lw=0.6)
    ax.set_ylabel("Cumulative net P\\&L (USD)" if mpl.rcParams.get("text.usetex") else "Cumulative net P&L (USD)")
    ax.legend(frameon=False, loc="lower right", bbox_to_anchor=(1.0, 0.3))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig_out.mkdir(parents=True, exist_ok=True)
    p = fig_out / "fig_case_study_2025.pdf"
    fig.savefig(p)
    print("->", p)


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    t = lambda y, m, d, h=0: int(dt.datetime(y, m, d, h, tzinfo=dt.timezone.utc).timestamp()) * 10**9
    F = {"event": np.array(["E1", "E1", "E2", "E3"], dtype=object), "ticker": np.array(["E1-A", "E1-A", "E2-B", "E3-C"], dtype=object),
         "side": np.array([1, -1, 1, 1]), "price": np.array([60, 40, 30, 50]), "qty": np.array([10, 5, 2, 4]),
         "net_c": np.array([-600.0, 200.0, 140.0, -50.0]), "capital_c": np.array([600, 300, 60, 200]),
         "hour_ns": np.array([t(2025, 8, 6, 23), t(2025, 8, 6, 1), t(2025, 8, 7, 0), t(2025, 8, 8, 5)], dtype=np.int64)}
    d = daily(F)
    check("fills are booked on their quoting day (23:00 stays on that day)", set(d) == {dt.date(2025, 8, 6), dt.date(2025, 8, 7), dt.date(2025, 8, 8)})
    check("daily net and capital in USD", d[dt.date(2025, 8, 6)] == (-4.0, 9.0))
    check("worst days ranked by net, worst first", worst_days(d, 2) == [dt.date(2025, 8, 6), dt.date(2025, 8, 8)])
    e = by_event(F, dt.date(2025, 8, 6))
    check("per-event totals on a day (net, capital, fills, contracts)", e == {"E1": [-4.0, 9.0, 2, 15]})
    L = legs_detail(F, dt.date(2025, 8, 6), "E1")
    check("legs split by side with contract-weighted mean price",
          L == [{"ticker": "E1-A", "side": "buy YES", "contracts": 10, "mean_price_c": 60.0, "net_usd": -6.0},
                {"ticker": "E1-A", "side": "sell YES", "contracts": 5, "mean_price_c": 40.0, "net_usd": 2.0}])
    check("return of a day", abs(pct(d[dt.date(2025, 8, 7)]) - 233.333) < 1e-2)
    check("days with no fills are absent, not zero-capital", dt.date(2025, 8, 9) not in d)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--simulate-random", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--fig-out", default=str(_REPO.parent / "fyp-report/figures"))
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.simulate_random:
        cmd_simulate_random()
    if a.report:
        cmd_report(Path(a.fig_out))


if __name__ == "__main__":
    main()
