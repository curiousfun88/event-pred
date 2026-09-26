# What the MECE population actually is (May–Sep 2025)

**Measured, VAL split, 12,177 complete basket-snapshots across 19 series.**
Produced by `diagnose_basket_composition.py`. Corrects two claims carried
over from the earlier investigation window.

**Terminology note added later:** the columns headed "opportunities" below
count snapshots whose last-trade basket sum deviates from $1 by more than the
stated threshold. `spread-artefact-finding.md` established that ~92.5% of that
deviation is bid/ask overround rather than mispricing, so read these as
**dislocation in traded prices**, which is what the composition analysis is
about, and not as tradeable opportunities. Nothing else in this document
changes.

## 1. It is not 93% weather

| category | all baskets | dislocation >1¢ | dislocation >5¢ |
|---|---|---|---|
| sports | **51.9%** | 45.5% | 24.4% |
| weather | 32.0% | 36.4% | **58.0%** |
| other | 6.9% | 7.7% | 8.8% |
| financials | 5.5% | 6.3% | 0.7% |
| politics | 3.7% | 4.1% | 8.2% |

The earlier figure of 249/267 (93%) weather came from the 2025-10/11
window. On the window the STGAT is actually trained and evaluated on, the
population is substantially more diverse, and **the composition depends on
the threshold**: sports dominates all baskets and small dislocations, while
weather dominates large ones.

The largest single series is `KXMLSGAME` at 26.3% of all baskets.

**Why this matters for the write-up.** The model is not learning one
family's seasonal pattern. It sees at least four structurally distinct MECE
partitions:

| family | structure | legs |
|---|---|---|
| soccer (MLS, EPL, LaLiga, Bundesliga, Ligue 1) | home / draw / away | 3 |
| Fed decision | discrete policy outcomes | 5 |
| weather `KXHIGH*` | temperature brackets | 6 |
| approval `KXAPRPOTUS` | rating brackets | 6 |

The generalisation claim can therefore be stated as "cross-sectional
no-arbitrage structure across sports, weather, macro-policy and political
prediction markets" rather than being scoped to weather. Seasonality drops
from a first-order concern to a caveat affecting the large-dislocation
tail.

## 2. Large baskets DO achieve full coverage — an earlier claim is superseded

`superseded-findings-summary.md` states that "every 14+ leg family has
**NEVER** contributed a single full-basket snapshot at any MAX_LEGS setting
tested". That was true on its window. It is **not** true on May–Sep 2025:

| series | legs | snapshots >5¢ | median \|dev\| |
|---|---|---|---|
| `KXF1RACE` | 20 | 76 | 20¢ |
| `KXNASCARRACE` | 41 | 52 | 30¢ |

Small numbers, but non-zero, and they carry the largest dislocations in the
dataset. The absolute wording in the summary doc should be qualified to its
window.

They remain untradeable, and for the documented reason: 41 legs at ~4.7¢ of
measured spread is roughly 96¢ of cost per contract against 30¢ of gross.
This is the leg-count mechanism in its most extreme observable form and is
a useful concrete illustration for the economics chapter.

## 3. Dislocation per leg peaks at six legs

| family | legs | median \|dev\| | **\|dev\| per leg** |
|---|---|---|---|
| soccer | 3 | 2.5¢ | 0.83¢ |
| Fed decision | 5 | 3.0¢ | 0.60¢ |
| weather `KXHIGH*` | 6 | 8.0¢ | **1.33¢** |
| approval `KXAPRPOTUS` | 6 | 14.0¢ | **2.33¢** |
| `KXLLM1` | 7 | 5.0¢ | 0.71¢ |
| F1 | 20 | 20.0¢ | 1.00¢ |
| NASCAR | 41 | 30.0¢ | 0.73¢ |

Execution cost scales strictly with leg count, so `|dev| / N` is what
decides whether a family is ever tradeable — not `|dev|` alone. It peaks at
six legs, which is exactly where the dislocation population concentrates
once a meaningful threshold is applied (weather rises from 32% of all
baskets to 58% of >5¢ dislocations).

This is a sharper, measured version of the project's central economic
claim: leg count creates the dislocation *and* prices it out of reach, and
the optimum sits around six legs.

**Consistency with the overround finding.** The overround prediction is
`h(2p−1)` per leg, so *signed* deviation grows linearly in N and `|dev|/N`
should be roughly flat at ~1.05¢ if the artefact were the whole story. The
table's 0.60–2.33¢ spread around that is the residual structure — and the
weather/approval peak is consistent with those families having the widest
per-leg spreads, which is exactly the mechanism §6 of
`settlement-arbitrage-result.md` identifies as anti-selective. Do not present
§3 as a pure mispricing gradient without that qualification.

## 4. Coverage

3,778 basket-snapshots were skipped as incomplete (at least one leg
unobserved), against 12,177 complete — consistent with the 18.3% partial /
5.4% sparse split reported by `diagnose_basket_coverage.py` on the same
split.

Note that these counts are **basket-hours**, not basket-days: the graph grid
is hourly and consecutive snapshots of one basket are overwhelmingly frozen.
The effective independent unit is the basket-day. See
`mece-yield-by-month.md` §4b.

## 5. Method note

The category rollup uses a keyword fallback over the series prefix, not
Kalshi's own category field. A first version classified `KXMLSGAME`,
`KXLALIGAGAME`, `KXBUNDESLIGAGAME`, `KXLIGUE1GAME`, `KXF1RACE` and
`KXNASCARRACE` as "other" — 52% of the population — because the keyword
list only covered the US leagues. It also classified `SOMETHINGNEW` as
crypto, because substring matching found "ETH" inside it; the matcher now
strips the `KX` prefix and requires the keyword at the start of the family.

Both were caught by the script's self-test and a real run respectively.
Prefer `--categories results/data_audit/kalshi_series_categories.parquet` where available; the
keyword list is a convenience, not a source of truth, and the script now
names any unclassified series when "other" exceeds 10%.

This is the same weak-instrument problem documented at greater length in
`data-window-liquidity-regime.md` §1, where a keyword sweep under-detected
sports by two orders of magnitude in a month when Kalshi's own category field
put sports at 86.9% of notional. Use the lookup, not keywords, for anything
load-bearing.

## 6. Follow-ups

1. Re-run on the extended 2024-11 → 2025-11 range once `cache/` is rebuilt.
   Football seasons start in August, so May–Sep straddles an off-season for
   several leagues and the sports share is likely understated relative to a
   full year.
2. Qualify the "14+ legs never" sentence in
   `superseded-findings-summary.md` to its window.
3. Report the §3 table in the economics chapter — it is the most direct
   evidence for the leg-count argument the project has — with the §3
   overround qualification attached.
