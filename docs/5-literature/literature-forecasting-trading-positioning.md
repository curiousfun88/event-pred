# Literature: forecasting models trading prediction markets, and cross-venue price discovery

Searched 2026-09-30, after the single 7/2/4 test run. Question: has a
forecasting model been shown to trade prediction markets profitably, and is
cross-venue lead-lag already studied? Web search only, not exhaustive.

## Forecasting models trading prediction markets (mostly losses)

- **Prediction Arena** (arXiv 2604.07355, 2026). Six frontier LLMs trade
  real capital on Kalshi and Polymarket for 57 days (2026-01-12 to
  03-09). Every model lost on Kalshi (-16.0% to -30.8%). Polymarket
  averaged -1.1%, the best +6.02% over 3 days.
- **PolyBench** (arXiv 2604.14199, 2026). 7 LLMs, 36,165 predictions on
  Polymarket (2026-02-06 to 02-12). Only 2 of 7 show positive returns
  (+17.6%, +6.2%): paper trading over one week.
- **Outcome-based RL** (arXiv 2505.17989). Hypothetical Polymarket profit
  of about $52-54: negligible.
- **Sports betting.** Hubáček et al. (IJF 2019) earned positive NBA
  profits by decorrelating the model from the bookmaker's odds. Kaunitz et
  al. (arXiv 1710.02824) profited from the cross-bookmaker consensus until
  their accounts were restricted. In both, the edge came from another price
  source (the consensus) or from avoiding the market's own information, not
  from out-forecasting the market.

## Where profits are documented (structural)

- **Saguillo et al., "Unravelling the Probabilistic Forest"** (arXiv
  2508.03474, AFT 2025). About $40M of realised arbitrage profit on
  Polymarket, 2024-04 to 2025-04. Two kinds: market rebalancing (outcomes
  of one market not summing to $1, this project's constraint) and
  combinatorial arbitrage across related markets. **Contrast for the
  thesis:** this project finds executable MECE edge of about 0 on Kalshi at
  hourly resolution (bid sum beats $1 in 1.8% of snapshots, about 2c before
  fees). Candidate reasons: Kalshi's fees, and windows that close well
  below an hour.

## Cross-venue price discovery (lead-lag)

- **Aktuğ & Torul, "Price Discovery Across Political Prediction Markets:
  Evidence from the 2024 U.S. Presidential Election"** (June 2026; read in
  full). One contract (Trump victory) on 9 venues, 2024-01 to 11, 5-minute
  data. Hasbrouck / Gonzalo-Granger / Putniņš shares. Polymarket and
  Betfair hold about 85% of information share. Polymarket leads at 5 min,
  Betfair at 1 h. Kalshi gains a non-trivial share within 32 days. Mean
  cross-venue gap 6.2 pp. Descriptive only: no strategy, no P&L.
- **Ng et al. (2025)** (seen via secondary citations, not read). Polymarket,
  Kalshi, PredictIt and Robinhood in the 2024 election, a 30-min VAR.
  Polymarket leads Kalshi, concentrated in high-volume periods; whale order
  imbalance predicts returns.
- **Semantic non-fungibility** (arXiv 2601.01706). Cross-venue gaps persist
  because resolution semantics differ and arbitrage is limited.
- **GNNs:** none found on prediction markets (cross-market GNNs exist for
  equities, e.g. CMGM).

## This project's check (2026-09-30, development months only)

`stg_infra/examples/cross_venue_leadlag.py`,
`logs/v2_forecast/cross_venue_leadlag_dev.log`. 40 matched MECE events
(28 Club World Cup, 10 F1, Fed, best-AI, PGA), 10,898 leg-hours, hourly,
leave-one-event-out fits.
- Polymarket does **not** lead Kalshi. PM last move predicting Kalshi's next
  move: 1.001x zero-move, CI [0.999, 1.004]. Combined with the level gap
  and Kalshi's own move: 0.997x, CI [0.986, 1.006].
- **Reverse holds:** PM's next move toward Kalshi, 0.815x, CI [0.738,
  0.904] (Club World Cup 0.874x, F1 0.717x). This is opposite to the 2024
  election evidence. It may be PM price noise correcting itself rather than
  information flow.
- The rough Kalshi taker check is negative after fees (-3.44c/contract, CI
  [-5.08, -1.71], realistic exit).
- Limits: 40 events; hourly only (the literature's lead is at 5 min).
- **Reverse detail** (`--reverse-detail`, `logs/v2_forecast/cross_venue_reverse_dev.log`).
  Is it a lead or PM noise?
  - PM lag-1 autocorrelation is -0.14 (planted bounce: -0.40).
  - PM's own last move predicts nothing (0.989x). The gap to Kalshi does
    (0.738x, CI [0.606, 0.901]). Adding Kalshi's last move improves it
    further (0.666x, CI [0.521, 0.818]): Kalshi's moves propagate to PM
    within the next hour.
  - The gap closes gradually: 41% by +1h, 52% by +2h, 65% by +6h (planted
    noise: ~100% within 1h, then flat). F1 closes mostly within 2h; Club
    World Cup closes gradually (27% -> 69% by 6h, wide CI).
  - Reading: **Kalshi leads Polymarket** on these 2025 sports/F1 MECE
    markets. That is information flow, not only bounce, and opposite to the
    2024 election evidence (Polymarket led).
  - Caveats: 40 events; whether PM's history is mid or last price is not
    documented; the median gap is only 1.0c. Not tradable as tested: no PM
    bid/ask history, PM access restrictions.

## Positioning

Consistent evidence, including this project's own STGAT, GBM, weather and
cross-venue results: Kalshi prices absorb public information. Documented
profits come from structure (arbitrage, market making, favourite-longshot,
avoiding informed flow near resolution), not from forecasting. Novel here:
the pre-registered graph-model test on MECE baskets, and the cross-venue
check on non-election MECE markets (Kalshi leads at 1 h).
