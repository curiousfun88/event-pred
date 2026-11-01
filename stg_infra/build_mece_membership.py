"""
build_mece_membership.py

WHICH EVENTS ARE MECE BASKETS, DECIDED WITHOUT LOOKING AT THE FUTURE.

WHY THIS EXISTS. The graph's basket membership came from
examples/mece_sum_to_one_check.py, a DETECTION script, and it chose baskets
with three pieces of information nobody has at snapshot time t:

  1. the event's OWN outcome (exactly one leg resolved YES);
  2. family history POOLED over the whole scan window, later instances
     included (>= 3 instances, all single-winner);
  3. whether the event LATER had a day on which every leg traded.

For detection that is fine. For forecasting it selects the evaluation
population with hindsight. This script writes one membership table carrying
TWO rules, and the graph build picks one per month by split:

  TRAIN months: HINDSIGHT. The event itself resolved single-winner and its
      family did so in >= MIN_INSTANCES instances across all history.
      Curating training data with known outcomes is legitimate, like
      labelling; it gives the model clean partitions to learn from.
  VAL/TEST months: CAUSAL. At window start t, the event's family has
      >= MIN_INSTANCES instances that were KNOWN resolved by t (last leg
      closed at least BUFFER before t), every one single-winner. The first
      instance known to resolve with n_yes != 1 revokes the family from then
      on. The event's own outcome and later coverage are never consulted.
      VAL must be causal too: it selects the checkpoint, so it has to
      mirror test.

What stays the same as the detection script: 3-100 legs, threshold ladders
excluded by title-template homogeneity, combo props excluded, family = the
event-ticker prefix before the first '-'. Leg count uses the final listing,
which is listing information, not an outcome. Legs created later than a
window are dropped from that window's basket by the graph build, via
leg_created, so the hub's leg count is causal in every split.

WHAT "KNOWN RESOLVED" MEANS HERE. The markets data records the ACTUAL
close_time and no settlement time. An instance counts as known BUFFER after
its last leg's close (default 24h), conservatively, since Kalshi usually
settles within hours.

OUTPUT: results/mece/mece_membership.parquet, one row per leg:
    event_ticker, ticker, family, leg_created,
    hind_ok  (bool: accepted by the hindsight rule)
    q_from   (causal: first window start at which the family qualifies; null = never)
    q_to     (causal: window start from which it is revoked; null = never)

USAGE (from the repo root)
    python stg_infra/build_mece_membership.py --self-test
    python stg_infra/build_mece_membership.py
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

MIN_LEGS, MAX_LEGS = 3, 100
MIN_INSTANCES = 3
BUFFER = timedelta(hours=24)
EXCLUDE_TICKER_SUBSTRINGS = ["SINGLEGAME", "MULTIGAME"]

# Verbatim from examples/mece_sum_to_one_check.py, so ladder exclusion is unchanged.
LADDER_KEYWORDS_PATTERN = r"\b(above|below|or higher|or lower|over|under|at least|at most|exceed)\b"
STRIKE_RE = re.compile(
    r"(?:above|below|or higher than|or lower than|over|under|at least|at most|exceed[s]?)\s*\$?([\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
FAMILY_RE = re.compile(r"^([^-]+)")


def extract_strike(title):
    if title is None:
        return None
    m = STRIKE_RE.search(title)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def title_template(title):
    if title is None:
        return None
    m = STRIKE_RE.search(title)
    if not m:
        return None
    return title[:m.start(1)] + "X" + title[m.end(1):]


def event_family(event_ticker: str) -> str:
    m = FAMILY_RE.match(event_ticker)
    return m.group(1) if m else event_ticker


# ---------------------------------------------------------------------------
# Pure rules (exercised by --self-test)
# ---------------------------------------------------------------------------

def event_table(legs: pl.DataFrame, buffer: timedelta = BUFFER) -> pl.DataFrame:
    """legs: ticker, event_ticker, title, result, created_time, close_time
    (naive UTC). One row per event with structure and resolution facts."""
    ladder_events = (
        legs.filter(pl.col("title").str.to_lowercase().str.contains(LADDER_KEYWORDS_PATTERN))
        .with_columns(pl.col("title").map_elements(extract_strike, return_dtype=pl.Float64).alias("strike"),
                      pl.col("title").map_elements(title_template, return_dtype=pl.Utf8).alias("template"))
        .filter(pl.col("strike").is_not_null())
        .group_by("event_ticker").agg(pl.col("template").n_unique().alias("n_templates"))
        .filter(pl.col("n_templates") == 1)["event_ticker"].to_list()
    )
    ev = (legs.group_by("event_ticker").agg(
            pl.col("ticker").n_unique().alias("n_legs"),
            pl.col("result").is_in(["yes", "no"]).sum().alias("n_resolved"),
            (pl.col("result") == "yes").sum().alias("n_yes"),
            pl.col("close_time").max().alias("last_close"))
          .with_columns(
            pl.col("event_ticker").map_elements(event_family, return_dtype=pl.Utf8).alias("family"),
            (pl.col("n_resolved") == pl.col("n_legs")).alias("fully_resolved"),
            (pl.col("last_close") + buffer).alias("known_at"),
            pl.col("event_ticker").is_in(ladder_events).alias("is_ladder"),
            pl.any_horizontal([pl.col("event_ticker").str.contains(s, literal=True)
                               for s in EXCLUDE_TICKER_SUBSTRINGS]).alias("is_combo"))
          .with_columns(((pl.col("n_legs") >= MIN_LEGS) & (pl.col("n_legs") <= MAX_LEGS)
                         & ~pl.col("is_ladder") & ~pl.col("is_combo")).alias("structural_ok")))
    return ev


def family_intervals(ev: pl.DataFrame, min_instances: int = MIN_INSTANCES) -> dict:
    """family -> (q_from, q_to). Built only from structurally valid, fully
    resolved instances, in the order they became KNOWN. Qualifies at the
    min_instances-th clean instance if no bad instance precedes it; revoked
    at the first bad instance (and never re-qualifies)."""
    inst = (ev.filter(pl.col("structural_ok") & pl.col("fully_resolved"))
              .select("family", "known_at", (pl.col("n_yes") == 1).alias("clean"))
              .sort(["family", "known_at"]))
    out = {}
    for fam, grp in inst.group_by("family", maintain_order=True):
        fam = fam[0] if isinstance(fam, tuple) else fam
        n_clean, q_from, q_to = 0, None, None
        for known_at, clean in zip(grp["known_at"].to_list(), grp["clean"].to_list()):
            if not clean:
                q_to = known_at
                break
            n_clean += 1
            if n_clean == min_instances:
                q_from = known_at
        if q_from is not None and q_to is not None and q_to <= q_from:
            q_from = None
        out[fam] = (q_from, q_to if q_from is not None else None)
    return out


def hindsight_ok(ev: pl.DataFrame, min_instances: int = MIN_INSTANCES) -> set:
    """Events accepted with full hindsight: structurally valid, the event
    itself fully resolved single-winner, and its family single-winner in
    every one of >= min_instances resolved instances across all history."""
    res = ev.filter(pl.col("structural_ok") & pl.col("fully_resolved"))
    fam = (res.group_by("family").agg(pl.len().alias("n"), pl.col("n_yes").min().alias("lo"),
                                       pl.col("n_yes").max().alias("hi"))
              .filter((pl.col("n") >= min_instances) & (pl.col("lo") == 1) & (pl.col("hi") == 1)))
    good = set(fam["family"].to_list())
    return set(res.filter(pl.col("family").is_in(list(good)) & (pl.col("n_yes") == 1))["event_ticker"].to_list())


def build_membership(legs: pl.DataFrame, buffer: timedelta = BUFFER,
                     min_instances: int = MIN_INSTANCES) -> pl.DataFrame:
    ev = event_table(legs, buffer)
    iv = family_intervals(ev, min_instances)
    hind = hindsight_ok(ev, min_instances)
    ok = ev.filter(pl.col("structural_ok")).select("event_ticker", "family")
    fam_rows = [(f, a, b) for f, (a, b) in iv.items()]
    fam_df = pl.DataFrame(fam_rows, schema={"family": pl.Utf8, "q_from": pl.Datetime("ns"),
                                            "q_to": pl.Datetime("ns")}, orient="row")
    mem = (legs.join(ok, on="event_ticker", how="inner")
               .join(fam_df, on="family", how="left")
               .with_columns(pl.col("event_ticker").is_in(list(hind)).alias("hind_ok"))
               .filter(pl.col("hind_ok") | pl.col("q_from").is_not_null())
               .select("event_ticker", "ticker", "family",
                       pl.col("created_time").alias("leg_created"), "hind_ok", "q_from", "q_to"))
    return mem.sort(["event_ticker", "ticker"])


def active(mem_row_hind: bool, q_from, q_to, window_start: datetime, mode: str) -> bool:
    """Whether a leg's event is a basket at this window, under a rule."""
    if mode == "hindsight":
        return bool(mem_row_hind)
    if mode == "causal":
        return q_from is not None and window_start >= q_from and (q_to is None or window_start < q_to)
    raise ValueError(f"mode must be 'hindsight' or 'causal', got {mode!r}")


# ---------------------------------------------------------------------------
# Real data
# ---------------------------------------------------------------------------

def load_all_markets() -> pl.DataFrame:
    files = sorted((_REPO_ROOT / "data/markets").glob("markets_kalshi_*/markets_*.parquet"))
    if not files:
        raise SystemExit("no markets files under data/markets/")
    cols = ["ticker", "event_ticker", "title", "result", "created_time", "close_time", "_fetched_at"]
    df = pl.concat([pl.scan_parquet(f).select(cols) for f in files]).collect()
    df = df.sort("_fetched_at", descending=True).unique(subset=["ticker"], keep="first")
    return df.with_columns(pl.col("close_time").dt.replace_time_zone(None).cast(pl.Datetime("ns")),
                           pl.col("created_time").cast(pl.Datetime("ns"))).drop("_fetched_at")


def run(args) -> None:
    legs = load_all_markets()
    print(f"markets: {legs.height:,d} tickers across all history")
    mem = build_membership(legs, timedelta(hours=args.buffer_hours), args.min_instances)
    n_ev = mem["event_ticker"].n_unique()
    n_h = mem.filter(pl.col("hind_ok"))["event_ticker"].n_unique()
    n_c = mem.filter(pl.col("q_from").is_not_null())["event_ticker"].n_unique()
    print(f"membership: {mem.height:,d} legs, {n_ev:,d} events "
          f"(hindsight rule: {n_h:,d}; causal rule, ever active: {n_c:,d}; "
          f"families qualifying causally: {mem.filter(pl.col('q_from').is_not_null())['family'].n_unique()})")
    old = pl.read_parquet(_REPO_ROOT / "results/mece/mece_sum_to_one_leg_prices.parquet")["event_ticker"].unique()
    print(f"previous detection-based membership: {old.len():,d} events; "
          f"of those, hindsight rule keeps {mem.filter(pl.col('hind_ok') & pl.col('event_ticker').is_in(old.implode()))['event_ticker'].n_unique():,d}")
    out = _REPO_ROOT / args.out
    mem.write_parquet(out)
    print(f"saved {out}")


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _legs(rows):
    """rows: (event, n_legs, winners, close_day, created_day, title)"""
    out = []
    for evt, n, winners, close_day, created_day, title in rows:
        for i in range(n):
            out.append({"ticker": f"{evt}-L{i}", "event_ticker": evt, "title": title,
                        "result": ("yes" if i < winners else "no") if close_day is not None else "",
                        "created_time": datetime(2025, 1, 1) + timedelta(days=created_day),
                        "close_time": (datetime(2025, 1, 1) + timedelta(days=close_day)) if close_day is not None else None})
    return pl.DataFrame(out, schema={"ticker": pl.Utf8, "event_ticker": pl.Utf8, "title": pl.Utf8,
                                     "result": pl.Utf8, "created_time": pl.Datetime("ns"),
                                     "close_time": pl.Datetime("ns")})


def self_test() -> None:
    failures = 0

    def check(name, cond, detail=""):
        nonlocal failures
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))
        failures += 0 if cond else 1

    D = lambda d: datetime(2025, 1, 1) + timedelta(days=d)
    B = BUFFER
    t = "Winner of game"
    legs = _legs([
        # family A: clean on days 10, 20, 30, bad (two winners) on day 40, then an open event
        ("A-1", 3, 1, 10, 0, t), ("A-2", 3, 1, 20, 0, t), ("A-3", 3, 1, 30, 0, t),
        ("A-4", 3, 2, 40, 0, t), ("A-5", 3, 1, 50, 45, t),
        # family B: bad first, then three clean -> never qualifies (strict rule)
        ("B-1", 4, 0, 5, 0, t), ("B-2", 4, 1, 15, 0, t), ("B-3", 4, 1, 25, 0, t), ("B-4", 4, 1, 35, 0, t),
        # family C: only two clean -> never qualifies
        ("C-1", 3, 1, 10, 0, t), ("C-2", 3, 1, 20, 0, t),
        # family D: clean x3; D-4 itself resolves with two winners AFTER its window of interest
        ("D-1", 3, 1, 10, 0, t), ("D-2", 3, 1, 12, 0, t), ("D-3", 3, 1, 14, 0, t), ("D-4", 3, 2, 60, 20, t),
        # family F: clean in every instance -> accepted by both rules
        ("F-1", 5, 1, 10, 0, t), ("F-2", 5, 1, 11, 0, t), ("F-3", 5, 1, 12, 0, t),
        # family L: a threshold ladder (single strike template) -> excluded structurally
        ("L-1", 3, 1, 10, 0, "Will BTC be above $100"), ("L-2", 3, 1, 20, 0, "Will BTC be above $100"),
        ("L-3", 3, 1, 30, 0, "Will BTC be above $100"),
        # combo prop and a 2-leg event -> excluded structurally
        ("KXMVESPORTSMULTIGAME-1", 3, 1, 10, 0, t), ("E-1", 2, 1, 10, 0, t),
    ])
    ev = event_table(legs)
    iv = family_intervals(ev)
    check("family qualifies when its 3rd clean instance becomes KNOWN (close + buffer)",
          iv["A"][0] == D(30) + B, str(iv["A"]))
    check("family is revoked when a two-winner instance becomes known", iv["A"][1] == D(40) + B)
    check("a bad instance before the 3rd clean one blocks qualification for good", iv["B"][0] is None)
    check("two clean instances are not enough", iv["C"][0] is None)
    check("ladders excluded structurally", "L" not in iv and not ev.filter(pl.col("family") == "L")["structural_ok"].any())
    check("combo props and <3-leg events excluded",
          not ev.filter(pl.col("event_ticker").is_in(["KXMVESPORTSMULTIGAME-1", "E-1"]))["structural_ok"].any())

    # causal: activity at a window depends only on what was known by then
    check("not active one second before qualification", not active(False, *iv["A"], D(30) + B - timedelta(seconds=1), "causal"))
    check("active from qualification", active(False, *iv["A"], D(30) + B, "causal"))
    check("inactive after revocation", not active(False, *iv["A"], D(41) + B, "causal"))
    # the event's OWN outcome is not used causally: D-4 (two winners, known only on day 61)
    # is a basket on day 30 because family D qualified on day 15
    check("causal rule ignores the event's own (future) outcome", active(False, *iv["D"], D(30), "causal"))

    mem = build_membership(legs)
    hind = set(mem.filter(pl.col("hind_ok"))["event_ticker"].unique().to_list())
    check("hindsight rule uses the event's own outcome (D-4 rejected)", "D-4" not in hind)
    check("hindsight rule pools all history (family A rejected: one bad instance)", not hind & {"A-1", "A-2", "A-3", "A-5"})
    check("hindsight accepts a family clean in >=3 instances", {"F-1", "F-2", "F-3"} <= hind)
    check("hindsight rejects a whole family for one bad instance anywhere (D)", not hind & {"D-1", "D-2", "D-3"})
    check("causal membership keeps family A's events (active window is decided per window)",
          set(mem.filter(pl.col("family") == "A")["event_ticker"].unique().to_list()) >= {"A-1", "A-5"})
    check("leg_created is carried through for the causal leg count",
          mem.filter(pl.col("event_ticker") == "A-5")["leg_created"][0] == D(45))
    check("unknown mode is refused", _raises(lambda: active(True, None, None, D(0), "oracle")))

    print(f"\nself-test: {'all passed' if failures == 0 else f'{failures} FAILED'}")
    if failures:
        raise SystemExit(1)


def _raises(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--buffer-hours", type=float, default=24.0)
    ap.add_argument("--min-instances", type=int, default=MIN_INSTANCES)
    ap.add_argument("--out", default="results/mece/mece_membership.parquet")
    args = ap.parse_args()
    if args.self_test:
        self_test()
    else:
        run(args)


if __name__ == "__main__":
    main()
