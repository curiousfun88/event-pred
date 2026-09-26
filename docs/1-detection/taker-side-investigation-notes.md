# Taker-Side / Bid-Ask Investigation — Research Notes

**Date:** 2026-08-31
**Purpose:** Working notes on today's checks into whether `taker_side` can be used to address the bid-ask-bounce limitation flagged in §5 of the Direction B feasibility report. Written to digest the reasoning, not as a polished report section.

## Background: why this investigation started

The report's §4.3 ladder monotonicity result (29-33% violation rate, ~8 cent median) is trade-print evidence, not proof of live executable arbitrage. The main open objection is **bid-ask bounce**: two trade prints being compared might just have landed on different sides of their own bid-ask spread (one a buy, one a sell), producing an apparent "violation" that never existed in the live order book.

The trades file has a `taker_side` column (`"yes"` / `"no"`) recording which side the trade's aggressor took. In principle this lets you tell, print by print, roughly which side of the spread a given price landed near, which could be used to filter the monotonicity test down to only "like-for-like" comparisons (same side on both legs) and get a cleaner read on whether the violations are real.

## Check 1: What does `taker_side` actually look like in the data?

Confirmed via `trades["taker_side"].unique()`: values are exactly `"yes"` and `"no"`, matching the expected convention.

**Original hypothesis (theoretical, not yet checked against data):** a taker buying YES crosses the YES ask, so `taker_side == "yes"` trades should print near the (higher) YES ask. A taker buying NO is economically the same as selling YES, so `taker_side == "no"` trades should print near the (lower) YES bid. Expected: `avg_yes_price` for `"yes"` > `avg_yes_price` for `"no"`.

## Check 2: Whole-history test on `KXMLB-25-LAD` (season-long market)

Grouped all 94,515 trades on this ticker by `taker_side`:

| taker_side | avg_yes_price | n_trades |
|---|---|---|
| no | 46.93 | 26,609 |
| yes | 40.85 | 67,906 |

**Result: opposite of the hypothesis**, and by a large margin (~6 cents). Initial explanation: this is a season-long futures-style contract (likely "will the Dodgers win the World Series"). Its true probability plausibly moved by tens of cents over the life of the contract as the season played out, which would swamp a few-cents bid-ask effect entirely. If `"no"` trades happened to cluster in a period when the true price was higher, and `"yes"` trades clustered when it was lower, that alone explains the gap, no bid-ask information needed.

## Check 3: Narrowing to a single day (2025-11-02)

To control for the season-long drift, narrowed to the single busiest day. That day turned out to hold **77,137 of the ticker's 94,515 total trades (82% of its entire lifetime volume in one day)**, a strong signal this was the actual World Series-deciding game.

| taker_side | avg_yes_price | n_trades |
|---|---|---|
| no | 46.81 | 23,355 |
| yes | 37.07 | 53,782 |

**Result: still reversed, and the gap barely shrank (~9.7 cents).** Revised explanation: a single day isn't a tight enough window when that day contains a live, decisive event. The true probability could have swung from ~50% to near 0%/100% within hours as the game resolved, still dwarfing the bid-ask spread. Concluded this specific ticker/day combination is a bad test case, need a genuinely calm, stable-price market instead.

## Check 4: Reconstructing the MECE family list

Needed a source of calm, short-duration tickers to test on instead. Rebuilt the family-consistency logic from `mece_sum_to_one_check.py` directly against `markets_2025-10.parquet` (October, since the most recent month's markets were all still unresolved/blank `result`, confirmed via `markets["result"].unique()` showing only an empty string until October data was used instead).

Result: **27 surviving families**, matching the report's §4.5 figure exactly. Top families by instance count: `KXBTC`, `KXETH`, `KXSHIBA`, `KXXRP` (crypto price buckets), `KXHIGHMIA` (Miami daily high temp), and others.

Noted that the crypto families were deliberately avoided for the next test, crypto prices can move plenty within a day too, so they carry some of the same drift risk the MLB ticker did. Weather was chosen instead as a genuinely low-drift underlying.

## Check 5: Calm-ticker test on `KXHIGHMIA-25NOV07-B86.5`

| taker_side | avg_yes_price | n_trades |
|---|---|---|
| no | 52.16 | 448 |
| yes | 51.53 | 632 |

**Result: still the same direction (no > yes), but now a small, plausible-spread-sized gap (~0.63 cents)** instead of the ~9.7 cent gap from the volatile MLB day.

## Conclusion / reasoning update

Two separate things were tangled together in Checks 2-3, and this result untangles them:

1. **The huge MLB gap was mostly a drift artifact**, not a spread effect. Once tested on a calm ticker, the gap shrank by roughly 15x (9.7 cents to 0.6 cents), consistent with the "decisive live game = huge intraday price swing" explanation.
2. **The direction of the effect itself was consistently backwards from the original hypothesis**, across both the volatile and the calm ticker. This means the original theoretical mapping (yes-side = ask/higher, no-side = bid/lower) was wrong, not just noisy. Corrected empirical finding: in this dataset, `taker_side == "no"` trades sit slightly *higher* in `yes_price`, and `taker_side == "yes"` trades sit slightly *lower*, the reverse of the naive assumption.

This is a case where checking the assumption against real data caught a wrong theoretical guess, worth keeping as a documented, validated (and corrected) assumption rather than a silent one.

**Practical implication for the ladder test:** the planned robustness check (only compare adjacent-strike pairs where both legs' relevant trades share the same `taker_side`) is unaffected by this correction, it only relies on avoiding a *mix* of sides, not on knowing which side is bid vs ask. Still worth building.

**Useful number for the report:** the calm-ticker baseline spread (~0.6 cents) is roughly an order of magnitude smaller than the ladder test's 8-cent median violation. That's suggestive evidence the violations aren't fully explained by ordinary spread noise, though not conclusive, since the ladder markets themselves may have wider spreads than this particular weather ticker.

## Next step (as of 2026-08-31)

Build the `taker_side`-filtered version of `pairwise_monotonicity_check.py`: split the violation-rate calculation into same-side pairs vs. mixed-side pairs, and see whether the violation rate holds up (real mispricing) or collapses (bounce artifact) once mixed-side comparisons are excluded.

---

# Addendum — 2026-09-02: Scaling the same-side check across all ladder pairs

**Purpose:** Follows directly from the 2026-08-31 next step. Builds and runs the full `taker_side`-filtered pairwise monotonicity check across all ladder pairs (not just one calm ticker), then stress-tests the result for robustness (sample-size sensitivity, spread-mismatch confound, violation magnitude, timing) and breaks it down by market category. This is where the investigation's main finding came from.

**Caveat carried over from 2026-08-31 and still true:** the same-side check does not depend on knowing which `taker_side` value is bid vs. ask — it only requires not mixing sides — so the reversed-direction finding from Checks 2/3/5 above does not affect anything below.

## Check 6: Building `pairwise_monotonicity_taker_side_check.py`

Extended the original naive check with: (a) same-`taker_side`-only violation rates (separately for `taker_side == "yes"` and `"no"`, since which one is bid vs. ask wasn't assumed), (b) per-pair sample-size tracking (`n` per leg per side) to flag thin pairs, and (c) an implied-spread-ratio flag per pair (`abs(avg_price["no"] - avg_price["yes"])` per leg, compared between the two legs of a pair) to flag pairs where the two legs' spreads differ a lot, since same-side cancellation logic is weaker when spreads are mismatched.

Ladder pairs were identified via a best-effort regex over ticker names (`FAMILY-DATE-B123.45` / `...-T123.45` pattern, adjacent thresholds within a family paired up) since the original validated family-identification logic wasn't reused here — worth confirming later whether this produced the same pair set as the original §4.3 script.

**Full-sample result (11,988 pairs):**

| metric | value |
|---|---|
| naive violation rate | 35.65% |
| same-side ("yes") violation rate | 23.71% |
| same-side ("no") violation rate | 23.19% |
| pairs low-n on at least one side (n<20) | 9,096 of 11,988 (76%) |
| pairs with spread ratio > 3x | 3,606 of 11,988 (30%) |

Both same-side rates land close to each other and below the naive rate — consistent with some (not all) of the naive violations being bounce artifacts. But the 76% low-n share meant this headline number wasn't trustworthy on its own yet.

## Check 7: Robustness follow-ups

**Well-sampled subset only** (both legs, both sides, n≥20 — 2,892 of 11,988 pairs): naive 23.86%, same-side yes 20.33%, same-side no 19.95%. The gap between naive and same-side shrank a lot here (~3.5-4 points, vs. ~12 points on the full noisy sample) — most of the bounce effect was concentrated in thin/illiquid pairs; on liquid pairs the ~20% rate mostly wasn't bounce to begin with.

**Spread-ratio buckets:** violation rate was roughly flat across low (<1.5x), mid (1.5-3x), and high (>3x) spread-ratio buckets (21.5%/22.9%/23.9% respectively) — violations aren't concentrated where the same-side cancellation assumption is weakest, so this isn't a hidden spread-mismatch artifact.

**Violation magnitude vs. spread (pooled, not yet split by category):** same-side "yes" violations: median gap 9.02 cents vs. avg leg spread 8.14 cents (ratio 1.11). Same-side "no": median gap 9.92 vs. 8.34 (ratio 1.19). Only modestly above 1 — flagged at the time as the weakest link in the case, until the category breakdown (Check 8) explained why the pooled number was muted.

**MIN_N_PER_SIDE sensitivity:** rate *rose* as the cutoff got stricter (yes-side: 21.5% at n≥10 → 20.9% at n≥20 → 23.0% at n≥50 → 28.1% at n≥100; no-side: 18.8% → 19.1% → 22.3% → 25.9%). This is the opposite of what pure small-sample noise would predict (more data should shrink a noise-driven rate, not grow it) — flagged as needing a category-level explanation, which Check 8 provided (composition shift toward weather at high n).

**Time gap between legs' trades** (for same-side violating pairs, comparing each leg's average trade timestamp, assumed nanoseconds from a `Datetime` column cast to `Int64` — **unit not explicitly confirmed against the real schema, treat as approximate**): yes-side violations (n=2,592) — median gap ≈19.8 minutes, mean ≈4.05 hours (pulled up by a long tail), 75th percentile ≈2.52 hours, max ≈15.7 days, min ≈12 ms. No-side violations (n=2,441) — median ≈19.3 minutes, mean ≈3.14 hours, 75th percentile ≈2.41 hours, max ≈9.8 days, min ≈0.23 ms. Most violating pairs' relevant trades were reasonably close in time (median under 20 minutes, three-quarters under ~2.5 hours), which is a mild point in favor of these being observable close to simultaneously rather than comparing trades from unrelated points in the market's life — though this doesn't establish true executable simultaneity.

## Check 8: Category breakdown — the main finding

Split pairs by underlying category via ticker keyword matching (crypto: BTC/ETH/SHIBA/XRP/SOL/DOGE; sports: NBA/MLB/NFL/NHL/WINS/etc.; weather/climate: HIGH/LOW/ARCTICICE/TEMP/RAIN/SNOW/HURRICANE; else "other"). Sanity-checked by sampling tickers per category — weather correctly caught city-temperature families (`KXHIGHDEN`, `KXHIGHNY`, `KXHIGHPHIL`, `KXHIGHMIA`, `KXHIGHAUS`), crypto correctly caught `KXBTCD`/`KXETH`/`KXETHD`, "other" turned out to be financial/macro ladders (`KXINX`, `KXINXU`, `KXNASDAQ100U`, `KXGDPYEAR`, `KXEURUSDH`) rather than noise, and sports caught `KXNBAWINS`. No evidence of keyword false-positives.

**Composition (all 11,988 pairs):** crypto 62.0%, other 27.6%, weather/climate 9.1%, sports 1.3%.

**Composition shifts toward weather as the MIN_N cutoff rises:** weather's share climbed from 9.1% (all pairs) → 17.6% (n≥10) → 23.1% (n≥20) → 32.0% (n≥50) → 42.0% (n≥100), while "other" and sports nearly disappeared. This explained Check 7's MIN_N-sensitivity surprise: the pooled rate wasn't rising because liquid pairs are inherently more violation-prone in general, it was rising because the pair mix was shifting toward a category (weather) that has an intrinsically much higher rate.

**Violation rate by category (at n≥20 same-side threshold):** crypto ≈10.5%/10.1% (yes/no), other ≈22.3%/19.9%, sports 0% (n=27, too small to read into), weather/climate ≈50.7%/50.4%. At n≥100: crypto ≈8.8%/7.1%, other ≈45.8%/43.9% (n=59, small), weather ≈50.5%/50.9% — weather's rate was essentially flat regardless of the liquidity cutoff.

**Violation magnitude by category (pooled sample, all n):**

| category | side | median gap | avg spread | n violations | gap/spread ratio |
|---|---|---|---|---|---|
| crypto | yes | 8.81¢ | 9.06¢ | 1,314 | 0.97 |
| crypto | no | 9.33¢ | 8.88¢ | 1,267 | 1.05 |
| other | yes | 6.75¢ | 10.18¢ | 707 | 0.66 |
| other | no | 7.43¢ | 10.54¢ | 669 | 0.70 |
| sports | yes | 35.21¢ | 33.84¢ | 6 | 1.04 |
| sports | no | 21.50¢ | 24.20¢ | 2 | 0.89 |
| weather/climate | yes | 15.40¢ | 3.75¢ | 565 | 4.11 |
| weather/climate | no | 16.97¢ | 3.82¢ | 503 | 4.44 |

Weather stood out sharply: tight spreads (~3.75-3.82¢, tighter than every other category) combined with large, persistent gaps (~15.4-17.0¢) gives a gap/spread ratio of ~4.1-4.4x — far above the "roughly spread-sized, probably noise" territory crypto and "other" sit in (both ≤~1.05x). Sports' sample was too small (2-6 violations) to read anything into.

**Adjacent-threshold spacing by category** (native units — degrees for weather, dollars for crypto, etc. — not directly comparable across categories): weather median spacing 2.0 (very fine-grained strikes), crypto median 250, other median 10. Sports showed an implausible mean (5.67e7) that's almost certainly a ticker-parsing artifact on a small, noisy sample — not treated as meaningful. Flagged as a plausible partial mechanism (finer-grained thresholds → smaller true gap between adjacent legs → easier to flip into an apparent violation from ordinary noise) but not confirmed on its own; the magnitude check (gap *still* being ~4x the spread despite the fine spacing) argues against this being the main explanation for weather's result.

## Check 9: Re-running Check 8 on the well-sampled subset only

Re-ran the category composition, rate, and magnitude checks restricted to the same well-sampled definition as Check 7 (both legs, both sides, n≥20 — 2,892 pairs) to make sure the weather signal wasn't itself a low-n artifact.

**Composition (well-sampled only):** crypto 65.0%, weather/climate 26.2% (up from 9.1% in the full sample — weather pairs disproportionately survive the liquidity filter), other 8.7% (down sharply from 27.6% — "other"/financial-index pairs are disproportionately thin), sports 0.03% (1 pair).

**Violation rate (well-sampled only):** crypto ≈9.0%/8.7%, other ≈19.8%/17.4%, weather/climate ≈48.5%/48.7% — essentially unchanged from the full-sample rate, confirming this isn't a small-sample artifact.

**Violation magnitude (well-sampled only):**

| category | side | median gap | avg spread | n violations | gap/spread ratio |
|---|---|---|---|---|---|
| crypto | yes | 4.57¢ | 8.33¢ | 170 | 0.55 |
| crypto | no | 5.20¢ | 8.06¢ | 164 | 0.65 |
| other | yes | 2.96¢ | 4.14¢ | 50 | 0.71 |
| other | no | 2.52¢ | 4.06¢ | 44 | 0.62 |
| weather/climate | yes | 23.61¢ | 4.29¢ | 368 | 5.50 |
| weather/climate | no | 23.65¢ | 4.37¢ | 369 | 5.42 |

The weather signal got *stronger*, not weaker, on the well-sampled subset — gap/spread ratio rose to ~5.4-5.5x and the median gap grew to ~23.6¢ (spread stayed tight, ~4.3¢). Crypto's ratio dropped further, to ~0.55-0.65 — even more consistent with pure spread noise than the pooled number suggested. This is the strongest, most defensible number produced by the investigation so far.

## Conclusion / reasoning update (2026-09-02)

The original §4.3 headline (29-33% naive violation rate) was a blend across every ladder family, and that blend was hiding sharply different behavior by category:

1. **Crypto ladders** (the majority of pairs) look close to efficiently priced once bid-ask bounce is controlled for — same-side violation rate ~9%, and the violations that remain are roughly spread-sized or smaller (ratio ≤~1, dropping below 1 on the well-sampled subset). Plausible explanation: crypto ladders reference one continuously observable live price, making cross-strike consistency easy for any participant to check and arbitrage away quickly.
2. **"Other" (financial/macro) ladders** show a similar pattern to crypto — weak evidence, gap/spread ratio consistently below 1.
3. **Weather/climate ladders** are the outlier and the main finding: a same-side violation rate of ~48-50% that's stable across every liquidity cutoff tested, and a gap/spread ratio of ~4-5.5x that got *stronger* on the most trustworthy (well-sampled) subset. This is hard to explain as bounce or ordinary noise — tight spreads combined with large, persistent cross-strike gaps is the signature of a real, structural pricing inconsistency, not measurement noise. A plausible (not yet confirmed) mechanism: fewer sophisticated participants actively cross-checking adjacent-strike consistency in weather markets compared to crypto.
4. Sports had too few well-sampled pairs (0-1) to draw any conclusion.

**Net implication for the report:** the ladder-arbitrage claim is better supported when narrowed specifically to weather ladder families rather than stated as a blanket property of all Kalshi ladder markets — a sharper, more defensible version of §4.3/§4.5's finding than the original pooled statistic.

**Still open / not yet tested:**
- Whether this pattern is stable out-of-sample (a held-out time window or held-out weather families not used in today's checks) rather than specific to the data mined so far.
- Whether the ~15-24¢ median gap survives Kalshi's trading fees and realistic execution slippage.
- Whether there's enough order-book depth to actually fill both legs near the observed prices in real time — everything so far is trade-print evidence, not a live order-book/liquidity check.
- Why weather specifically shows this pattern (participant/maker concentration and order-book depth by category haven't been checked) — currently a plausible story, not a confirmed mechanism.
- Whether the regex-based ladder-pair identification used in Check 6 matches the original §4.3 script's validated pair list (not yet cross-checked).

## Next steps (as of 2026-09-02)

1. Cross-check the Check 6 pair list against the original, validated §4.3 pair-identification logic to confirm today's pairs match.
2. Confirm the `TIMESTAMP_COL` dtype/unit used in Check 7's time-gap test (assumed nanoseconds, not verified) so those numbers can be trusted quantitatively rather than just directionally.
3. Investigate order-book depth / maker concentration specifically for weather vs. crypto ladders, to test the "fewer sophisticated participants" explanation directly rather than leaving it as a plausible story.
4. Apply a fee/slippage estimate to the well-sampled weather violation gaps to see how much of the ~23¢ median survives realistic execution costs.
5. Re-run the well-sampled category check on a held-out time window (e.g. a later month not used in today's checks) to test out-of-sample stability of the weather result.
