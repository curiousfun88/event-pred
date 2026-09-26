> **§3 SUPERSEDED** by `split-design-correction.md`. The "train on B, hold
> out A" design tests on data 26 months *earlier* than training, which is a
> backcast, not a forecast. §4b's "+$617 unverified" concern was resolved by
> `settlement-pnl-robustness.md` and then overtaken entirely by
> `spread-artefact-finding.md`. §1, §2, §4 and §5 stand.

# MECE basket yield by month — window, units, and the liquidity filter

Answers three things: how many months of usable MECE data exist (§1–3),
whether to pivot away from MECE (§5), and what the model's actual
training unit is (§4). Both discrepancies flagged in the first version of
this doc are now **resolved** (§4), and one of my own claims in it was
wrong (§4b).

Source: `stg_infra/examples/mece_yield_by_month.py` over all 54 months;
`mece_sum_to_one_check.py`; `diagnose_basket_coverage.py --split val`.

---

## 1. The MECE structure predates sports by three years

The candidate-family list over the full history contains the **pre-`KX`
generation** of the brackets currently traded:

| family | events | legs | category |
|---|---|---|---|
| `KXETH` / `KXBTC` | 5,418 / 5,404 | 75 | crypto |
| `HIGHCHI` / `HIGHNY` | 911 / 910 | 6 | weather/climate |
| `USDJPY` / `EURUSD` | 752 / 750 | 7 | financials |
| `HIGHMIA` / `HIGHAUS` | 531 / 528 | 6 | weather/climate |

`HIGHNY` → `KXHIGHNY` is one continuous mechanism under two ticker
conventions. 86 families qualify over the full history versus 29 on
2025-10/11 alone. **Sports launching in 2025-01 bounded the
multi-category mix, never the mechanism.** The earlier "ten months is the
ceiling" conclusion was wrong because it reasoned from listed-market
counts rather than basket coverage.

Hard floor: 2021-06 → 2022-03 have **zero** candidate-leg trades. Data
starts 2022-04.

## 2. Coverage is two dense blocks around a 23-month trough

44 of 54 months have ≥1 fully-covered basket; 41 have ≥10; 21 have ≥100.

| block | months | basket-days | per month | median \|dev\| | median leg gap |
|---|---|---|---|---|---|
| **A** 2022-04…2022-11 | 8 | 914 | 114 | 3.1¢ | 3.15h |
| trough 2022-12…2024-10 | 23 | 861 | 37 | 8.1¢ | 5.49h |
| **B** 2024-11…2025-11 | 13 | 5,806 | 447 | 4.3¢ | 3.95h |
| *current window* 2025-05…09 | *5* | *3,242* | *648* | *3.8¢* | *3.09h* |

**The trough is not usable.** 37 basket-days/month at a 5.5h median leg
gap and 8¢ median deviation is stale pricing, not mispricing —
2024-01…06 is worst (11–15.5¢ at 5–6.6h gaps). Including it would
inflate opportunity counts and PnL with artefacts.

Blocks A+B: **21 months, 6,720 basket-days — 2.07× the observations of
the current window across 4.2× the span**, at comparable quality.

## 3. Recommended design: train on B, hold out A — SUPERSEDED

Block B for train/val; Block A (2022-04…2022-11) held out entirely as a
second test set — 26 months earlier, ~60× thinner platform, previous
ticker generation, sports absent.

**This is retracted.** See `split-design-correction.md`: block A predates
the training window, so using it as a test set is a backcast presented as
a forecast. The corrected design is expanding-window walk-forward inside
block B, with block A retained only as a clearly labelled backcast.

The seasonality point survives the retraction: A is Apr–Nov, B spans a
full winter, so together they cover every season.

## 4. Both discrepancies resolved

**(a) Reimplementation validated.** `mece_sum_to_one_check.py` (now set
to `TARGET_MONTHS` = 2025-02…2025-11) reports **4,891** full-basket
(event, day) snapshots. Summing `mece_yield_by_month.py` over the same
ten months gives **4,959** — a **1.4%** difference, explained by pooling
identification over 54 months (86 families) rather than ten (51). §2 is
validated. The **267** figure in `superseded-findings-summary.md`
is stale: it predates the `FAMILY_RE` fix and `MAX_LEGS` 60→100, and was
for two months only.

**(b) The grid is HOURLY, and the 8× inference was wrong.**
`diagnose_basket_coverage.py` iterates timesteps of the graph's own grid
(`chunk_len=168` = one week of hours) and counts every basket hub per
hour. A "basket-snapshot" is a (basket, **hour**), not a (basket, day).
Val: **15,955** basket-hours — 12,177 FULL (76.3%), 2,915 PARTIAL
(18.3%), 863 SPARSE (5.4%).

An earlier note suggested this meant the dataset was "~8× larger than the
table implies". **That was wrong in the sense that matters.** Hourly
snapshots of one basket on one day are overwhelmingly autocorrelated —
this project already established that 85–90% of pair-snapshots are
*frozen* between steps, and `ladder-conclusion-overturned.md` §1 showed
that pooling over frozen observations measures untradedness rather than
dynamics. The hourly count is the number of gradient steps; the
**effective independent sample is near the basket-day count**. The
correct figure to quote to a supervisor is 6,720 over 21 months, not a
resampled multiple of it.

**Operational consequence:** the leg-prices file now spans ten months,
but `diagnose_basket_coverage.py` and the training path still use
`PILOT_MONTHS = 2025-05…09` and a `cache/` of monthly bundles. The cache
must be rebuilt for any new months before the model sees them.

## 4b. The liquidity filter

`mece_sum_to_one_check.py` reports the per-leg liquidity split, and it is
severe. Of 4,891 full-basket snapshots, only **1,338 (27.4%)** have every
leg trading ≥20 times that day (the same bar the ladder mechanism uses via
`MIN_N_PER_SIDE`). Deviations in that subset are far tighter:

| time gap | all snapshots | liquid only |
|---|---|---|
| 0–0.25h | n=707, mean 5.0¢, **21.8%** >5¢ | n=495, mean **3.0¢**, **11.7%** >5¢ |
| 0.25–1h | n=630, mean 4.9¢, 25.9% >5¢ | n=239, mean **2.7¢**, **11.3%** >5¢ |
| 1–4h | n=1330, mean 6.6¢, 38.0% >5¢ | n=262, mean 5.6¢, 31.3% >5¢ |
| 4–12h | n=1770, mean 6.7¢, 46.7% >5¢ | n=335, mean 5.4¢, 42.7% >5¢ |

**Roughly half the "meaningful mispricings" at tight time gaps are
thin-leg artefacts.** The genuinely tradeable core is ~**734** snapshots
(liquid, all legs within 1 hour) across ten months, of which ~**85**
exceed 5¢.

This motivated the robustness filters in
`settlement-pnl-robustness.md`. The deeper problem — that the deviation
itself is mostly the bid/ask spread — was found later and is in
`spread-artefact-finding.md`.

### Two contaminated populations visible in the tail

- **`KXCLUBWCGAME` is probably not a partition.**
  `KXCLUBWCGAME-25JUN28BENCHE` shows sum=$1.89 with `min_leg_trades=369`
  and a **0.02h** time gap — liquid, simultaneous, and an 89¢ deviation,
  which is not credible as a standing arbitrage. Legs: TIE $0.99, BEN
  $0.57, CHE $0.33. Club World Cup Round of 16 is a **knockout** match,
  so "tie" and "winner" almost certainly resolve on different bases (90
  minutes vs after extra time/penalties) and the three legs are not
  mutually exclusive. If confirmed, exclude the family exactly as
  `SINGLEGAME`/`MULTIGAME` combo props were excluded. MLS/EPL regular
  season, where a draw is a terminal outcome, is unaffected.
- **Resolution-day contamination.** `KXHIGHCHI-25APR02` on 2025-04-02
  shows two *adjacent* temperature brackets at $0.99 and $0.72 within a
  1.06h gap (sum $1.75). Two adjacent brackets cannot both be
  near-certain. Most likely a post-determination print mixed into the
  daily last trade. Candidate fix: exclude snapshots on the event's own
  resolution date, or require trade times before determination.

## 5. Do NOT pivot — neither to the ladder nor to cointegration

**Ladder.** `ladder-conclusion-overturned.md` is FINAL: the all-pairs
ratio is minimised at epoch 0 (1.0015), rises monotonically under every
mover weight (W=2: 1.058×, W=3: 1.070×, moved-only: 1.98×), and
approaches 1.0 *from above* as W→0. "Not a tuning problem." Mechanism:
reprice timing is not in the features, so learned reversion bleeds onto
the 75–85% frozen population at ~4 units of error per unit gained. After
the `yes_sub_title` correction the valid-pair pool is crypto/financials
only — **narrower** than MECE, not broader.

**Cointegration pairs trading.** Fails on the exact axis motivating it:
it is the most data-hungry framing available (the standard formation
window is 12 months *per pair*), while Kalshi contracts live days to
weeks. Worse, it is theoretically ill-posed here — contracts are bounded
martingales with a known terminal date and binary payoff, so both legs
converge to their outcomes rather than to each other, and any fitted
"equilibrium" is non-stationary by construction. With 4.2M tickers,
spurious cointegration after millions of pairwise tests is guaranteed.

**What would be given up:** a MECE basket's legs *must* sum to $1 at
resolution — an identity, not an estimate. The current design has zero
estimation risk in the relationship itself. Cointegration reintroduces it
at the foundation, making a bad result unattributable between the fitted
relationship and the forecast. It also dissolves the architecture: the
graph's edges are currently *known* structural relations, which is the
only reason the ~92% ablation result means anything; estimated
correlation edges reduce the contribution to "a GNN on a correlation
graph".

**Right use of the ladder work:** keep it as the negative control in a
two-mechanism comparison — two similar no-arbitrage constraints, one
where the STGAT adds measurable value over a causal control and one where
it provably cannot, with an identified mechanism (magnitude is learnable,
timing is not, and only timing pays). Stronger than either alone, and no
work is discarded.
