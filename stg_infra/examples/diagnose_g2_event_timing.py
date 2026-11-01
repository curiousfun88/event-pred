"""
diagnose_g2_event_timing.py

DIAGNOSTIC (exploratory, validation window only): where in a market's life does G2-W3 make
and lose money? Fills are binned by the hours between the quoting hour H and the market's
SCHEDULED event time T_ref = Kalshi `expected_expiration_time` (known when the market is
listed; for soccer game markets about 3h after kick-off, calibrated below from the tape).

Question: are G2-W3's losses concentrated close to scheduled information (kick-off, in-play,
race start, index close)? If so, a pre-declared "do not quote within k hours of T_ref" gate
is a candidate NEW arm (pre-registration §10). Any k read off this window is chosen on
validation, so it may only be tested forward; it is never a result in itself.

Fills, candidates and scores are produced exactly as `retrain_g2.py validate` does for
G2-W3 (validation 2026-09-07..10-04, the 23 A13 series). The script first checks that the
non-weather pessimistic return reproduces amendment L1's +6.73%.

USAGE (from repo root, memory-capped):
    python stg_infra/examples/diagnose_g2_event_timing.py --self-test
    python stg_infra/examples/diagnose_g2_event_timing.py
"""
from __future__ import annotations

import argparse
import datetime as dt
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

H_NS = 3_600_000_000_000
WEATHER = ("KXHIGH", "KXLOW")
# hours from quoting hour H to T_ref; a fill at H rests over [H, H+1h)
BINS = [(-np.inf, 0), (0, 2), (2, 3), (3, 4), (4, 6), (6, 12), (12, 24), (24, 72), (72, np.inf)]
GATES_H = [2, 3, 4, 6, 12]


def iso_ns(s: str | None) -> int | None:
    if not s:
        return None
    return int(dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1e9)


def hours_to_ref(H: int, ref_ns: int | None) -> float:
    return np.nan if ref_ns is None else (ref_ns - H) / H_NS


def bin_label(lo, hi):
    a = "-inf" if lo == -np.inf else f"{lo:g}"
    b = "inf" if hi == np.inf else f"{hi:g}"
    return f"[{a},{b})h"


def bin_of(d: float):
    if np.isnan(d):
        return None
    for lo, hi in BINS:
        if lo <= d < hi:
            return (lo, hi)
    return None


def group_of(series: str) -> str:
    if series.startswith(WEATHER):
        return "weather"
    return "soccer game" if series.endswith("GAME") else "other non-weather"


# ---------------------------------------------------------------- data

def ref_times():
    """ticker -> T_ref (ns) from the cached market metadata of the validation window."""
    import retrain_g2 as rg
    import smoke_test_2026 as st
    from fetch_kalshi_api_months import SERIES_A13
    start = int(dt.datetime.fromisoformat(rg.VAL[0]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    end = int(dt.datetime.fromisoformat(rg.VAL[1]).replace(tzinfo=dt.timezone.utc).timestamp()) * 10**9
    out = {}
    for x in SERIES_A13:
        for m, _, _ in pickle.loads((st.CACHE / f"{x}_{start}_{end}.pkl").read_bytes()):
            out[m["ticker"]] = iso_ns(m.get("expected_expiration_time"))
    return out


def scores_g2_w3(legs, events, charged, start, end, months):
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    lookup = mp.category_lookup()
    cand = []
    s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, months, record=cand)
    rows, keys = [], []
    for ev, tk, H, sd, pr, b, a in cand:
        if not (start <= int(H) < end):
            continue
        r = rg.features("G2", legs, events, charged, lookup, ev, tk, int(H), int(sd), int(pr))
        if r is not None:
            rows.append(r)
            keys.append((tk, int(H), int(sd)))
    blob = pickle.loads(rg.model_path("W3", "G2").read_bytes())
    pred = blob["model"].predict(rg.matrix("G2", rows, blob["cats"]))
    return dict(zip(keys, pred))


# ---------------------------------------------------------------- report

def line(r):
    return (f"fills {r['fills']:>5,}  events {r['events']:>4}  net ${r['net_c'] / 100:+8.2f}  "
            f"ret {r['ret']:+6.2f}% CI [{r['lo']:+6.2f}, {r['hi']:+6.2f}]  markout {r['markout_c_per_contract']:+.2f}c")


def by_bin(fills, ref, summarise, title):
    print(f"  {title}")
    for lo, hi in BINS:
        sub = [f for f in fills if bin_of(hours_to_ref(int(f[9]), ref.get(f[1]))) == (lo, hi)]
        if sub:
            print(f"    {bin_label(lo, hi):<12} {line(summarise(sub))}")
    miss = [f for f in fills if np.isnan(hours_to_ref(int(f[9]), ref.get(f[1])))]
    if miss:
        print(f"    {'no T_ref':<12} {line(summarise(miss))}")


def soccer_calibration(legs, events, ref):
    """Share of soccer-game trade contracts by hour relative to T_ref (where in-play sits)."""
    tot = {}
    for ev, tks in events.items():
        if not legs[tks[0]]["series"].endswith("GAME"):
            continue
        for tk in tks:
            r = ref.get(tk)
            if r is None:
                continue
            L = legs[tk]
            h = np.floor((np.asarray(L["tt"], float) - r) / H_NS).astype(int)
            for k, c in zip(h, np.asarray(L["tc"], float)):
                if -8 <= k <= 1:
                    tot[k] = tot.get(k, 0.0) + c
    z = sum(tot.values()) or 1.0
    print("  soccer games: share of traded contracts in the 8h before T_ref (hour k = [T_ref+k, T_ref+k+1))")
    for k in sorted(tot):
        print(f"    {k:+d}h  {100 * tot[k] / z:5.1f}%")


def run():
    import retrain_g2 as rg
    import simulate_maker as s
    legs, events, charged, start, end = rg.val_data()
    months = ["2026-09", "2026-10"]
    win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
    nonw = lambda fl: [f for f in fl if not legs[f[1]]["series"].startswith(WEATHER)]
    ref = ref_times()
    have = sum(ref.get(t) is not None for t in legs)
    print(f"VALIDATION {rg.VAL[0]}..{rg.VAL[1]}  legs {len(legs):,}  with T_ref {have:,}")
    soccer_calibration(legs, events, ref)

    pol = scores_g2_w3(legs, events, charged, start, end, months)
    cfg = rg.sim_cfg("G2", policy="x", policy_t=1.0)
    G = {m: win(s.simulate(cfg, m, legs, events, charged, months, policy_scores=pol)) for m in ("pess", "strict")}
    ALL = win(s.simulate(s.Config(**__import__("maker_policy").BROAD), "pess", legs, events, charged, months))

    r = s.summarise(nonw(G["pess"]))
    print(f"\nREPRODUCTION CHECK (amendment L1: non-weather +6.73%, CI +2.4..+11.4, 1,725 fills)\n"
          f"  G2-W3 non-weather pess  {line(r)}")
    ok = r["fills"] == 1725 and abs(r["ret"] - 6.73) < 0.01
    print(f"  {'REPRODUCED' if ok else 'DOES NOT REPRODUCE -- read everything below with that in mind'}")

    for grp in ("soccer game", "other non-weather"):
        sel = lambda fl: [f for f in fl if group_of(legs[f[1]]["series"]) == grp]
        print(f"\n== {grp.upper()}  (hours from quoting hour to T_ref)")
        print(f"  total G2-W3 pess    {line(s.summarise(sel(G['pess'])))}")
        by_bin(sel(G["pess"]), ref, s.summarise, "G2-W3, pessimistic fills")
        by_bin(sel(G["strict"]), ref, s.summarise, "G2-W3, strict fills")
        by_bin(sel(ALL), ref, s.summarise, "quote everything, pessimistic fills")

    print("\n== GATES, re-simulated (non-weather; G2-W3 scores, but no quote while T_ref - H < k hours)")
    print("   chosen-on-validation: descriptive only; a gate can only be tested forward as a new arm")
    for k in GATES_H:
        gp = {key: (v if hours_to_ref(key[1], ref.get(key[0])) >= k or np.isnan(hours_to_ref(key[1], ref.get(key[0])))
                    else -np.inf) for key, v in pol.items()}
        for m in ("pess", "strict"):
            fl = nonw(win(s.simulate(cfg, m, legs, events, charged, months, policy_scores=gp)))
            print(f"  k={k:>2}h [{m:<6}] {line(s.summarise(fl))}")
    for m in ("pess", "strict"):
        print(f"  no gate [{m:<6}] {line(s.summarise(nonw(G[m])))}")


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
        ok &= bool(c)

    t = iso_ns("2026-09-20T18:30:00Z")
    check("iso_ns parses Z suffix", t == int(dt.datetime(2026, 9, 20, 18, 30, tzinfo=dt.timezone.utc).timestamp() * 1e9))
    check("iso_ns(None) is None", iso_ns(None) is None)
    H = t - 3 * H_NS
    check("3h before T_ref -> 3.0", hours_to_ref(H, t) == 3.0)
    check("3h before falls in [3,4)", bin_of(3.0) == (3, 4))
    check("2.5h falls in [2,3)", bin_of(2.5) == (2, 3))
    check("after T_ref falls in [-inf,0)", bin_of(-0.5) == (-np.inf, 0))
    check("100h falls in [72,inf)", bin_of(100.0) == (72, np.inf))
    check("missing T_ref -> nan, no bin", np.isnan(hours_to_ref(H, None)) and bin_of(np.nan) is None)
    check("bins partition the line", all(BINS[i][1] == BINS[i + 1][0] for i in range(len(BINS) - 1)))
    check("weather group", group_of("KXHIGHNY") == "weather" and group_of("KXLOWTCHI") == "weather")
    check("soccer group", group_of("KXEPLGAME") == "soccer game")
    check("other group", group_of("KXINX") == "other non-weather")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run()


if __name__ == "__main__":
    main()
