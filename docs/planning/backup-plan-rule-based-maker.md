# Backup plan: rule-based maker as the profitable strategy

Recorded 2026-09-30, after the single test run (commit 18c8649). **Status:
parked.** It is used only if no route makes the STGAT useful for a
profitable strategy. It awaits the supervisor's answers (below).

## Why a backup is needed

The supervisor requires a profitable strategy. On the test months
(2025-08..11):
- The STGAT gives no trading value. The mid-move head is 1.015-1.041x
  zero-move, every CI above 1. The S4 filter never fired (S4 - base =
  0.00pp). S5 made +24.2% on 49 fills, CI [-37, +91].
- The rule-based A10 maker returned +1.8% net (pessimistic), CI [-48, +62],
  on 83 fills over 29 events. The point estimate is positive under all three
  fill models, but the pre-registered verdict (CI excluding 0) fails.
- The A6 maker (same idea, no 24 h cut-off) lost 10.6% (pessimistic) and
  23.8% (strict).

## Candidate strategies (at most 3, economically motivated)

1. **A10 unchanged:** forward test only, no re-tuning.
2. **Favourite buyer:** A10's bid side only (buy YES at 85-99¢, improve 1¢,
   no quote within 24 h of close). Motivation: Kalshi favourites earn small
   positive returns (Bürgi, Deng & Whelan 2026, favourite-longshot bias).
   A10 also sells favourites, which works against that. This tension was
   flagged in `docs/5-literature/literature-maker-positioning.md` on
   2026-09-29, before any test run. A10's test P&L has **not** been
   inspected by side.
3. **Broad maker + 24 h rule:** makers earn +1.5% in aggregate on taker-only
   series (RESEARCH_LOG). The broad simulated maker (S1) lost 1.53%
   pessimistic on test without the 24 h rule.

## How to test (pending supervisor)

- **Preferred: fresh data.** Fetch 2025-12 to about 2026-08 (settled
  markets): trades, results and hourly quotes. The maker simulator needs no
  STGAT cache. The trades archive ends 2025-11-25 and no trades fetcher
  exists yet (`stg_infra/fetch_quote_candles.py` covers quotes). Tune on
  all 13 months to 2025-11, freeze, pre-register, test once. About 1 week
  of data work.
- **Fallback: reused test months.** Tune the favourite buyer on development
  months only, pre-register, run once on 2025-08..11, and disclose it in
  the thesis as a second evaluation after A10's result was known. Expect
  about 40-50 fills, so the CI will likely include 0 even if the edge is
  real.
- **Never:** retune and retest on 2025-08..11 repeatedly, or leave the
  reuse undisclosed.

## Questions for the supervisor (email drafted 2026-09-30, not yet sent)

1. Is a positive out-of-sample return, reported with its uncertainty,
   enough (A10 already qualifies)? Or must it be statistically
   distinguishable from zero?
2. Must the profitable strategy use the STGAT?
3. Is a disclosed second test on the same held-out months acceptable, or
   should fresh data be fetched?

## Related STGAT route (primary, still open)

If the STGAT must drive the strategy, the one economically motivated
route found so far is an **upset-risk filter**. Train on a settle-YES
target and compare the model's probability with the market price, so as
to skip favourites the model rates riskier than their price implies (A10's
losses come from upsets). It is untested and would need a fresh-data test.

**Upset-risk filter: KIV (2026-09-30).** Judged low-prior: the test showed
no skill beyond price (unsettled 1.09x the family oracle; mid-move 1.03x
zero-move); within a MECE basket the other legs are already in the price;
and the favourite-longshot pattern needs only a calibration curve. If
revisited, first run a dev-only diagnostic (about 1-2 h). Take favourites
at 85-99¢ more than 24 h from close, and check whether a GBM on simple
features beats price plus a calibration curve at predicting upsets, with
event-grouped CV. If it does not, drop the route.

## STGAT-for-trading routes: status (2026-09-30)

| route | status |
|---|---|
| Next-hour mid-move signal (S4/S5) | tested on test months: no skill (S4 = base; S5 49 fills, CI [-37, +91]) |
| Settlement-danger filter ("S6"; re-proposed 2026-09-30 as "#1") | **dropped 2026-09-29** after a validation check (session bc8a4f00, 10:41-10:49): the A6 maker had no large near-resolution losses (10 worst fills -$15 total); the losing activity was 881 fills at 6-24 h (small losses each); the model's settlement skill would at best reproduce a time-to-close rule, which A10's 24 h cut-off now implements. The only new angle (early resolution before the scheduled close) has no support: A10 test fills show a +5.0c/contract 1 h markout, not adverse |
| Upset-risk filter | KIV; 1-2 h dev-only GBM diagnostic first |
| Weather forecasts + STGAT | low prior (Crosier 2026: market beats forecasts and leads them); 2-3 h dev-only check that market + forecast beats market alone on the settled bracket |
| Parlays (KXMVE) | not feasible before the deadline (RFQ one-offs, text-only legs, no data before 2025-10); future work |
