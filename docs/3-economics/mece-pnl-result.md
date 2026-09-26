# MECE forecast PnL: a directional edge, killed by the round trip

Test split, h=1 (2h round trip), 7,035 complete basket-snapshots across
345 distinct baskets, 100 contracts/leg, measured-taker cost model.

> **Two corrections to this document, both material:**
>
> 1. **The "measured-taker cost model" was not measured.** Every spread lookup fell
>    through to a global median borrowed from the *ladder* pairs file
>    (`spread sources: global=27,335`), which contains only crypto/financials pairs.
>    The §"Costs kill it" section flagged this as a known weakness, correctly. It is
>    now **fixed**: per-leg spreads are measured from MECE legs themselves
>    (`ticker=22,516, series=4,576`, 100% measured), the `--spreads` default points
>    at `mece_leg_spreads.parquet`, and a coverage guard banners below 50% measured.
> 2. **The gross edge is not a mispricing edge.** `gross` is computed from `|dev|`,
>    and ~92.5% of `|dev|` is bid/ask overround
>    (`spread-artefact-finding.md`). The model-vs-random comparison survives —
>    it is paired on identical events at identical cost, so the spread cancels
>    exactly — but the *level* of the gross column does not measure available
>    profit. The closing section's "maker could flip the sign, +$1.23/trade" is
>    **withdrawn**; see the note there.

## The table

| strategy | trades | win% | gross $ | gross/trade | net $ | net/trade |
|---|---|---|---|---|---|---|
| **model** | 2,366 | **51.1%** | **6,918** | **$2.92** | −72,372 | −30.59 |
| oracle_shrink | 2,405 | 45.5% | 4,937 | $2.05 | −77,708 | −32.31 |
| always_revert | 5,493 | 35.2% | 5,653 | $1.03 | −154,168 | −28.07 |
| random | 2,366 | 34.1% | 18 | $0.01 | −79,272 | −33.50 |
| static_arb | 5,493 | 100% | 30,541 | $5.56 | −49,961 | −9.10 |

## The model's edge is real and beats every predictive baseline

`random` trades the **same 2,366 events** as `model`, by construction —
same entry rule, coin-flip direction. That makes it a clean paired
comparison with no subset-selection confound:

- gross: **$6,918 vs $18**
- win rate: **51.1% vs 34.1%** (1.50× the null)

Random's 34.1% rather than 50% implies ~32% of baskets have a sum that
does not move at all between snapshots, which is consistent with the 74%
node-level flat rate. On baskets that do move, the model's directional
accuracy is roughly 75%.

Against the other predictive strategies on gross per trade, the model is
**2.84× always_revert** and **1.42× the shrinkage oracle**. `always_revert`
is barely distinguishable from random (35.2% vs 34.1%), so at h=1 the
naive reversion rule has almost no directional content — the model's edge
is not just rediscovering mean reversion.

**What the direction is a direction *in*.** The model predicts the sign of the
change in the basket sum, and the basket sum is dominated by where each leg's last
print sat in its spread. So the honest statement is that the model forecasts the
sign of the next move in a quantity that is mostly microstructural — which is a real
forecasting achievement and not a mispricing edge. The paired comparison is valid
either way; the label is what changes. The bid-side re-score settles it.

## Costs kill it, and not because of the spread assumption

| | per trade |
|---|---|
| fees | $6.76 |
| spreads | $26.76 |
| **break-even move required** | **33.5c** |
| mean \|delta\| observed | 2.26c |
| 90th percentile \|delta\| | 6.00c |

**Known weakness (since fixed):** `spread sources: global=27,335` — every lookup fell
through to the global median. Not one MECE ticker matched the per-ticker
or per-series tables in the ladder pairs file, so ~6.9c/leg is a constant
borrowed from a different market universe, and it is 80% of the cost.

*Resolution: measured per-leg spreads for MECE legs are **4.68¢** (windowed,
drift-corrected) and **5.61¢** (pooled). The borrowed 6.9¢ was too high, so this
run over-costed itself — but §"Why the conclusion survives" is unaffected, because
that argument runs at zero spread. A later, separate lesson: do not reason about
basket cost from a per-leg **median**, because cost is a **sum** over ~6 legs, the
mean governs, and the distribution is right-skewed (mean 5.43¢ vs median 4.68¢).
Predicting the direction of a cost change from the median got it wrong twice.*

**Why the conclusion survives anyway:** at *zero* spread cost, fees alone
require a 6.76c move against a 6.00c 90th percentile. Fewer than 10% of
opportunities clear costs even with a perfect forecast and free execution.
The binding constraint is the round trip — entry and exit on every leg —
not forecast quality and not the spread estimate.

At zero spread the net figures would be: model −$9,067, always_revert
−$35,133, **static_arb +$9,557**.

*That last figure is the one that motivated the hold-to-settlement redesign, and the
redesign was correct: settling rather than exiting removes one full set of fees and
one spread crossing per leg, worth ~$21/trade. It produced a positive backtest. It
is still not profit, because the gross term is the overround —
`settlement-arbitrage-result.md` §6.*

## On comparing against static arbitrage

Two different benchmark classes, and they answer different questions:

- **Model benchmarks** (same trade structure, different signal):
  oracle_shrink, always_revert, random. The model wins all three on gross
  edge. This answers "is the STGAT doing something".
- **Deployment benchmarks** (different trade structure): static_arb
  crosses each leg once because settlement is free. This answers "what
  should someone actually run", and is not a statement about the model.

Static arbitrage is *not* "bound to be better" — it also loses money here
(−$9.10/trade). It is less bad because of its cost structure, not because
it is smarter.

*Of the three model benchmarks, only `random` shares the model's trade set, so only
that comparison is cost-invariant. The other two have their own gates and therefore
their own spread bills; their gaps are conditional on the cost model. Worth stating
when the table is reproduced.*

## Where this sits in the literature

- Whelan, *Makers and Takers: The Economics of the Kalshi Prediction
  Market* — average return on Kalshi contracts is about **−20%**; makers
  **−9.64%** vs takers **−31.46%**. Through April 2025 Kalshi charged fees
  to takers only. Makers earned **+2.6%** on contracts above 50c. A
  negative net result for a taker strategy is the norm, not an anomaly.
- *Executable Arbitrage and Market Efficiency in Prediction Markets*
  (arXiv 2608.00666) opens "contrary to assumptions of unprofitability" —
  i.e. unprofitability after costs is the literature's default. It finds
  $1.12M on Polymarket using **depth-aware executable portfolio values**,
  and 97% of that came from a converter primitive rather than from
  settlement baskets.
- *Semantic Non-Fungibility and Violations of the Law of One Price*
  (arXiv 2601.01706) — 2-4% execution-aware deviations persist even in
  liquid venues, with high-yield opportunities "typically short-lived".

*The Executable Arbitrage paper is the closest methodological neighbour and the
comparison is now sharper than this section makes it: its panels run 14 Apr – 19 May
2026 (~5 weeks, order book) and settlement baskets are only ~3% of its $1.12M, so it
is **not** primarily a sum-to-one study. Of the three nearest papers only the AFT one
treats sum-to-one as a primary object, over a 12-month window. See
`literature-sample-periods.md`. Its use of **depth-aware executable** values rather
than trade prints is precisely the methodological point this project arrived at
independently, by a different route.*

## CITATION CORRECTION NEEDED

`superseded-findings-summary.md` (and anywhere else it is
repeated) describes the AFT/arXiv 2508.03474 result as **"~$39.6M
apparent, ~1% exploited"**. The paper's abstract reads *"a realized
estimate of 40 million USD of profit extracted"*, and a full-text check
confirms it **does not quantify apparent opportunity and reports no
capture rate**. The current phrasing says close to the opposite of the
source and must not go into the dissertation as written.

*Still outstanding. `superseded-findings-summary.md` is now retired as stale,
which removes the immediate risk, but check the LaTeX before submission.*

## What this does and does not establish

Established: a genuine, replicated directional edge on MECE basket
dislocation that beats every no-model baseline on gross PnL, and which
is unprofitable as a **taker** round-trip strategy for a structural,
quantified reason.

Not established: whether a **maker** implementation clears. Taker fees are
$6.76/trade; the maker rate of 0.0175 puts the same fees at ~$1.69, and a
posted order earns the spread rather than paying it. Against a gross edge
of $2.92/trade that is roughly **+$1.23/trade**. This is the one remaining
change that could flip the sign, and it requires a fill model with adverse
selection — Whelan's makers still lost 9.64% on average.

> **The +$1.23/trade is withdrawn, and the reasoning behind it is the project's
> most instructive error.** The calculation treats the gross edge and the spread as
> two independent quantities, so that earning the spread instead of paying it adds
> the spread to the edge. They are not independent: the gross edge **is**
> substantially the spread. 68.7% of prints being ask-side puts each leg ~1.05¢ above
> mid, which is +6.3¢ on a 6-leg basket — predicted in advance, measured at +5.25¢.
> Subtract the spread and what remains is **−0.07¢** at executable quotes.
>
> So earning the spread does not convert this edge into profit; it converts the
> strategy into market making, whose economics are adverse selection and are measured
> nowhere in this project. The maker route stayed provisional (fee shape never
> verified, no fill model) and is below the cut line. See
> `maker-execution-provisional.md` and `spread-artefact-finding.md`.
>
> The general lesson, which belongs in the methodology chapter: **before adding a
> cost term back as revenue, check that the edge you are adding it to is not the same
> quantity.**
