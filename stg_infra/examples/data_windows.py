"""
data_windows.py

Single source of truth for which months of Kalshi data each category's
data is trustworthy for, and where the train/val/test split boundaries
sit on the shared master calendar.

Background: category_history_audit.py found that financials and crypto
each went through a step-change in how many markets Kalshi issues per
month (financials ~14x in 2024-04, crypto ~17x in 2024-12) -- before
those points, under 2% of each category's total historical volume
exists, in a structurally thinner, different liquidity regime.
weather_spike_check.py found weather's Dec 2024/Jan 2025 spike is a
KXCITIESWEATHER product-rollout burst (one series doubling twice
month-over-month while every other series stays flat), not steady-state
trading -- excluding just January still keeps 6.4x the original 2-month
sample at a representative density.

Every script that scans raw markets/trades data should import its
window from here instead of hardcoding TARGET_MONTHS, so a future
change to any of these boundaries only has to happen in one place.
"""

FINANCIALS_START = "2024-04"
CRYPTO_START = "2024-12"
WEATHER_START = "2025-02"  # excludes the KXCITIESWEATHER rollout burst (2024-12, 2025-01)
END_MONTH = "2025-11"      # confirmed elsewhere: no December 2025 file exists yet

# Matches the ladder mechanism's MIN_N_PER_SIDE=20. Shared here (not
# duplicated in mece_sum_to_one_check.py and mece_sum_to_one_pnl_backtest.py
# separately) after mece_liquidity_check.py found the MECE pipeline had NO
# liquidity filter at all: 15/20 of the largest full-basket deviations had
# a leg with under 20 trades that day, several with just 1-3 trades total.
# A basket "summing to $2.01" on one or two thin trades per leg isn't a
# mispricing, it's the absence of a real market.
MIN_LEG_TRADES = 20


def month_range(start: str, end: str) -> list[str]:
    """Inclusive [start, end] list of 'YYYY-MM' strings."""
    y, m = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    out = []
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


# Ladder mechanism only ever uses crypto + financials (weather is
# structurally excluded -- see
# pairwise_monotonicity_ladder_identification_crosscheck.py and the
# sub_title bracket/threshold finding). Scripts that process both
# categories together in one pass scan from the EARLIER of the two
# starts and let classify_ticker()'s per-row filtering handle the rest
# -- scanning from crypto's later start would silently drop financials
# months that classify_ticker() would otherwise have picked up.
LADDER_START = min(FINANCIALS_START, CRYPTO_START)
LADDER_MONTHS = month_range(LADDER_START, END_MONTH)

# MECE mechanism is category-agnostic in principle, but the validated
# findings are overwhelmingly weather (93% of opportunities), with no
# confirmed full-basket structure in crypto/financials yet. Start from
# weather's window; widen to LADDER_START only if a future audit finds
# genuine MECE structure elsewhere.
MECE_START = WEATHER_START
MECE_MONTHS = month_range(MECE_START, END_MONTH)

# Full master window -- for anything that needs one shared calendar
# across every category (e.g. the joint STGAT adjacency/feature tensor,
# which needs one T index even though node population grows over time
# as each category's window opens -- weather nodes simply don't exist
# before 2025-02, crypto nodes don't exist before 2024-12, etc).
MASTER_START = min(FINANCIALS_START, CRYPTO_START, WEATHER_START)
MASTER_MONTHS = month_range(MASTER_START, END_MONTH)


# --- Train/val/test split, defined ONCE on the master calendar ---
#
# Applies to every mechanism and every category, even though each
# category's own data window opens at a different point within it.
# This piece MUST be shared, not chosen independently per mechanism: a
# per-mechanism split risks the shared temporal backbone learning about
# a calendar period through one mechanism's training data while another
# mechanism is simultaneously treating that same period as held-out
# test -- a leak that wouldn't show up in either mechanism's own
# results individually.
#
# 15 months train / 2 months val / 3 months test, chronological order
# (no shuffling -- these are time series). Adjust only here.
TRAIN_END = "2025-06"  # last month included in train
VAL_END = "2025-08"    # last month included in val
# test = everything after VAL_END through END_MONTH


def active_split() -> tuple:
    """(train_end, val_end) in force. Defaults to the constants above, so every
    earlier figure reproduces exactly. A run can override them via
    set_split(), which writes the FYP_SPLIT environment variable. It is read at
    CALL time, because this module is imported under two paths
    (examples.data_windows and data_windows) that may be separate module
    objects; an override stored as a module global could be seen by one and
    not the other, putting the chunker and the split guard on different
    splits."""
    import os
    v = os.environ.get("FYP_SPLIT")
    if v:
        tr, va = (x.strip() for x in v.split(","))
        if not (len(tr) == 7 and len(va) == 7 and tr < va):
            raise ValueError(f"FYP_SPLIT must be 'YYYY-MM,YYYY-MM' with train_end < val_end, got {v!r}")
        return tr, va
    return TRAIN_END, VAL_END


def set_split(train_end: str, val_end: str) -> None:
    """Override the train/val boundaries for this process (and its children)."""
    import os
    if not (len(train_end) == 7 and len(val_end) == 7 and train_end < val_end):
        raise ValueError(f"split must be 'YYYY-MM','YYYY-MM' with train_end < val_end, got {train_end!r}, {val_end!r}")
    os.environ["FYP_SPLIT"] = f"{train_end},{val_end}"


def split_for(month: str) -> str:
    """Returns 'train', 'val', or 'test' for a given 'YYYY-MM' month, on
    the shared master calendar. Every script should call this rather
    than defining its own split logic, so a boundary change only has to
    happen in this one file."""
    train_end, val_end = active_split()
    if month <= train_end:
        return "train"
    if month <= val_end:
        return "val"
    return "test"
