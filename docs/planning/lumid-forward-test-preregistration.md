# Lumid forward test of the learned maker policy G: pre-registration

**Status:** DRAFT 2026-10-06. Frozen by the commit that precedes the first
published signal; nothing below changes after that except by a dated amendment.
**Seen before writing:** two dry runs of the producer (2026-10-05, hour 15 UTC):
candidate counts, selection shares and category mix only. No fill, outcome or
P&L of the live period has been observed.

**Why.** The supervisor (2026-10-05): start with the own simulator, then move to
the platform; "baselines will be from forward testing", from now until the
presentation. Policy G passed its pre-registered test on 2025-08..11 (A12:
pessimistic +3.55%, CI [+2.51%, +4.60%], 34,086 fills; random selection of the
same share -0.23%). This test asks whether that holds on live markets that did
not exist when G was frozen.

---

## 1. Questions

1. **Live profitability.** Is G's net P&L after fees positive on the live period?
2. **Model value.** Does G beat random selection of the same share of quotes,
   and quoting everything, on the same candidates in the same hours?
3. **Generalisation.** Does the result differ between series G was trained on,
   new series in categories G has seen, and categories G has never seen?
4. **Benchmarks.** Risk-adjusted, is the strategy a better use of capital than
   an equity index or T-bills over the same dates?

## 2. Period

- **Start:** the hour of the first published batch that the platform confirms
  (signal visible in `lqt.signals`).
- **End of quoting:** 2026-11-11 00:00 UTC. The presentation is in the week of
  2026-11-16 (day not yet fixed); this leaves the 48h settlement allowance below
  and three days of analysis before the earliest possible day.
- **Scored positions:** fills in events that settle by the end of quoting + 48h.
  Positions in events still open then are reported separately, marked to the
  last mid, and excluded from the verdicts.
- **Interim cut for the written report (due 2026-11-03):** fills before
  **2026-10-28 00:00 UTC**, in events settled by 2026-10-30 00:00 UTC, scored
  exactly as §4-§6. The report states these as **interim** results of a test
  still running. The verdicts of §5 are taken at the final cut (end of
  quoting) and presented at the presentation. Nothing (arms, threshold, period,
  verdicts) changes because of the interim result, and the test does not stop
  early whatever it shows.

## 3. Arms (fixed)

Three `.lqts` strategies generated from one template
(`stg_infra/lqt/maker_template.lqts`). They differ **only** in the signal read:

| arm | signal | selects |
|---|---|---|
| `gbt_maker_v1` | `gbt_bid` / `gbt_ask` | G's predicted net c/contract > 1c |
| `rnd_maker_v1` | `rnd_bid` / `rnd_ask` | random candidates, at G's selection share **that hour** |
| `cand_maker_v1` | `cand_bid` / `cand_ask` | every candidate (quote everything) |

Common to all: both sides; improve by 1c when spread >= 3c, join the touch at
2c; 10 contracts per order; |net position| <= 50 per leg.

**Producer** (`stg_infra/live_signal_producer.py`): hourly at minute 1 UTC.
Candidates and features come from the simulator's and `maker_policy.py`'s own
code; on 488 replayed test-month scores the live path reproduced the backtest
exactly (max abs diff 0). Model `runs/maker/policy_G_model.pkl`, sha1
`e39cc4ca97bbebd4`, unchanged since A12. Threshold t = 1c, unchanged.

**Universe.** The producer scores every open Kalshi event that is flagged
mutually exclusive, has 3-100 legs, is not a combo, and whose series has >= 3
recent settled events all with exactly one YES. What the strategies can trade is
that set intersected with the platform's monitored universe, which the platform
controls. Universe changes affect all three arms identically.

## 4. Two evaluation channels

**B. Documented fill rule on the same live hours (primary for the verdicts).**
The producer logs every candidate and every arm's score each hour
(`runs/live/scores/`). The Kalshi trade tape for those hours is fetched and
`simulate_maker.py` is run unchanged (pessimistic, optimistic, strict fills)
with the logged scores as the policy. Run as a Lumid workflow reporting each
arm's net P&L into a Lumid study if feasible; otherwise run locally and
labelled so. Channel B uses the same fill rule as the A12 test, so live and
backtest results are directly comparable, and gives event-cluster CIs.

**A. Platform paper lane (always reported beside B).** The forward-test
scorecards for each arm: fills, buy/sell split, `net_usd`, `fees_usd`,
markouts, and the platform's Sharpe and max drawdown.

**Why B decides.** The platform's rule for filling resting limit orders is
undocumented (asked; answer recorded here when received). A verdict that
depended on it would measure the fill model as much as the policy. This choice
is fixed before any live result.

## 5. Verdicts (fixed now)

| claim | holds if (channel B, pessimistic fills) |
|---|---|
| **G profitable live** | net return > 0 with the event-cluster 95% CI excluding 0 |
| **The model adds value live** | paired difference G - random > 0 with the CI excluding 0 |

Channel A is reported for every arm whatever it shows. Where A and B differ in
sign for either claim, the difference is reported and discussed as a finding
about fill models; it does not change the verdict. If channel A produces no
usable scorecards (e.g. the platform cannot fill resting orders), that is
reported.

## 6. Metrics

- Net return = net P&L after fees / capital committed at fill prices (as in
  A12); net c/contract; fills; events; 1-hour markout.
- **Benchmarks.** Daily P&L divided by the peak capital committed over the
  period gives a daily return series. Reported: annualised return, volatility,
  Sharpe (excess over the T-bill rate), max drawdown, and correlation with the
  index. Benchmarks over the same dates: S&P 500 total return (SPY adjusted
  close) and the 3-month T-bill rate (FRED `DTB3`). With a window of weeks,
  these are descriptive; no verdict rests on them.

## 7. Splits (reported, never verdicts)

- **Generalisation groups:** (i) series with G training fills (2024-11..2025-05);
  (ii) other series in categories G was trained on; (iii) categories G never saw
  (scored as unknown category, e.g. Economics, Commodities, Elections).
- Category; taker-only vs maker-fee series; week.

## 8. Predictions (before any live result)

- G pessimistic net return positive but below the test months: **+0.5% to +3%**.
- G > random; random and quote-everything near zero or negative.
- G's selection share near **40%** (dry runs), not the 20% of the test months,
  because of the different market mix.
- Group (i) >= group (ii) > group (iii); group (iii) near zero or negative.
- Channel A differs from channel B in fill counts by a large factor, in a
  direction that depends on the platform's fill model.

## 9. Known limitations (stated now)

- The platform's fill rule for resting limit orders is undocumented.
- `.lqts` rules are re-evaluated on every market update, so an arm may re-submit
  within an hour; the simulator posts one order per side per hour.
- The 200-contract per-event limit of the simulator cannot be expressed in
  `.lqts` and is not enforced.
- Live quotes at H are a listing snapshot taken just after the top of the hour;
  the backtest used candle closes. The 24h-ago quote comes from the producer's
  own store or the candle ending at H-24h.
- Scores persist on the platform until overwritten. A producer outage leaves the
  last scores in force; outages are logged (`runs/live/runs.jsonl`) and reported.
- A window of a few weeks gives far fewer events than the four test months;
  wide CIs are expected.
- The live basket rule uses Kalshi's mutually-exclusive flag and recent settled
  history, not the full-history family scan of `build_mece_membership.py`.

## 10. What may change after the freeze

- **Before the first confirmed publish:** plumbing only (the `signal.publish`
  envelope, authentication, scheduling). No change to arms, model, threshold,
  candidates, features or verdicts.
- **After it:** nothing, except a bug that makes the producer publish something
  other than this document specifies. Any such fix is a dated amendment, and the
  platform cohort is checkpointed so rows before and after are not pooled.
