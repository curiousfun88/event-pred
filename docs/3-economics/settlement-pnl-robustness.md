> **SUPERSEDED IN PART (2026-09-26).** The headline "+$292 over 257 trades"
> below was withdrawn later the same day. `spread-artefact-finding.md` shows
> the deviation it prices is ~92.5% bid/ask overround and that the executable
> edge is one tick against 1.3–5.8¢ of fees. §2 (cost-model invariance) and
> §3 (the retraction) stand and are load-bearing. Kept unedited as the record
> of what was believed at this point.

# Settlement PnL — robustness complete

Week 1 of `four-week-plan-and-reframe.md`. Val, cap 25%, taker, horizon 1,
checkpoint epoch 11, measured per-leg spreads at 100% coverage
(22,516 ticker-level, 4,576 series-level; file covers 5,334 tickers across
20 series).

**Verdict: PASS, and robustly.** The gate is profitable in every
configuration tested including full-spread crossing. The model's edge over
its causal control is *provably invariant* to the cost model. One earlier
conclusion is retracted (§3) and one new issue found (§5).

---

## 1. Full sweep at measured per-leg spreads

| config | kept | `cost_gated` | per trade | trades | gated median \|dev\| |
|---|---|---|---|---|---|
| vol≥20, ttc>1s | 3,424 (29.5%) | +299 | 1.159 | 258 | 19¢ |
| **vol≥20, ttc>1h** | **3,354 (28.9%)** | **+292** | **1.135** | **257** | 19¢ |
| vol≥20, ttc>24h | 1,219 (10.5%) | +50 | 0.449 | 112 | 8¢ |
| **vol≥20, ttc>1h, FULL spread** | 3,354 | **+46** | **1.290** | **36** | 37¢ |

**The gate survives full-spread crossing** (`--spread-multiplier 1.0`),
the honest taker worst case: +$46 over 36 trades. Per-trade profit is
*higher* than at half-spread (1.290 vs 1.135) because the gate becomes far
more selective — median deviation 37¢ vs 19¢. Doubling the spread cost
does not flip the sign; it shrinks the qualifying population by 86%.

**Headline: +$292 over 257 trades, +$1.135/trade** (vol≥20, ttc>1h,
half-spread, measured per-leg spreads). **Worst case: +$46 over 36
trades** at full-spread crossing. Positive at every setting.

## 2. The model-vs-control result is provably cost-model-invariant

`model_timed − random_timed` across every cost model tried:

| cost model | point | CI |
|---|---|---|
| wrong ladder table, 5.308¢ flat | +0.1703 | [+0.107, +0.247] |
| measured per-leg, half-spread | +0.1703 | [+0.107, +0.247] |
| measured per-leg, **full** spread | +0.1703 | [+0.107, +0.247] |

Identical to four decimals across a 26% cost increase and then a doubling
of the spread component. Not luck: the spread cost is
`sum(leg spreads) × multiplier × C`, depending only on the basket's
tickers and size — both fixed per event — so it **cancels exactly** in a
paired comparison between two strategies trading the *same* baskets at
different moments. Only the price-dependent fee differs, negligibly.

**This is the strongest number in the project.** The standard objection to
any prediction-market PnL is that the cost assumptions are doing the work;
for this result, provably, they are not. State it explicitly.

(At the 24h bar it is +0.0560 [+0.020, +0.106] — still significant, on a
different population. `model_timed − static_now` is the only comparison
that goes inconclusive there: [−0.0022, +0.0388].)

## 3. RETRACTION, now replicated four times

`model_timed_gated − cost_gated`, per trade:

| cost model | point | CI | verdict |
|---|---|---|---|
| wrong table, ttc>1s | −0.2730 | [−0.530, −0.091] | WORSE |
| wrong table, ttc>1h | −0.2576 | [−0.512, −0.055] | WORSE |
| **measured, ttc>1s** | **−0.0014** | [−0.209, +0.112] | inconclusive |
| **measured, ttc>1h** | **+0.0029** | [−0.215, +0.111] | inconclusive |
| **measured, ttc>24h** | **+0.0032** | [−0.112, +0.028] | inconclusive |
| **measured, full spread** | **−0.0297** | [−0.224, +0.122] | inconclusive |

The "model significantly worsens the profitable rule" finding was **an
artefact of costing weather and sports baskets with crypto/financials
ladder spreads**. With the correct cost model it is a clean null at all
four settings, point estimate within ±0.03 of zero.

Total profit is consistently higher because the model trades a larger
population: **+20.8% / +21.3% / +2.5% / +19.4%**. Per-trade is flat and
trades rise ~21%, so the entire gain is **population size at constant
quality** — waiting one step when the model says the dislocation will
widen pushes ~54 sub-threshold baskets over the gate without diluting the
average.

Claim: *the model expands the gated population by ~21% at unchanged
per-trade profit, adding ~+$62 total.* State that per-trade improvement is
**not** demonstrated.

## 4. The 24-hour bar is a different experiment, and its gate misbehaves

| | ttc>1h | ttc>24h |
|---|---|---|
| population median legs | 6 | 3 |
| population median days to close | 0.6 | 2.7 |
| **gated subset** median legs | 6 | 6 |
| **gated subset** median days to close | 0.7 | **7.0** |
| **gated subset** thinnest leg vol | 44 | **27** |
| per trade | 1.135 | 0.449 |

At the 24h bar the script's own selection warning applies: the gated
subset sits **7 days** from close against a 2.7-day population, on
*thinner* legs (27 vs 44). The gate is reaching for duration and
illiquidity to find qualifying deviations. Combined with lockup p90 of
14.9 days, that is the one configuration whose PnL should not be presented
as executable. Report it as a sensitivity with this note; its value is
that the sign holds, not its magnitude.

## 5. NEW ISSUE: the spreads file looks drift-contaminated

The loaded file reports **global median 5.613¢/leg**. The earlier spread
triangulation produced:

- borrowed ladder global: 4.70¢
- **pooled over each ticker's life: 5.61¢** ← matches
- windowed, drift-corrected (2-hour windows): 4.68¢

5.613¢ matches the *pooled* figure almost exactly, so
`mece_leg_spreads.parquet` was almost certainly built **without
`--window`** and carries the price-drift contamination that the windowed
estimator exists to remove. Pooled spreads are biased *upward*, which
means current costs are overstated and **the PnL is understated**.

Rebuild with the drift correction and re-run. The printed global median
should drop to ≈4.68¢:

```
python stg_infra/build_mece_leg_spreads.py --window 2h \
    --min-windows 2 --min-n 5 --out results/mece/mece_leg_spreads_windowed.parquet
python stg_infra/evaluate_mece_settlement_pnl.py --split val --max-participation 0.25 \
    --min-leg-volume 20 --min-ttc 3600 --spreads results/mece/mece_leg_spreads_windowed.parquet
```

Report both: pooled is the conservative bound, windowed the corrected
estimate.

## 6. Why the 100% win rate is definitional

`cost_gated` wins on 100% of trades by construction — it enters only when
|dev|·C exceeds *modelled* cost, and hold-to-settlement captures |dev|
deterministically because the legs must sum to $1. No CI against zero is
meaningful.

The result's exposure is therefore to three assumptions, not sampling
noise: the cost model not understating cost, every leg settling, the
basket being a genuine partition. §5 of the previous version was
assumption (1) failing silently, which is why a coverage guard was added
rather than only the path fixed — the sources line now carries
`[x% measured per-leg, y% fallback]` and banners below 50%.

## 7. Corrections of record

- **The default `--spreads` was the ladder results file**
  (`pairwise_monotonicity_taker_side_results_corrected.parquet`), which by
  its own docstring contains only crypto/financials pairs. No weather or
  sports leg was in it, so every lookup fell through to a global median
  borrowed from a different mechanism, while runs were described as using
  "measured per-leg spreads". Fixed; default is now
  `mece_leg_spreads.parquet`. Correct the wording in
  `settlement-arbitrage-result.md` — it was not true until now.
- **`--min-ttc 24` was 24 seconds.** `TIME_TO_CLOSE` is slot 8, "seconds
  from window_end to market close_time (0 if past)". It dropped 1,849
  baskets (15.9%) and the 1-hour bar drops only 71 more, so that 15.9%
  sits at `ttc == 0`: **markets already past close**. The evaluation was
  including closed markets — a correction, not a sensitivity row.
- **`KXCLUBWCGAME` is not in val** (28 June, before the split), so it never
  touched these figures. Check train membership and its leg rules.

---

## Reportable claims

- **Model-free:** the arithmetic cost gate is profitable on liquid, open,
  fully-covered baskets at measured per-leg spreads — **+$292 over 257
  trades, +$1.135/trade**, 100% win rate by construction. Positive at
  every configuration tested, down to **+$46** under full-spread
  crossing.
- **Model-attributable, primary:** the model beats its randomised-timing
  control by **+$0.170/trade, CI [+0.107, +0.247]**, identical across
  three cost models — **provably invariant to the cost assumptions**.
- **Model-attributable, secondary:** the model expands the gated
  population ~21% at unchanged per-trade profit (~+$62). Per-trade
  improvement not demonstrated; null replicated at four settings.

## Next

1. Rebuild spreads with `--window` (§5) and re-run — expect the PnL to
   rise.
2. `KXCLUBWCGAME` leg rules and train membership.
3. Fix "measured per-leg spreads" wording in
   `settlement-arbitrage-result.md`.

Then Week 2: rebuild `cache/` on ten months, move `PILOT_MONTHS` off the
five-month pilot, retrain, re-run model-vs-control there.
