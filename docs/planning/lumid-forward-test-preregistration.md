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

---

## Amendment L2 (2026-10-11 ~15:55 UTC, BEFORE any live fill, outcome or P&L is seen): trade-store bug fix, and the producer moves to a Lumid sandbox

**Bug.** `live_signal_producer.update_trades` kept the ids of trades fetched after the hour H in its
"already seen" set, but dropped those trades from the store (`t <= H`). At the next hour they were skipped
as already seen, so every trade made between the top of the hour and the fetch was lost for good. The
feature `trades_24h` (one of the 14 G/G2 features; G2+ also uses prints in the last hour) was therefore
undercounted in every live hour since the producer started (2026-10-06). Training and validation used the
archive's complete tape and are unaffected. Found 2026-10-11 by comparing two producer instances for the
15:00 UTC hour and checking 8 legs against Kalshi's own trade records (e.g. 95 and 107 stored vs 150 true);
reproduced with a planted feed (now in the producer's self-test). The earlier replay check (0 mismatches)
used stored historical trades, not the live fetch, so it could not see this.

**Fix.** Each trade's id is stored with the trade, so "seen" means "stored"; entries in the old format are
refetched over the full 25 h window once, which also repairs the counts carried over.

**Consequences (fixed now).**
1. **Hours before the fix are scored and reported separately and never pooled with hours after it** (§10).
   The first hour on the fixed code is recorded in `runs/live/runs.jsonl` and in the report. Hours before it
   are reported as "pre-fix (features undercounted)".
2. Models, arms, threshold, candidates, other features and verdicts are unchanged.
3. The effect of the bug on the arms' selections is measured once (the share of candidates whose
   post/do-not-post decision flips when `trades_24h` is recomputed from Kalshi's records for one pre-fix
   hour) and reported; it changes nothing above.

**Producer host (plumbing, §10).** The producer moves from the laptop to a Lumid sandbox (site `office`;
Kalshi throttles the `home` site's shared address), kept alive across the 24 h sandbox limit by
`stg_infra/lumid_sandbox_keeper.py`. Same code and models: for 15:00 UTC on 2026-10-11 the laptop and the
sandbox gave identical predictions on every candidate whose inputs agreed (max difference 0.0); inputs
differed only through quotes moving between the two snapshots (0.2 s apart) and the trade-store state.
The laptop producer stops once the sandbox publishes; hours are attributed to the host that produced them.

**L2 effect, measured 2026-10-12 00:35 SGT (16:35 UTC, as committed in item 3; still before any live P&L is
seen).** Hour 2026-10-11 15:00 UTC (laptop, pre-fix), `trades_24h` (and G2+'s `prints_1h`, `imb_1h`)
recomputed from the fixed store, all else as logged; the logged predictions are reproduced exactly from the
logged features. Decisions (prediction > 1c) flipped: **G 0.2%, G2 0.5%, G2+ 0.5%** of candidates; posted
shares unchanged to 0.1 point (G2 43.9% both). `trades_24h` changed on about 9% of candidates; about 70% of
candidates are legs with no trades in 24 h, which the bug cannot affect. Log:
`logs/v2_forecast/live_tradestore_bug_effect_20261011T15.log`. Item 1 (no pooling) stands.

## Amendment L3 (2026-10-13, BEFORE any live fill, outcome or P&L is seen): decision latency, evaluation engine, added baseline arms

**Why.** (1) **Decision timing.** The backtest posts orders at H and lets them rest over (H, H+1h]. Live, the
snapshot is taken about 1.6 min after H, and an hour's decisions exist only when the producer's cycle ends,
25-31 min after H (`runs/live/runs.jsonl`, `secs` 1,510-1,853 on 2026-10-11/12). Trades in (H, snapshot] are
already reflected in the snapshot the models scored, so counting them as fills is look-ahead. Trades in
(snapshot, cycle end] were not seen by the models; counting them assumes the decision was computed
instantly, an execution assumption (the backtest makes the same one), not a leak. Found in a methodology
audit on 2026-10-13; nothing has been evaluated. (2) **Channel A is unavailable.** As of 2026-10-12 every deployed
strategy has `live_enabled: false` (Lumid API), so the platform has never run a cycle for any arm; the
supervisor's reply also judged the platform's paper fills unrealistic. (3) **Baselines.** Simple in-market
baselines answer "is the model only picking wide spreads / liquid legs?" and "is boosting needed?".

**Changes (fixed now).**
1. **Evaluation = channel B (reverses L1 item 1).** Verdicts (§5) are taken on the documented fill rule
   applied to Kalshi's real trade tape, pessimistic fills, as originally pre-registered. Channel A is reported
   only if the platform ever runs the arms.
2. **Order window.**
   - **Primary (verdicts): from the snapshot.** For hour H, orders rest over (`snap_ns`, H+1h], cut at the
     market's close. This removes the look-ahead and keeps the backtest's instant-execution assumption, so
     live and backtest results stay comparable. The report states that the primary result assumes decisions
     are executed at the snapshot time.
   - **Sensitivity (as executed; reported, never a verdict): from the decision time.** Orders rest over
     (D_H, H+1h], where D_H is when that hour's cycle ended: what the current producer actually achieves.
     The producer logs D_H from now on (`t_decided_ns`, plumbing under §10). For earlier hours
     D_H = `snap_ns` + `secs`, never earlier than the true cycle end (the snapshot is taken after the cycle
     starts). An hour with D_H >= H+1h has no orders in this sensitivity.
   - Counting from H is not reported: it contains the look-ahead above.
3. **Engine: hourly paper trader, plus replay.** A paper trader on the Lumid sandbox settles each hour's fills
   shortly after H+1h from Kalshi's trades for (D_H, H+1h], with `simulate_maker.py`'s own fill, fee, limit and
   settlement code (positions carry across hours per event, as in the simulator). It starts at hour S, recorded
   in its log and in the report. The same engine run on the fetched tape (replay) covers hours before S and any
   hour the paper trader missed. On hours covered by both, fills must agree exactly; any disagreement is
   reported and explained, and the replay figure is used for that hour. Within an hour, fills are allocated in
   the simulator's fixed order (leg by leg, order by order), not by trade time; this matters only when a
   position limit binds.
4. **Added arms (secondary, descriptive; §10: reported separately, never verdicts).** Computed from the
   candidate features the producer already logs at H, on the same one-level candidates, scope and fill rule:

   | arm | rule |
   |---|---|
   | `wide3` | post a candidate iff its spread >= 3c |
   | `liq` | post iff its `trades_24h` >= that hour's median `trades_24h` over the hour's candidates |
   | `lin2` | ridge regression (alpha 1.0; standardised features; category one-hot; missing `dmid_24h` set to 0 with a missing-indicator) on G's 14 features, trained on exactly G2-W3's training fills and targets; post if predicted > 1c. Its sha1 is recorded here before any live hour is evaluated |

   Paired differences reported: `g2` - `wide3`, `g2` - `liq`, `g2` - `lin2`.
5. **Inference sensitivity.** Every CI is also computed with clusters = UTC day of the order hour (events on the
   same day may move together); reported beside the event-cluster CI, which stays the basis of the verdicts.
6. **Recording.** Each cut's results are posted to Lumid Research Fleet as a FlowMesh job (metrics and a
   summary); fills, logs and the report stay in the sandbox home and are copied into the repo.
7. **Unchanged:** models, thresholds, candidates, features, scope (L1: platform-listed and whitelisted
   series, weather excluded, identical for all arms), verdicts (§5), benchmarks (§6), cuts (interim
   2026-10-28, final 2026-11-11), no pooling across the L2 fix.

**Predictions (before any live result).** The primary window removes about 1.6 min of each hour (~3%):
fills and returns close to what counting from H would give. The as-executed sensitivity removes roughly
40-50% of each hour's fill opportunities: fewer fills and lower total P&L for every arm; the effect on
return per unit of capital is unclear in sign. `wide3`: -1% to
+1%. `liq`: -2% to 0%. `lin2`: between `rnd2` and `g2`. `g2` - `lin2` positive but with a CI including 0 at
the interim cut.

## Amendment L4 (2026-10-13, BEFORE any live fill, outcome or P&L is seen, and BEFORE any validation data for the new series is fetched): primary universe = the strategy's own markets; validation-selected categories as a secondary arm; P&L reported by category

**Revision note.** A first version of L4 (commit b447d01, same day, not yet public) made the
validation-selected categories the primary universe. It was revised before it was pushed, before any
validation data was fetched and before any live result was computed, because selecting the primary universe
narrows the research question ("profitable on the categories that were profitable last month") and removes
from the headline the categories in which the model fails, which are findings for the thesis question
(where does a learned model add value?). The selection survives as a secondary arm (item 4).

**Why.** L1 limited the evaluated universe to Lumid-listed series (plus the publish whitelist) because
Lumid's own fills (channel A) were to decide the verdicts. Since L3 the verdicts use channel B, which scores
any Kalshi market from the producer's logged scores and Kalshi's trade tape. The L1 universe is set by the
platform's coverage, not by the strategy: 157 tickers and 56 distinct events in the first 36 hours after the
L2 fix (141 G2-posted candidates per hour). The strategy itself scores and would quote about 3,000
non-weather events in the same hours (about 4,100 G2-posted candidates per hour). Nothing live has been
evaluated: no fill, P&L or fill count has been computed for any arm.

**Changes (fixed now).**
1. **Primary universe = the strategy's markets.** The 290 non-weather series (not `KXHIGH*`/`KXLOW*`, as
   L1) that appear in the live producer's scores from 2026-10-11 15:00 to 2026-10-13 02:00 UTC, frozen in
   `docs/planning/l4_candidate_pool.json` (series, logged category, events seen) in the first L4 commit.
   Applied to every arm, to every live hour since the L2 fix, and to both cuts. The verdicts of §5 are taken
   on this universe. Series that first appear after 02:00 UTC on 2026-10-13 are reported separately.
2. **Net P&L by category (descriptive).** For every arm and both cuts the report gives one table: overall
   net P&L ($), net return, event-cluster 95% CI, fills and events, then the same per category, and the
   paired `g2` - `rnd2` difference per category. Category rows are findings about where the model adds
   value; they are never a verdict, and no category is added or removed because of its live result.
3. **Also reported, never verdicts:** the L1 universe (continuity with L1) and the 23 training series vs
   the rest (§7).
4. **Secondary arm `g2_sel` (validation-selected categories).** G2 restricted to the categories that pass
   this rule on validation data:
   - data: Kalshi markets, quotes and trades for the pool's series over the A13 validation window (quoting
     hours 2026-09-07 00:00 to 2026-10-05 00:00 UTC), fetched after this commit with the code that built the
     A13 validation cache (`smoke_test_2026.py` cache, `retrain_g2.val_data` assembly), on a Lumid sandbox;
   - measurement: G2-W3 (sha1 `de87439617ba9476`) exactly as in the A13 validation (BROAD candidates, post
     if predicted > 1c, pessimistic fills, same fee, limit and settlement code);
   - grouping by Kalshi category (as logged by the producer), never by series;
   - a category is selected iff its validation net return is **> 0** and it has **at least 20 events with
     fills**; if none qualifies, `g2_sel` is empty and reported as such.
   The selection (each category's return, CI, fills, events, net $, pass/fail) is committed before any live
   P&L is computed. `g2_sel` and the paired difference `g2_sel` - `g2` are reported at both cuts **whatever
   the primary result shows**. `g2_sel` never replaces the primary arm and no further variant is added after
   live results are seen; an idea arising during the test is evaluated only on live hours after its own
   registration, reported separately.
5. **Unchanged:** models, threshold, arms, candidates, features, verdicts (§5), metrics (§6), cuts (interim
   2026-10-28, final 2026-11-11), the L3 engine and order windows, no pooling across the L2 fix. Lumid
   publishing (channel A plumbing) keeps its L1 scope.

**Disclosed now.** Most of the primary universe lies outside G2's 23 training series (Sports holds 213 of
290 series and about 2,700 of 3,000 events seen), so this tests G2 beyond the markets it was trained on;
the 23-series split is reported. `g2_sel` selects on validation point estimates, so its validation return is
optimistic; the live hours are its unbiased check. Category composition and edges have changed over time
before (weather carried 76% of G's 2025 test profit and lost on the 2026 validation), which is what
`g2_sel` - `g2` measures.

**Predictions (before any validation fetch or live result).** Primary `g2`: return lower than on the 23
training series' validation, sign uncertain; `g2` - `rnd2` positive. Sports passes the `g2_sel` rule; most
small categories (Politics, Entertainment, Science and Technology, Elections, Commodities) fail the
20-event minimum; Crypto and Economics uncertain. `g2_sel` - `g2`: CI including 0.
