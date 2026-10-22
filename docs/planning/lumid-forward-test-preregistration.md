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

## Amendment L5 (2026-10-13, BEFORE any live fill, outcome or P&L is seen): signal publishing to the Lumid inbox stops; results and an hourly audit record go to Research Fleet via FlowMesh

**Why.** Nothing reads the published signals: every deployed strategy has `live_enabled: false` (L3), so the
platform has never run an arm, and since L4 the evaluated universe is the strategy's own markets, most of
which Lumid does not list. Publishing (paced batches, retries, backlog resends) takes a large part of each
hourly cycle, which delays the decision time D_H used by the L3 as-executed sensitivity. The inbox's one
remaining use, a third-party timestamp, covered only the Lumid-scope subset.

**Changes (fixed now).**
1. From the first hour the producer runs without `--publish` (recorded in `runs/live/runs.jsonl` and in the
   report), no signals are sent to the Lumid inbox. Scores, signal files and logs are written as before;
   models, features, candidates and scores are unchanged.
2. **Audit record.** Each hour's `runs.jsonl` line carries the sha256 of that hour's score files
   (`one_`, `two_`) and signal file. At the end of each cycle the producer (`--fleet`) submits one FlowMesh
   job to Research Fleet whose output is that hour's summary line, hashes included, so Research Fleet's own
   `created_at` timestamps every scored market hourly (the job id is logged as `fleet_job`). Results are
   posted to Research Fleet at each cut (L3 item 6); a failed post is logged and never costs the hour.
3. **Decision time.** D_H becomes earlier from the switch-over hour. The as-executed sensitivity (L3) is
   reported for hours before and after it separately as well as pooled; the primary order window (from
   `snap_ns`) is unaffected.
4. Channel A is not reported (it never ran). Unchanged otherwise: models, arms, universe (L4), verdicts,
   metrics, cuts, the L3 engine, no pooling across the L2 fix.

**Correction (2026-10-13 06:35 UTC, after the first L5 hour, still before any live P&L).** The "Why" above
overstated publishing's share of the cycle. Score files were written at about :29-:30 past each hour and the
cycle ended about a minute later, so the cycle is almost entirely data fetching (about 5,900 Kalshi calls)
and scoring. The first L5 hour (20261013T06) took 1,680 s against 1,819-1,861 s for the three hours before:
D_H moves about 2-3 minutes earlier, not 10-15. The decision to stop publishing stands on the other
reasons (nothing reads the inbox; the universe is the strategy's own markets). Item 3 is unchanged. The
first hourly Research Fleet record is job `office:fm:wfl-47990c10-1440-4229-9a8f-5ea6647fb6c3`.

## Amendment L6 (2026-10-13, BEFORE any live fill, outcome or P&L is seen, and BEFORE lin2 or mlp2 is trained): neural-network baseline arm `mlp2`

**Why.** L3 added `lin2` to ask whether boosting is needed. A neural network on the same inputs asks the
matching question from the other side (does a different flexible model family do better or worse than
boosting?), which fits a thesis about a neural forecasting model. Other boosting implementations
(LightGBM, XGBoost) are not added: same model family as G2, and A15 already measured G2's sensitivity to
its settings.

**Changes (fixed now).**
1. **Arm `mlp2` (secondary, descriptive; never a verdict).** Trained on exactly G2-W3's training fills and
   targets, the same rows as `lin2` (built once; `stg_infra/examples/train_baselines.py`, which also trains
   `lin2` and checks the G2-W3 refit sha1 `de87439617ba9476`). Inputs as `lin2`: G's 13 numeric features,
   missing `dmid_24h` set to 0 with a missing-indicator, category one-hot, standardised; the target is
   standardised for fitting and predictions are returned in c/contract. Model: sklearn `MLPRegressor`,
   hidden layers (64, 32), ReLU, Adam (learning rate 1e-3), L2 1e-4, minibatch 1,024, `random_state` 0.
   Early stopping on a **time-ordered** holdout: the latest 10% of training rows by quoting hour, up to
   100 epochs, patience 10, the best epoch's weights kept (fitted on the earlier 90%). No tuning.
2. **Rule:** post a candidate iff predicted > 1c, its own criterion, as `g2` and `lin2`. Whatever share it
   posts (including very few) is reported as its result.
3. **Recording:** the sha1 of `mlp2` (and `lin2`) is recorded here before any live hour is evaluated.
   Both are scored on the candidate features the producer logs each hour, same candidates, universe (L4)
   and fill rule as every arm.
4. **Reported:** `mlp2` overall and by category, and the paired difference `g2` - `mlp2`.
5. **Unchanged:** everything else (L3-L5).

**Predictions (before training).** `mlp2` posts a share within 20 points of `g2`'s; its return lies between
`lin2`'s and `g2`'s; `g2` - `mlp2` has a CI including 0. `lin2`'s and `mlp2`'s training posting shares are
recorded with their hashes.

**L3/L6 record: baseline models frozen (2026-10-13 ~07:55 UTC, before any live hour is evaluated).**
Trained on the `batch` sandbox (`stg_infra/examples/train_baselines.py --verify-g2`,
log `logs/v2_forecast/train_baselines_sandbox.log`):

| arm | file | sha1 | training rows | posts on training rows (> 1c) |
|---|---|---|---|---|
| `lin2` | `runs/maker/policy_lin2_W3_model.pkl` | `d11f158330cd2575` | 679,400 | 10.0% |
| `mlp2` | `runs/maker/policy_mlp2_W3_model.pkl` | `bc334d5dba6032b1` | 679,400 (fit on the earlier 611,460; best epoch 6) | 30.1% |

`dmid_24h` is missing on 67.8% of training rows (no two-sided quote 24 h earlier), so the missing-indicator
carries much of that feature's information.

**Row check, changed method (disclosed).** The planned check compared the refit G2-W3's pickle sha1 with
`de87439617ba9476`. Pickle bytes depend on the Python build: the frozen model itself, loaded and re-saved on
the sandbox (Python 3.11.17; it was trained under 3.12.3), hashes to `931fa452d57b6485`, and the refit to
`b23e29fbbdfe9d24`. The check was therefore replaced by prediction equality: on all 679,400 rebuilt rows the
refit and the frozen G2-W3 give identical predictions (max difference 0.0, 400 iterations each, same post
decision on every row), and the per-month row counts equal the original training log. The rows are G2-W3's
rows exactly (`stg_infra/examples/verify_g2_refit.py`, `logs/v2_forecast/verify_g2_refit_sandbox.log`).

## Amendment L7 (2026-10-13 ~14:00 UTC, BEFORE any live fill, outcome or P&L is computed): `g2_sel` becomes a walk-forward selection on the live test; September fetch dropped; batch-job rate limits

**Why.** L4 item 4 selected `g2_sel`'s categories on September 2026 validation data for the 290-series pool.
That needs per-market candles and trades for well over 100,000 markets (Sports and hourly Crypto series
dominate): days of fetching. Running it (07:36-13:37 UTC, 4 req/s) beside the paper trader's tape fetch
(3 req/s) throttled the live producer on the shared Kalshi egress: hours **20261013T09 and T11 were not
produced**, and T08, T10, T12 ended 65-75 min after the hour (`runs/live/runs.jsonl`; L3 records gaps).
Both jobs were stopped at 13:37 UTC. Partial September results (Climate and Weather 1 event, Commodities 4
events; both below the 20-event minimum) were seen; they are validation, not live, and change nothing.
The reproduction gate passed exactly (1,725 fills, 153 events, +6.73%).

**Changes (fixed now).**
1. **`g2_sel` = weekly walk-forward category selection on the live test.** Folds (quoting hours, UTC):

   | fold | selection window | `g2_sel` trades |
   |---|---|---|
   | 1 | 2026-10-11 15:00 to 10-18 00:00 | 10-18 00:00 to 10-25 00:00 |
   | 2 | 10-18 00:00 to 10-25 00:00 | 10-25 00:00 to 11-01 00:00 |
   | 3 | 10-25 00:00 to 11-01 00:00 | 11-01 00:00 to 11-11 00:00 (end of quoting) |

   In each selection window, `g2`'s fills (primary order window, pessimistic, L4 primary universe) are
   grouped by category (as logged), counting **only events settled by the end of that window**, so the
   selection uses only information available when the trading week starts (no overlap of outcomes with
   the trading week: purging in the sense of López de Prado 2018). A category is selected for the next
   week iff its net return is > 0 and it has >= 20 events with fills (the L4 rule, unchanged). `g2_sel`
   in a trading week = `g2`'s fills in that week in the selected categories; an empty selection means no
   `g2_sel` orders that week, reported as such.
2. **Reported (secondary, never a verdict):** `g2_sel` per fold and pooled over the three trading weeks;
   the paired difference `g2_sel` - `g2` on the same trading weeks (event-cluster CI, day-cluster
   sensitivity); each fold's selection table (category, return, events, pass/fail). At the interim cut,
   fold 1 and the part of fold 2 before 10-28 are reported.
3. **The September validation fetch for the pool is dropped.** `stg_infra/examples/validate_g2_sel.py` and
   its partial cache are kept as a record and are not used for any selection.
4. **Batch jobs and the live producer.** Any job using Kalshi from Lumid runs only after the producer has
   logged the current hour and before minute 58, at <= 2 requests/s; the paper trader's tape collection
   follows this rule.
5. **Unchanged:** L4's primary universe and verdicts, all arms and models (L3, L6), order windows, cuts.

**Rationale and literature.** Selecting groups by their recent performance and holding them next period
follows the industry- and factor-momentum design (Moskowitz and Grinblatt 1999; Arnott, Kalesnik and
Linnainmaa 2023, RFS 36(8)). Re-selecting at each step from past data only, and testing over several
successive out-of-sample periods rather than one, follows recursive real-time selection (Pesaran and
Timmermann 1995) and rolling-origin evaluation for non-stationary series (Hewamalage, Ackermann and
Bergmeir 2023, DMKD 37(2)). Combinatorial purged cross-validation outperforms walk-forward for *backtests*
(Arian, Norouzi Mobarekeh and Seco 2024, Knowledge-Based Systems), but it resamples periods in any order;
in a live test the next week does not exist when the selection is made, so walk-forward is the only causal
design. Fixing the full rule, thresholds and windows in advance is a complete pre-analysis plan, which
Brodeur, Cook, Hartley and Heyes (2024, JPE Micro) find reduces p-hacking where registration alone does not.

**Predictions (before any live P&L).** Sports is selected in every fold; most small categories fail the
20-event minimum; `g2_sel` - `g2` has a CI including 0 in every fold and pooled.

**L7 addendum: producer outage 13:42-13:57 UTC on 2026-10-13 (recorded before any live P&L).** Lumid allows
two sandboxes per account on the `office` site. The extra `batch` sandbox used for the jobs above made
the keeper's handover (creating `prod-a`) fail with HTTP 409 from 13:16; `prod-b` expired at 13:42 and
the producer stopped. `batch` was deleted and `prod-a` started at 13:57:29 (`stg_infra/lumid_start.sh`).
Effect: hour 20261013T13 was produced only from 13:57 (its order window is about 2 minutes); T14 starts
late. Together with T09 and T11 (not produced) and T08, T10, T12 (late), these hours are reported as gaps
or late hours and are not repaired. Rule added to L7 item 4: no non-production sandbox is held while a
producer handover can occur; batch work runs inside the production sandbox's quiet minutes.

## Amendment L8 (2026-10-13 ~15:00 UTC, BEFORE any live fill, outcome or P&L is computed): one-sided verdict tests; the unselected A13 windows as live arms; day-cluster CIs implemented

**Why.** (1) Both verdict hypotheses of §5 are directional ("G2 is profitable", "G2 adds value over random
selection"); a one-sided test at 5% is the matching test, and it is fixed here before any live result.
(2) G2-W3 was chosen among three pre-specified training windows on one month of validation (A13), a choice
whose result is optimistic (Cawley and Talbot 2010) and whose dependence on the window should be checked
(Rossi and Inoue 2012). The two windows not selected are already trained and frozen, so they can be tested
on the same live hours at no cost. (3) L3 item 5 (day-clustered CIs) is implemented in the paper trader.

**Changes (fixed now).**
1. **Verdicts (§5), one-sided.** "G2 profitable live" holds iff the one-sided 95% lower bound of `g2`'s net
   return (event-cluster bootstrap, 2,000 draws, seed 0; the 5th percentile) is > 0. "G2 adds value live"
   holds iff the one-sided 95% lower bound of `g2` - `rnd2` (paired, union of events, same draw) is > 0.
   The same rule applies to the secondary G2+ and decay claims. Two-sided 95% CIs are reported beside every
   one-sided bound, and the report states which test decides.
2. **Arms `g2w1` and `g2w2` (secondary, descriptive; never verdicts).** G2-W1 (sha1 `e14a70b183731891`,
   111,033 training fills, 2026-06..08) and G2-W2 (sha1 `6774af73c6b5bb46`, 248,333 fills, 2026-03..08),
   trained 2026-10-06 on data ending 2026-08 (`logs/v2_forecast/g2_W{1,2}_train_validate.log`; hashes in
   the A13 metadata committed in 9fc486a; the model files are committed now). Same features, candidates,
   universe, fill rule and 1c threshold as `g2`; scored on the logged hourly features. Reported with
   `g2` - `g2w1` and `g2` - `g2w2`: whether the one-month selection mattered.
3. **Day-cluster sensitivity (L3 item 5)**: every return and paired difference is also reported with the
   UTC day of the order hour as the cluster. Event clusters remain the basis of the verdicts.
4. **Unchanged:** everything else (L3-L7).

**Prediction (before any live P&L).** `g2w1` and `g2w2` within 2 points of `g2`, all three differences
with CIs including 0. With the one-sided test, "G2 profitable live" is more likely than under the
two-sided rule, and still uncertain at the interim cut.

## Amendment L9 (2026-10-13 ~15:30 UTC, BEFORE any live fill, outcome or P&L is computed, and before the comparison below is run): the headline window is chosen on a six-month walk-forward, not one month

**Why.** A13 chose G2's training window (W1 3 months, W2 6 months, W3 all history) on one validation month,
where the windows did not differ significantly (W3 - W2 +1.77 points, CI -0.56 to +3.97), and their
category results disagreed in sign (weather: W1 +1.93%, W3 -1.60%). One month cannot choose confidently.
A15's walk-forward table and folds already exist, and all three windows are live arms (L8), so the choice
can be made on six months with nothing new deployed.

**Rule (fixed now).**
1. **Recipes**: W1 = train on the 3 calendar months before the test month; W2 = the 6 months before; W3 =
   every month before (A15's `hgb_a12` folds). Model, features, hyperparameters, target and threshold are
   G2's (A12/A13), unchanged.
2. **Folds**: test months 2026-04, 05, 06, 07, 08 (A15's table `runs/tune_gbm/features.npz`, G2-W3's exact
   training rows, single-winner events) and the A13 validation window 2026-09-07..10-05 as a sixth fold,
   scored with the frozen G2-W1/W2/W3 models (they are exactly these recipes trained through 2026-08) on that
   window's BROAD pessimistic fills of the 23 A13 series, single-winner events (as A15's folds).
3. **Score**: A15's offline score per fold (fills predicted above 1c; return = net / capital).
4. **Selection**: the recipe with the highest **mean** return over the six folds, among recipes keeping at
   least 200 fills in every fold. The worst fold and every fold are reported. If W3 is selected, nothing
   changes. If W1 or W2 is selected, that window's model becomes the primary arm `g2` for all verdicts
   (§5, L8) before any live P&L, and G2-W3 becomes a secondary arm; the universe (L1, L4) is unchanged.
5. The September fold's offline score is reported beside A13's simulator figure for the same window.

**Disclosed now.** The selection uses the same September month as A13 plus five months inside W3's training
period; the folds are offline (no inventory interaction); the universe's weather exclusion was decided on
W3's September result, which favours W3 in the live comparison regardless of this rule.

**Prediction (before running).** W3 has the highest mean; W1 has the most variable folds.

**L7 addendum, continued (2026-10-13 16:10 UTC, before any live P&L).** Hour 20261013T14 was not produced: the
late T13 cycle (started 13:57) ended at 14:26, and the producer loop by design waits for the next full hour
after any cycle. Normal hourly operation resumed at T15 (1,909 s). Gaps attributable to the 2026-10-13 batch
jobs and outage: T09, T11, T14 (not produced), T13 (order window about 2 min), T08, T10, T12 (late).

**L9 result (2026-10-14 03:00 UTC, before any live P&L).** Mean return over the six folds: W1 +1.53%, W2 +1.88%,
**W3 +2.65%** (worst month: W1 +0.90%, W2 -0.40%, W3 +1.95%); W3 positive in all six months and best in four.
**W3 is selected; the headline arm `g2` (G2-W3) is unchanged.** W3's April-August folds equal A15's `hgb_a12`
exactly. September fold, offline score: W3 +2.36% (A13 simulator figure for the same window: +1.41%, which
includes inventory interaction). Prediction partly held: W3 highest mean; the most variable recipe was W2,
not W1. Files: `results/live/l9_window_selection.json`, `logs/v2_forecast/l9_window_selection.log` (resumed
run; the first run, interrupted after 8 of 18 fits, is in `l9_window_selection_interrupted.log`).

**Exploratory note (2026-10-14, before any live P&L; no decision depends on it).** After L9, the same six folds
are scored for the baselines the live test uses, offline: random selection at W3's kept share (mean of 20
seeds), `wide3` (spread >= 3c), `liq` (trades_24h >= the fold month's median; the live rule uses the hour's
median, which the stored table cannot reproduce), and the `lin2` and `mlp2` designs refit per fold on the
same windows as W3 (September: the frozen `lin2`/`mlp2`). Reported as exploratory, pre-live context for the
live comparisons; it changes no arm, rule or verdict.

**Exploratory note 2 (2026-10-14, before any live P&L; no decision depends on it).** Volume-matched comparison of
G2-W3 and `lin2` on the six L9 folds: each model's top-ranked candidates at fixed shares (2, 5, 10, 15, 20, 25,
30, 40% of each fold's candidates), return and net P&L pooled over the folds, beside each model's own 1c rule.
Answers whether `lin2`'s higher return comes from ranking or from posting fewer orders. Changes no arm, rule
or verdict; the pre-registered `g2` - `lin2` comparison stays in net return, with net P&L reported beside it.

**Exploratory note 3 (2026-10-14, before any live P&L; nothing is selected or deployed).** Sensitivity analysis of the
neural baseline `mlp2`, to check whether its instability comes from its fixed settings. Eight settings, each one
change from `mlp2` (as A15 for G2): `mlp2` itself; hidden (32); hidden (128, 64); hidden (64, 32, 16); L2 1e-3;
L2 1e-2; learning rate 3e-4; tanh activation. Same six folds as L9 (2026-04..08 from A15's table, trained on all
earlier months; September trained on all months through 2026-08), same time-ordered early stopping, A15's offline
score. Reported per setting: every fold, mean, worst month, months positive, beside G2's recipe and `lin2`. No
setting is selected, adopted or added as an arm; `mlp2` stays as frozen in L6.

**Exploratory note 4 (2026-10-14, before any live P&L; nothing is selected or deployed).** Volume-matched curves
completed for both baselines and both years: G2-W3's recipe vs the `lin2` and `mlp2` designs on the six L9 folds
(2026; `mlp2` refit per fold with its default settings, as in note 3), and the frozen G vs `lin2-2025` and
`mlp2-2025` (A16 models) on G's test months 2025-08..11 (features month by month, BROAD pessimistic candidate
fills). Each model's top-ranked candidates at 2, 5, 10, 15, 20, 25, 30, 40 and 50% of candidates; return and net
P&L pooled per year; offline scoring (no inventory interaction), as note 2.

**Exploratory note 5 (2026-10-14; diagnostic, nothing selected).** Pick overlap behind note 4: at each matched share,
the fraction of G2's (2026) / G's (2025) selected candidates that the linear and the neural design also select, per
year, same models and data as note 4. Tests whether the 2025 convergence at high shares is mechanical overlap.

## Amendment L10 (2026-10-14, BEFORE any live fill, outcome or P&L is computed): live paper-trading ledger; the forward-test verdicts use live-ledgered hours only

**Why.** The supervisor (2026-10-14) requires live paper trading, not a replay of logged decisions: results must
be recorded as time passes, without knowledge of the future. Decisions are already live (the producer); this
amendment makes the fills and P&L live too.

**Changes (fixed now).**
1. **Ledger** (`stg_infra/paper_ledger.py`, run by `paper_trader.py --loop --ledger --fleet` in the production
   sandbox, started and watched by the keeper). Each round (hourly, in the producer's quiet minutes), for every
   completed hour not yet recorded, one entry file is appended (`runs/live/paper/ledger/entries/<hour>.json`):
   that hour's new fills per order window and arm (L4 primary universe), the events settled since the previous
   round with each arm's realised P&L, and cumulative realised, unrealised (open positions at the latest
   logged mid, net of fees) and total P&L, capital and return per arm, plus the verdict statistics so far.
   Entries are hash-chained (each carries the previous entry's sha256) and never rewritten.
2. **Re-verification.** Every round recomputes all fills; recorded fills must match exactly (L3 item 3).
   Any mismatch is recorded in the next entry and reported; recorded entries are never repaired.
3. **Third-party timestamps.** Each round posts the newest entry's summary (cumulative P&L of the main arms,
   the one-sided verdict bounds so far) and its hash to Research Fleet as a FlowMesh job (`fwdtest-pnl-<hour>`).
4. **Live start S** = the first ledgered hour, recorded in `ledger/state.json` and the report. **The verdicts
   of §5 (one-sided, L8) are taken on fills in hours >= S only.** Hours from the L2 fix to S are computed by the
   same engine as a replay and reported separately, labelled replay, never pooled into the verdicts.
5. **Reporting.** Hourly P&L = change in total P&L between entries; cumulative realised P&L is the verdict basis
   (settled events, as §2). Cuts unchanged (interim 2026-10-28, final 2026-11-11); the interim cut covers live
   hours from S.
6. Unchanged: arms, models, rules, universe, order windows, statistics (L3-L9).

**L10 note (2026-10-14, before the live start).** The paper trader now runs the fill models section 4 already commits
to: pessimistic (verdicts), optimistic and strict (bounds) on the primary order window, each its own ledger stream
(`primary`, `primary_opt`, `primary_strict`), plus the L3 decision-time sensitivity (pessimistic). Found missing in
review before any live P&L; no change of rule.

**Section 6 implementation note (2026-10-15, before the live start).** `stg_infra/cut_report.py` computes the cut
metrics from the live ledger. Daily series: the ledger's total P&L (realised + marked, net of fees) at each UTC
day's end; daily return = change / peak capital in open positions over the live period (section 6's "peak capital
committed"); annualised over 365 days (Kalshi trades every day); Sharpe over the mean 3-month T-bill rate (FRED
DTB3); maximum drawdown of the hourly total-P&L curve. Index benchmark: Stooq SPY close where available, else
FRED SP500 (price index without dividends, about 0.1 point per month below SPY's total return; the source used is
printed in the report). Added descriptive metrics: fill rate, hit rate, top-10-event profit share, fees paid,
peak open capital, 1-hour markout. Reporting only; no rule changes.

## Amendment L11 (2026-10-15, BEFORE any live fill, outcome or P&L is computed, and BEFORE the check below is run): the weather exclusion is decided on the six-month walk-forward

**Why.** L1 excluded weather series (`KXHIGH*`, `KXLOW*`) on one validation month (G2-W3 weather -1.60%, CI -5.2 to
+2.0, not significant). The six walk-forward months of L9 allow a stronger basis.

**Rule (fixed now).** G2-W3's recipe (all history, G2 settings) is scored on the six L9 folds (2026-04..08 from A15's
table, each trained on all earlier months; 2026-09-07..10-05 with the frozen G2-W3), restricted to weather series
(category Climate and Weather; within the 23 A13 series these are exactly the `KXHIGH*` series), with A15's offline
score (fills predicted above 1c; net / capital). **If the mean weather return over the six folds is > 0, weather is
re-included in the primary universe (L4) before the live start; otherwise the L1 exclusion stands.** Non-weather is
scored the same way and reported beside it.

**Also (reporting only, whatever the outcome).** The live report adds a descriptive `weather` universe (all
`KXHIGH*`/`KXLOW*` series the producer scores; never a verdict) and a trade-date daily series (each fill's final net
on its quoting day) beside the equity-curve series, so Sharpe and drawdown are computed as in the 2025 results.

**Prediction (before running).** Weather mean negative; the exclusion stands.

**L11 result (2026-10-15, before any live P&L).** G2-W3's recipe on weather, six folds: +2.66, +2.12, +2.94, +2.80,
+0.43 and about -1.36% (Sep), **mean +1.60%** (5 of 6 positive); non-weather mean +4.94% (6 of 6). By the rule,
**weather is re-included in the primary universe** for every arm and both cuts; the L4 pool without weather is
reported as the descriptive `non_weather` universe, and weather alone as `weather`. The prediction (exclusion stands)
was wrong. File: `results/live/l11_weather_split.json`.

**Exploratory note 6 (2026-10-15, after L11, before any live P&L; descriptive, no decision depends on it).** The
model's weather edge by month (`stg_infra/examples/weather_edge_by_month.py`, `results/live/weather_edge_by_month.json`):
picks earned +1.3 to +3.1c per contract in 2025-05..12 (6 of 8 event-cluster CIs above 0; Sep 2025 the best, +3.07c,
so not seasonal) and +0.3 to +2.0c in 2026-01..08 (no CI above 0, intervals about twice as wide), then -0.99c
[-3.59, +1.52] in 2026-09-07..10-05. Each of Aug and Sep 2026 is within noise of the 2026 level, and a similar dip
(Jan-Feb 2026) reversed. The clearer change is 2025 -> 2026: a smaller, noisier edge while median weather trades in 24 h
rose from about 50 to 300-380.

## Amendment L12 (2026-10-15, BEFORE the first ledger entry): host fallback and missing hours

**Incident.** The last hourly Research Fleet record from the Lumid producer is 2026-10-14 12:31 UTC (hour T12). From
then the Lumid office sandbox service did not answer authenticated API calls or ssh (checked 10:27-10:33 UTC on
15 Oct; lum.id itself answered). The outage began in the keeper's handover window, so the most likely cause is that
the handover could not create the next sandbox and the running one expired; this is not verified. Hours from T13 on
14 Oct until the fallback starts are lost (reference hours only; the ledger had not started).

**Fallback.** While Lumid is unavailable, the producer runs on the laptop (`stg_infra/laptop_fallback.sh`): same code
and models, `--loop --fleet`, so each hour is still hashed and recorded on Research Fleet. The paper trader and ledger
run on the same host as the producer. Exactly one producer runs at a time; moving back to Lumid is done by stopping
the laptop producer first, and every move between hosts is recorded here with its time.

**Missing hours (fixed now).** An hour with no live snapshot is missing. It is never reconstructed later from
historical prices (that would be a replay), and it is excluded from every arm alike. Verdicts are computed over the
hours actually recorded; the report lists every gap with its cause. A host change does not reset S or the ledger.

## Amendment L13 (2026-10-15, BEFORE the first ledger entry): fewer Kalshi calls, same data

**Why.** The producer made about 5,800 Kalshi calls an hour (one candle call and one trade call per leg). Lumid's
home site shares one outbound address whose Kalshi allowance other users mostly consume (at 1 request per 20 s,
3 of 4 succeed; at 8/s, 0 of 50), and any host is more robust with fewer calls. Only *how* the data is fetched
changes; the data, its timing and every feature are unchanged.

**Change (`--bulk`).** (1) Price history: Kalshi's batch candle endpoint, 100 legs per call, same window and
parsing (~4,600 calls -> ~50). (2) Trades: a leg's trades are fetched only if the listing's total traded volume
changed since its last fetch; otherwise the stored trades are complete. Trades after H are kept in the store and
cut at H when features are computed (without this, a trade between H and the listing would be counted in the volume
yet dropped, and lost on a skipped leg -- found and fixed before any use).

**Equivalence (before use).** Self-tests: batch == per-leg candles; skipped-leg trades seen by the features equal a
full per-ticker refetch, including a trade one minute after H. Live data, 2026-10-15 11:00 UTC hour: per-leg and
batch candles for 500 random open legs (3,262 candles) identical, 0 mismatched legs (526 calls vs 5). Every hour,
an audit refetches up to 30 skipped legs and logs any trade missing from the store (`skip_audit` in the hour's
summary); any miss is reported, and the affected hours are listed in the report.

## Amendment L14 (2026-10-15, BEFORE the first ledger entry): an independent public timestamp each hour

**Why.** Research Fleet's job service also runs on Lumid's office site: since the outage every hourly post fails
("502 compute service unreachable"), so the scores had no third-party timestamp. Hour 2026-10-15 T11 (the first laptop
hour) has no Research Fleet record for this reason.

**Change.** Each producer hour, the audit record (H, snapshot time, decision time, sha256 of the hour's score and signal
files, model ids) is written to `runs/live/stamps/<H>.json` and submitted to the public OpenTimestamps calendars
(`ots stamp`, `--ots`); each ledger round does the same for the ledger head (entry hash and previous hash,
`runs/live/paper/ledger/stamps/`). The calendars' receipts are upgraded to Bitcoin attestations with `ots upgrade`
before each cut, and `ots verify` checks them. Research Fleet records continue whenever Lumid answers; either record
is sufficient. A failed stamp is logged in the hour's summary, never fatal.

## Amendment L15 (2026-10-15, BEFORE any verdict is computed): first ledger voided after its own check failed; ledger restarted

**What happened.** The ledger started on the laptop at 15:54 UTC (first entry H = 2026-10-15 T15). Its second round
(entry T16) reported verification issues on every arm: re-simulated fills for T15 differed from the recorded ones. Two
defects in the paper trader, neither in the producer or the models:
1. *Tape alignment.* `fetch_tape_hour` built price/count/side with one sort (time, price, count, side) and ticker/
   trade id with another (time only). Trades sharing a timestamp could be paired with another trade's market or
   price (up to 110 trades an hour sat on timestamps shared across markets).
2. *Tie order.* `load_tape` sorted by (ticker, time) only, so the order of same-timestamp trades (5,445 of 10,926 in
   T15) was arbitrary run to run; fill splits changed and, through the per-event inventory limit, fill totals too.
Also the check compared pre-start reference hours (never recorded) and reported them as extra; corrected.

**Fix (commit 0fa7bfe).** Tape columns from one sorted list; ties broken as in every backtest (time, price, count,
side, then trade id); the check covers only hours >= the ledger start. Self-tests: alignment under shared timestamps;
one order for 20 shuffles; pre-start fills not compared.

**Determinism on live data (before restart).** All tapes refetched with the fixed code (same trade counts per hour).
Two consecutive ledger rounds in a test folder: round A (tapes to T16) wrote T16; round B (tapes to T17, active-event
recomputation) re-derived T16 identically and wrote T17: 0 verification issues, chain ok, 0 candidate mismatches, all 13
arms (`logs/v2_forecast/l15_determinism_round{A,B}.log`). The Lumid blind tests ran one round only, which is why this
was not caught before.

**Restart.** The two-entry ledger (`runs/live/paper/ledger_void_20261015`), the old tapes and the g2 selection archive
are kept, marked void, and never used. The ledger restarts empty; the new first entry is the new S (L10). No verdict or
P&L figure from the void ledger was computed or looked at.

**L12 host log.** 2026-10-15 (UTC): 10:36 laptop producer service started (first cycle T11, failed 11:46 under
Kalshi throttling caused by Claude's concurrent tests; rerun late at 11:59 with `--bulk`); 12:27 restarted with `--ots`
and the loop fix (T12 late, snapshot 12:28); 15:54-17:54 laptop paper trader (ledger voided, L15); 19:37:43 laptop
producer stopped (last laptop hour T19); 19:39 home sandbox `prod-a` created (4 h lifetime, so its first handover is
observed the same evening), laptop live state copied (trade store, scores, run log, stamps, tapes); 19:44:48 keeper on
home started the producer and the paper trader (fresh ledger). Exactly one producer ran at every moment.
20:44:56 first home handover failed partway: the keeper could not stop the producer it had started (home forbids
signalling another session, own children included; PermissionError), leaving `prod-b` created and idle while `prod-a`
kept running. Fixed (1f2e395): no signals; the successor's keeper waits until the predecessor is deleted via the API.
20:56:23 new keeper started in `prod-b` (waiting); 20:56:37 `prod-a` deleted (its producer, paper trader -- first
round unfinished, no entry written -- and old keeper stopped with it); 20:56:39 `prod-b` started producer and paper
trader. One producer at every moment; producer hours T20 (prod-a) and from T21 (prod-b).
2026-10-16 01:48:47 keeper handover test (`--handover-now`, the code path of the automatic handover): `prod-b` created
`prod-a` (4 cores / 16 GB; paper rounds had taken ~1.9 h on 2 cores), confirmed its keeper waiting, deleted itself at
01:49:14; 01:49:30 `prod-a` started producer and paper trader (paper round for T00-T01 restarted; no entry lost). Ledger
S = 2026-10-15 T19 (first entry on home); entries T19-T23 written with 0 verification issues.

## Amendment L16 (2026-10-16, reporting/operations only; no rule, model or statistic changes): off-site backup and stall alert

**Why.** Lumid keeps each site's home folder on that site only ("not replicated, deliberately"), so the ledger, scores and
stamps existed in one place; an outage like office's (10-14 on) would have stopped the test and cut off the ledger.

**Change.** Every 10 minutes the keeper copies the run log, every hour's scores, the stamps, the ledger and the tapes to the
repository `curiousfun88/event-pred-live` (`stg_infra/live_backup.py`; deploy key with write access to that repository only;
commits only when something changed, about hourly; never fatal). Not copied: the trade store (rebuilt by a cold-start hour),
signal payloads (derived from the scores), the market cache (refetched). A scheduled check in that repository fails, and
GitHub emails the owner, if the newest producer hour is over 150 min old or the newest ledger entry over 8 h.
**Restore rule.** If the host site is lost, the newest backup is restored on another host (laptop or another Lumid site) and
the ledger continues from its last entry (L12 host change); hours with no live snapshot stay missing (L12).
**Restore drill (2026-10-16 03:1x UTC).** Backup cloned on the laptop: ledger chain verifies (5 entries, S = T19, head
matches state); the newest hour's score file in the backup has the sha256 in its OpenTimestamps record.

## Amendment L17 (2026-10-16, BEFORE any result of the new arm is computed; descriptive only): `liq` is degenerate live; `liq_traded` added

**Finding.** In the live candidates about 80% of legs have no trade in the previous 24 h (11 Oct T15: 77%; 15 Oct T19:
80%; the same before and after L13, so not a fetch artefact), so the hour's median `trades_24h` is 0 and `liq`
("post iff trades_24h >= the hour's median") posts every candidate: live it is identical to `cand` (15 Oct T23: same
2,518 fills, same capital). Offline the rule split candidates 50/50 (median 50-245 trades; 2-3% zero) because those
tables were built from filled orders. `liq` stays exactly as pre-registered and is reported with this note.

**Added (descriptive, never a verdict).** `liq_traded`: post iff `trades_24h` > 0 and `trades_24h` >= the hour's median
over the candidates with `trades_24h` > 0 -- the more liquid half of markets that trade, the offline meaning of `liq`.
Same fills, fees, limits and windows as every arm. It enters the ledger from the first round after deployment; the cut
report also computes it from the paper trader's deterministic recomputation over all hours from S (L15 showed
recomputation is exact), and reports `g2` - `liq_traded` beside `g2` - `liq`.
**L17 cut procedure.** The ledger round recomputes only events active in the last 4 days, so before each cut the paper
trader is run once in full (`python stg_infra/paper_trader.py --run`, no ledger, every event) on the copy of `runs/live`
the cut is computed from; `cut_report.py` then reads `liq_traded` from that recomputation for every hour from S.

**Operations note (2026-10-16; no change to any rule, model or statistic).** Paper-trader rounds on home took 1.6-2.6 h,
almost all waiting on Kalshi: the settlement refresh made one call per active event (~2,650) through home's throttled
address. It now fetches an event whole only when new, when a candidate leg is uncached, or once per 24 h, and otherwise
refreshes known legs 100 tickers per call. Same cache contents: self-tests, and on 60 live events (426 legs, 18 of them
settled since the cached copy) the batched and per-event refreshes agreed on every leg (0 mismatches; 5 calls vs 60).
Active from the next sandbox handover.
**L16 alert verified in practice (2026-10-16).** A commit made on GitHub in the backup repository (the alert workflow,
03:16 UTC) left the sandbox's clone behind, so backup pushes were refused for 5.5 h; the staleness check failed from about
04:30 UTC and GitHub emailed the owner ("live-test-staleness: All jobs have failed"). Fixed 08:42 UTC (clone rebased, 18
backup commits pushed, none lost); the backup now pulls before pushing.
2026-10-16 08:40 UTC handover prod-a -> prod-b (batched settlement refresh live; rounds 2.6 h -> 5-20 min); 13:40 UTC
handover prod-b -> prod-a (ledger check compares an arm from the hour it joined; backup pulls before push; public dashboard
summary). One producer at every moment. Public dashboard: https://curiousfun88.github.io/event-pred-live/ (reads the
backup's site/summary.json). Entries 10-16 T08-T10 carry check notes on liq_traded's pre-join hours only (nothing
recorded missing); a check artefact, not a ledger discrepancy.

## Amendment L18 (2026-10-16): main result on the 23 backtested series; the full universe as a secondary test of generalisation

**What changes.** The main reported result (the verdicts of §5: G2's return with the L8 one-sided bound, and G2 minus
`rnd2`) is computed on the **23 series on which the strategy was trained and backtested** (`SERIES_A13`; the `train23`
universe of §7), for every arm and both cuts. The full live universe (all 290 non-weather pool series plus weather) is
reported beside it, in full and unchanged, as a **secondary test of whether the strategy's hourly quoting edge
generalises to markets it never saw**; it was the original headline, fixed before the start. Nothing about trading, fills,
the ledger or any other statistic changes; only which universe is presented as the main result.

**Counted from.** The main result uses only live hours after this amendment is public: quoting hours from **2026-10-16 17:00 UTC** to each cut. Hours from S (2026-10-15 T19)
to 2026-10-16 T16 are reported in full but are not part of the main result. The full-universe result covers every hour
from S, as before. For a like-for-like comparison the full universe is also reported over the same hours as the main result
(from 2026-10-16 17:00 UTC), descriptively, beside the full-universe result from S.

**Why.** Every backtest (G's 2025 test, G2's training, the six-month walk-forward and the September validation) used the
same 23 series, so those 23 are the scope on which the strategy was validated. The main result should test the strategy
where it was validated; whether it carries over to other series is a separate question, which no backtest addressed.

**Incident 2026-10-16/17 (L12 host log).** From 2026-10-16 T23 the producer's Kalshi requests from Lumid home's shared
address were throttled for long stretches; with 12 retries (~5 min) per request every cycle failed, so hours
2026-10-16 T23 and 2026-10-17 T00-T03 are missing (L12: never reconstructed; excluded from every arm alike). The backup
heartbeat went stale and the stall alert emailed the owner (00:54 UTC). Fix d12f24b: up to 15 min of retries per request,
honouring Retry-After, rate 3/s; handover 04:30 UTC; T04 then ran late (snapshot 04:34 UTC, decided 05:04 UTC).

## Amendment L19 (2026-10-17, before the rule can fire): fallback to the 23 series if producer hours keep failing

**Why.** On 2026-10-16/17 five producer hours were lost to Kalshi throttling of Lumid home's shared address (host log).
Most of the producer's Kalshi requests serve series outside the 23 used for the main result (L18); restricting the
producer to those 23 cuts its requests by roughly 85-90% and protects the main result.

**Rule (fixed now).** Counting from quoting hour **2026-10-17 07:00 UTC**: if **3 or more producer hours fail** (no
completed producer record for the hour) within any 24-hour window, the producer is restricted to the 23 series
(`SERIES_A13`) from the next sandbox handover after the trigger, made at the first quiet minute. Checked with
`stg_infra/l19_switch.py`. If it fires, the full-universe result (secondary, L18) is reported up to the switch hour and
labelled as ended early for this operational reason, with the failed hours listed; the main result continues unchanged.

**Applied now.** The incident of 2026-10-16/17 already meets this threshold (five failed hours, 2026-10-16 T23 and
2026-10-17 T00-T03, within 24 hours; host log above), so the restriction is applied at the first sandbox handover after
this amendment is public; the switch hour is recorded in the host log. From then on every arm trades only the 23 series;
arms whose rule uses an hourly statistic over candidates (`rnd2`'s posting share, `liq`/`liq_traded`'s medians) compute it
over the restricted candidates. The full-universe results cover quoting hours from S to the switch.

**L19 switch (host log).** 2026-10-17 05:40 UTC handover prod-a -> prod-b; from 05:41 UTC the producer runs with
`--series` = the 23 series. Last full-universe quoting hour: 2026-10-17 T05; first restricted hour: **2026-10-17 T06**.
Full-universe results cover quoting hours from S to T05 (L19).

**Incident 2026-10-18/19 (L12 host log).** Kalshi again throttled Lumid home's shared address. Producer hours
**2026-10-18 T17 and T18 are missing** (no completed producer record; L12: never reconstructed; excluded from every arm
alike); the producer recovered at T19 and has recorded every hour since. The paper trader's tape requests for T14-T16
failed after 20 tries in several rounds, so the ledger stayed at 2026-10-18 T13 until the backlog was fetched; the
round of 2026-10-19 ~04:40 UTC wrote entries T14 to 2026-10-19 T02 in order, with T17 and T18 recorded as entries with
no fills. The stall alert (L16) failed at 2026-10-18 22:00 and 2026-10-19 00:16 UTC. No fill, decision or rule was
changed. L19 had already applied. Operations (L16): from 2026-10-19 04:35 UTC the stall alert checks every 10 minutes
(was 30) and fails when the newest producer hour is more than 90 minutes old (was 150).

**Deploy 2026-10-19 (L12 host log).** Files copied to the production sandbox 2026-10-19 ~15:50 UTC (sha256 prefixes:
`paper_ledger.py` 8db076f40b2e, `cut_report.py` c37b9fc64776, `live_backup.py` f581aad23c18, dashboard page
2a0f1b5df0e5; code at event-pred c0810c2); running processes keep their loaded code, so they took effect at the handover
**2026-10-19 23:40 UTC** (prod-b -> prod-a): the L20 fix (first entries written under it: 2026-10-19 T22 and T23, at
2026-10-20 00:39 UTC), the L19 reporting correction, the dashboard changes and the main-result-only daily Research
Fleet record (first: 2026-10-20 02:01 UTC, day 20261019). Checked after the handover: dashboard curve source
"recounted from recorded fills (L20)"; G2 main result settled +$105.56 identical on the dashboard and in the daily record.
Ledger verification has flagged the descriptive L17 arm `liq_traded` in entries 2026-10-19 T19, T20 and T22 (missing
and extra fills on re-derivation, every window); the first two were written before the deploy. No verdict arm is
affected; the cause is under investigation and is recorded here when found.

**`liq_traded` check flags: cause and fix (2026-10-20, L12 host log; no rule, fill or verdict changes).** Cause: a
ledger round re-derives recent hours after filtering the candidates to events active in the last four days, and
`liq_traded`'s rule uses the hour's median `trades_24h`, which over that subset differs from the median over the
hour's full candidate set that the recorded fills used. Checked on 2026-10-19 T19: the subset re-derivation differs
from the recorded picks by 16; with the full hour's median, by 0. The recorded fills follow the L17 rule; only the
check was wrong, and no other arm uses a population statistic. Fix: `paper_trader.hour_medians` computes the medians
before the active-events filter (self-tested with a planted hour whose busy event drops out). The dashboard counts the
flags in entries before 2026-10-21 T00 as explained notes, apart from issues (as the 2026-10-16 pre-join flags); a
flag on any arm in any later entry counts as an issue. Active from the next sandbox handover.

**Research Fleet hourly metrics trimmed (2026-10-20, L12 host log; display only, no rule, fill, ledger or verdict
changes).** The hourly post's metrics listed full-universe running totals (every hour since S, including the throttled
hours after the L19 cut-off), mark-to-market totals, and verdict statistics computed on the full universe, which read
as if they were the main result. `paper_ledger.fleet_summary` now posts only the main result's settled net P&L per arm,
`main_<arm>_net_usd`, and `main_g2_minus_rnd2_usd`, the names the daily record uses. The post's output still carries
the entry hash and the full cumulative breakdown and verdict; the ledger entries are unchanged. Self-tested. Copied to the
production sandbox 2026-10-20 (sha256 e4cab5e30d56; self-test 38/38 there); active from the handover at 20:41 UTC
(sbx_keeper.log; the ~23:40 estimate was wrong).

**Dashboard: secondary result shown as one line (2026-10-21, L12 host log; display only, no rule, fill, ledger or verdict
changes).** The collapsible full-universe section (two tables) is replaced by one line that states the secondary
result, its window (quoting hours 15 Oct 19:00 to 17 Oct 05:00 UTC, L19) and G2's and random's settled net and
return, read live from the same summary file. The full tables stay in the cut report and the report's appendix; the
ledger and summary file are unchanged. Copied to the production sandbox 2026-10-21 02:22 UTC (sha256 a34c97eaedb6); active
from the next backup run.

**Research Fleet posts: home site first (2026-10-21, L12 host log; routing only, no rule, fill, ledger or verdict
changes).** The hourly posts (`fwdtest-hour`, `fwdtest-pnl`) tried the office site first and home only if office
refused; since office's job service returned (2026-10-18) they all landed on office, which the account's Research
Fleet view does not show. They now try home first and office as the backup, as the daily record already did. Home
accepted and then lost some jobs on 2026-10-16; the hourly re-post step reads every posted job back and re-sends any
it cannot read (since a4d0cd6). Jobs already on office stay there. Self-tested (producer, ledger, re-post step).
`fleet_backfill.py` loads the files on each run, so re-posts switch at once; the live producer and paper trader
switch at the next handover after the files are copied. Copied 2026-10-21 02:59 UTC (live_signal_producer 284f3842a2f2,
paper_ledger e331c320e2cc; self-tests on the sandbox: 55, 39 and 6 passed).

**Research Fleet hourly P&L output: main result only (2026-10-21, L12 host log; display only, no rule, fill, ledger
or verdict changes).** The `fwdtest-pnl` job's output carried the full-universe running totals (`cumulative_primary`)
and the verdict statistics computed on them beside the main result, which a reader of the evaluation view could take
for the result. `paper_ledger.fleet_summary` now posts only the entry and previous hashes, the main result's block,
the settlement count and the verification issues. The full-universe figures are unchanged and stay in the ledger
entries themselves, the dashboard's secondary line and the cut report; jobs already posted keep them. Self-tested.
Copied 2026-10-21 08:46 UTC (paper_ledger f69da79a1d21, self-tests pass on the sandbox); re-posts use it at once, live
posts from the next handover.

**Outage 2026-10-21/22 (L12 host log; no rule changes).** Timeline (UTC): 21 Oct 05:29-05:44 three 502 errors from
Lumid's sandbox API; 15:16 the keeper on prod-b could not reach lum.id ("certificate is not valid for 'lum.id'");
15:21 last backup (producer hour 15, ledger entry 14); prod-b then disappeared and, with Lumid unreachable, no
successor was created (no sandbox on either site at 00:24 on 22 Oct; the staleness check failed at 19:29, 22:38 and
00:53). 22 Oct 00:26 a new prod-a was created by hand and the keeper started at 00:35; its network to Lumid, Kalshi and
GitHub worked, but processes reading the home volume hung in uninterruptible I/O (state D): the keeper logged at 00:37
and started the producer (00:38) and paper trader (00:39), which then stalled; by 02:10 no producer hour had
completed. Probable cause: Lumid's home-volume storage (to be reported to Lumid). 02:14 prod-a deleted by API
(home volume kept) so its producer cannot resume beside another; 02:16 the producer started on the laptop under the L12
fallback (`stg_infra/laptop_fallback.sh`, command restricted to the 23 series as L19). **Lost producer hours (L12: never
reconstructed): 2026-10-21 T16 to 2026-10-22 T01** (final list when the sandbox resumes: the volume may hold hours
produced after the last backup). The laptop's first hour, 2026-10-22 T02, completed at 02:17 (snapshot 16 minutes late,
73 s cycle, Research Fleet job on home). A test sandbox at 02:18-02:27 (no keeper started) still read the home volume
about a thousand times slower than normal (5 KB file 15 s, directory listing 29 s, Python start-up over 45 s); deleted.

**Move to the office site (2026-10-22, L12 host log; no rule changes).** The office site's sandboxes read their own
home volume normally (2 ms per file; same library versions as home), reach Kalshi unthrottled and reach GitHub. 03:38
office `prod-a` created (4 cores, 16 GB, 24 h); `stg_infra/restore_on_site.sh office` rebuilt the setup from GitHub (code
and models at 466dda2 from event-pred, model fingerprints identical to the live ones; live state from the
event-pred-live backup: producer record to 2026-10-21 T15, ledger to T14; Research Fleet posted list rebuilt so nothing is
re-posted; 23-series producer command; self-tests pass) and the backup key was copied in. The laptop producer's 04:00
cycle failed at 04:15 (the laptop could no longer reach Kalshi's API at all); it was stopped,
`stg_infra/send_laptop_hours.sh` sent its hours T02 and T03 to office, and the office keeper started at 04:20:11. Office
produced T04 late (snapshot 04:20, 33 s, 90 API calls, Research Fleet job on home) and the backup resumed at 04:20:16.
The ledger continues from its entry T14 on office (catch-up in progress). **Lost producer hours: 2026-10-21 T16 to
2026-10-22 T01** (ten hours, L12: never reconstructed); T02 and T03 come from the laptop and T04 ran late. The live test
stays on office until it ends; office sandboxes are sized as home's (4 cores, 16 GB, keeper change 466dda2).
**Settlement cache after the restore (2026-10-22).** The paper trader's settlement cache (`runs/live/paper/markets.pkl`)
was not in the backup, so office started with none; the dashboard then counted no event as settled, and the ledger's
next entry would have valued every settled event as open. No entry was written: the paper trader was stopped at 04:29
(ledger still ending at 20261021T14), `stg_infra/rebuild_markets_cache.py` refetched all 1,880 events with ledger fills
(14,671 markets, 12,427 settled, 566 s), and the settled figures on the same 140 entries matched the last pre-outage
dashboard except for events settled since (counts only rose; arms without new settlements identical to the cent; G2
+$117.53 on 48 events -> +$118.30 on 51). The paper trader restarted at 04:45:49. From the next keeper start the backup
also stores the cache as text (`markets.jsonl`, 582d019) and the restore rebuilds it. Hours the laptop produces are copied into the home volume's `runs/live` before a sandbox producer
starts again; the paper trader then fills them from Kalshi's tape like any other hour. Positions taken before the outage
settle on Kalshi regardless and are booked when the paper trader resumes.

## Amendment L20 (2026-10-19, erratum; no trading rule, fill, decision, model or outcome changes): repeated identical fills were dropped from the ledger's running totals

**What was wrong.** When one resting order is filled by several trades in its hour, the simulator emits one fill per
trade, and those fills can have identical keys (event, ticker, side, price, contracts, fee, capital, hour). Each is a
real fill. Every entry's `new_fills` lists all of them, and the entry hashes and OpenTimestamps proofs cover that full
list. But `paper_ledger.recorded_fills` read the earlier entries back into a *set*, so each later round counted a
repeated key once. That affected the `cumulative`, `main_result_l18` and `verdict` blocks stored in entries, the Research
Fleet metrics posted from them, and the dashboard curves and cut-report risk figures built from the stored totals.
`verify` also compared sets, so it could not see the difference. Found on 2026-10-19, when the ledger's main-result
G2 realised P&L (+$26.59, entry 2026-10-19 T04) disagreed with the dashboard's settled table (+$28.77). That entry
held 507 recorded main-result G2 fills, but only 431 distinct keys.

**Size (entry 2026-10-19 T04, primary window, pessimistic fills, realised P&L; stored -> correct).** Main result (L18):
G2 +$26.59 -> **+$28.77**; Random -$66.68 -> -$65.18; Quote all -$34.60 -> -$41.20; G2-W1 -$10.51 -> +$9.02. Full
universe from S: G2 -$658.46 -> -$732.06; Random -$1,099.07 -> -$1,291.75; Quote all -$2,758.07 -> -$3,223.97. The error
does not consistently favour any arm.

**Not affected.** The record itself (`new_fills` in every entry, the hash chain and the timestamps); every decision
and fill; and the cut report's verdict figures (net P&L, returns, event- and day-cluster CIs, one-sided bounds), which
are computed from the recorded fill lists.

**Fix (fixed now, before any cut).**
1. `paper_ledger.py`: recorded fills are read as lists, so every repeat counts; `verify` compares counts, not only
   distinct keys.
2. `cut_report.py`: the hourly P&L curve (behind drawdown, daily returns and Sharpe) is recomputed from the recorded
   fills with `paper_ledger.recount_curve`, not taken from the totals stored in entries. Hour H is valued as the
   ledger round for H normally runs, at the end of hour H+1. Events settled by H+2h count as realised; open fills are
   marked at the ticker's latest logged mid at or before H.
3. Dashboard (`live_backup.py`): the curves are recomputed with the same function. The settled table now counts an
   event only once all its legs have settled (it previously counted settled legs one by one); this is the criterion
   used by the cut report and the ledger.
Each change is self-tested with planted repeated fills. On the planted case the old code returns +$0.60 and 1 fill,
where the correct figure is +$1.20 and 2 fills.

**Past entries are not rewritten** (L10). Their stored summary blocks, and the Research Fleet metrics posted from
them, are superseded by the recount; the report says so. Entries written from the deploy hour on compute their
totals correctly; the deploy is recorded in the host log. Verified on a copy of the live record (ledger through
2026-10-19 T04): for every arm, the recounted main-result realised P&L equals the dashboard's settled table. The cut
report gives G2 **+$28.77, +4.04%, 21 events, 236 settled fills** on the main result, the same as the dashboard.

**Exploratory note 7 (2026-10-19, during the live test; offline only, nothing is selected or deployed).** Sensitivity
of the linear baseline `lin2` to its one fixed setting, the ridge penalty (alpha 1.0, L3), which was never varied;
the companion to note 3 for `mlp2` and A15 for G2. Alpha 0.01, 1, 100, 1e4 and 1e5, each a single change from
`lin2`; same six folds as note 3 (2026-04..08 from A15's table trained on all earlier months; September trained on
all months through 2026-08), A15's offline score, own 1c rule. Reported per alpha: every fold, mean, worst month,
months positive, posted share, the largest coefficient change and the posted-set overlap relative to alpha 1.
Gate: alpha 1 must reproduce `offline_baselines.json`'s `lin2` on the five A15-table folds exactly. Live P&L has
been seen by now, but this touches no live hour; no alpha is adopted, `lin2` stays as frozen in L3 and the live
arms are unchanged. **Prediction, written before the run:** with about 680,000 standardised training rows the
penalty is small against the data term, so returns at alpha 0.01-100 lie within +-0.2 points of alpha 1 in every
fold, with near-identical coefficients and posted sets; any material change appears only at alpha 1e4 or above,
and no alpha closes the net-P&L gap to G2, which comes from `lin2` posting few orders, not from its coefficients.
Script: `stg_infra/examples/offline_baselines.py --lin-sens` -> `results/live/lin_sensitivity.json`.

**Note 7 result (2026-10-19; `results/live/lin_sensitivity.json`).** Gate passed (alpha 1 reproduces `lin2` on all
five A15-table folds exactly). Alpha 0.01, 1 and 100 give identical posted sets and returns in every fold (largest
coefficient change 0.03% of the largest coefficient): mean +3.76%, worst +2.84%, 6/6 months positive. Alpha 1e4:
mean +3.78% (fold changes -0.10 to +0.25 points, posted sets 98% the same). Alpha 1e5: mean +4.42%, worst +3.46%,
6/6 positive, but the posted share falls from 5.9% to 4.7% and a quarter of the posted set changes: the stronger
penalty pulls predictions towards the mean, so fewer clear the 1c rule, and the return rises as `lin2` becomes more
selective. That is the posting-share effect note 2 measures, where G2-W3 leads `lin2` at every matched share.
Prediction: the first two parts confirmed (one fold moved 0.25 points at 1e4, just outside the stated +-0.2); the
net-P&L part was not measured by this run. Nothing adopted; `lin2` unchanged.

**Note 7 addendum (2026-10-19, before the re-run).** The prediction's third part (no alpha closes the net-P&L gap to
G2) is now measured: the same sweep re-run with each alpha's net P&L per fold, beside G2-W3's net P&L from
`offline_baselines.json` (`--dollars`). Gate: alpha 1 must reproduce the stored `lin2` net P&L in every fold. The
prediction stands as written: at every alpha, `lin2`'s total net P&L over the six folds stays below G2-W3's
(+$3,291).

**Note 7 addendum result (2026-10-19).** Both gates passed (alpha 1 reproduces `lin2`'s return and net P&L in every
fold). Total net P&L over the six folds: alpha 0.01-100 +$1,455.04 (identical); 1e4 +$1,441.25; 1e5 +$1,301.41,
against G2-W3's +$3,291.02. G2-W3 nets more than `lin2` in 6/6 folds at every alpha. The higher return at 1e5
(+4.42%) comes with $154 less net P&L. Prediction's third part confirmed. Nothing adopted.

**Exploratory note 8 (2026-10-21, during the live test; offline only, nothing is selected or deployed).** Risk
metrics for G2's 2026 walk-forward (L9 / A15 folds, test months 2026-04..08, G2-W3's recipe), which until now had
monthly returns only: the walk-forward table keeps each fill's month but not its hour. `stg_infra/examples/
wf_risk_2026.py` rebuilds the API-month fills exactly as `tune_gbm.build()` did, keeping each fill's quoting hour, and
computes the 2025 A16 addendum's metrics with `cut_report`'s functions: trade-date daily series, peak open capital,
Sharpe over the 3-month T-bill, maximum drawdown, correlation with the S&P 500; random selection of the same number of
fills per month (5 seeds) as the control. Gates: the rebuilt rows equal the table's rows for every test month (count,
features, net) and each refitted month reproduces the recorded return. A first run was made in a scratch script the
same day and its results seen before this script was written and committed; the committed run reproduces it exactly.
Descriptive only: no setting, window or arm changes.

**Note 8 result (2026-10-21; `results/live/wf_risk_2026.json`, `logs/v2_forecast/wf_risk_2026.log`).** Gates passed
(372,702 rebuilt fills; every month reproduces +1.95/+2.30/+3.26/+3.46/+2.59%). Pooled over 153 days: G2 +$2,962.91
(+2.63%), Sharpe 7.33, maximum drawdown $266.95 (7.8% of $3,433 peak open capital), 66% profitable days, correlation
with S&P daily returns 0.18. Random at the same share: net -$207 to -$991, Sharpe -0.85 to -3.95, drawdown $445 to
$1,004 (22-48%), 41-47% profitable days. Benchmarks 2026-04-01..08-31: S&P 500 +16.9% (FRED price index; the Stooq
SPY download failed), 3-month T-bill +1.5% (3.67% a year). Against 2025 (A16: G, Sharpe 11.7, drawdown $103 = 4.2%,
73% profitable days, correlation 0.12), 2026 is weaker on every measure, consistent with quote-everything losing more
in 2026. The Sharpe is for comparing strategies only (simulated fills, small fast-recycling capital, annualised).

**L19 reporting correction (2026-10-19; implements L19 as written, no rule changes).** L19 fixes the full-universe
result to quoting hours S to 2026-10-17 T05, but the cut report (`headline`) and the dashboard's settled tables
(`live_backup.settled_split`) still counted every hour from S, so from T06 they added the 23 series' later hours to
the "full universe". Both now stop at T05 (`FULL_TO`), and the same-hours table covers 2026-10-16 T17 to 2026-10-17
T05; the cut report's per-arm block (every live hour, so the 23 series only from T06) is labelled as such. The main
result is unaffected. On a copy of the live record (ledger through 2026-10-19 T04), G2 settled-only: full universe
-$732.06 (-5.67%) as previously shown -> **-$760.34 (-6.11%)**; same hours -$168.75 -> -$197.03; main result +$28.77
both ways. The full-universe figures still change as positions from those hours settle. Self-tests cover a planted
post-switch fill. Active on the dashboard from the deploy hour (recorded in the host log).
