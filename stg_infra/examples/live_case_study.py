"""
Case study 3 (exploratory, 2026-10-27): the live test's bad weather day, 25 October 2026.

Between ledger entries 20261025T11 and 20261026T12, G2's settled P&L on the 23 series fell by about $78. This script
reads the hash-chained ledger entries (the public backup, github.com/curiousfun88/event-pred-live) and reports, for the
events that settled in that window, each arm's realised P&L (primary window, pessimistic fills, all fills since the
live start), and G2's fills per leg on the worst events. Nothing is recomputed: the figures are the ledger's own.

    python stg_infra/examples/live_case_study.py --self-test
    python stg_infra/examples/live_case_study.py --entries <clone>/runs/live/paper/ledger/entries

Writes results/live/case_study_20261025.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "stg_infra"))

WINDOW = ("20261025T11", "20261026T12")
ARMS = {"g2": "G2", "rnd2": "Random at G2's share", "cand": "Quote everything", "lin2": "Linear"}
OUT = _REPO / "results/live/case_study_20261025.json"
N_DETAIL = 3


def series(event: str) -> str:
    return event.split("-")[0]


def settled_in_window(entries, universe, window=WINDOW):
    """{event: {arm: realised USD}} for events settled in ledger entries within `window` (inclusive)."""
    out = {}
    for e in entries:
        if not (window[0] <= e["H"] <= window[1]):
            continue
        for s in e.get("settlements", []):
            if series(s["event"]) in universe:
                r = s["realised_usd"].get("primary", {})
                out[s["event"]] = {a: float(r.get(a, 0.0)) for a in ARMS}
    return out


def legs(entries, event, arm="g2"):
    """G2's fills on one event across all entries, by (ticker, side): contracts and contract-weighted mean price (c)."""
    acc = defaultdict(lambda: [0, 0])
    for e in entries:
        for f in e["new_fills"]["primary"].get(arm, []):
            if f[0] == event:
                a = acc[(f[1], "buy YES" if f[2] == 1 else "sell YES")]
                a[0] += f[4]; a[1] += f[3] * f[4]
    return [{"ticker": k[0], "side": k[1], "contracts": v[0], "mean_price_c": round(v[1] / v[0], 1)} for k, v in sorted(acc.items())]


def run(entries_dir: Path):
    from fetch_kalshi_api_months import SERIES_A13
    entries = [json.loads(p.read_text()) for p in sorted(entries_dir.glob("*.json"))]
    ev = settled_in_window(entries, set(SERIES_A13))
    tot = {a: round(sum(v[a] for v in ev.values()), 2) for a in ARMS}
    worst = sorted(ev, key=lambda k: ev[k]["g2"])[:N_DETAIL]
    out = {"note": "exploratory; realised P&L from the ledger's settlement records, primary window, all fills since the live start",
           "window": WINDOW, "events": len(ev), "totals_usd": tot,
           "by_event": {k: {a: round(v[a], 2) for a in ARMS} for k, v in sorted(ev.items(), key=lambda kv: kv[1]["g2"])},
           "g2_legs_worst": {k: legs(entries, k) for k in worst},
           "last_entry": entries[-1]["H"] if entries else None}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1))
    print(json.dumps({"totals_usd": tot, "worst": {k: out["by_event"][k] for k in worst}}, indent=1))
    print("->", OUT)


def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    fill = lambda ev, tk, side, px, q: [ev, tk, side, px, q, 0.0, px * q, 0]
    entries = [
        {"H": "20261024T10", "settlements": [{"event": "KXHIGHNY-26OCT24", "realised_usd": {"primary": {"g2": 9.0}}}],
         "new_fills": {"primary": {"g2": [fill("KXHIGHAUS-26OCT25", "KXHIGHAUS-26OCT25-B83.5", 1, 60, 10)]}}},
        {"H": "20261025T15", "settlements": [], "new_fills": {"primary": {"g2": [fill("KXHIGHAUS-26OCT25", "KXHIGHAUS-26OCT25-B83.5", 1, 64, 30),
                                                                                  fill("KXHIGHAUS-26OCT25", "KXHIGHAUS-26OCT25-B83.5", -1, 29, 5)]}}},
        {"H": "20261026T10", "settlements": [
            {"event": "KXHIGHAUS-26OCT25", "realised_usd": {"primary": {"g2": -21.0, "rnd2": -14.0, "cand": -7.0}}},
            {"event": "KXOTHER-26OCT25", "realised_usd": {"primary": {"g2": -99.0}}}], "new_fills": {"primary": {}}},
        {"H": "20261026T13", "settlements": [{"event": "KXHIGHPHIL-26OCT25", "realised_usd": {"primary": {"g2": -5.0}}}],
         "new_fills": {"primary": {}}}]
    ev = settled_in_window(entries, {"KXHIGHAUS", "KXHIGHNY", "KXHIGHPHIL"})
    check("only settlements inside the window, only universe series", list(ev) == ["KXHIGHAUS-26OCT25"])
    check("missing arms count as zero", ev["KXHIGHAUS-26OCT25"] == {"g2": -21.0, "rnd2": -14.0, "cand": -7.0, "lin2": 0.0})
    L = legs(entries, "KXHIGHAUS-26OCT25")
    check("fills across entries pooled by leg and side, contract-weighted price",
          L == [{"ticker": "KXHIGHAUS-26OCT25-B83.5", "side": "buy YES", "contracts": 40, "mean_price_c": 63.0},
                {"ticker": "KXHIGHAUS-26OCT25-B83.5", "side": "sell YES", "contracts": 5, "mean_price_c": 29.0}])
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--entries", type=Path)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.entries)


if __name__ == "__main__":
    main()
