"""
shortcut_vs_simulator.py

Why the walk-forward's fill-level score (select_g2_window.py: quote-everything's simulated fills, kept where the
model predicts > 1c) differs from running the same model in the simulator (retrain_g2.py validate()). Exploratory;
no decision depends on it. Report: ch4-method.tex, "Fill-level score" paragraph.

For one window's frozen G2 model on the 2026-09-07..10-05 validation window, pessimistic fills, it splits the gap into
  extra   : contracts the simulator fills that the shortcut does not have,
  missing : shortcut contracts the simulator does not fill,
so that  simulator net = shortcut net + extra net - missing net  (checked to the cent), and describes each part:
same-side share and 1h markout of the extra contracts; leg and event room under the limits, for the model and for
quote-everything, at each missing quote.

USAGE (from repo root, laptop, memory-capped):
    python stg_infra/examples/shortcut_vs_simulator.py --self-test
    systemd-run --user --scope -p MemoryMax=5G .venv/bin/python stg_infra/examples/shortcut_vs_simulator.py \
        --window W3 | tee logs/v2_forecast/shortcut_vs_simulator_W3_sep2026.log
"""
from __future__ import annotations

import argparse
import pickle
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS.parent))
sys.path.insert(0, str(_THIS))

# fill tuple from simulate_maker.simulate: (ev, tk, side, price, contracts, fee, net, cap, markout, H)
EV, TK, SIDE, PRICE, QTY, FEE, NET, CAP, MK, H = range(10)
POS_LIMIT, EVENT_LIMIT = 50, 200


def key(f):
    """One quote: event, leg, hour, side."""
    return (f[EV], f[TK], int(f[H]), f[SIDE])


def positions_before(fills):
    """Per fill, the leg's signed position just before it (fills in simulator order: per event, by hour)."""
    pos, out = defaultdict(int), []
    for f in fills:
        out.append(pos[f[TK]])
        pos[f[TK]] += f[SIDE] * f[QTY]
    return out


def quote_room(fills):
    """{quote key: (leg room, event room)} on its side at the quote's first fill, under the simulator's limits."""
    st, lp, ep = {}, defaultdict(int), defaultdict(lambda: defaultdict(int))
    for f in fills:
        k = key(f)
        if k not in st:
            st[k] = (POS_LIMIT - f[SIDE] * lp[f[TK]], EVENT_LIMIT - sum(abs(v) for v in ep[f[EV]].values()))
        lp[f[TK]] += f[SIDE] * f[QTY]
        ep[f[EV]][f[TK]] += f[SIDE] * f[QTY]
    return st


def room_at(fills, ev, tk, hour, side):
    """(leg room, event room) on `side` from all of `fills` strictly before `hour` (a quote the run never filled)."""
    lp, ep = 0, defaultdict(int)
    for f in fills:
        if f[EV] == ev and int(f[H]) < hour:
            ep[f[TK]] += f[SIDE] * f[QTY]
            if f[TK] == tk:
                lp += f[SIDE] * f[QTY]
    return POS_LIMIT - side * lp, EVENT_LIMIT - sum(abs(v) for v in ep.values())


def decompose(short, sim):
    """Split sim against short by quote. Returns (extra, extra_pos, missing):
    extra     : sim fill pieces beyond the shortcut's contracts at that quote (net, fee, cap pro rata),
    extra_pos : the leg position before each extra piece, in the simulator,
    missing   : {quote key: (contracts, net, cap)} the shortcut has and sim does not (pro rata at the shortcut's rate)."""
    agg = defaultdict(lambda: [0, 0.0, 0.0])
    for f in short:
        a = agg[key(f)]
        a[0] += f[QTY]; a[1] += f[NET]; a[2] += f[CAP]
    rem = {k: v[0] for k, v in agg.items()}
    extra, extra_pos = [], []
    for f, p in zip(sim, positions_before(sim)):
        k = key(f)
        have = rem.get(k, 0)
        if have >= f[QTY]:
            rem[k] = have - f[QTY]
            continue
        x = f[QTY] - have
        rem[k] = 0
        r = x / f[QTY]
        extra.append((f[EV], f[TK], f[SIDE], f[PRICE], x, f[FEE] * r, f[NET] * r, f[CAP] * r, f[MK], f[H]))
        extra_pos.append(p)
    missing = {k: (n, agg[k][1] * n / agg[k][0], agg[k][2] * n / agg[k][0]) for k, n in rem.items() if n > 0}
    return extra, extra_pos, missing


def tot(fills, i):
    return float(sum(f[i] for f in fills))


def ret(net, cap):
    return 100 * net / cap if cap else float("nan")


def markout(fills):
    m = [f for f in fills if not np.isnan(f[MK])]
    q = sum(f[QTY] for f in m)
    return sum(f[MK] for f in m) / q if q else float("nan")


def run(window):
    import maker_policy as mp
    import retrain_g2 as rg
    import simulate_maker as s
    legs, events, charged, start, end = rg.val_data()
    events = rg.single_winner_events(legs, events)
    lookup = mp.category_lookup()
    months = ["2026-09", "2026-10"]
    inwin = lambda fl: [f for f in fl if start <= int(f[H]) < end]
    blob = pickle.loads(rg.model_path(window, "G2").read_bytes())

    # shortcut, as select_g2_window.september_fold()
    qa_all = s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months)
    rows, kept = [], []
    for f in inwin(qa_all):
        r = rg.features("G2", legs, events, charged, lookup, f[EV], f[TK], int(f[H]), int(f[SIDE]), int(f[PRICE]))
        if r is not None:
            rows.append(r); kept.append(f)
    pred = blob["model"].predict(rg.matrix("G2", rows, blob["cats"]))
    short = [f for f, p in zip(kept, pred) if p > 1.0]

    # simulator, as retrain_g2.validate()
    cand = []
    s.simulate(rg.sim_cfg("G2"), "pess", legs, events, charged, months, record=cand)
    crow, keys = [], []
    for ev, tk, hh, sd, pr, b, a in cand:
        if not (start <= int(hh) < end):
            continue
        r = rg.features("G2", legs, events, charged, lookup, ev, tk, int(hh), int(sd), int(pr))
        if r is not None:
            crow.append(r); keys.append((tk, int(hh), int(sd)))
    pol = dict(zip(keys, blob["model"].predict(rg.matrix("G2", crow, blob["cats"]))))
    sim_all = s.simulate(rg.sim_cfg("G2", policy="x", policy_t=1.0), "pess", legs, events, charged, months,
                         policy_scores=pol)
    sim = inwin(sim_all)

    # positions run from the start of the simulated months, so pre-window fills count towards the limits
    extra, extra_pos, missing = decompose(short, sim_all)
    extra = [(f, p) for f, p in zip(extra, extra_pos) if start <= int(f[H]) < end]
    extra, extra_pos = [f for f, _ in extra], [p for _, p in extra]
    missing = {k: v for k, v in missing.items() if start <= k[2] < end}

    ttc = lambda tk, hh: (legs[tk]["close"] - hh) / 3.6e12 if legs[tk]["close"] is not None else np.nan
    sn, sc, mn, mc = tot(short, NET), tot(short, CAP), sum(v[1] for v in missing.values()), sum(v[2] for v in missing.values())
    en, ec = tot(extra, NET), tot(extra, CAP)
    print(f"G2-{window}, validation window {start}..{end} ns, pessimistic fills")
    print(f"shortcut : {len(short):>6,} fills {tot(short, QTY):>7,.0f} contracts  net ${sn / 100:+9.2f}  ret {ret(sn, sc):+.2f}%"
          f"  {sn / tot(short, QTY):+.2f}c/contract")
    print(f"simulator: {len(sim):>6,} fills {tot(sim, QTY):>7,.0f} contracts  net ${tot(sim, NET) / 100:+9.2f}  "
          f"ret {ret(tot(sim, NET), tot(sim, CAP)):+.2f}%")
    mq = sum(v[0] for v in missing.values())
    print(f"extra    : {tot(extra, QTY):>7,.0f} contracts  net ${en / 100:+9.2f}  ret {ret(en, ec):+.2f}%  "
          f"{en / tot(extra, QTY):+.2f}c/contract")
    print(f"missing  : {mq:>7,} contracts  net ${mn / 100:+9.2f}  ret {ret(mn, mc):+.2f}%  {mn / mq:+.2f}c/contract  "
          f"{len({k[0] for k in missing})} events")
    print(f"check    : shortcut + extra - missing = ${(sn + en - mn) / 100:+.2f}  vs simulator ${tot(sim, NET) / 100:+.2f}")
    print(f"return with extra only {ret(sn + en, sc + ec):+.2f}%, without missing only {ret(sn - mn, sc - mc):+.2f}%")

    q = np.array([f[QTY] for f in extra]); sd = np.array([f[SIDE] for f in extra]); p = np.array(extra_pos)
    same = (np.sign(p) == sd) & (p != 0)
    print(f"\nextra: {q[same].sum() / q.sum():.0%} of contracts add to a same-side leg position; "
          f"1h markout {markout(extra):+.2f}c (shortcut {markout(short):+.2f}c); "
          f"hours to close median {np.nanmedian([ttc(f[TK], int(f[H])) for f in extra]):.1f} "
          f"(shortcut {np.nanmedian([ttc(f[TK], int(f[H])) for f in short]):.1f})")

    rq = quote_room(qa_all)
    rs = quote_room(sim_all)
    leg_less = ev_less = 0
    gl, ql, ge, qe = [], [], [], []
    for k, (n, _, _) in missing.items():
        g = rs.get(k) or room_at(sim_all, *k)
        qa = rq[k]
        leg_less += n * (g[0] < qa[0]); ev_less += n * (g[1] < qa[1])
        gl.append(g[0]); ql.append(qa[0]); ge.append(g[1]); qe.append(qa[1])
    print(f"missing: the model had less leg room than quote-everything for {leg_less / mq:.0%} of contracts, "
          f"less event room for {ev_less / mq:.0%}; median leg room model {np.median(gl):.0f} vs quote-everything "
          f"{np.median(ql):.0f}, event room {np.median(ge):.0f} vs {np.median(qe):.0f}; hours to close median "
          f"{np.nanmedian([ttc(k[1], k[2]) for k in missing]):.1f}")


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    F = lambda ev, tk, side, q, net, hh, cap=None, mk=0.0: (ev, tk, side, 50, q, 0.0, net, cap if cap is not None else 50 * q, mk, hh)
    # quote-everything fills both sides of leg a (offsetting); the model fills only buys and reaches the cap
    short = [F("e", "a", +1, 30, 30.0, 1), F("e", "a", +1, 20, 200.0, 3)]      # hour 3: very profitable
    sim = [F("e", "a", +1, 30, 30.0, 1), F("e", "a", +1, 20, -40.0, 2)]        # hour 2: extra, same side, loses;
                                                                               # hour 3: blocked, leg at the cap
    extra, pos, missing = decompose(short, sim)
    check("extra: the hour-2 fill the shortcut does not have", [(f[H], f[QTY], f[NET]) for f in extra] == [(2, 20, -40.0)])
    check("extra adds to a same-side position of 30", pos == [30])
    check("missing: the hour-3 quote, 20 contracts, +200c", missing == {("e", "a", 3, +1): (20, 200.0, 1000.0)})
    check("reconciles: shortcut + extra - missing = simulator",
          tot(short, NET) + tot(extra, NET) - sum(v[1] for v in missing.values()) == tot(sim, NET))
    # a partly filled quote: shortcut 10 contracts, simulator 4 -> 6 missing pro rata; simulator 15 -> 5 extra pro rata
    m = decompose([F("e", "b", -1, 10, 100.0, 5)], [F("e", "b", -1, 4, 40.0, 5)])[2]
    check("partial: 6 of 10 contracts missing, net pro rata 60c", m == {("e", "b", 5, -1): (6, 60.0, 300.0)})
    x = decompose([F("e", "b", -1, 10, 100.0, 5)], [F("e", "b", -1, 15, 150.0, 5)])[0]
    check("partial: 5 of 15 contracts extra, net pro rata 50c", len(x) == 1 and x[0][QTY] == 5 and x[0][NET] == 50.0)
    check("split fills of one quote are summed before matching",
          decompose([F("e", "c", +1, 3, 3.0, 7), F("e", "c", +1, 2, 2.0, 7)], [F("e", "c", +1, 5, 5.0, 7)]) == ([], [], {}))
    # room: two-sided fills offset, one-sided fills use the leg's room
    qa = [F("e", "a", +1, 30, 0, 1), F("e", "a", -1, 20, 0, 2), F("e", "a", +1, 5, 0, 3)]
    g = [F("e", "a", +1, 30, 0, 1), F("e", "a", +1, 20, 0, 2)]
    check("quote-everything's room at hour 3: leg 40, event 190 (net +10)", quote_room(qa)[("e", "a", 3, +1)] == (40, 190))
    check("the model's leg room at hour 3 is 0 (net +50)", room_at(g, "e", "a", 3, +1) == (0, 150))
    check("positions_before replays per leg in order", positions_before(qa) == [0, 30, 10])
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--window", default="W3", choices=["W1", "W2", "W3"])
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    run(a.window)


if __name__ == "__main__":
    main()
