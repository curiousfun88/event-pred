# Data window: the binding constraint is a liquidity regime change, not the catalogue

Settles two questions at once: (a) is `category_history_audit.py`'s
"sports first appears 2024-12" a classification artefact? (b) how many
months of Kalshi history can legitimately be pooled into one training
set?

Produced by `stg_infra/examples/sports_categorisation_check.py`
(checks A/B on all 54 months of markets files; check C on trades
2024-06 → 2025-11). 21 self-tests pass, including a planted-early-sports
recovery case and a 5,000-market election decoy that must NOT count as
sports.

---

## 1. The sports categorisation is correct

Prompted by the published figure that sports is >90% of Kalshi site
activity and 89% of revenue in 2025, which appears to contradict a
2024-12 first-seen month.

**Check B is decisive.** `kalshi_series_categories.parquet` maps 13,738
series, and `mapped_share` is ~1.00 in every one of the 54 months —
minimum 0.86 (2022-09), and exactly 1.00 for all of 2021. The lookup is
**not** time-bounded to currently-listed series. Every early-month
series therefore carried Kalshi's own `category` field, and the nine-word
keyword fallback was never load-bearing for the audit. The hypothesised
failure mode (retired series falling through to a weak heuristic) does
not exist.

**Check A corroborates.** Exactly 8 markets across 3 series match an
unambiguous sports pattern before 2024-12:

| series | first month | markets | Kalshi category |
|---|---|---|---|
| `NFLVIEW` | 2021-09 | 4 | entertainment |
| `MLBOAK` | 2021-11 | 3 | entertainment |
| `MLBCBA` | 2021-11 | 1 | entertainment |

None is a sporting event contract. They are NFL viewership, the Oakland
A's relocation, and the MLB collective bargaining agreement — *news about
sports*, which Kalshi could list under CFTC rules. Wagers on game
outcomes it could not, until the regulatory position shifted in late
2024. Kalshi's `entertainment` label is defensible; the distinction is
the regulatory one.

Real launch profile: `KXNBATEAM` (1 market, 2024-12) → `KXNHL`,
`KXNBA`, `KXNBAEAST/WEST`, `KXUEFACL` (2025-01) → ~26 series at once in
2025-02 (`KXPGATOUR`, `KXMLB`, `KXNCAAF`, `KXLALIGA`, `KXSERIEA`,
`KXBUNDESLIGA`, `KXWNBA`, …). That is a product launch, not a
reclassification.

### Caveat on check A's instrument

Check A is a *weak* instrument and should not be cited on its own. In
2025-03 Kalshi's category field puts sports at 86.9% of notional while
the keyword sweep sees 0.7% — the sweep under-detects sports by two
orders of magnitude in the same month. That is exactly why check B
matters: the audit never depended on keywords. Any future claim about
early-month categories should rest on B, not A.

### Minor gaps found (no material effect)

- 32 of 330 strong-sports series carry a non-sports Kalshi label. All
  inspected cases are arguably correct: `KXESPYNFL`/`KXESPYUFC` (ESPY
  awards → entertainment), `KXSUPERBOWLHEADLINE`, `KXNBA2KCOVER`,
  `KXCANNESGRANDPRIX` (film festival, matched on `GRANDPRIX`),
  `KXDJTGOLF` (politics).
- `KXMLBWINS` (150 markets, 2025-05) is genuinely unmapped and genuinely
  sports — one of only 16 unmapped series platform-wide.
- The `weak` column explodes to 120,311 in 2025-10: the `exotics`
  NFL/NBA parlays, consistent with the earlier exotics finding.

---

## 2. The published volume claim reproduced in our own data (check C)

Sports share of monthly traded notional:

| month | sports % | month | sports % |
|---|---|---|---|
| 2025-01 | 4.1 | 2025-07 | 75.2 |
| 2025-02 | 3.8 | 2025-08 | 80.0 |
| **2025-03** | **86.9** | 2025-09 | 82.3 |
| 2025-04 | 69.8 | 2025-10 | 86.5 |
| 2025-05 | 78.5 | 2025-11 | 87.2 |
| 2025-06 | 83.4 | | |

The takeover step is **2025-03**, and 87.2% in 2025-11 reproduces the
89%-of-revenue figure independently. Before 2025-01 sports is absent
from the trades files entirely — further confirmation of §1.

This also resolves the apparent paradox in the original audit: sports is
~2% of *listed markets* (60,243 of ~4.2M) and ~87% of *volume*, because
crypto and financials mint hundreds of thousands of hourly strikes that
barely trade while one game market absorbs enormous size.

---

## 3. The actual finding: a 369× liquidity regime change

Total platform traded notional per month:

| month | total notional | weather/climate notional |
|---|---|---|
| 2024-06 | $3.2M | $0.31M |
| 2024-09 | $3.7M | $0.54M |
| 2024-11 | $49.6M | $12.6M |
| 2024-12 | $24.4M | $10.3M |
| 2025-02 | $26.0M | $5.6M |
| 2025-05 | $211.0M | $2.95M |
| 2025-09 | $490.9M | $4.42M |
| 2025-11 | $1,193.0M | $4.77M |

**2024-06 → 2025-11 is 369×.** The current training window (2025-05…09)
averages $264M/month; 2024-06…09 averages $3.75M/month — a **70×** gap.

This is the answer to "the number of months is too few". Adding 2024
months does not enlarge the sample; it pools observations from a venue
two orders of magnitude thinner. Every quantity the thesis measures —
implied leg spread, basket completeness, deviation persistence,
executable participation size — is a function of depth, so pooling
across a 70× depth change estimates a parameter that does not exist in
either regime. The window is bounded by **liquidity stationarity**,
which is a methodological argument, not an apology.

### Weather liquidity: the nuance that matters for the extension

Weather's *share* collapses from 42.3% (2024-12) to 0.4% (2025-11), but
that is the denominator exploding. In absolute terms:

- 2024-06…09 mean: **$0.49M/month**
- 2025-02…04 mean: **$4.37M/month**
- 2025-05…09 mean: **$3.59M/month** (current training window)

Weather — 58% of the >5¢ MECE opportunity population — was *more* liquid
in 2025-02…04 than in the months currently trained on. Extending
backwards therefore adds months of comparable or better depth in the
dominant opportunity category.

---

## 4. Decision

**Use 2024-11 → 2025-11.** (An earlier version of this document proposed
2025-02 → 2025-11; `mece-yield-by-month.md` later established that
2024-11 and 2024-12 belong to the same dense block, and
`split-design-correction.md` fixed the split design.) Justified on
grounds now measured rather than assumed:

1. Sports, 51.9% of the basket population, does not exist before
   2025-01 — a regulatory fact, not a data artefact (§1).
2. Total notional inside the window still spans a large multiple, which
   must be reported; extending to 2024 would make it 369× (§3).
3. Weather depth in early 2025 is comparable to the current window, so
   the added months are usable for the dominant opportunity category
   (§3).

### Reporting obligation

The within-window growth must appear as a stated limitation, with the
split boundaries chosen so train/val/test are not silently ordered by
platform size. A test split of 2025-10…11 is several times the notional
of the training months — out-of-sample in liquidity as well as in time.
