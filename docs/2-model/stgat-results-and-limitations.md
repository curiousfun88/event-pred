# STGAT on Kalshi: Results, Validation, and What Cannot Be Claimed

**Consolidated.** Supersedes all earlier versions. The ladder
sections of the previous revision predated
`ladder-conclusion-overturned.md` and asserted a random-walk conclusion
that is now withdrawn; they are corrected here.

> **Two later findings change this document's headline and one of its tables.
> Both are marked inline:**
>
> 1. **`spread-artefact-finding.md`**: ~92.5% of apparent MECE basket deviation is
>    bid/ask overround, not mispricing. Every gross-edge and PnL figure below is
>    measured at last trade prints and is a backtest artefact. §0 and §5 are
>    corrected. This is now the project's central finding and it is **not in this
>    document's original structure at all** — see §4d, added.
> 2. **`mece-graph-ablation-result.md`**: §3b's "graph context for MECE: no
>    detectable effect" came from a **broken ablation** (two `--drop-edges` keys
>    that do not exist in the cache, while the real MECE key was omitted). The
>    corrected figure is that the graph supplies **~92%** of the margin. Corrected
>    in §3b and §8.

Data: 5 months of Kalshi (2025-05 … 2025-09). Split per `examples/data_windows.py`:
**train** = May+June, **val** = July+August (checkpoint selection),
**test** = September (never used to fit weights or any statistic).

*The window has since been redecided as **2024-11 … 2025-11** with seven expanding
walk-forward folds; see `split-design-correction.md` and
`data-window-liquidity-regime.md`. Everything below is on the five-month pilot.*

---

## 0. SUMMARY

**MECE dislocation is forecastable, and the result survives held-out test.**

- 0.853× the optimal shrinkage oracle on test, replicating val's 0.851×.
- The incremental gain over the oracle holds at ~14.8% across two splits
  that offered *different amounts* of reversion (α = 0.870 val, 0.917 test),
  so the edge is not rediscovered shrinkage.
- **The graph supplies ~92% of that margin** (no-graph 0.988× vs full 0.851×),
  and its entire contribution is to the basket aggregate, not to individual legs.
  *(Corrected: the original version of this summary reported the ablation as
  showing no effect.)*
- Directional contribution over a coin flip through identical execution:
  **+$2.50 to +$3.95 per trade**, CIs excluding zero across a 17× change
  in sample size. *(Round-trip era. The consolidated figure under the correct
  hold-to-settlement structure is **+$0.170/trade, CI [+0.107, +0.247]**,
  cluster-bootstrapped by basket and provably invariant to the cost model. Quote
  that one — it is smaller, better identified, and unaffected by the spread
  finding.)*

**The forecast target is ~92.5% overround, so the economic label is unsettled.**

- The quantity forecast is the basket sum of **last trade prints**. 68.7% of prints
  are ask-side; at a 2.8¢ half-spread that predicts +6.3¢ of signed deviation on a
  6-leg basket from order flow alone. Measured +5.25¢.
- The graph's entire contribution is to that aggregate (node-level ~0.990×), so the
  model may be forecasting microstructure rather than mispricing.
- **Highest-priority open item: re-score the existing checkpoint against bid-side
  basket sums.** A re-score, not a retrain.

**Ladder violations revert sharply, but only when a leg trades — and that
is not predictable.**

- Pooled α ≈ 0.99 is an artifact: 75–90% of pairs have both legs untraded,
  where `gap(t+h) ≡ gap(t)` by arithmetic.
- Conditional on a reprice, a **+18.51¢ violation collapses to +0.07¢** in
  one 2-hour step (test, h=1). Eighteen cells across two splits agree.
- A model trained on that population beats the oracle (0.971×) but cannot
  be deployed: the all-pairs ratio is minimised at initialisation and rises
  monotonically under every mover weight tested.

**No profitable strategy, for four separately quantified reasons** *(the fourth
added later and it is the decisive one)*.

- Taker round trip: −$30.59/trade. Break-even needs 33.5¢; the basket sum
  moves 2.26¢ on average, 6.00¢ at p90. **Even at zero spread, fees alone
  require 6.76¢.**
- Maker execution is worth **+$29.44/trade** and still loses (−$1.15).
- In the realistic configuration the model is beaten by a one-line
  reversion rule, because its signal concentrates in expensive baskets.
- **The apparent edge is the spread.** Hold-to-settlement removes the round-trip
  arithmetic above and produces a positive backtest (+$292 to +$757 over two
  months), but repriced at executable quotes the same population buys at $1.1334,
  sells at $0.9993 and settles $1.0000 — **−0.07¢ gross** before a 1.3–5.8¢ fee.
  Gating makes selection *worse* (84% → 54% positive), because large apparent
  deviation is produced by wide spreads. See §4d.

---

## 1. What `mask` means, and the staleness claim that was withdrawn

An earlier version reported 90% of consecutive observations showing no
price change, 98.3% of surviving violations with zero movement, and
concluded apparent arbitrage is "the shadow of illiquidity" — stale prints.

`diagnose_mask_semantics.py` refuted the assumption underneath it.
`window_volume == 0` on **0.0%** of masked ticker positions; the median
masked position carries **183 contracts**, 204 on price-unchanged ones.

**`mask = True` implies a trade.** So the 90% means something close to the
opposite: legs trade repeatedly, hours apart, **at the same price**. A
sticky price under active trading, not a data artifact. The
limits-to-arbitrage story becomes "the market genuinely quotes through
these violations", which is stronger.

> **Qualification, and it is the project's biggest irony.** The withdrawal above is
> correct about *staleness* and wrong in its broader implication. "Not a data
> artifact" was read as "therefore a real mispricing", which does not follow: a
> print can be fresh and still sit at the bid or the ask rather than at mid. The
> apparent arbitrage **is** largely a measurement artifact — just one-sidedness
> rather than staleness. The original conclusion of this section was reinstated by a
> different mechanism. See `staleness-correction.md` §4, corrected, and
> `spread-artefact-finding.md`.

**Citation correction.** The AFT/arXiv 2508.03474 Polymarket study was
cited as "~$39.6M apparent, ~1% exploited". The paper reports *"a realized
estimate of 40 million USD of profit extracted"* and quantifies no apparent
total and no capture rate. Check `superseded-findings-summary.md`
before submission; it may still carry the original phrasing.

*Further detail on that paper, verified since: its window is 1 Apr 2024 – 1 Apr
2025 (12 months), it treats sum-to-one "market rebalancing" as a co-equal primary
arbitrage type, and the $40M is aggregated across both its types with no per-type
breakdown — so no per-type share can be quoted. It is the only one of the three
nearest papers that treats sum-to-one as a primary object. See
`literature-sample-periods.md`.*

---

## 2. Phase 1: reconstruction, and why it was abandoned

- **It lost to the leg's own last price**, 4.4× on test, 7.9× on val. The
  baseline set had five cross-sectional predictors and no temporal one. It
  did beat every cross-sectional baseline (complement +16.1%,
  partner_price ~7×), so it had learned real graph structure.
- **Two of three trade filters were degenerate by proof.** MeceOutputHead's
  softmax makes the model's basket deviation *identically* the naive
  rule's; LadderOutputHead's `fair_a ≥ fair_b` forces `model_gap ≥ g/2`.
  The third carried real information and was beaten 6.8× by sorting on gap
  size.
- **The reduction:** `pnl = gap × C − fees(prices) − spreads × m × C`. Only
  the spread is unobservable. Selecting among guaranteed-payoff
  opportunities is arithmetic, not prediction — which is what motivated
  forecasting *future* dislocation instead.

*Note for the methods chapter: the reconstruction era was **replaced**, not used as
pre-training. `train_forecast.py` trains from scratch. The masked-pretraining
literature (STEP, GPT-ST, STD-MAE) justifies masked reconstruction as an objective
but does not describe this pipeline — do not claim a pre-train/fine-tune design.
See `stgat-forecasting-redesign.md` §3.*

---

## 3. Phase 2: forecasting

`ResidualForecastHead` predicts `price(t+h) = observed_now + delta` with a
zero-initialised final layer, so the model starts exactly as persistence.

### 3a. MECE — confirmed on held-out test

| | val (n=64,717) | test (n=41,700) |
|---|---|---|
| model MSE | 0.006568 | 0.00397 |
| persistence | 0.008251 | 0.00485 |
| shrinkage oracle | 0.00772 (α=0.870) | 0.00466 (α=0.917) |
| **model / oracle** | **0.851×** | **0.853×** |

The test split is *harder* — the oracle captured 3.9% over persistence
there against 6.4% on val — and the model's incremental gain was 14.9% and
14.7%. Less reversion available, same margin.

### 3b. Ladder — the conclusion was overturned; see the detail doc

**Withdrawn:** "the ladder gap is a random walk with no level to revert
to", and the constraint-geometry argument offered for it (MECE pinned to a
level, ladder bounded only by an inequality). The data contradicts it.

| split, h=1 | frozen share | pooled α | α on MOVED |
|---|---|---|---|
| val | 89.8% | 0.9962 | 0.9273 |
| test | 85.0% | 0.9928 | 0.8760 |

Conditional on a reprice (test, h=1):

| bucket | n | gap t | gap t+h | shrink ratio |
|---|---|---|---|---|
| +1¢..+3¢ | 110 | +1.90¢ | **−4.85¢** | 0.726 |
| +3¢..+8¢ | 174 | +5.13¢ | **−5.55¢** | 0.741 |
| ≥ +8¢ | 184 | +18.51¢ | **+0.07¢** | **0.421** |

Cross-checked: `diagnose_staleness.py` independently found survival
collapsing to 33.5% at h=1; val's small-violation bucket gives 33.6%.

**Why it still cannot be used**, tested four ways:

| role | result |
|---|---|
| forecast target, all pairs | 1.98× persistence |
| target, mover-weighted (W=3, W=2) | 1.070×, 1.058× — minimised at epoch 0, rising |
| target, moved-only (oracle-conditioned) | 0.958× — not deployable |
| graph **context** for MECE (ablation) | ~~no detectable effect~~ → **corrected below** |

> **Correction to the last row.** That ablation was broken. Its `--drop-edges`
> list named `leg_to_hub` and `hub_to_leg`, neither of which exists in the cache,
> while omitting the real key `mece_basket_to_leg`; argparse accepted them because
> they were in `choices`. Caught because `mece_nograph` came back **bit-for-bit
> identical** to `mece_noladder` across all 18 epochs. Fixed, with a startup
> verifier that raises `SystemExit` on any name absent from the materialised chunk
> and always prints what the backbone will actually see.
>
> The corrected result: **no-graph 0.988× the oracle against the full model's
> 0.851×** — the graph supplies ~92% of the entire forecasting margin. One caveat
> to quote with it: the no-graph run had not converged (best at its final epoch
> 24), so 0.988× is an upper bound on its ability. The `--drop-edges
> ladder_monotonic` row above used a valid key and stands. See
> `mece-graph-ablation-result.md`.

The trade is fixed at ~**4 units of error on unmoved pairs per unit gained
on moved ones**, and as the mover weight → 0 the model converges to
persistence and the ratio approaches 1.0 *from above*. There is no weight
at which it crosses.

**The forecastable object is the size of the correction. The
unforecastable one is its timing — and only the timing was ever missing**,
because the static arbitrage captures the size by holding.

*Scope note: after the `yes_sub_title` correction the validated ladder pair pool
is crypto/financials only, narrower in category coverage than MECE.*

### 3c. Node level

Test: 0.990× persistence on the 118,559 positions that **moved**. The
pooled 1.010× includes 343,551 flat positions (74%) where persistence has
MSE exactly zero. Report the `moved` stratum.

*This number is load-bearing in a way it did not look at the time: because
node-level is ~0.990× while basket-aggregate is 0.851×, the graph's contribution
is entirely at the aggregate — which is the ~92.5%-overround quantity.*

---

## 4. Does it make money? No, four times over

### 4a. Taker round trip — the arithmetic forbids it

Kalshi's taker fee summed over a basket whose legs total 1 gives
`Σpᵢ(1−pᵢ) = 1 − Σpᵢ²` ≈ `(1 − 1/N)`, so round-trip fees are about
`2 × 0.07 × C × (1 − 1/N)` — **nearly independent of leg prices**. A fixed
toll.

| strategy | trades | win% | gross/trade | net/trade |
|---|---|---|---|---|
| **model** | 2,366 | **51.1%** | **$2.92** | −$30.59 |
| oracle_shrink | 2,405 | 45.5% | $2.05 | −$32.31 |
| always_revert | 5,493 | 35.2% | $1.03 | −$28.07 |
| random | 2,366 | 34.1% | $0.01 | −$33.50 |
| static_arb | 5,493 | 100% | $5.56 | −$9.10 |

`random` trades the **same 2,366 events** as `model` at **identical cost**
($33.51 both) — so $6,918 against $18 gross is a clean paired comparison
with no confound.

### 4b. Maker execution — worth $29/trade, still negative

−$30.59 → −$1.15 by changing only execution. Fees fall 4×; spreads go from
−$26.76 to $0 because a posted entry earns half the spread and a crossed
exit pays it back. Consistent with Whelan's maker/taker gap (−9.64% vs
−31.46%).

Fills are derived from order flow (`net_flow × side < 0`), not assumed.

| configuration | model | coin flip | **gap** | 95% CI |
|---|---|---|---|---|
| all_or_nothing (n=99) | +$2.98 | −$0.97 | **+$3.95** | [+1.99, +5.93] |
| cross_remainder (n=1,729) | −$18.39 | −$20.89 | **+$2.50** | [+0.72, +4.21] |

The +$2.98 is not a strategy: it exists in the 4.2% where every leg fills,
that subset is selected on *realised volatility* (|delta_real| +39%) rather
than model confidence (|delta_pred| +7%), and 99 trades across five months
is not capacity.

*The maker route stayed provisional and is below the cut line: the fee shape was
never verified and there is no adverse-selection model. And if the apparent
dislocation is the spread, earning the spread rather than paying it is not
harvesting a dislocation — it is market making, a different business. See
`maker-execution-provisional.md`.*

### 4c. Beaten by a one-line rule, diagnosably

| | model | reversion |
|---|---|---|
| gross edge/trade | **$3.55** | $1.12 |
| cost/trade | $21.95 | **$15.72** |
| net | −$18.39 | −$14.59 |

Signal 3.2× stronger; trades 40% more expensive. The entry gate fires on
predicted dislocation, dislocation scales with leg count, and so do fees
and spread crossings. **Signal strength and execution cost share a common
cause.** A trade-selection failure, not a forecasting one.

*This diagnosis anticipated the eventual finding without quite reaching it. The
common cause is sharper than leg count: apparent dislocation is produced by the
spread, so the baskets with the strongest signal are the ones with the widest
spreads. That is why gating makes selection worse rather than better — see §4d.*

### 4d. THE DECISIVE ONE: the apparent edge is the spread — ADDED

Not in the original structure of this document. It is now the results chapter's
lead.

Hold-to-settlement removes §4a's round-trip arithmetic: the legs must sum to $1 at
resolution, so a position held to settlement captures `|dev(t)|` and pays **one-way**
costs. Worth ~$21/trade, more than every modelling decision in the project combined,
and it produces a positive backtest (+$292 pooled-spreads to +$757 windowed-spreads
over two months, positive in every configuration tested).

**It is not real.** The gross term is `|dev(t)|` measured from last trade prints,
and a last trade sits at the bid or the ask, never at mid:

- **Predicted before measured.** Ask-side print share 68.7%, half-spread 2.8¢ ⇒ each
  leg's last print sits `h(2p−1) = 1.05¢` above mid ⇒ a 6-leg basket shows **+6.3¢**
  of signed deviation from order-flow imbalance alone.
- **Measured: +5.25¢** — i.e. ~92.5% of apparent deviation.
- **Repriced at executable quotes** (legs within 1h, both sides priced, n=662): buy
  the basket at asks **$1.1334**, sell at bids **$0.9993**, settles **$1.0000**.
  Selling nets **−0.07¢ gross**, before a Kalshi taker fee of `0.07·C·p(1−p)` per
  leg = 1.3¢ (peaked) to 5.8¢ (flat) on six legs.
- **The gate is anti-selective:** among gated baskets the share with positive
  executable edge falls **84% → 54%**, because wide apparent deviation is *produced
  by* wide spreads and wide-spread baskets execute worst.

`taker_side` semantics were verified independently before this was run: `"yes"` =
taker lifted the ask, `"no"` = sold YES into the bid, median per-ticker
`mean(yes) − mean(no)` = **+3.82¢** across 1.9M prints, 75.6% of tickers positive.
An earlier note had concluded the opposite from three tickers; that is corrected in
`taker-side-investigation-notes.md`, and the correction is load-bearing — with the
mapping reversed, the +6.3¢ prediction would have had the wrong sign.

**What this costs the project:** the profitability claim, in every form.
**What it buys:** a methodological finding stated as a prediction and confirmed,
which is stronger evidence of method than any of the positive results. And the
one economic result that survives it — model beats randomised-timing control,
+$0.170/trade, CI [+0.107, +0.247] — survives *because* the spread term is
`sum(leg spreads) × multiplier × C`, depending only on tickers and size, both
fixed per event, so it **cancels exactly** in a paired comparison. Identical
across three cost models. Provably cost-model invariant.

---

## 5. Answering the supervisor's requirement

> *"model must beat baseline strategies and show PnL to be made"*

- **Forecast accuracy: YES.** 0.853× the oracle on held-out test, with the graph
  supplying ~92% of the margin. *Caveat: measured on the basket aggregate, which is
  the ~92.5%-overround quantity; the bid-side re-score decides whether the label is
  "mispricing" or "microstructure".*
- **Directional PnL vs the causal control: YES.** +$0.170/trade, CI [+0.107,
  +0.247], cluster-bootstrapped by basket, identical across three cost models
  because the spread cancels in a paired comparison. *(The +$2.50–$3.95 figures in
  §4b are the round-trip-era numbers on smaller samples; prefer the consolidated
  one.)*
- **vs a competing strategy: NO.** Four tests against the cost gate give a mean
  point estimate of −0.005 with the best-powered test at +0.005, CI [−0.065,
  +0.093]. A null, not an underpowered result. *(The original wording here was
  "configuration-dependent", which was true of the round-trip era but reads as
  hedging now that the null is well powered. And the gate it fails to beat is
  itself unprofitable.)*
- **PnL to be made: NO**, and the reason is now stronger than capacity or fees. At
  executable prices the no-arbitrage band is effectively everywhere-binding; the
  apparent violations are overround. Four quantified reasons, not an assertion.

**The defensible contribution:**

1. **A measurement finding, stated as a prediction and confirmed.** A naive
   last-trade backtest on prediction-market partitions manufactures profit that
   does not exist at executable prices, because the deviation it measures is
   order-flow imbalance against the spread. Predicted +6.3¢ in advance from the
   ask-side print share; measured +5.25¢. *This is the lead, and it was not in the
   original list.*
2. A **controlled comparison of two arbitrage mechanisms** with a measured
   explanation of why one is forecastable and the other is not.
3. A **forecasting result that survives an oracle baseline** on held-out
   data, shown independent of how much reversion the period offered, with the
   graph's contribution isolated by ablation at ~92%.
4. A **quantified anatomy of why a real edge does not trade**, in four
   independent layers: fee arithmetic, execution mode, the correlation
   between signal strength and cost, and the overround.
5. A **methodological result** (§7): published conclusions of this project were
   overturned twice by conditioning on something the first analysis pooled over —
   whether the price moved at all, and which side of the book it printed on.

---

## 6. Engineering findings

**Node churn breaks the standard STGNN data model.** METR-LA has 207 static
sensors; Kalshi has ~700 markets alive at once but ~15,000 distinct per
month, so a padded dense `(T, N, F)` tensor grows with the square of
calendar range (1 month 0.2 GB, 5 months 4.4 GB, 14 months 34.6 GB). Fixed
by per-month build/cache with month-bounded chunks; peak RSS flat from 1 to
12 months.

**Data quality** (1,075,725 observations): `last_yes_price` outside
[0,100]¢ in 2.50%; `yes_vwap` negative in 0.73%; `time_to_close` > 2 years
in 0.33%.

**Feature scaling dominated learning.** Raw standard deviations spanned
**37,726,891×**; standardization plus validity filtering took val loss from
0.374 to 0.0301.

*One unit gotcha worth recording here: `time_to_close` is feature slot 8 and is in
**seconds** ("0 if past"). `--min-ttc 24` is 24 seconds, not hours — and running it
revealed that 15.9% of the evaluated PnL population sat at `ttc == 0`, i.e. markets
already past close.*

---

## 7. Claims withdrawn, and the pattern behind them

1. Leg pruning destroyed the arbitrage guarantee.
2. 20× opportunity over-counting from 2-hourly snapshots.
3. Blindfolded model — evaluation masked *every* leg.
4. Over-claimed a negative: output-head identities prove two statistics
   degenerate, not that the model *cannot* win.
5. Then over-claimed the positive: `excess` reported before any control
   existed; beaten 6.8× by gap-size sorting once one was added.
6. **The cost assumption was load-bearing and untested** — a flat 1¢/leg
   haircut moved the headline from +$12,618 to +$948, and −$15,700 at the
   pessimistic bound. *An assumption that determines the sign of the result
   is not a parameter; it is the result.*
7. The fair-value baseline set omitted the obvious temporal baseline.
8. The staleness interpretation rested on an unverified assumption about
   `mask`.
9. A one-sided bootstrap verdict printed a significantly **negative** gap
   as "includes 0".
10. **"The ladder gap is a random walk"** — an artifact of pooling over
    pairs where neither leg traded (§3b).
11. A mover weight applied to the *reported* metric as well as the loss,
    tripling the persistence baseline and making a 1.070× ratio read as
    0.996×.
12. **"The graph has no detectable effect on MECE"** — the ablation named two
    `--drop-edges` keys that do not exist in the cache and omitted the real one.
    Caught because two supposedly different runs were bit-for-bit identical. The
    true figure is ~92% of the margin (§3b).
13. **"There is PnL to be made."** Withdrawn in full. ~92.5% of apparent deviation
    is the overround; the executable edge is under one tick against a 1.3–5.8¢ fee
    (§4d).
14. **`--spreads` defaulted to the *ladder* results file** (crypto/financials only),
    so zero MECE legs matched and every leg silently fell through to a global median
    borrowed from a different mechanism — while runs were described as using
    "measured per-leg spreads". Default fixed; a coverage guard now banners below
    50% measured.
15. **`taker_side` direction**, concluded backwards from three tickers. Corrected to
    `"yes"` = ask-side, median gap +3.82¢ over 1.9M prints.
16. **"The mechanism is materially more present on Kalshi than on Polymarket."**
    Invalid comparison: Polymarket's figures are order-book asks at a single
    instant, ours are last trades separated by a median of 406 minutes. The honest
    claim is that the *structure* is more present, not the arbitrage.
17. **A proposal to train on block B and test on block A (2022).** Backwards for a
    forecasting thesis — block A is 26 months *earlier* than training, so it is a
    backcast, not a test set. Replaced by expanding walk-forward inside block B.

**The pattern, stated once because it recurred eight times:** the baseline or
the conditioning set omitted the obvious case — gap-size for selection,
last-value for fair value, a coin flip for direction, persistence-vs-
shrinkage for forecasting, *did the price move at all* for reversion, *which side
of the book did it print on* for the deviation itself. **A
result is only as strong as the most trivial alternative it was tested
against.**

And the corollary that #8 and #13 together supply: **ruling out one way the data
could fake a result licenses nothing about the others.** Enumerate them — for a
last trade print, at minimum "is it recent" and "which side of the book is it on" —
and test them all before claiming the phenomenon.

---

## 8. Limitations to state explicitly

- ~~**Spread coverage.** Every MECE spread lookup fell through to a global
  median borrowed from the ladder pairs file.~~ **Fixed.** `build_mece_leg_spreads.py`
  now measures per-leg spreads from MECE legs themselves (100% measured coverage:
  `ticker=22,516, series=4,576`), the `--spreads` default points at
  `mece_leg_spreads.parquet`, and a coverage guard banners below 50% measured. One
  outstanding item: the file on disk is the **pooled** estimate (median 5.613¢);
  rebuild with `--window` for the drift-corrected 4.68¢. The difference is ~5.6¢ of
  cost on a 6-leg basket, which is why two otherwise identical runs report +$757 and
  +$292.
- **Order-book depth is unobservable.** Kalshi does not retain historical
  book state; its API exposes depth only for the current moment, so
  retrospective depth analysis requires prospective recording or a
  commercial archive. PnL is stated per 100 contracts/leg and scales
  linearly; ratios between strategies are invariant. `--max-participation`
  caps trades at a fraction of window volume as the closest available
  proxy. (This is also why the prediction-market depth literature is
  Polymarket-based — its book is on-chain and permanent.) **This is the single
  most consequential limitation**, because the bid/ask reconstruction in §4d is
  inferred from `taker_side` on prints rather than read from a book.
- **Cross-leg non-simultaneity.** The legs of one basket last-trade a median of
  **406 minutes** apart. Constrain the *cross-leg span*, not the within-leg gap;
  and note that basket sums built from daily *means* are unusable for this reason.
- **Composition.** Sports is 51.9% of all baskets but weather is 58.0% of
  dislocations above 5¢, so the large-deviation tail is dominated by one category
  with a seasonal underlying. See `mece-population-composition.md`.
- **The collection funnel**: 11,607 → 3,354 → 257. State it.
- **maker_taker's spread nets to $0 by construction** — one static per-leg
  spread on both sides. Exit slippage is unmodelled.
- **Cluster bootstrap below ~10 baskets collapses** rather than widening,
  so basket counts are printed per row; all reported rows have 63–341. *Print the
  cluster count `k` alongside every CI.*
- **One test month.** Surviving effects live in tails. *Addressed by the redesign:
  seven expanding walk-forward folds inside 2024-11…2025-11 give seven forward test
  evaluations instead of one, which is the real answer to "twelve months is not
  enough".*
- ~~**The ladder ablation is inconclusive**, not negative: the effect was
  smaller than the epoch-to-epoch variation of a single run.~~ Superseded: the
  MECE ablation is now decisive (~92%), and the remaining caveat is that the
  no-graph run had not converged, so the graph's contribution is bounded above
  rather than pinned.
- **No comparison against a published spatio-temporal baseline** (STGCN, DCRNN,
  AGCRN, Graph WaveNet). The architectural claim rests on an internal ablation. An
  examiner may probe this; the mitigation is in
  `literature-architecture-positioning.md` §6.
- **Do not act on the cost-concentration finding using test data.** Gating
  on predicted-dislocation-per-unit-cost is the obvious next move; the
  hypothesis came from looking at test, so it must be fitted on val. *Moot in
  practice — §4d shows gating on apparent dislocation is anti-selective at
  executable prices.*

---

## 9. Where each result lives

| claim | evidence | doc |
|---|---|---|
| **The overround finding** | `mece_spread_artefact_check.py` | **`spread-artefact-finding.md`** |
| MECE forecast, test-confirmed | `score_forecast.py` | `mece-test-result.md` |
| Graph ablation, ~92% | `train_forecast.py --drop-edges` | `mece-graph-ablation-result.md` |
| MECE PnL, taker round trip | `evaluate_mece_forecast_pnl.py` | `mece-pnl-result.md` |
| MECE PnL, hold-to-settlement | `evaluate_mece_settlement_pnl.py` | `settlement-arbitrage-result.md` |
| Robustness filters | same | `settlement-pnl-robustness.md` |
| Maker execution + fills | `evaluate_mece_maker_pnl.py` | `maker-execution-provisional.md` |
| Model vs baselines, with CIs | same, `_gap_bootstrap` | `pnl-scorecard.md` |
| Ladder overturn + closure | `diagnose_ladder_conditional.py` | `ladder-conclusion-overturned.md` |
| `mask` semantics | `diagnose_mask_semantics.py` | `staleness-correction.md` |
| `taker_side` semantics | `mece_spread_artefact_check.py` | `taker-side-investigation-notes.md` |
| Population composition | `diagnose_basket_composition.py` | `mece-population-composition.md` |
| Data window | `mece_yield_by_month.py`, `sports_categorisation_check.py` | `data-window-liquidity-regime.md`, `mece-yield-by-month.md` |
| Split design | — | `split-design-correction.md` |
| Literature positioning | — | `literature-{ladder,mece,architecture}-positioning.md`, `literature-sample-periods.md` |
| Codebase | — | `architecture-map.md`, `code-index.md` |
