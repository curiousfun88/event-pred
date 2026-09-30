# STGAT on the 13-month window: tuning, 7/2/4 evaluation, and S4

**Status:** pre-registered 2026-09-28, before any cache rebuild, tuning run or result.
**Approved by supervisor:** the 7/2/4 split (train 7 months, validation 2, test 4).

## 1. Split (shared with the maker simulator, amendment A4)

| split | months | STGAT use |
|---|---|---|
| Train | 2024-11 to 2025-05 | fit weights |
| Validation | 2025-06, 2025-07 | tuning selection, checkpoint selection, early stopping |
| **Test** | **2025-08 to 2025-11** | **scored once**, after everything is frozen |

Every quantity fitted from data (feature standardisation, the shrinkage-oracle
alphas used for *selection*) is fitted on train or validation only. The test
oracles are fitted on the test split, deliberately optimistic, as throughout
the project.

## 2. Data

`cache_causal/` is extended to all 13 months with the same causal pipeline
(`run_real_training.py`):
- no carry-forward past close;
- `time_to_close` zeroed as an input;
- ladder edge features zeroed;
- causal MECE membership in validation and test (curated in train).

**Cache for 7/2/4: `cache_724/`.** `cache_causal/` is left untouched, so earlier
results reproduce. The membership rule is chosen per month by its split
(hindsight for train, causal for validation and test), so the build runs under
`FYP_SPLIT=2025-05,2025-07`.
- **Reused** (linked) from `cache_causal/`, because their rule is unchanged:
  2025-05 (train, hindsight), 2025-07 to 2025-09 (causal).
- **Built:** 2024-11 to 2025-04 (train) and 2025-10/11 (test).
- **Rebuilt: 2025-06.** It was a *training* month under the pilot split, built
  with the hindsight rule, but it is *validation* under 7/2/4 and must use the
  causal rule. Reusing it would have put hindsight membership into
  validation.

## 3. Tuning (validation only)

**Objective:** minimise validation MECE MSE (`whole_settle`), the metric
`train_forecast.py` already selects on.

**Search space:**

| hyperparameter | values |
|---|---|
| hidden size (`embed_dim`) | 32, 64, 128 |
| attention heads | 2, 4, 8 (must divide the hidden size) |
| learning rate | 3e-4, 1e-3, 3e-3 |
| dropout | 0, 0.1, 0.2 |
| MECE loss weight | 0.5, 1, 2 |

**Budget-aware procedure (successive halving):**
1. **Screen:** 16 configurations sampled from the space with a fixed seed,
   plus the current defaults (hidden 32, 4 heads, lr 1e-3, dropout 0, MECE
   weight 1). Each is trained **6 epochs** on the full train window, seed 0.
2. **Promote:** the top 4 by validation MECE continue to **20 epochs**
   (patience 5, minimum improvement 0.5%; see early stopping below).
3. **Final:** the single best is trained with **4 seeds** (0–3), up to 40
   epochs, patience 5, minimum improvement 0.5%, checkpoint = best
   validation MECE.

If the defaults win the screen, that is reported as the finding ("the
untuned model was near-optimal within this space").

**Early stopping, to avoid spending time when tuning is not helping:**
1. **Defaults run first.** Each later screening configuration is checked at
   epochs 2 and 4. It is stopped (pruned) if its validation MECE is worse
   than the median of earlier configurations at the same epoch. A controller
   reads each run's per-epoch `history.csv` and stops the run.
2. **Early exit from screening:** if none of the first 8 configurations
   beats the defaults' epoch-4 validation MECE by >= 2%, screening stops,
   promotion is skipped, and the defaults go to the final run. The same 2%
   rule applies at the end of screening.
3. **Within-run early stopping** for promotion and final runs: patience 5
   (was 8), and an epoch counts as an improvement only if validation MECE
   falls by >= 0.5% relative to the best so far.
4. **Not skippable:** the 4-seed final run of the chosen configuration.
   Existing checkpoints were trained on the 2-month pilot window and cannot
   stand in for the 7/2/4 test.

**Stop rule, fixed now:** if no screened configuration beats the defaults'
6-epoch validation MECE by at least 2%, promotion is skipped and the defaults
go straight to the final 4-seed run. Tuning is then reported as "not
material".

## 4. Test (once, after freezing)

On 2025-08 to 2025-11, per seed and as the mean and range over 4 seeds, with
event-cluster CIs and k:
- MECE model / single-alpha oracle and / persistence (`whole_settle`), split
  into settled and unsettled;
- unsettled model / per-series × horizon oracle, the hard baseline;
- ladder (exploratory, as before).

The same baselines and code as the causal rerun are used. No other metric is
promoted to headline after the fact.

## 5. S4: the STGAT as a market-making filter

- Base: the maker simulator's **frozen validation winner** (amendment A4).
- S4 = the base strategy, but a side is **not quoted** at hour H when the
  tuned STGAT's h=1 forecast, taken from the latest snapshot ending at or
  before H, predicts a move against it larger than half the quoted spread.
  For a bid that means a predicted fall; for an ask, a predicted rise.
- Scored on the **test months (2025-08 to 2025-11)**, both fill models,
  **paired** against the base on identical quote opportunities, with an
  event-cluster CI.
- **Verdict:** the model adds economic value if the pessimistic S4 − base
  difference is > 0 with the CI excluding 0.

## 6. Predictions (before any run)

- Tuning: a modest gain, 2–8% lower validation MECE MSE, because the current
  model underfits.
- Test forecasting: beats persistence clearly. Against the family oracle on
  unsettled positions, within ±5%.
- S4 vs base: a small positive difference, probably not significant.

## 6a. Amendment B1 (2026-09-28, before any build or result): quote inputs and a next-hour mid-move head

**Purpose:** give the STGAT its best honest chance on both the forecasting
comparison and S4. Two findings motivate it:
- the model sees only trade prints, which are mostly bid/ask bounce (82–87%
  of apparent basket deviation);
- S4's decision ("will the quoted mid move against my quote in the next hour?")
  differs from the current target (basket sums 2–24 h ahead).

**B1.1 Quote features (inputs), strictly causal.** For ticker node *i* at
snapshot *t*, whose window ends at E_t, use the **latest hourly candle ending at
or before E_t**. Never a later one.

| feature | definition |
|---|---|
| `q_bid`, `q_ask`, `q_mid` | candle close bid, ask, (bid+ask)/2, in [0,1] |
| `q_spread` | ask − bid |
| `q_print_minus_mid` | last trade price in the window − `q_mid` (print side) |
| `q_no_bid`, `q_no_ask` | 1 if bid = 0 / ask = 1 (one-sided book) |
| `q_age_h` | (E_t − candle end) in hours, capped at 24 |
| `q_has` | 1 if any candle exists at or before E_t, else 0 (all other q_* = 0) |

- Basket hubs get causal aggregates over their linked legs: Σ`q_mid` − 1,
  Σ`q_bid`, Σ`q_ask`, and the share of legs quoted.
- Standardisation is fitted on train only, as for all features.
- **Known-answer test (required before any training):** planted candles at
  E_t − 1h, E_t and E_t + 1h. The feature must use the E_t candle; with that
  candle removed it must use E_t − 1h, with age 1h; it must never use E_t + 1h.

**B1.2 Next-hour mid-move head (auxiliary output).** An extra linear head on
the backbone predicts, for ticker node *i* at E_t:
    y = q_mid(candle ending E_t + 1h) − q_mid(candle ending E_t)
- The target is defined only when both candles exist and are two-sided;
  otherwise it is masked. The target uses only quotes after E_t, and it is
  never an input.
- The loss is the existing loss + `w_mid` × MSE(head, y).
- Test report: head MSE vs the zero-move baseline and vs a shrinkage oracle,
  with an event-cluster CI.
- The basket-sum forecasting objective is unchanged, so the §4 comparison
  stays valid (multi-task, not a replacement).

**B1.3 Tuning dimensions added to §3:**
- `quote_features` {off, on};
- `w_mid` {0.5, 1, 2}.
The defaults entry has quote features off, `w_mid` = 1, and the head always
present (S4 needs it).

**B1.4 Ablation.** If the winning configuration has `quote_features = on`, the
best configuration with `quote_features = off` is also trained with 4 seeds and
tested, so the thesis reports whether the book helps. That run happens only if
the screen shows quote features winning by at least 2%, to save time.

**B1.5 S4 rule (replaces the §5 rule).** At hour H, using the latest snapshot
ending at or before H: skip the bid if the predicted next-hour mid move is less
than −½·spread; skip the ask if it is more than +½·spread. Everything else in
§5 is unchanged: test months, paired comparison, verdict.

**B1.6 Predictions.**
- Quote features win the screen.
- The mid-move head beats the zero-move baseline on test, but by a small
  margin.
- The S4 − base difference is positive; whether its CI excludes 0 is
  uncertain (roughly a 25–35% chance).

## 6b. B1 implementation notes (2026-09-29, before any tuning run or result)

Recorded when B1 was implemented. No STGAT has been trained on `cache_724/`,
and no quote-feature or mid-move output has been seen.

- **Attached at load time, not built into the cache.** `model/quote_features.py`
  joins the quote partitions (`data/quotes/by_month/`) to each chunk as it is
  materialised, using the bundle's `timestamps` and `node_ids`. `cache_724/`
  is unchanged (F = 10 on disk), so no month is rebuilt for B1.
- **Layout.** The 9-slot block is inserted before the node-type slot (width
  10 -> 19), so existing slots keep their indices (time_to_close stays slot 8,
  still zeroed) and the type indicator stays last. On hubs, slots 0-3 of the
  block hold the four B1.1 aggregates; the rest are 0.
- **Definitions fixed where B1.1 left room:**
  - `q_print_minus_mid` uses the window's last trade (slot 0) only when the
    leg traded in the window (volume > 0); otherwise it is 0, because a
    carried-forward print is not "the last trade in the window".
  - Hub aggregates sum over legs linked to the hub in that snapshot and having
    a candle (`q_has` = 1); the share quoted is over linked legs.
  - The lookup reaches back to the start of the previous month. Candles are
    hourly while a market is listed, so this does not bind for live legs.
  - Quote inputs are 0 wherever the node is unobserved (mask false), as for
    all inputs.
- **B1.2 target:** requires candles ending **exactly** at E_t and E_t + 1h,
  both two-sided (bid > 0, ask < 1), on an observed ticker. It is in
  dollars, and the zero-move baseline is scored on the same positions.
- **Head:** one zero-initialised linear layer. It is constructed outside the
  RNG stream, so `--w-mid 0` without `--quote-features` reproduces earlier
  runs exactly. With `--w-mid > 0`, history.csv gains `val_mid`,
  `val_mid_zero`, `val_mid_ratio` and `val_mid_n`.
- **B1.4 rule in code:** the ablation runs when the winner has quote inputs on
  and the best quote-on **screened** run beats the best quote-off screened
  run by >= 2% (validation MECE).
- **Known-answer test:** `python stg_infra/model/quote_features.py --self-test`
  (24 checks, all pass), including the three planted candles B1.1 requires.

## 6c. Amendment B2 (2026-09-29, before any tuning run or result)

No tuning run has started and no STGAT has been trained on `cache_724/`
beyond one-epoch smoke runs used only to check memory and plumbing.

**B2.1 Search space: `embed_dim` {16, 32}, replacing {32, 64, 128}.** Measured
peak for one training step (forward + backward) on the largest train chunk
(2025-05, N = 8,816 nodes, T = 142), quote inputs on, under a 5.8 GB cgroup
cap on the 7.8 GB WSL VM:

| embed_dim | peak | fits? |
|---|---|---|
| 32 | 4.6 GB | yes |
| 48 | 6.1 GB | at the cap, no headroom |
| 64 | killed (est. ~8 GB) | no |
| 128 | killed (est. ~14 GB) | no, even at 12 GB |

Two-thirds of the old space would have been OOM-killed and recorded as failed
runs with partial histories, which biases the screen. {16, 32} keeps a model
size dimension that fits with headroom. All other dimensions are unchanged.
The defaults entry (d32) is unchanged, so the 2% rule compares against the
same baseline.

**B2.2 Temporal attention node batch = min(512, 2048 / n_heads).** An 8-head
model at 512 doubled the attention transient. Attention is per node, so this
changes memory, not results: h <= 4 keeps 512 exactly; at h = 8 (256) outputs
and gradients match 512 to float rounding (checked on random inputs).

**B2.3 Test-time scoring, fixed now (`score_forecast.py`).**
- B1.2 report: head MSE vs zero move and vs a one-parameter shrinkage oracle
  y_hat = alpha * x, where x is the **previous-hour quoted-mid move**,
  mid(E_t) - mid(E_t - 1h), from candles ending exactly at those times and
  both two-sided (else x = 0). alpha is fitted on the scored split
  (optimistic), as for the other oracles.
- 95% CIs resample **events** (ticker minus its last `-` segment, e.g.
  `KXHIGHNY-25JUN08-T81` -> `KXHIGHNY-25JUN08`), alpha refit per resample;
  k is printed beside every CI.
- The S4/S5 signal (`export_mid_signal.py`): m_hat in cents on observed
  ticker nodes, keyed by window end E_t, averaged over the 4 final seeds;
  seeds must cover identical positions or the export fails.

**B2.4 Data note.** The raw trades for 2025-11 end on 2025-11-25 at about
19:50 UTC, so the 2025-11 test month has 296 snapshots (to 11-25 18:00), not
a full month. Known before any test result.

**B2.5 Known boundary effect (recorded during tuning, before any result).**
The B1.2 target at a split's last snapshot uses the candle ending one hour
into the next split: the last train snapshot (2025-05-31 22:00, E = 06-01
00:00) is labelled from the 06-01 01:00 candle (validation), and the last
validation snapshot from the 08-01 01:00 candle (test). That is 1 of 2,135
train and 1 of 610 validation snapshots, one hour of quotes, on an auxiliary
head not used for selection (selection is on val MECE). Negligible; not
corrected, so the running tuning is unchanged. All other targets (horizon,
MECE, settlement) are built inside split-homogeneous chunks and never cross
a boundary.

## 6d. Amendment B3 (2026-09-29, after the screen, BEFORE any quote-on final run or test result)

**Observation (validation only).** The screen's early-exit rule fired: none of
the first 8 configurations beat the defaults by 2% on val MECE, so the defaults
(quote inputs OFF, w_mid 1) went to FINAL. The three sampled quote-on configs
were paired with unfavourable settings (lr 3e-4 / 3e-3, dropout 0.2, w_mid 2),
so the screen does not isolate the effect of quote inputs. The defaults' mid-move
head scores ~1.00x the zero-move baseline on validation: it must forecast QUOTE
moves from trade features alone.

**Problem.** One selection (on val MECE, the basket-forecasting metric) was
made for two jobs. S4/S5 use the mid-move head, which nothing selected for.

**Change: two jobs, each selected on its own validation metric.**
- **Forecasting model (A):** the tuned defaults, quote inputs off, 4 final
  seeds. Unchanged; every basket-forecasting result comes from A.
- **Signal model candidate (B):** the identical configuration and command with
  `--quote-features` added (nothing else differs), 4 seeds (0-3), 40 epochs,
  same early stopping and checkpoint rule (val MECE). Dirs
  `runs/tune/b3_quotes_s{0..3}`.
- **Rule (`select_signal_model.py`, self-tested):** per run, val_mid_ratio
  (head MSE / zero-move MSE, validation) at the epoch saved as best.pt;
  seed means compared. B supplies the S4/S5 signal if mean(B) <= 0.98 x
  mean(A); otherwise A does. Written to `runs/tune/signal_model.json`, and the
  signal export uses exactly those checkpoints.
- Also reported (exploratory, no decision): B's val MECE vs A's, as a clean
  one-factor test of whether quote inputs help basket forecasting.
- Order: A's finals -> B's 4 seeds -> selection -> maker A10 -> single test run.
- B1.4's ablation is not triggered (the winner has quote inputs off) and is
  superseded by B.

## 6e. Decision after B3 (2026-09-30, BEFORE maker A10 and any test result)

**Choice: Model A for both jobs** (basket forecasting and the S4/S5 signal),
the outcome of the B3 rule, confirmed by the author after a side-by-side on
validation (`logs/v2_forecast/val_ab/`, `score_forecast.py --split val`):

| val, 4-seed mean | A (quotes off) | B (quotes on) |
|---|---|---|
| MECE vs shrinkage oracle | 0.904x (0.859-0.930) | 0.906x (0.862-0.988) |
| mid-move head vs zero-move | 1.007x | 1.036x (s1 1.111x) |
| node, pooled vs persistence | 0.995x | 0.982x |

Reason: basket forecasting is tied and B's seeds spread wider. B's mid head
is worse and fails the <= 0.9865 bar. B's only gain (node-level, about 1.3
points) feeds neither job. It is reported as exploratory.

**Expectation stated before test:** neither mid-move head beats zero-move on
validation (every seed >= 1.00x; only A s2 and B s3 have CIs that include 1).
So S4/S5 are expected to be close to the base maker. A null S4/S5 result is
the predicted outcome, not a failure of the protocol.

**Settled/unsettled split for A on validation** (`score_mece_bidside.py`,
last-print strata; a decomposition added after val s0 was first seen in
September, used for no choice): unsettled positions (75.5%) score 0.916x
the single-alpha oracle (0.869-0.948, 4/4 CIs exclude 1) and 0.970x the
per-series x horizon oracle (0.920-1.004, 1/4 CIs exclude 1). The earlier
causal checkpoints scored 0.887x on this stratum on val and 1.034x on test,
so a val margin of this size is not expected to transfer. Test will report
the same strata once.

## 7. Known constraints

- CPU only and 7 GB of RAM, so one job runs at a time. Estimated cost:
  cache ~1–2 h, screen ~4–6 h, promotion ~3–4 h, final 4 seeds ~10–14 h.
- `train_forecast.py` currently takes its train/val/test boundaries from
  `data_windows.py` (pilot split). The boundaries must become the 7/2/4 split,
  with a check that the printed split matches §1 exactly before any training
  starts.
