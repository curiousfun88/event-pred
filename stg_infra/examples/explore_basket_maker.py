"""Exploratory (development months only): can a whole-basket maker be positive
WITHOUT look-ahead? Every decision uses information at H (quote) or H+1h
(completion); every attempt is counted, partial fills included.

Per basket-hour attempt, 1 contract per leg:
  sell side: ask at a-1 (a if spread < 3) on EVERY leg; fills from taker buys in (H, H+1h]
  buy side : bid at b+1 (b if spread < 3) on EVERY leg; fills from taker sells
Partial-fill rules at H+1h:
  naked    : keep what filled, hold to settlement
  complete : trade the unfilled legs as a taker at the H+1h quote (bid for sell side,
             ask for buy side), paying the taker fee -> exact $1 structure
  cond     : complete only if the locked-in result is >= 0, else stay naked
Filters at H: basket size, every leg traded in (H-3h, H], quoted edge vs $1 >= margin.
"""
import sys, math, json
import numpy as np
sys.path.insert(0, "stg_infra")
import simulate_maker as s

H = s.H_NS


def taker_fee_c(p_c, n=1):
    p = p_c / 100.0
    return float(math.ceil(round(0.07 * n * p * (1 - p) * 100, 6)))


def attempts_for_month(month):
    legs, events, charged = s.load([month], "mece")
    rows = []
    for ev, tks in events.items():
        if len(tks) < 2:
            continue
        # NO filter on outcomes: a basket where no listed leg (or 2+ legs) resolves YES is
        # kept -- a real strategy cannot know at H that the listed set is exhaustive.
        hours = sorted({int(e) for t in tks for e in legs[t]["e"]})
        for Hh in hours:
            if s.month_of(Hh) != month:
                continue
            q, ok = {}, True
            for t in tks:
                L = legs[t]
                j = np.searchsorted(L["e"], Hh)
                if j >= len(L["e"]) or L["e"][j] != Hh or (L["close"] is not None and Hh >= L["close"]):
                    ok = False; break
                b, a = L["bid"][j], L["ask"][j]
                if b is None or a is None or np.isnan(b) or np.isnan(a):
                    ok = False; break
                b, a = int(round(b * 100)), int(round(a * 100))
                if not (0 < b < a < 100):
                    ok = False; break
                nb = na = None
                if j + 1 < len(L["e"]) and L["e"][j + 1] == Hh + H:
                    b1, a1 = L["bid"][j + 1], L["ask"][j + 1]
                    if not (np.isnan(b1) or np.isnan(a1)):
                        nb, na = int(round(b1 * 100)), int(round(a1 * 100))
                q[t] = (b, a, nb, na)
            if not ok:
                continue
            mo = month
            ch = charged(legs[tks[0]]["series"], mo)
            liquid = all(s.recent_trades(legs[t]["tt"], Hh, 3 * H) > 0 for t in tks)
            for side in (-1, +1):
                filled, px, rest = [], {}, []
                for t in tks:
                    b, a, nb, na = q[t]
                    imp = (a - b) >= 3
                    price = (a - 1 if imp else a) if side < 0 else (b + 1 if imp else b)
                    px[t] = price
                    L = legs[t]
                    lo = np.searchsorted(L["tt"], Hh, side="right"); hi = np.searchsorted(L["tt"], Hh + H, side="right")
                    if L["close"] is not None:
                        hi = min(hi, np.searchsorted(L["tt"], L["close"], side="left"))
                    f = s.fills_for_order(side, price, 1, imp, "pess", L["tp"][lo:hi], L["tc"][lo:hi], L["ts"][lo:hi], lambda _s: 1)
                    (filled if f else rest).append(t)
                edge = (sum(px.values()) - 100) if side < 0 else (100 - sum(px.values()))
                winners = {t for t in tks if legs[t]["yes"]}          # 0, 1 or more
                mfee = sum(s.maker_fee_c(px[t], 1, ch, mo) for t in filled)
                # naked: hold filled legs to settlement
                if side < 0:
                    naked = sum(px[t] for t in filled) - mfee - 100 * len(winners & set(filled))
                else:
                    naked = 100 * len(winners & set(filled)) - sum(px[t] for t in filled) - mfee
                # completion at H+1h quotes (taker)
                can = all(q[t][2] is not None and 0 < q[t][2] < q[t][3] < 100 for t in rest)
                if not filled or not rest:
                    comp = naked
                elif can:
                    if side < 0:
                        comp = sum(px[t] for t in filled) + sum(q[t][2] - taker_fee_c(q[t][2]) for t in rest) - mfee - 100 * len(winners)
                    else:
                        comp = 100 * len(winners) - sum(px[t] for t in filled) - sum(q[t][3] + taker_fee_c(q[t][3]) for t in rest) - mfee
                else:
                    comp = np.nan
                # "cond" may only use what is known at H+1h: the LOCKED-IN value assuming the
                # partition holds (exactly one winner), never the realised outcome.
                lock = np.nan
                if filled and rest and can:
                    lock = (sum(px[t] for t in filled) + sum(q[t][2] - taker_fee_c(q[t][2]) for t in rest) - mfee - 100) if side < 0                         else (100 - sum(px[t] for t in filled) - sum(q[t][3] + taker_fee_c(q[t][3]) for t in rest) - mfee)
                    cond = comp if lock >= 0 else naked
                else:
                    cond = comp if comp == comp else naked
                # columns 11+ (added for the per-category breakdown; 0-10 unchanged):
                # series, completion possible at H+1h, locked-in value if completed
                rows.append((ev, month, side, len(tks), liquid, edge, len(filled), len(winners), naked,
                             comp if comp == comp else naked, cond,
                             legs[tks[0]]["series"], bool(can), lock))
    return rows


if __name__ == "__main__":
    months = sys.argv[1:]
    out = []
    for m in months:
        r = attempts_for_month(m)
        print(f"{m}: {len(r):,} attempts", flush=True)
        out += r
    np.save(f"results/mece/basket_explore_{months[0]}_{months[-1]}.npy", np.array(out, dtype=object))
