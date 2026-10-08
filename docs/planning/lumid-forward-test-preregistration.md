# Live forward test of the learned maker policies: pre-registration

**Status:** FROZEN 2026-10-06 by the commit that adds this version, before the
first logged live hour. Nothing below changes except by a dated amendment.
**Seen before writing:** producer dry runs on 2026-10-05 (candidate counts,
selection shares, category mix); the A13/A14 validation on 2026-09-07..10-04.
No fill, outcome or P&L of the live period has been observed.

**Why.** The supervisor (2026-10-05): start with the own simulator, then move to
the platform; "baselines will be from forward testing", from now until the
presentation. The 2025 policy G passed its test on 2025-08..11 (A12: +3.55%
pessimistic) but returned -1.41% on 2026-09-07..10-04, the same as quoting
everything (A13 context). Retrained policies were then selected on that window
(A13/A14): G2-W3 +1.41% and G2+-W3 +1.05% pessimistic, each about +2.5 to +2.9
points above quoting everything. This test asks whether retraining recovers a
live, out-of-sample edge.

---

## 1. Questions

1. **Live profitability.** Is the retrained policy's net P&L after fees positive?
2. **Model value.** Does it beat random selection of the same share of quotes,
   and quoting everything, on the same candidates in the same hours?
3. **Decay.** Does the 2025 policy G keep losing relative to the retrained ones?
4. **Adverse-selection defences.** Does G2+ differ from G2?
5. **Generalisation and benchmarks** (descriptive): results by category and for
   series outside the 23 training series; risk-adjusted returns against an equity
   index and T-bills over the same dates.

## 2. Period

- **Start:** the first hour logged by the hourly producer service after this
  commit (`runs/live/runs.jsonl`). Platform publishing starts separately, when
  the platform runs user strategies (§4 A).
- **End of quoting:** 2026-11-11 00:00 UTC. The presentation is in the week of
  2026-11-16 (day not yet fixed).
- **Scored positions:** fills in events that settle by the end of quoting + 48h.
  Positions in events still open then are reported separately, marked to the last
  mid, and excluded from the verdicts.
- **Interim cut for the written report (due 2026-11-03):** fills before
  2026-10-28 00:00 UTC, in events settled by 2026-10-30 00:00 UTC, scored exactly
  as below and stated as **interim**. The verdicts are taken at the final cut.
  Nothing changes because of the interim result; the test does not stop early.

## 3. Models and arms (fixed)

| arm | model / rule | signals |
|---|---|---|
| `g2` (**primary**) | G2-W3 (A13), sha1 `de87439617ba9476`, post if predicted > 1c | `g2_bid`, `g2_ask` |
| `g2p` | G2+-W3 (A14), sha1 `fcad35080c11d957`, better level per side, post if > 1c | `g2p_bid/_ask`, `g2p_bid_lvl/_ask_lvl` |
| `g` | G (A12, 2025), sha1 `e39cc4ca97bbebd4`, decay reference | `g_bid`, `g_ask` |
| `rnd2` | random one-level candidates at G2's share that hour | `rnd2_bid`, `rnd2_ask` |
| `rnd2p` | random two-level candidates at G2+'s share that hour | `rnd2p_*` incl. levels |
| `cand` | every one-level candidate (quote everything) | `cand_bid`, `cand_ask` |

Strategies: `stg_infra/lqt/*_maker_v1.lqts`, from two templates
(`maker_template.lqts`, `maker_template_two_level.lqts`): both sides; improve by
1c when spread >= 3c, else join the touch (two-level arms follow their level
signal); 10 contracts per order; |net position| <= 50 per leg.

**Producer** (`stg_infra/live_signal_producer.py`): hourly. Candidates and
features from the simulator's, `maker_policy.py`'s and `retrain_g2.py`'s own
code. Replaying the validation window through the live path reproduced the
validation scores exactly (798 G2 and 1,344 G2+ scores, 0 mismatches;
`logs/v2_forecast/live_producer_v2_replay_check.log`).

**Universe.** Every open Kalshi event flagged mutually exclusive, with 3-100 legs,
not a combo, whose series has >= 3 recent settled events all with exactly one
YES. On the platform, additionally limited to its monitored universe, which it
controls and which affects all arms identically.

## 4. Two evaluation channels

**B. Documented fill rule on the live hours (primary for the verdicts).** The
producer logs every candidate and every arm's score each hour
(`runs/live/scores/`). The Kalshi trade tape for those hours is fetched and
`simulate_maker.py` is run unchanged (pessimistic, optimistic, strict fills) with
the logged scores as each arm's policy. Same fill rule as A12/A13, so live,
validation and backtest results are directly comparable; event-cluster CIs. Run
as a Lumid workflow/study if feasible, otherwise locally and labelled so.

**A. Platform paper lane (reported beside B whenever available).** Forward-test
scorecards per arm: fills, buy/sell split, `net_usd`, `fees_usd`, markouts, the
platform's Sharpe and max drawdown. As of 2026-10-06 the platform was returning
503 errors, and a deployed probe strategy had never run a cycle
(`live_enabled: false`); channel A starts when deployed strategies run.

**Why B decides.** The platform's rule for filling resting limit orders is
undocumented. A verdict that depended on it would measure the fill model as much
as the policy. Fixed before any live result.

## 5. Verdicts (fixed now; channel B, pessimistic fills, final cut)

| claim | holds if |
|---|---|
| **G2 profitable live** | `g2` net return > 0 with the event-cluster 95% CI excluding 0 |
| **G2 adds value live** | paired difference `g2` - `rnd2` > 0 with the CI excluding 0 |
| G2+ profitable / adds value | the same tests for `g2p` (vs `rnd2p`); secondary |
| Decay confirmed | `g2` - `g` > 0 with the CI excluding 0; secondary |

Channel A is reported for every arm whatever it shows; where A and B differ in
sign, the difference is discussed as a finding about fill models and does not
change the verdict.

## 6. Metrics

- Net return = net P&L after fees / capital committed at fill prices; net
  c/contract; fills; events; 1-hour markout.
- **Benchmarks (descriptive).** Daily P&L divided by the peak capital committed
  gives a daily return series: annualised return, volatility, Sharpe (excess over
  the T-bill rate), max drawdown, correlation with the index. Same dates: S&P 500
  total return (SPY adjusted close) and the 3-month T-bill rate (FRED `DTB3`).

## 7. Splits (reported, never verdicts)

Category; the 23 training series vs other series; taker-only vs maker-fee
series; week.

## 8. Predictions (before any live result)

- `g2`: positive but small, **0% to +2%**; CI likely includes 0 at the interim cut.
- `g2` > `rnd2` and > `cand`; `rnd2`, `rnd2p`, `cand` negative, around -1% to -2%.
- `g` near `cand` (decayed).
- `g2p` close to `g2`, not clearly better.
- Selection shares around 35-45%.

## 9. Known limitations (stated now)

- The platform's fill rule for resting limit orders is undocumented; channel A
  may not run at all if user strategies stay disabled.
- `.lqts` rules are re-evaluated on every market update, so an arm may re-submit
  within an hour; the simulator posts one order per side per hour. The
  simulator's 200-contract per-event limit is not expressible in `.lqts`.
- Quotes at H are a listing snapshot just after the top of the hour; the backtest
  used candle closes. Earlier quotes are candle closes, as in the backtest.
- The producer runs on one machine; hours it misses (machine off, outage) are
  logged as gaps in `runs/live/runs.jsonl` and reported. On the platform, scores
  persist until overwritten, so an outage leaves the last scores in force.
- A few weeks give far fewer events than the four 2025 test months; wide CIs
  are expected, especially at the interim cut.
- The validation window selected the models (best of three windows per design),
  so validation returns are optimistic; this test is their first unseen data.

## 10. What may change after the freeze

- Plumbing only (the `signal.publish` envelope, authentication, scheduling, the
  machine the producer runs on). No change to arms, models, threshold,
  candidates, features or verdicts.
- A model tuned later (walk-forward on training months only, declared in an
  amendment first) may be **added** as a new arm from the day it is ready,
  reported separately with its shorter window; existing arms are untouched.
- Any bug fix that changes what is published is a dated amendment, and rows
  before and after are not pooled.

---

## Amendment L1 (2026-10-08, BEFORE any strategy has traded on Lumid and before any live P&L is seen)

**Why.** (1) The supervisor requires the forward test to be evaluated on Lumid. (2) Validation by
market group (G2-W3, 2026-09-07..10-04, pessimistic): non-weather series **+6.73%** (CI +2.4 to +11.4,
1,725 fills), weather series **-1.60%** (CI -5.2 to +2.0, 3,490 fills). (3) Lumid's universe and its
signal mailbox are capacity-limited (first full publish: 75,000 rows, all 503/504).
Already established before this amendment: custom signals published via `signal.publish` are recorded
(backtest of `g2_maker_v1` on `KXBTCD-26OCT0723-T82899.99`: "Real on all three axes: prices, signals,
settlement", 0 actions with the sentinel values published).

**Changes (fixed now):**
1. **Evaluation = Lumid's paper lane (channel A becomes primary).** The verdicts of §5 are taken on the
   Lumid fills of each arm. If Lumid reports P&L for user strategies, its figure is used; if it reports only
   decisions/fills, P&L is computed from Lumid's recorded fills, settlement results and the Kalshi maker fee
   schedule. CIs by event-cluster bootstrap. The own-simulator replay (channel B) is kept as a supplementary
   check on the same universe.
2. **Universe: weather series excluded** (Kalshi daily-high/low temperature series, `KXHIGH*`, `KXLOW*`),
   on the validation result above, decided at the group level (weather vs non-weather), not by series.
   All other qualifying basket series in Lumid's universe are traded by all arms.
3. **Start of the Lumid test:** the first hour in which all six arms are deployed and publishing covers
   the non-weather series in the monitored universe; recorded in `runs/live/runs.jsonl` and in the report.
   If Lumid's universe is later widened by the operator, the widening date is recorded and results are
   reported for the periods before and after it.
4. Unchanged: arms, models, threshold, signals, interim (2026-10-28) and final (2026-11-11) cuts.
