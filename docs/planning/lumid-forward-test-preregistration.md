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
