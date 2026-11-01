# Kalshi maker fees: check against the official schedule (2026-10-16)

Source: `kalshi-fee-schedule.pdf` (Kalshi, "Last updated and effective: July 7, 2026"), saved by hand (kalshi.com refuses
downloads from this network with 429).

- **Formula.** Maker fee = round up(M x 0.0175 x C x P x (1-P)); M = 0 unless the series is listed under "Non-Standard
  Fees" (sports, economics, awards, ...: M = 1; combos `KXMVE`: M = 2). Charged only when a resting order executes;
  cancelling is free. Same as the simulator's `maker_fee_c` on charged series.
- **Which series.** The simulator charges makers iff the API `fee_type` is `quadratic_with_maker_fees` (or the combo
  variant). Every listed series present in the live series cache agrees with the table (7 of 7: KXFEDDECISION,
  KXUCLGAME, KXNBA, KXPGATOUR, KXLALIGA charged; KXBTCY, KXETHY not). 59 of 1,383 cached series charge makers; weather
  (`KXHIGH*`/`KXLOW*`) does not.
- **Rounding (difference, conservative).** Kalshi rounds so that fee + position cost is a whole centicent ($0.0001); the
  simulator rounds each fill's fee up to a whole cent. E.g. 10 contracts at 50c: Kalshi 4.375c, simulator 5c; 1 contract
  at 50c: 0.44c vs 1c. The simulator therefore overstates maker fees on the charged series and understates every arm's
  P&L slightly. Kept as pre-registered; reported as a conservative assumption.
- **Not verifiable here.** The flat 0.25c/contract maker fee assumed before 2025-07 (G's training months only); this is
  the current schedule and carries no history. Per-series fee types before 2025-10-04 are taken from today's API flags.
