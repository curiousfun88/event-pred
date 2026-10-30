"""
live_equity_curve.py

Cumulative net P&L by quoting day (UTC) at a cut, main result, pessimistic fills, primary order window: G2, G2
two-level, random quoting at G2's share and quoting everything. Descriptive; the report's live P&L figure (Chapter 6).
Fills, settlement and the main-result filters are the cut report's own, as in live_day_breakdown.py. Each arm's total
is checked against the cut report's json before anything is drawn.

USAGE (from repo root; LIVE_DIR = the copy of runs/live the cut report was run on):
    python stg_infra/examples/live_equity_curve.py --self-test
    LIVE_DIR=<copy> python stg_infra/examples/live_equity_curve.py --cut 2026-10-28T00 --settle-by 2026-10-30T00 \
        --check-json results/live/cut_interim.json --fig-out ../fyp-report/figures \
        | tee logs/v2_forecast/live_equity_curve_interim.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pickle
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(_THIS))

from live_day_breakdown import by_day  # noqa: E402

TEXT_W = 6.27                                      # A4 with 1in margins, inches
MAIN = "train23 (L18 main result, hours from 2026-10-16 17:00 UTC)"
ARMS = {"g2": "G2", "g2p": "G2 two-level", "rnd2": "Random at G2's share", "cand": "Quote everything"}


def cumulative(days_by_arm: dict) -> tuple[list, dict]:
    """(sorted days, {arm: cumulative net in dollars per day}) over the union of every arm's quoting days."""
    days = sorted(set().union(*days_by_arm.values()))
    out = {}
    for a, d in days_by_arm.items():
        run, c = 0.0, []
        for k in days:
            run += d.get(k, [0.0, 0.0])[0]
            c.append(run / 100)
        out[a] = c
    return days, out


def figure(days, cum, fig_out: Path):
    import matplotlib as mpl
    mpl.use("Agg")
    import matplotlib.pyplot as plt
    mpl.rcParams.update({"font.family": "serif", "font.serif": ["Nimbus Roman", "Times New Roman", "STIXGeneral", "DejaVu Serif"],
                         "mathtext.fontset": "stix", "font.size": 9, "axes.labelsize": 9, "legend.fontsize": 8,
                         "xtick.labelsize": 8, "ytick.labelsize": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "pdf.fonttype": 42})
    style = {"g2": dict(color="black", lw=1.6), "g2p": dict(color="#eb6834", lw=1.2),
             "rnd2": dict(color="#3182bd", lw=1.0), "cand": dict(color="#636363", lw=1.0, ls="--")}
    x = [dt.datetime.fromisoformat(d) for d in days]
    fig, ax = plt.subplots(figsize=(TEXT_W, 2.6))
    ax.axhline(0, color="grey", lw=0.6)
    for a, lab in ARMS.items():
        ax.plot(x, cum[a], marker="o", ms=2.5, label=lab, **style[a])
        v = cum[a][-1]
        ax.annotate(f"{'+' if v >= 0 else '−'}\\${abs(v):,.0f}", (x[-1], v), xytext=(4, 0),
                    textcoords="offset points", va="center", fontsize=7.5)
    ax.set_ylabel("Cumulative net P&L (USD)")
    ax.set_xlim(x[0] - dt.timedelta(hours=12), x[-1] + dt.timedelta(days=1.2))
    import matplotlib.dates as mdates
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.legend(frameon=False, loc="lower left")
    fig.tight_layout()
    fig_out.mkdir(parents=True, exist_ok=True)
    p = fig_out / "fig_live_equity.pdf"
    fig.savefig(p)
    print("->", p)


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    a = {"2026-10-16": [100.0, 1000.0], "2026-10-18": [-50.0, 500.0]}
    b = {"2026-10-17": [30.0, 300.0]}
    days, c = cumulative({"a": a, "b": b})
    check("days are the union of every arm's days, sorted", days == ["2026-10-16", "2026-10-17", "2026-10-18"])
    check("an arm with no fills on a day carries its total forward (cents -> dollars)",
          c["a"] == [1.0, 1.0, 0.5] and c["b"] == [0.0, 0.3, 0.3])
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def run(cut, settle_by, check_json, fig_out):
    import cut_report as cr
    import paper_ledger as pl_
    m = pickle.loads((cr.LIVE / "paper" / "markets.pkl").read_bytes())
    res = {t: v.get("result") for t, v in m.items()}
    st = cr.settle_times(m)
    _, fills, _ = cr.read_ledger(cr.LEDGER)
    cr.apply_corrections(cr.LEDGER, fills)
    mf, cut_ns, sb = cr.ns_of(cr.MAIN_FROM), cr.ns_of(cut), cr.ns_of(settle_by)

    def done(arm):
        K = [k for k in fills[("primary", arm)] if cr.is_train23_key(k) and mf <= int(k[7]) < cut_ns
             and st.get(k[0]) is not None and st[k[0]] <= sb]
        return [pl_.as_fill(k, res.get(k[1])) for k in K]

    D = {a: by_day(done(a)) for a in ARMS}
    ref = json.loads(Path(check_json).read_text())["headline"]["primary"][MAIN]["arms"]
    for a in ARMS:
        got = round(sum(v[0] for v in D[a].values()) / 100, 2)
        print(f"check {a:<5} here ${got:+9.2f}   cut report ${ref[a]['net_usd']:+9.2f}")
        if abs(got - ref[a]["net_usd"]) > 0.01:
            raise SystemExit(f"{a} does not match the cut report; nothing drawn")
    days, cum = cumulative(D)
    print(f"\ncumulative net P&L (USD) by quoting day (UTC), cut {cut}, settled by {settle_by}")
    print(f"{'day':<12}" + "".join(f"{a:>12}" for a in ARMS))
    for i, d in enumerate(days):
        print(f"{d:<12}" + "".join(f"{cum[a][i]:>+12.2f}" for a in ARMS))
    figure(days, cum, fig_out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cut", default="2026-10-28T00")
    ap.add_argument("--settle-by", default="2026-10-30T00")
    ap.add_argument("--check-json", default="results/live/cut_interim.json")
    ap.add_argument("--fig-out", type=Path, default=Path("../fyp-report/figures"))
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.cut.replace("-", "").replace(":", ""), a.settle_by.replace("-", "").replace(":", ""), a.check_json, a.fig_out)


if __name__ == "__main__":
    main()
