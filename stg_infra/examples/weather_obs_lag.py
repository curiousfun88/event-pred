"""Exploratory (development months only): do Kalshi daily-high brackets lag
LIVE station observations?

The official daily high (NWS CLI, local-standard-time day) can only be >= any
observed reading at the settlement station, so a bracket whose upper bound is
below the running observed maximum cannot win: it is "dead". Dead is declared
with a safety margin: running max >= upper + MARGIN.

Steps:
  1. Station check: for each city and candidate station, the share of days
     where the observed max exceeds the winning bracket's upper bound
     (impossible for the true station, up to rounding).
  2. Dead-bracket audit: every dead leg must have settled NO.
  3. Lag: Kalshi quoted bid on dead legs at the hour they die and after.
     Selling YES at that bid (taker) earns bid - fee when the leg settles NO.

Observation times are UTC; only readings strictly before the quote hour H
are used. IEM ASOS archive (data/weather_obs/<STATION>.csv).

    python stg_infra/examples/weather_obs_lag.py --self-test
    python stg_infra/examples/weather_obs_lag.py
"""
import sys, re, math, argparse, datetime as dt
from pathlib import Path
import numpy as np

H = 3600
MARGIN = 1.0
LST = {"NY": -5, "PHIL": -5, "MIA": -5, "CHI": -6, "AUS": -6, "HOU": -6, "DEN": -7, "LAX": -8}
CANDIDATES = {"NY": ["NYC", "LGA"], "CHI": ["MDW", "ORD"], "AUS": ["AUS"], "MIA": ["MIA"], "DEN": ["DEN"],
              "PHIL": ["PHL"], "LAX": ["LAX"], "HOU": ["HOU", "IAH"]}


def taker_fee_c(p_c):
    p = p_c / 100.0
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6))


def bracket(sub):
    """'82° to 83°' -> (82, 83); '81° or below' -> (-inf, 81); '90° or above' -> (90, inf)."""
    s = sub.replace("°", "").strip()
    m = re.match(r"(-?\d+)\s*to\s*(-?\d+)", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"(-?\d+)\s*or below", s)
    if m:
        return -math.inf, float(m.group(1))
    m = re.match(r"(-?\d+)\s*or above", s)
    if m:
        return float(m.group(1)), math.inf
    return None


def city_of(event_ticker):
    return event_ticker.split("-")[0].replace("KXHIGH", "")


def event_date(event_ticker):
    return dt.datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()


def lst_day_bounds(day, offset_h):
    """UTC [start, end) of a local-standard-time calendar day."""
    start = dt.datetime(day.year, day.month, day.day, tzinfo=dt.timezone.utc) - dt.timedelta(hours=offset_h)
    return int(start.timestamp()), int(start.timestamp()) + 86400


def running_max(obs_t, obs_v, start, t):
    """Max of readings with start <= time < t (nan if none)."""
    lo, hi = np.searchsorted(obs_t, start, "left"), np.searchsorted(obs_t, t, "left")
    return obs_v[lo:hi].max() if hi > lo else np.nan


def load_obs(station):
    import polars as pl
    d = pl.read_csv(f"data/weather_obs/{station}.csv", null_values=["M"], infer_schema_length=0)
    d = d.with_columns(pl.col("valid").str.to_datetime("%Y-%m-%d %H:%M", time_zone="UTC").dt.epoch("s").alias("t"),
                       pl.col("tmpf").cast(pl.Float64)).drop_nulls("tmpf").sort("t")
    return d["t"].to_numpy(), d["tmpf"].to_numpy()


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    check("bracket parse", bracket("82° to 83°") == (82, 83) and bracket("81° or below") == (-math.inf, 81)
          and bracket("90° or above") == (90, math.inf))
    s, e = lst_day_bounds(dt.date(2025, 7, 15), -5)
    check("NY LST day starts 05:00 UTC", dt.datetime.fromtimestamp(s, dt.timezone.utc).hour == 5 and e - s == 86400)
    t = np.array([0, 3000, 3600, 7000]); v = np.array([70., 75., 80., 90.])
    check("running max excludes readings at/after t", running_max(t, v, 0, 3600) == 75.0)
    check("running max uses only [start, t): 3001..7000 -> 80", running_max(t, v, 3001, 7000) == 80.0)
    check("event date parse", event_date("KXHIGHNY-25JUL15") == dt.date(2025, 7, 15))
    check("fee at 3c = 1c", taker_fee_c(3) == 1)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    mk = pl.scan_parquet("data/markets/markets_kalshi/*.parquet").select(
        "ticker", "event_ticker", "yes_sub_title", "result", "close_time").filter(
        pl.col("event_ticker").str.contains(r"^KXHIGH(NY|CHI|AUS|MIA|DEN|PHIL|LAX|HOU)-")).collect().unique("ticker")
    mk = mk.filter(pl.col("result").is_in(["yes", "no"]))
    mk = mk.with_columns(pl.col("event_ticker").map_elements(event_date, return_dtype=pl.Date).alias("day"))
    mk = mk.filter((pl.col("day") >= dt.date(2024, 11, 1)) & (pl.col("day") <= dt.date(2025, 7, 31)))
    legs = {r["ticker"]: r for r in mk.iter_rows(named=True)}
    events = {}
    for r in legs.values():
        events.setdefault(r["event_ticker"], []).append(r["ticker"])
    print(f"DEVELOPMENT MONTHS ONLY (2024-11..2025-07): {len(events):,} weather events, {len(legs):,} legs")

    obs = {st: load_obs(st) for sts in CANDIDATES.values() for st in sts}

    # 1. station check
    print("\n1. STATION CHECK: share of days where observed LST-day max > winning bracket's upper bound"
          " (+margin 0 / +1F); ~0 for the settlement station")
    station = {}
    for city, sts in CANDIDATES.items():
        best = None
        for st in sts:
            ot, ov = obs[st]
            n = v0 = v1 = inside = 0
            for ev, tks in events.items():
                if city_of(ev) != city:
                    continue
                win = [legs[t] for t in tks if legs[t]["result"] == "yes"]
                if len(win) != 1 or bracket(win[0]["yes_sub_title"]) is None:
                    continue
                lo, hi = bracket(win[0]["yes_sub_title"])
                s, e = lst_day_bounds(legs[tks[0]]["day"], LST[city])
                mx = running_max(ot, ov, s, e)
                if np.isnan(mx):
                    continue
                n += 1; v0 += mx > hi; v1 += mx >= hi + MARGIN; inside += (lo - 0.5 <= round(mx) <= hi + 0.5)
            if n:
                print(f"   {city:<5} {st}: days {n:>4}  obs max > upper: {v0 / n:6.1%}  >= upper+1F: {v1 / n:6.1%}"
                      f"  rounded obs max inside winning bracket: {inside / n:6.1%}")
                if best is None or v1 / n < best[1]:
                    best = (st, v1 / n)
        station[city] = best[0]
    print("   chosen:", station)

    # quotes
    q = pl.concat([pl.read_parquet(f) for f in sorted(Path("data/quotes/by_month").glob("quotes_*.parquet"))
                   if "2024-10" < f.stem[-7:] <= "2025-07"], how="diagonal_relaxed")
    q = q.filter(pl.col("ticker").is_in(list(legs))).with_columns(pl.col("end_ts").dt.epoch("s").alias("h"))
    quotes = {}
    for tk, h, b, x in zip(q["ticker"], q["h"], q["bid_close"], q["ask_close"]):
        quotes.setdefault(tk, {})[int(h)] = (b, x)
    print(f"\nquoted legs: {len(quotes):,} of {len(legs):,}")

    # 2 + 3. dead legs
    rows, bad = [], 0
    for ev, tks in events.items():
        city = city_of(ev)
        ot, ov = obs[station[city]]
        s, e = lst_day_bounds(legs[tks[0]]["day"], LST[city])
        for tk in tks:
            br = bracket(legs[tk]["yes_sub_title"])
            if br is None or tk not in quotes or math.isinf(br[1]):
                continue
            close = int(legs[tk]["close_time"].timestamp())
            died = None
            for Hh in sorted(quotes[tk]):
                if Hh < s or Hh >= close:
                    continue
                mx = running_max(ot, ov, s, Hh)
                if np.isnan(mx) or mx < br[1] + MARGIN:
                    continue
                if died is None:
                    died = Hh
                b, x = quotes[tk][Hh]
                bid_c = round(b * 100) if b is not None and b > 0 else 0
                rows.append((ev, tk, city, (Hh - died) // H, bid_c, legs[tk]["result"]))
            if died is not None and legs[tk]["result"] == "yes":
                bad += 1
    ev_ = np.array([r[0] for r in rows]); lag = np.array([r[3] for r in rows]); bid = np.array([r[4] for r in rows])
    res = np.array([r[5] for r in rows])
    print(f"\n2. DEAD-LEG AUDIT: {len(set(r[1] for r in rows)):,} legs declared dead; settled YES anyway: {bad}"
          f"  (must be ~0; >0 means station/rounding/day errors)")
    print("\n3. KALSHI BID ON DEAD LEGS, by hours since death (quoted hours only)")
    print(f"   {'hours':>5} {'leg-hours':>9} {'bid>=1c':>8} {'bid>=2c':>8} {'bid>=5c':>8} {'mean bid':>9} {'mean (bid-fee | bid>=2c)':>26}")
    for L in (0, 1, 2, 3, 6):
        sel = lag == L
        if not sel.any():
            continue
        bb = bid[sel]
        g = bb[bb >= 2]
        net = np.mean([x - taker_fee_c(x) for x in g]) if len(g) else float("nan")
        print(f"   {L:>5} {sel.sum():>9,} {np.mean(bb >= 1):>8.1%} {np.mean(bb >= 2):>8.1%} {np.mean(bb >= 5):>8.1%} "
              f"{bb.mean():>8.2f}c {net:>25.2f}c")
    first = lag == 0
    g = first & (bid >= 2)
    if g.any():
        nets = np.array([x - taker_fee_c(x) for x in bid[g]])
        print(f"\n   AT DEATH (first dead hour), bid >= 2c: {g.sum():,} legs in {len(np.unique(ev_[g])):,} events; "
              f"net per contract if sold at bid {nets.mean():+.2f}c; all settled NO: {bool(np.all(res[g] == 'no'))}")
        for city in sorted(set(r[2] for r in rows)):
            cs = np.array([r[2] == city for r in rows]) & g
            if cs.any():
                print(f"     {city:<5} {cs.sum():>5} legs  mean bid {bid[cs].mean():5.2f}c")


if __name__ == "__main__":
    main()
