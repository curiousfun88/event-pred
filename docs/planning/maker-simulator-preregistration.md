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
