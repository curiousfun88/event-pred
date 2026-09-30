# Literature: weather forecasts vs Kalshi weather markets (positioning)

Searched 2026-09-30, after the single 7/2/4 test run, while looking for a
route by which an external-information STGAT could trade profitably. Web
search only, not exhaustive.

## Closest work

**Crosier, "Prediction Markets Beat the Weather Forecast on Tomorrow's High
Temperature"** (arXiv 2609.23969, 20 Sept 2026).
- Kalshi daily-high temperature ladders (mutually exclusive intervals), 7 US
  cities (New York, Chicago, Miami, Austin, Philadelphia, Denver, Los
  Angeles), five years to 2026-08-12, 7,590 city-days.
- Six public forecasts: NBM, NDFD, LAMP, GFS MOS, HRRR, ECMWF.
- The market's implied high has lower error than the best single forecast:
  RMSE 2.44°F vs NBM 2.70°F at the open (10% lower), 1.88°F vs 2.12°F at
  NBM's final bulletin on the target morning (11% lower). It is 3-4%
  lower than an optimally weighted combination of all six forecasts.
- The market leads: "the NBM travels four times further toward the market
  between its postings than the market travels toward the NBM." Prices do
  not jump on forecast updates.
- The advantage vanishes in Miami (NBM RMSE 1.6°F) and shrinks to 1-4% in
  July-October, when the forecasts are already good. It is 10-16% when
  NBM error is 3°F or more.
- Accuracy only: no trading test. Market + forecast combined is not tested.

**Public backtest (dev.to, "I backtested a forecast-based model against
Kalshi's temperature markets -- the market won", 2026).**
- Normal distribution around an Open-Meteo GFS/ECMWF blend (previous-runs
  archive) with per-city errors. 24 cities, 2026-07-25 to 09-22, 1,317
  city-days, 7,902 markets.
- Brier: market 0.1195, model 0.1466. Trading lost -37.7% ROI (YES) and
  -7.2% (NO).
- The only edge found was stable per-station bias (Miami about +3.7°F, LAX
  about -4.0°F vs forecast), which active traders already exploit. Grey
  literature: cite with care.

**CalibShi (Zerve gallery), Kalshi KXHIGHNY calibration.** 8,494 settled
markets. Raw expected calibration error 0.016 (0.001 after isotonic
recalibration). The market is already well calibrated. Grey literature.

## Relation to this project

- The same pattern as this project's own negatives: the STGAT on Kalshi
  data does not beat the per-series oracle on unsettled baskets (test
  1.09x). The mid-move head is worse than zero-move (test 1.03x). A GBM
  on quote features is 0.996x zero-move (dev). Kalshi prices absorb public
  information. What remains is structural (favourite-longshot,
  maker/taker, pre-resolution adverse selection).
- Open question, not answered by Crosier: does market + forecast jointly
  predict the settled bracket better than the market alone? That is the
  necessary condition for any forecast-fed STGAT to trade weather baskets.
