# Maker (liquidity-provision) pathway: design and pre-registration

**Status:** pre-registered 2026-09-28, before any simulator code or result.
**Why this pathway.** The supervisor's criterion is a strategy that survives
realistic costs on realistic tapes; the student is to judge which pathways are
worth pursuing. Pathways tested so far all *take* liquidity: pairs trading, MECE
hold-to-settlement, ladders, favourite–longshot. None survives costs (RESEARCH_LOG
§7, `runs/README.md`).

The May–June tape screen shows the only positive after-fee return on the other
side of those trades. Makers in aggregate earn **+2.2% net, CI [+0.6%, +3.6%]**;
on taker-only series, **+1.5%, CI [+0.6%, +2.3%]**, broad-based
(`logs/v2_forecast/taker_maker_screen_2025-05_06.log`). Quoted basket bids sum to
$0.944 and asks to $1.093, so the spread takers pay is what makers collect.

**The question.** Can a *new entrant*, without queue priority, capture that edge
after fees, adverse selection and inventory risk? The aggregate figure cannot
answer this. A fill simulator driven by the actual trade tape can bound it.

---

## 1. Data

| input | source | months |
|---|---|---|
| Trade tape: ticker, time (ns), count, yes_price, `taker_side` | `data/trades/` | all |
| Hourly top of book: best bid/ask OHLC per candle | `fetch_quote_candles.py` | Jul–Sep 2025 fetched; **May–Jun to fetch (development)**; Oct–Nov to fetch (confirmation) |
| Settlement result | `data/markets/` (`result`) | all |
| Fee type per series and fee-change log | Kalshi API, `results/mece/kalshi_series_fee_*.json` | — |

**Universe:** legs of whole MECE baskets in the causal membership
(`results/mece/mece_membership.parquet`), as used throughout the project.

## 2. Month roles (fixed now)

| role | months | use |
|---|---|---|
| **Development** | 2025-05, 2025-06 | build and debug the simulator; **no parameter is tuned here** |
| **Test** | 2025-07, 2025-08, 2025-09 | primary results, scored once |
| **Confirmation** | 2025-10, 2025-11 | never used by any part of this project; reported separately |

Strategy parameters are fixed a priori (§3). None is chosen from data. The
development months exist only to find bugs.

## 3. Strategies (fixed; no others will be reported as results)

All strategies refresh hourly. At the start of hour *H*, orders are posted using
the book known then: the close of the candle ending at *H*. They rest until the
end of *H*, then are cancelled and re-posted. Every position is held to
settlement. Tick size is 1¢.

- **S1: join the touch (primary).** On each eligible leg, post a YES bid at the
  quoted best bid and a YES ask at the quoted best ask, **q = 10 contracts**
  each. Post only when the quote is two-sided (0 < bid < ask < 100) and the
  spread is at least 2¢.
- **S2: improve by one tick.** As S1, but at bid+1 and ask−1, only when the
  spread is at least 3¢. This puts us first in the queue at a new price level.
- **S3: basket completion (uses the constraint).** Post YES bids at the best
  bid on **every** leg of a basket, and only when Σ bids ≤ 1.00 − (sum of maker
  fees at those prices), q = 10 per leg. This targets a complete basket bought
  below $1. Partial completion leaves directional inventory, which is held and
  scored as is.
- **S4: S1 filtered by the model (tests the STGAT).** As S1, but skip posting a
  side when the causal STGAT (`v2_mece_causal_s{0..3}`, trained on May–June)
  predicts a move against that side over the next snapshot larger than the
  half-spread. For a bid, that means predicted price change < −½·spread. Scored
  on September only for the "clean" claim, since July–August were its selection
  months; reported on all test months with that caveat.

**Risk limits (all strategies):** |net position| ≤ 50 contracts per leg and ≤ 200
contracts per event. Once a limit is hit, that side stops quoting until the
position falls back.

## 4. Fill models (both reported for every strategy)

Kalshi semantics: `taker_side == "no"` means a taker **sold YES into resting
bids** at `yes_price`; `"yes"` means a taker **bought YES from resting asks**.

| | resting YES bid at *b* fills when… | resting YES ask at *a* fills when… |
|---|---|---|
| **Optimistic** (front of the queue) | a `taker_side=="no"` trade prints at yes_price ≤ *b* | a `taker_side=="yes"` trade prints at yes_price ≥ *a* |
| **Pessimistic** (back of the queue) | a `taker_side=="no"` trade prints at yes_price **< *b*** (the level at *b* was exhausted) | a `taker_side=="yes"` trade prints at yes_price **> *a*** |

- Fill size is `min(remaining order size, trade count)`, accumulated over the
  hour's trades in time order. The fill price is always our limit price.
- For S2 (a price level nobody else occupied), optimistic and pessimistic
  coincide: a trade at or through our price fills us, as we are alone at the
  front.
- Our orders are assumed not to change other traders' behaviour. Cancellation
  is instant and free. No latency is modelled beyond the hourly refresh.

## 5. P&L and fees

- Per fill: **settlement payoff − fill price − maker fee**, in cents.
- The maker fee applies only on series whose `fee_type` charges makers at the
  fill month: 0.25¢/contract before 2025-07, then
  `ceil(0.0175·C·P·(1−P))`. No rebates or market-maker programme benefits are
  assumed.
- Also reported:
  - **1-hour markout:** quoted mid one hour after the fill, minus the fill
    price. This measures adverse selection separately from the outcome.
  - Fill rate, inventory held at settlement, and capital lockup in contract-days.

## 6. Reporting and inference

- Net return = total net P&L / total capital committed at fill prices. Also
  reported: net ¢ per contract, and total $ at q = 10.
- 95% CI by **event-cluster bootstrap** (2,000 resamples), with k printed.
- Split by: fee type (taker-only vs maker-fee series), category (weather,
  sports, other) and month.
- S4 vs S1 is a **paired** comparison on identical quote opportunities,
  clustered by event.

## 7. Decision rules (fixed now)

Applied to the **pooled test months** (Jul–Sep):

| outcome | verdict |
|---|---|
| S1 or S3 **pessimistic** net return > 0 with CI excluding 0 | **Pathway viable**: survives realistic costs even from the back of the queue |
| S1 **optimistic** net return ≤ 0 (point estimate) | **Pathway closed**: even front-of-queue fills do not survive |
| anything else | **Indeterminate**: the verdict depends on queue position, which historical data cannot resolve; report the bounds |
| S4 − S1, pessimistic, paired > 0 with CI excluding 0 | **The model adds value** as an adverse-selection filter |

The October–November confirmation months are run once, after the test verdict,
and reported whatever they show.

## 8. Predictions (before any code)

- S1 optimistic: positive, +1% to +3% (close to the aggregate maker figure).
- **S1 pessimistic: near zero or negative.** Back-of-queue fills are adversely
  selected. **Verdict most likely indeterminate or closed.**
- S3: fewer fills, and most baskets only partly completed; the result is
  dominated by directional inventory. Not better than S1.
- S2: more fills, worse markouts. Not better than S1.
- S4 vs S1: small improvement, not significant.

## 9. Known limitations (stated now)

- Hourly top of book, not tick-level: the posted quote can be up to an hour
  stale, and intra-hour book changes are invisible.
- No depth or queue data. The two fill models bound the truth; they do not
  measure it.
- Kalshi account position limits and market-maker programme terms are not
  modelled.
- The maker fee rates come from secondary sources (the primary fee PDF is
  unreachable from this network). Per-series fee types come from the Kalshi API,
  whose change log starts 2025-10-04.
- July–August were validation months for the STGAT, so only September gives a
  clean S4 result.

## 10. Build order

1. Fetch May–June quotes (development) and Oct–Nov quotes (confirmation).
2. Build `stg_infra/simulate_maker.py` with a `--self-test` of planted tapes and
   known fills, covering optimistic/pessimistic fills at, through and away from
   the price, partial fills, position limits and fees. Run it only on
   development months until it is correct.
3. Freeze the code, then run the test months once. Report against §7.
4. Run the confirmation months once. Report.

---

## Amendment A1 (2026-09-28, before any simulator code or result)

**Objective, per the student:** find a strategy with positive net PnL under
realistic costs. To pursue that without producing an overfit, pseudo-profitable
backtest:

1. **Strategy search is allowed on the development months only (May–June).** A
   declared grid (below) is evaluated there, and the search is free to be
   aggressive. The simulator **refuses** to run the grid on any month from
   2025-07 onward.
2. **Selection rule, fixed now:** highest **pessimistic** net return on
   development, among configurations with at least 300 fills and at least 30
   distinct events filled. Ties go to more fills.
3. **The selected configuration is frozen and committed**, and then run **once**
   on the test months (Jul–Sep), under both fill models. The pre-registered S1
   is run beside it as the reference. Nothing else from the grid is evaluated on
   test.
4. **Verdict** (as §7, applied to the selected configuration): viable if its
   pessimistic test return is > 0 with the event-cluster CI excluding 0.
   October–November confirmation follows once.
5. The fill models, fees, settlement P&L and position limits (§4–§5) **cannot
   be changed** to improve results. Realism is not a tuning parameter.

**Declared grid** (maker only, hourly refresh, held to settlement):

| dimension | values |
|---|---|
| sides quoted | both; bid only (buy YES); ask only (sell YES) |
| price level | join the touch; improve by 1¢ (needs spread >= 3¢) |
| order-price band (¢) | 1–15; 15–85; 85–99; 1–99 |
| minimum quoted spread (¢) | 2; 4 |
| series | all; taker-only (no maker fee) |
| order size q | 10 |
| basket mode (S3) | off; on (bids on every leg when Σbid <= 100 − Σ maker fee) |

That is at most 3 × 2 × 4 × 2 × 2 × 2 = 192 configurations. The model filter
(S4) is evaluated only as an add-on to the selected configuration, on September
(clean for the STGAT).

## Amendment A2 (2026-09-28, before any simulator result)

**Scale to the full 13-month dataset (2024-11 to 2025-11) without re-running
anything.**

| role | months (was) | months (now) |
|---|---|---|
| Development (strategy search) | 2025-05, 2025-06 | **2024-11 to 2025-06** (8 months; covers winter and summer) |
| Test (scored once) | 2025-07 to 2025-09 | unchanged |
| Confirmation (never used) | 2025-10, 2025-11 | unchanged |

- **Universe:** legs of **causally qualified** MECE families (membership
  `q_from <= leg_created`, so no hindsight), with hourly quotes. Legs are now
  found from the membership file and the trade tape, not from a graph cache, so
  any window works.
- **No re-runs:** quotes are fetched only for legs and time ranges not already
  on disk. Every simulation is cached under a key of (config, fill model,
  months, simulator version). The development search resumes where it stopped.
- The selection rule, grid, fill models, fees and verdict rules of A1 are
  unchanged.

## Amendment A3 (2026-09-28, before the development search)

**Disclosure.** The only simulator output seen before this amendment is S1
(the pre-registered reference) on May–June 2025, a development-only timing
run: optimistic +0.19% [−0.42, +0.77], pessimistic −2.17% [−2.89, −1.41]. No
test month has been simulated.

**Objective (student): maximise the honest chance of positive net PnL.** Three
dimensions are added to the development grid. All are decidable at quoting
time. Test months remain untouched.

| dimension | values | rationale |
|---|---|---|
| **universe** | `mece` (causal membership, as before); `liquid` (every market with downloaded quotes: >=20 trades over the window, about 98% of all trading) | the maker edge in the tape screen is market-wide; about 10x the fill opportunities |
| **causal liquidity rule** | quote a leg only if it had >= {0, 5} trades in the **previous 24h** | concentrate on active markets. The download scope (>=20 trades over 13 months) is known only after the fact and is **never** used as an eligibility rule |
| **inventory cap** | {50, 25} contracts net per leg | limits directional exposure built up by adverse selection |

- Basket mode (S3) runs in the `mece` universe only.
- The selection rule is unchanged (best pessimistic development return, >=300
  fills, >=30 events), taken over both universes. The best configuration **per
  universe** is also reported.
- **Deferred, not implemented: "stop quoting near expiry"** (motivated by
  Bürgi et al.'s final-day maker losses). The markets file records the
  *actual* close time, which for early-resolving markets is known only after
  the fact, so using it would leak outcome timing. It needs each market's
  *scheduled* close, which the current data lacks.
- Simulator version bumped to 2 (older cached results are ignored).

## Amendment A4 (2026-09-28, before the development search): train / validation / test

Replaces the development/test/confirmation split of A1–A2.

| split | months | what runs there |
|---|---|---|
| **Train** (7) | 2024-11 to 2025-05 | the full grid (A1 + A3). Shortlist = **top 10** by pessimistic train return, among configurations with >=300 fills and >=30 events |
| **Validation** (2) | 2025-06, 2025-07 | **only the 10 shortlisted configurations**. Selected = best pessimistic validation return with >=100 fills and >=10 events; frozen and committed |
| **Test** (4) | 2025-08 to 2025-11 | **only the frozen winner** (plus the S1 reference), run **once**. This is the reported result |

- The strategies are fixed rules, so "train" means the months the search runs
  on. Nothing is fitted.
- **Verdict** (as A1, on the 4 test months): viable if the winner's
  pessimistic return is > 0 with the event-cluster CI excluding 0.
- The simulator refuses the grid on any month from 2025-06 onward.
- **Disclosure:** the S1 timing run (A3) covered May–June 2025, so the reference
  strategy was seen on one validation month (June) before this split was set.
  No shortlisted configuration has been seen anywhere.
- **S4 (STGAT filter):** the current checkpoints used 2025-07/08 for selection
  and 2025-09 as their test, so for S4 only 2025-10/11 are clean. S4 is
  evaluated there, or after the STGAT is retrained or tuned.

## Amendment A5 (2026-09-28, before any search result): MECE universe only

The `liquid` (all-markets) universe added in A3 is **dropped**. The search,
validation and test cover the **MECE universe only**: legs of causally
qualified MECE families.

- **Reason:** resources. The all-markets universe needs about 2 more hours of
  downloading and about 5–6 hours more search on a 7 GB, CPU-only machine.
  MECE is also where the sum-to-one constraint and the STGAT (S4/S5) apply.
- **Scope of claims:** results describe market making on Kalshi's **MECE
  markets** (predominantly weather and sports), not the exchange as a whole.
- **Realism is unchanged:** tape-driven fills, real quotes, current fees,
  queue bounds.
- The grid is now the 448 MECE configurations of A1 + A3. The selection rules
  of A4 are unchanged.
- **No result informed this decision.** The only simulator output seen so far
  is the A3-disclosed S1 timing run.

## Amendment A6 (2026-09-29, after train/validation, BEFORE any test-month simulation)

**Gate 1 outcome (train/validation only).** The frozen winner
(`runs/maker/selected.json`): sell YES 1¢ below the best ask, order price
85–99¢, spread >= 4¢, inventory cap 25, MECE.
- Train: +6.62% [−11.52, +25.78], 3,011 fills.
- Validation: +24.19% [−12.28, +61.28], 1,125 fills.
- Both are positive point estimates, so per the plan the STGAT route (S4/S5) is
  pursued. No test month has been simulated.

**A6.1 Stricter fill check ("strict").** For an *improved* order (bid+1 or
ask−1) the optimistic and pessimistic models coincide, since we are alone at a
new level. That assumes other makers do not also improve. The strict model
fills an improved order only on trades **strictly beyond the original touch**:
- for a bid at b+1: taker sells at yes_price < b;
- for an ask at a−1: taker buys at yes_price > a.

These are trades that would also have swept a competitor who matched our
price. For non-improved orders, strict = pessimistic. It is reported beside
the main result and used for no selection.

**A6.2 Test run of the frozen base (now).** Months 2025-08 to 2025-11, once,
under the optimistic, pessimistic and strict models, beside the S1 reference.
- **Verdict (A1/A4):** viable if the pessimistic return > 0 with the
  event-cluster CI excluding 0.
- Strict and optimistic are reported as bounds.

**A6.3 S4 and S5, fixed now, before the base test is seen.**
- **Signal:** the tuned 7/2/4 STGAT's next-hour quoted-mid-move head (B1.2),
  **averaged over the 4 final seeds**. It is taken from the latest snapshot
  whose window ends at or before the quoting hour H. m̂ = predicted change in
  the mid, in cents; s = quoted spread at H.
- **S4 (filter on the base):** identical to the frozen base, except the ask is
  **not** posted when m̂ > +s/2 (a predicted rise against a seller).
- **S5 (model-led quoting):**
  - universe: all MECE legs;
  - order price 1–99¢, spread >= 4¢, inventory cap 25, improve by 1¢ when the
    spread is >= 3¢;
  - post a bid at b+1 **only if** m̂ > +s/2; post an ask at a−1 **only if**
    m̂ < −s/2; otherwise post nothing.
- **Evaluation:** test months 2025-08 to 2025-11; optimistic, pessimistic and
  strict models; event-cluster CIs.
  - S4 − base is paired on identical quoting hours.
  - S5 is judged on its own return and against the base.
- **Verdicts:**
  - the STGAT adds value as a filter if S4 − base > 0 (pessimistic) with CI
    excluding 0;
  - S5 is a viable STGAT-led strategy if its pessimistic return > 0 with CI
    excluding 0.
- The strict model is reported for both.
- **No parameter of S4/S5 (thresholds s/2, bands, caps) may be changed after
  the base test result is seen.**

## Amendment A7 (2026-09-29, BEFORE any test-month simulation)

**A6.2 timing: the base test is deferred.** It is no longer run "now". It runs
in the same session as S4/S5 (A6.3), once the 7/2/4 STGAT is frozen: B1
implemented, tuning done, 4 final seeds trained. Reason: 2025-08..11 are also
the STGAT's test months, and seeing the base result first could influence the
B1 implementation or tuning. The base config, the fill models, S4/S5 and every
verdict rule are unchanged. No test month has been simulated.

## Amendment A8 (2026-09-29, BEFORE any test-month simulation or STGAT result)

**S4/S5 implementation choices where A6.3 left room** (`simulate_maker.py
--signal`, self-tested):
- **Signal lookup:** m_hat from the latest snapshot with window end E_t <= H
  (a snapshot ending exactly at H is used; never a later one).
- **No signal for a leg at H** (not an observed node, or no snapshot yet):
  S4 posts the base order unchanged; S5 posts nothing.
- **Ties:** the thresholds are strict. S4 skips the ask only if
  m_hat > +s/2; S5 bids only if m_hat > +s/2 and asks only if m_hat < -s/2.
- **Comparisons:** S4 - base and S5 - base in percentage points of return,
  under the optimistic, pessimistic and strict models. The 95% CI resamples
  the union of events, with the same draw for both strategies; an event where
  a strategy has no fills contributes 0 net and 0 capital to it. Verdicts as
  A6.3, on the pessimistic model.
- S5's configuration is fixed in code as `S5_CONFIG` and matches A6.3.

## Amendment A9 (2026-09-29, BEFORE any test-month simulation or STGAT result)

**S4/S5 use only a fresh signal.** STGAT snapshots are 2 h windows ending on
even UTC hours, and the mid-move head at a snapshot ending at E predicts the
quoted-mid move over (E, E+1h]. Under A6.3/A8 as written, at an odd quoting
hour H the latest snapshot ends at H-1h, so m_hat forecasts a move that has
already happened (and is visible in the quote at H), not the hour (H, H+1h]
the order is exposed to.
- **Change:** m_hat is used only when a snapshot ends **exactly at H**. At any
  other hour there is no signal, and the A8 no-signal rules apply: S4 posts
  the base order unchanged; S5 posts nothing.
- **Secondary report (added now):** S4 - base and S5 - base restricted to
  fills from quotes posted at signal hours (H on the 2 h grid), under all
  three fill models, same event resampling. The all-hours comparison stays
  the primary verdict; the restricted one shows the effect where the filter
  operated, without dilution by hours it could not act on.
- Unchanged: the base, thresholds, S5 configuration, fill models, verdicts.
- Rationale is timing correctness, decided before any result; the effect on
  S4/S5 P&L is unknown in sign.

## Amendment A10 (2026-09-29, BEFORE any test-month simulation): robust re-selection of the base

**Why.** The A6 winner was the best pessimistic return on train (448
configurations), then the best of a 10-config shortlist on validation. That
two-stage selection flatters its figures, and on validation it fails the
strict (competing makers also improve) fill model: -4.60%. A10 re-selects for
robustness on development data only.

- **Data:** the 9 development months 2024-11..2025-07, pooled. No test month
  is loaded (`simulate_maker.py --robust` refuses months >= 2025-08).
- **Space:** the A1-A5 grid x `min_ttc_h` {0, 24} (no quote on a leg within
  24 h of its close; losses come from favourites failing near resolution):
  896 configurations, each simulated once over the 9 months under the
  pessimistic and strict models. Monthly returns come from each fill's
  quoting hour.
- **Eligible:** >= 300 pessimistic fills, >= 30 events, fills in >= 7 of 9
  months.
- **Qualifies:** pooled pessimistic return > 0 AND strict return > 0 in >= 6 of
  9 months (a month without strict fills is not positive).
- **Winner:** highest pooled strict return; ties -> more pessimistic fills.
  Written to `runs/maker/selected_a10.json`. If none qualifies, the A6 winner
  stays the primary base and A10 is reported as "no robust alternative".
- **Test run (still once), designated now:**
  - **Primary:** the A10 winner. Verdict as A6.2: pessimistic return > 0 with
    the event-cluster CI excluding 0; strict and optimistic reported as bounds.
  - **Secondary:** the A6 winner (`runs/maker/selected.json`), reported beside
    it whatever it shows.
  - S4 (A6.3/A8/A9) is built on the primary base; S5 unchanged.
  - Command: `--config runs/maker/selected_a10.json --secondary
    runs/maker/selected.json --signal <seed-averaged signal> --months 2025-08
    2025-09 2025-10 2025-11`.
- **Caveats, stated in advance:** the validation months have already been used
  once for selection, and the best of 896 is still optimistic, so the test is
  expected to come in below development. A10 improves robustness; it does not
  guarantee a positive test.
- Runs after the STGAT tuning finishes (CPU/RAM), before any test run.

## Amendment A11 (2026-09-30, AFTER A10, BEFORE any test-month simulation): A10 outcome and predictions

**A10 outcome (development months 2024-11..2025-07, `logs/v2_forecast/after_tuning.log`).**
61 of 896 configurations qualify. Winner, frozen in `runs/maker/selected_a10.json`:
MECE, both sides, improve 1¢, band 85-99¢, spread >= 4¢, taker-only series,
inventory cap 25, `min_ttc_h` 24.
- Pessimistic +21.72% [+7.35, +41.52], 345 fills, 93 events.
- Strict +24.19% [+7.99, +48.24], 144 fills, strict > 0 in 8/9 months.
- The 24 h rule carries the result. The same configuration without it
  scores +3.97% pessimistic and -1.21% strict (6,117 fills). The A6 winner
  over the same months scores +11.24% pessimistic and -9.14% strict (4,130
  fills).

**Predictions, stated before the test run.**
- Primary pessimistic fills: about 130-150 over 2025-08..11 (2025-11 ends
  on the 25th).
- Point estimate positive but well below development (best of 896).
- CI likely includes 0, so the A6.2 verdict (CI excluding 0) is not
  expected to pass. A negative return is plausible: one or two favourites
  failing more than 24 h before close would produce it.
- S4 - base about 0: the signal has no validation skill (7/2/4 §6e,
  mid-move head 1.007x zero-move).
- S5: few fills; return sign unknown; CI wide.

**Not added: whole-basket (Sports) strategy.** An exploratory breakdown on
development months (`stg_infra/examples/explore_basket_maker.py`,
`summarise_basket_explore.py`, `logs/v2_forecast/basket_explore_dev_by_category.log`)
found complete basket fills common only in 3-leg Sports baskets (18-25% of
filled attempts). The P&L lead (+1.07¢/attempt, CI [-0.18, +2.35]) is one
cell of about 28 post-hoc cells. It is dropped, not tested, and reported only
as a direction for future work.

## Amendment A12 (2026-09-30, BEFORE any run of a learned policy on the test months): learned maker policies G and G+S

**Context (development months only).** An offline check (`stg_infra/examples/learned_maker_policy.py`,
`logs/v2_forecast/learned_maker_policy_dev.log`) trained a gradient-boosted model on the fills of the broadest
cached MECE configuration (key `b85bd3c8cb9be1ee`: both sides, improve 1c, 1-99c, spread >= 2c, all series,
inventory 50, event limit 200, no ttc rule, pessimistic fills) to predict each fill's net P&L per contract at
settlement, after fees. On validation (2025-06..07), keeping fills with predicted P&L > 0 gave +2.22c/contract,
CI [+1.51, +2.90], vs -0.01 for quoting everything. The leak audit
(`logs/v2_forecast/learned_maker_policy_leak_audit.log`) passed: shuffled labels give ~0, and the edge survives
without time-to-close (sports `close_time` is the ACTUAL match end, so it is excluded below), without
fee status/category, and on non-sports series. Offline scoring ignored inventory interactions; the policy
is therefore re-validated inside the simulator before any test run.

**Test months already seen.** Aug-Nov 2025 were used for A10/A6/S4/S5 (A6.2/A11). Every result below on those
months is a disclosed later evaluation of the same months. No design choice below uses any test-month result.

**G (primary learned policy).**
- Candidate orders: exactly those of the broad configuration above (same simulator logic).
- Features at the quoting hour H (shared code, `stg_infra/maker_policy.py`): side, order price, order price - mid,
  spread, mid, trades in (H-24h, H], mid change over 24h, basket size, legs quoted, basket sum of mids, best other
  mid, hour of day, maker-fee status, category. **Not** time-to-close.
- Model: `HistGradientBoostingRegressor(max_iter=400, learning_rate=0.03, max_leaf_nodes=31, min_samples_leaf=300,
  l2_regularization=1.0, random_state=0)`, target net c/contract (pessimistic fills), trained on **2024-11..2025-05
  only**, frozen and saved with a hash.
- Rule: post an order only if predicted P&L > **t = 1c** per contract (fixed now).
- Inventory limits, fees, fill models: unchanged simulator.

**G+S (STGAT variant).** Identical to G plus STGAT inputs at H: the seed-averaged Model A (the four
`runs/tune/final_*_s{0..3}` checkpoints) outputs from the latest snapshot ending at or before H and at most 2h
old: next-hour mid-move head (cents) and forecast-head predicted change at horizons 1, 2, 3, 6, 12 (cents);
missing when no fresh snapshot or node. Same training months, model, threshold, gates and verdict.
Known caveat, stated now: the STGAT was trained on the same train months, so its train-month outputs are in-sample.

**Gates and verdict (each variant separately).**
1. Validation gate: in-simulator run on 2025-06..07; proceed to the test months only if the pessimistic
   return > 0 (point estimate). Otherwise report and stop.
2. Test: 2025-08..11, once, optimistic / pessimistic / strict. **Verdict:** pessimistic return > 0 with the
   event-cluster CI excluding 0; strict and optimistic reported as bounds; A10 reported beside it.
3. The STGAT contribution is reported as G+S minus G (pessimistic, same months).
4. G may be run on the test months before G+S is built; G+S's specification above does not change after
   G's result is seen. If G+S cannot be built as specified, that is reported, not redesigned.

No parameter above (features, model, months, threshold, gates, verdict) may be changed after any test-month
result of G or G+S is seen.

## Amendment A13 (2026-10-06, BEFORE any 2026 training data is fetched or any retrained model exists): retrained policy G2

**Context (exploratory, reported).** The frozen G, run unchanged on 2026-09-07..10-04
(`stg_infra/examples/smoke_test_2026.py`, `logs/v2_forecast/smoke_test_2026-09.log`), returned -1.41%
pessimistic (CI [-4.10, +1.36]), the same as quoting everything (-1.45%). The diagnosis
(`logs/v2_forecast/smoke_test_2026_diagnosis.log`) finds the families still present, not a seasonal effect,
a harder market for every maker (weather quote-everything markout +0.31c -> -0.67c per contract, 4.6x more
prints, tighter spreads) and a ranking that no longer finds profitable quotes (top decile +4.1c -> -0.7c).
Question for G2: is this model decay (fixable by retraining) or market decay (not)?

**Seen already.** 2026-09-07..10-04 was used by the smoke test, so it is G2's **validation** window only.
G2's test is the live forward test (`docs/planning/lumid-forward-test-preregistration.md`).

**G2 design: identical to G** except the training months. Same candidates (BROAD config), same features
(`FEATS_G`, no time-to-close), same model and hyperparameters (`maker_policy.HP`), same target (net c/contract
at settlement after fees, pessimistic fills), same threshold t = 1c. No feature, hyperparameter or threshold
is chosen on the validation window.

**Series.** The 23 series of the smoke test: G's 26 test-month series minus KXAPPRANKFREE2 (fails the live
basket rule) and KXDOGE, KXETH (hourly crypto ranges, tens of thousands of legs). Training baskets: events of
these series with 3-100 legs that resolved with exactly one YES (hindsight curation of training data, as for
G's training months). 2024-11..2025-11 come from the local data (`simulate_maker.load`, restricted to these
series); 2025-12..2026-08 from Kalshi's public API (archive and live endpoints), cached as compact arrays.

**Candidate training windows (three, fixed now):**
- W1 recent: 2026-06..2026-08
- W2 medium: 2026-03..2026-08
- W3 long: 2024-11..2026-08

**Selection rule (fixed now).** Each window's model is run on the validation window in the unchanged
simulator, pessimistic fills. G2 = the window with the highest pessimistic validation return **among those
with return > 0**. Also reported for each: optimistic/strict returns, the paired difference vs quoting
everything, and random selection at the same share.
- If no window is > 0: reported; the forward test runs G, random and quote-everything only, and whether to
  add a G2 arm is decided with the supervisor and recorded as a further amendment.
- The selected window's validation return is optimistic (best of three); it is not a test result.

**Descriptive only (never part of the selection):** month-by-month quote-everything returns and markouts
2025-12..2026-09 (when did the market change?), and the similarity of each candidate window's candidate-quote
features to the live market's (the producer's 2026-10-05 snapshot), using features only, no outcomes.

**Live arms if G2 is selected:** G2, G (the 2025 model, as a decay reference), random at G2's hourly share,
quote everything.

## Amendment A14 (2026-10-06, BEFORE any G2 training or validation result): adverse-selection variant G2+

**Why.** The 2026 diagnosis (A13) points to adverse selection: quote-everything markouts in weather turned
negative (+0.31c -> -0.67c per contract). G2+ adds defences against it. It is declared now, before any G2
result, so that G2 and G2+ are a planned comparison, not a retry after a failure.

**G2+ = G2 plus three changes (fixed now):**
1. **Both quote levels as candidates.** For each side, a candidate at the touch and, when the spread is
   >= 3c, a candidate 1c inside (new simulator option `levels="both"`; default off, every earlier result
   and cache key unchanged). The policy posts, per side, the candidate with the higher prediction if it is
   above t = 1c. Training fills come from posting both levels.
2. **Toxicity features** at H, from the trade tape and quotes only: prints in (H-1h, H]; signed taker
   imbalance in (H-1h, H] ((buy - sell contracts) / total, 0 if no trades); mid change since H-1h and
   since H-3h (missing if no quote); an indicator for the improved level.
3. **Time to close for non-sports series**, in hours (missing for category Sports, where close_time is the
   actual match end and would leak).
Everything else as G2: candidates' other rules, the 14 G features, hyperparameters, target, threshold,
series, windows W1-W3, validation window.

**Selection.** The A13 rule applied to all six models (G2 and G2+ x W1-W3): each design's selected window is
its highest positive pessimistic validation return. Both designs may go live as separate arms if both have a
selected window. Comparing six models on one validation window makes the best figure optimistic; the live
forward test is the test.

**Live arms if both pass:** G2, G2+, G (2025 model), random at each model's hourly share, quote everything.

## Amendment A15 (2026-10-11, BEFORE any fold is scored): walk-forward hyperparameter sensitivity of G2

**Why.** G2's hyperparameters were fixed by judgement in A12 and never searched. This asks whether G2's
results depend on them. It is a sensitivity analysis for the report and, secondarily, a possible new
forward-test arm under the "tuned model" clause of the Lumid pre-registration (walk-forward on training
months only, declared first). **G2 and every existing arm are unchanged.**

**Data.** G2-W3's exact training fills: 679,400 rows, 2024-11..2026-08, built by
`stg_infra/examples/tune_gbm.py build`. Refitting the A12 model on this table reproduces the saved G2-W3
model exactly (max prediction difference 0.0). The September 2026 validation window and all forward-test
hours are not read.

**Folds.** Five, strictly forward: test months 2026-04, 05, 06, 07 and 08, each trained on every month
before it.

**Settings (fixed now, `tune_gbm.GRID`).** G2's model (scikit-learn `HistGradientBoostingRegressor`), 14 rows:
`hgb_a12` (G2 itself); leaf size 100 and 1000; 15 and 63 leaves; learning rate 0.1 with 120 trees; 800
trees; L2 penalty 10; 80% of features per split; early stopping on the last training month instead of a
random 10% holdout; recency half-lives of 3 and 6 months; absolute-error loss; a 5-member bootstrap bag.
Each row changes one thing from G2, except the learning-rate row, which changes rate and trees together.
`xgb_a12` (XGBoost, A12-matched, CPU or GPU) is a library **benchmark only** and is never selected.

**Score.** Per fold: candidate fills predicted above 1c (A12 threshold); return = net / capital,
pessimistic fills. Offline: no inventory interaction.

**Selection.** The highest worst-fold return among the 14 rows with at least 200 kept fills in every fold.
If none qualifies, nothing is selected. If `hgb_a12` is selected, G2's settings are confirmed.

**What follows.** All 15 rows are reported fold by fold, with quote-everything alongside. The selected row
and `hgb_a12` are re-run in the full simulator on the same five months. The September validation window is
looked at once, descriptively. A new forward-test arm is added only through a separate dated amendment. No
setting, fold, threshold or rule is changed once any fold is scored.

**Prediction (before measuring).** No row beats `hgb_a12` by much: differences within about +/-1 point of
worst-fold return, because the limit is the noisy target, not the settings.

## Amendment A16 (2026-10-14, BEFORE any run below): the live test's baselines on G's 2025 test months (descriptive)

**Why.** The Lumid forward test compares G2 with rule, linear and neural baselines (L3, L6). G's pre-registered
2025 test (A12: +3.55%, CI +2.51 to +4.60) compared G only with quoting everything, random selection and A10.
Running the same baselines on G's test months shows whether the pattern seen in 2026 also holds in 2025.

**Months already used.** 2025-08..11 were used for A10, A6, S4/S5, G and G+S (disclosed). This is a further
descriptive evaluation of the same months. **G, its result and its verdict are unchanged; nothing is selected.**

**Baselines (fixed now).**
- `wide3`: post iff spread >= 3c. `liq`: post iff trades in the last 24 h >= that hour's median over the
  hour's candidates (the live rule).
- `lin2-2025` and `mlp2-2025`: the `lin2` and `mlp2` designs of `stg_infra/examples/train_baselines.py`
  (defaults, unchanged), trained on **exactly G's training rows** (A12: BROAD pessimistic fills, 2024-11..2025-05,
  `maker_policy.quote_features`), frozen with hashes recorded before the test months are scored.
- Random selection at G's posting share (5 seeds), as in A12's audit.
- Same candidates (BROAD), same simulator, all four months in one run, pessimistic fills; post if score > 1c.

**Reproduction gate.** G re-scored and re-simulated in the same run must reproduce A12 exactly (pessimistic
+3.55%, 34,086 fills, 1,325 events); otherwise nothing below is reported as a result.

**Reported.** Each arm's return, event-cluster 95% CI, fills, events, net P&L; paired differences G - each
(event clusters); the 2026 comparison beside it. Descriptive only.

**A16 gate, first run (2026-10-14, recorded before any baseline figure was looked at).** The first test run
computed features with all four test months loaded together; G gave +3.48% (34,044 fills, 1,325 events) instead
of A12's +3.55% (34,086), and the gate stopped the run. Cause: A12 scored candidates month by month
(`maker_policy.cmd_score` loads one month), so 24-hour features at each month's start differ. The script now
assembles features month by month and additionally requires G's scores to equal A12's saved scores
(`runs/maker/policy_G_scores_2025-08_2025-11.parquet`) exactly before simulating. The baseline lines the first
run printed before stopping were not used. Everything else in A16 is unchanged.

**A16 result (2026-10-14).** Gate passed: G's scores equal A12's saved scores exactly and G reproduces A12
(+3.55%, 34,086 fills, 1,325 events). Pessimistic, 2025-08..11: lin2-2025 +4.03% [+2.94, +5.14] on 18,305 fills
(+$2,427); mlp2-2025 +2.11% [+1.30, +2.92] (+$3,104); wide3 +0.07%; liq -0.05%; random at G's share mean -0.23%
(5 seeds). G minus: random +3.2 to +4.4 (all CIs exclude 0), wide3 +3.47 [+2.50, +4.45], liq +3.60 [+2.64, +4.55],
mlp2-2025 +1.43 [+0.47, +2.38], lin2-2025 -0.48 [-1.73, +0.81]. Models: lin2-2025 `fa45b1b80bdd3d0c`,
mlp2-2025 `676be7ad1458479e`. Descriptive; G and its verdict unchanged.
