# Pre-registration: Kalshi -> Polymarket catch-up (research backtest)

Written 2026-09-30, **before any 2026 data is fetched or inspected**. It is
research only. Public data, a paper backtest, no live trading (supervisor:
"it's just research").

## What was seen before writing this (development evidence, 2025)

Development months only, 40 matched MECE events: 28 Club World Cup, 10 F1,
Fed, best-AI, PGA. Logs: `logs/v2_forecast/cross_venue_*_dev.log`.
- Polymarket (PM) does not lead Kalshi (0.997x zero-move). Kalshi leads PM:
  PM's next move ~ gap is 0.815x, and adding Kalshi's last move gives
  0.666x. The gap closes gradually (41% by 1 h, 65% by 6 h). PM lag-1
  autocorrelation is -0.14.
- When **Kalshi moved and PM had not** (|gap| >= 3c; 284 leg-hours, 35
  events, mean gap 6.7c), PM moved +3.14c toward Kalshi in 1 h (CI [2.23,
  4.25]).
- PM's price history is mostly midpoints: 54% of values in 5-95c sit on
  half cents, which a 1c-tick book can only produce as a mid.

These numbers generated the hypothesis. They are **not** evidence for it.
The test below uses only data from 2026.

## Hypothesis

On matched MECE legs, when Kalshi's quoted mid moves and PM's mid has not
followed, PM's mid moves toward Kalshi over the next hour by more than the
cost of crossing PM's spread.

## Rule (fixed now)

At each hour H (Kalshi hourly candle end; PM mid as-of H, nothing after H
used as input):
- gap = Kalshi mid(H) - PM mid(H); dK = Kalshi mid(H) - mid(H-1h); dP = PM
  mid(H) - PM mid(H-1h).
- **Signal:** |gap| >= 3c AND sign(gap)*dK >= 1c (Kalshi opened the gap)
  AND -sign(gap)*dP < 1c (PM did not move away).
- Kalshi must be two-sided at H and H-1h (0 < bid < ask < 100c), and H+1h
  must be before the Kalshi leg's close.
- **Trade:** buy PM YES if gap > 0 (Kalshi above PM), else buy PM NO
  (equivalently sell YES). 1 contract per signal. At most one open position
  per leg: a new signal on a leg with an open position is skipped.
- **Exit:** at H+1h.
- **Cost model (primary, conservative):** entry at PM mid + s/2 in the trade
  direction, exit at PM mid(H+1h) - s/2. s is inferred from the mid's
  fractional part: half cent -> s = 1c; whole cent -> s = 2c; otherwise s =
  2c. No depth limit (1 contract). PM fee = 0 in the primary; a sensitivity
  charges 1c per contract round trip.
- **Secondary horizons** (reported, not for the verdict): exit at H+2h and
  H+6h.

## Data (2026, never inspected before this document)

- Events: Kalshi MECE game/race events in series KXEPLGAME, KXMLSGAME,
  KXUCLGAME, KXLALIGAGAME, KXF1RACE, with Kalshi close between 2026-01-01
  and 2026-09-25. Legs matched to PM negRisk events by
  `stg_infra/examples/match_polymarket_events.py` (the same rules; failures
  left unmatched).
- Kalshi hourly quote candles:
  `GET /trade-api/v2/series/{series}/markets/{ticker}/candlesticks`
  (period 60). PM mids: CLOB prices-history, fidelity 60.
- Real spreads and depth (sanity only): Tardis free first-of-month PM books
  (2026-06-01, 07-01, 08-01, 09-01) for any matched token they cover.

## Verdict (primary)

Mean net P&L per trade (cents per contract, conservative cost model, fee 0)
with a 95% CI resampling **events**. The effect is supported if the mean is
> 0 and the CI excludes 0. Also reported whatever it shows: number of trades
and events; the fee sensitivity; the H+2h and H+6h exits; per-series results;
the Tardis spread check (share of signal hours where the real PM spread is
<= the assumed s).

## Not allowed after the 2026 data is seen

Changing the thresholds (3c, 1c, 1c), the exit, the cost model, the series
list or the date range; dropping events other than by the matcher's fixed
rules. Any further analysis is labelled exploratory.

## Limitations known in advance

Hourly grid (faster lags are invisible). PM quote depth is unknown outside
the Tardis days. PM mid, not executable quotes, outside those days. The
matcher may miss events. Legal access to PM is not assessed: research only.
