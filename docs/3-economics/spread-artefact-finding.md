# The MECE deviation is largely a spread artefact

**Provisional but serious.** Established below with no model and no mid
estimate. Bears directly on the settlement PnL headline. Produced by
`stg_infra/examples/mece_spread_artefact_check.py` (27 self-tests).

---

## 1. The question

A last trade is struck at the bid or the ask, never the mid. For a six-leg
basket with a per-leg spread near 5.6¢, if each leg's last print lands on
either side at random the sum has SD ≈ √6 × 2.8¢ ≈ 6.9¢ around $1 with **no
mispricing at all**, median |dev| ≈ 4.6¢. The project's measured median is
**4¢**. So the headline deviation had to be tested rather than assumed.

## 2. Mechanism, predicted then measured

Kalshi trades carry `taker_side`. A taker buying YES lifts the ask; a taker
buying NO sells YES into the bid. In one month's trades:

- ask-side prints: **1,313,622** (68.7%)
- bid-side prints: **597,773** (31.3%)

With ask-share *p* = 0.687 and half-spread *h* = 2.8¢, each leg's last print
sits above mid by *h*(2*p*−1) = 1.05¢, so a six-leg basket should show a
signed mean deviation of **+6.3¢** from order-flow imbalance alone.

**Prediction stated before running. Measured: +5.25¢, with 92.5% of 4,891
baskets summing above $1.** A genuine mispricing population would be roughly
balanced between sum > $1 and sum < $1. This is the classic betting-market
overround.

Orientation independently confirmed: median `mean(yes) − mean(no)` per ticker
is **+3.82¢**, positive as required (75.6% of tickers; the remaining quarter
is the same price-drift contamination that made pooled per-leg spreads read
5.61¢ against a windowed 4.68¢).

## 3. The executable reading

Restricting to baskets where every leg has both sides priced and all legs'
last prints fall within 30 minutes of each other (**n = 467**, 9.5% of
4,891):

| | sum of last prints |
|---|---|
| buy every leg at the **ask** | **$1.1492** |
| sell every leg at the **bid** | **$0.9987** |
| settlement pays | **$1.0000** |

**Selling the "overpriced" basket at executable prices nets −0.13¢ gross,
before any fee.** Buying at the ask loses 14.92¢. The implied mid sits at
$1.074, but nothing trades at mid.

Stable across settings: bid-side sum is $1.0114 at a 60-minute span and
$0.9993 with no span limit. The apparent +4¢ deviation lives entirely on the
ask side and **is not capturable on the average basket**.

## 4. The gated tail — RESOLVED, and it fails too

The cost gate does not trade the average basket, it trades the tail. Test 3
was rewritten to ask that population the executable question directly: sell
at the bid if the basket is above $1, buy at the ask if below, compare
against $1.00 settlement. No mid, no cross-leg averaging.

Result (span 60, gate threshold 10¢):

| population | n | median gross | share positive |
|---|---|---|---|
| all two-sided baskets | 662 | **+1.00¢** | **84.0%** |
| gated tail (\|dev\| > 10¢) | 37 | **+1.00¢** | **54.1%** |

**The gate selects worse baskets, not better.** Share positive falls from
84% to 54% and the mean goes to −4.08¢. Selecting on a large last-trade
deviation does not select on executable edge; it selects on *wide spreads*,
because a wide spread is what produces a large apparent deviation. Wide-spread
baskets execute worse. The selection criterion is anti-correlated with the
thing it is meant to find.

The +1.00¢ median with a −0.07¢ mean is, on cent-quantised prices, the
smallest expressible positive value: the bid sum rounding just above $1
slightly more often than not. Against Kalshi's taker fee on a six-leg basket:

| leg price profile | taker fee per basket-contract |
|---|---|
| flat (6 × 16.7¢) | 5.83¢ |
| skewed | 4.45¢ |
| peaked, near resolution | 1.31¢ |

Fees are 1.3× to 5.8× the gross edge, and selling at the bid means *taking*.
No configuration survives.

**Caveat.** Test 3's gate is a crude `|dev_last| > 10¢` threshold, not the
production gate `|dev|·C > modelled cost`. But that does not rescue the
production gate, which computes gross profit as `|dev_t| × C` from mixed
last prints — the quantity now known to be ~92.5% overround. It subtracts a
modelled spread from a gross that *is* the spread.

## 5. Consequences

- **The +$292 half-spread figure is withdrawn.** A half-spread charge does
  not move the entry price from a mixed last print to the bid.
- The **+$46 full-spread** figure is the candidate survivor and should be
  re-derived from side-appropriate entry prices; expect it to shrink.
- The deviation is described throughout as **dislocation in traded prices**,
  never as arbitrage.
- **The model-versus-control result is untouched.** It is a paired
  comparison on identical baskets and is provably invariant to the entire
  cost model (`settlement-pnl-robustness.md` §2), which now carries more
  weight than when that was first noted.

## 6. Three bugs found in the checking script itself

Recorded because each produced a confidently wrong reading before it was
caught:

1. **The verdict could not express "the mid is worse than the last."** It
   printed "−242% of it was spread → the dislocation largely survives,"
   which is nonsense. A mid larger than the last-trade deviation means the
   mid is contaminated, not that the dislocation is real.
2. **The gap limit constrained the wrong gap.** `--max-side-gap` aligns each
   leg's own ask and bid prints; a basket sum needs the *legs* contemporaneous
   with *each other*, and the median cross-leg span is **406 minutes**. Added
   `--max-basket-span`, with a self-test that plants two legs three hours
   apart and proves the old limit accepts them.
3. **Test 3 read the mean-based mid**, which no span limit can clean because
   the span constrains last-print *times* while the mean averages the whole
   day. Systematic effect: sum of daily means runs ~8¢ above sum of last
   prints, because thinly-traded losing legs keep their early high prices in
   the average. All mid reasoning now uses last prints; the mean-based row
   survives as a diagnostic only.

## 7. What this makes the contribution

A backtest on prediction-market partitions that prices legs from trade
prints **without regard to execution side** manufactures profit that does
not exist at executable prices. The magnitude was predicted from the
order-flow imbalance before it was measured. That is the finding; the
withdrawn PnL is the illustration of why it matters.
