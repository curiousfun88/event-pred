# CORRECTION: the violations are not stale prints

Written 2026-09-19. **This supersedes §1b of `stgat-results-and-limitations.md`
and every conclusion drawn from it.** Script: `diagnose_mask_semantics.py`.

> **Later qualification, and it is important.** This document correctly
> establishes that a leg appears in the dataset *only when it traded*, so an
> unchanged price is a sticky price under active trading, not a carried-forward
> stale one. That finding stands and is verified.
>
> What this document then inferred from it — that the apparent violations are
> therefore genuine mispricings and the opportunity set is real — **does not
> survive.** A price can be freshly traded and still be unusable for measuring
> a constraint, because a trade prints at the **bid or the ask, never at mid**.
> `spread-artefact-finding.md` measured that: 68.7% of prints are ask-side, and
> ~92.5% of apparent MECE basket deviation is the resulting overround.
>
> So there were two distinct data-quality objections, not one. This document
> disposes of **staleness**. It does not touch **one-sidedness**, and
> one-sidedness is the one that turned out to matter. §4 below is corrected
> accordingly.

---

## 1. What was claimed

`stgat-results-and-limitations.md` §1b reported that apparent ladder arbitrage on
Kalshi is overwhelmingly an artifact of comparing two stale last-trade prints:

> 90% of consecutive snapshot observations show no price change... 98.3% of
> violations surviving one snapshot had zero price movement on both legs...
> `last_yes_price` is a last *traded* price, not a live quote. Two stale prints
> struck hours apart will show a monotonicity violation indefinitely, and neither
> is a price anyone can trade against.

The measurements are correct. **The interpretation is wrong** — specifically the
word *stale*. The final clause ("neither is a price anyone can trade against")
turns out to be right for a different reason; see the banner.

## 2. What was never checked

The reading assumed `mask = True` means "this leg has a price, possibly carried
forward from an old trade." It was never verified. It is false.

Measured over masked ticker positions (val split, 186,809 positions):

| slot | feature | zero% | p25 | median | p75 | max |
|---|---|---|---|---|---|---|
| 0 | last_yes_price | 0.0% | 4.00 | 23.00 | 58.00 | 99.00 |
| 4 | **window_volume** | **0.0%** | **30** | **183** | **935** | 3,002,222 |
| 5 | net_flow | 0.4% | −0.689 | 0.820 | 1.000 | 1.000 |
| 6 | buy_ratio | 20.3% | 0.156 | 0.910 | 1.000 | 1.000 |

**`window_volume` is zero on 0.0% of observed positions.** A leg appears in this
dataset only when it traded in that window.

And restricted to positions whose price did **not** change from the previous
snapshot — the exact population behind the staleness claim — median volume is
**204**, *higher* than the overall 183.

## 3. The corrected reading

> Both legs traded, a median of ~200 contracts each, and came out at the same
> price. Repeatedly, for up to 24 hours. **The market is actively trading
> through these monotonicity violations without correcting them.**

An unchanged price is a *sticky* price under active trading, not an absent one.

This is the durable content of this document, and it is worth stating in the
thesis. It is also the fact that makes the overround explanation *necessary*: if
the prints were merely old, the deviation would need no further explanation. They
are not old. They are one-sided.

## 4. What changes — CORRECTED

The original version of this section is struck through where later work reversed
it. The correction is not that the measurements were wrong; it is that "not
stale" was read as "therefore tradeable", which does not follow.

**Stronger than before, and still stronger:**

1. ~~**The opportunity set is real.** The 2,489 September violations are not ~98%
   artifacts. They are genuine, actively traded, persistent mispricings. This was
   the weakest link in the thesis and it is removed.~~ **Half-withdrawn.** They
   are genuine, actively traded and persistent — but they are not *mispricings*.
   On the MECE mechanism the same class of apparent violation was decomposed and
   ~92.5% of it is the bid/ask overround; the executable edge is −0.07¢ before a
   1.3–5.8¢ fee. "Not a staleness artifact" and "a mispricing" are different
   claims and only the first is established here. The weakest link in the thesis
   was not removed; it moved.
2. ~~**Liquidity exists at the quoted level.** Median ~200 contracts per 2-hour
   window means a resting order at that price has counterparties.~~ **Restated.**
   Median ~200 contracts traded per window is real and does mean there are
   counterparties. What it does *not* establish is depth at a *specific* price,
   because the archive contains no order-book data at all — only prints. The
   claim "a resting order does not fill against a price nobody is posting" was
   withdrawn here on the strength of volume; that withdrawal was premature,
   because volume at unknown prices is not depth at a known one.
3. ~~**The maker route is live again.**~~ **Not pursued.** Zero maker fees on the
   non-listed series is a real feature, but the fee shape was never verified and
   there is no fill model, and adverse selection is unaffected by anything in
   this document. Recorded as provisional in
   `maker-execution-provisional.md` and left below the cut line.
4. **Limits to arbitrage is now a clean finding, not a confound.** The market
   trades through violations it does not correct. **This survives, and the later
   work sharpened rather than weakened it:** the explanation is friction, and the
   friction turns out to be the spread itself in the most direct possible sense —
   the apparent violation *is* the spread. That is a stronger version of the
   textbook result, not a retreat from it, and it is now measured rather than
   inferred from a cost comparison.

**Unaffected:**

- Ladder pair identification and direction. `verify_ladder_direction.py`:
  **100.0%** of 2,472,029 pairs have `strike(leg_a) < strike(leg_b)`, zero
  threshold/bracket mixing. The gap sign is correct everywhere. *(Separately,
  the `yes_sub_title` correction later narrowed which pairs count as a valid
  monotone chain — that is a membership question, not a direction one.)*
- Measured spreads, fee formulas, the ex-ante ceiling, and the MECE/ladder
  output-head identities (§3a).
- The conditional-survival measurement itself: violations do persist while prices
  hold, and mostly vanish when a price moves. That is now near-tautological —
  `gap = p_b − p_a`, so if neither price moves the gap cannot — and should be
  reported as a property of price stickiness, not of data quality.

**Weakened:**

- ~~Any claim that apparent arbitrage in prediction markets is largely a
  measurement artifact. It is not, on this venue, in this dataset.~~ **This
  reversal is itself reversed.** Apparent arbitrage in this dataset *is* largely
  a measurement artifact — just not the artifact this document tested. The
  mechanism is one-sided prints, not stale ones. The project's central finding is
  now precisely the claim this bullet retracted, arrived at by a different route.
- The "surveillance not trading" framing for coverage (§4) still holds on its own
  evidence (estimation error exceeds signal), but its second argument — "those
  legs are unobserved because they are illiquid" — needs restating: legs in this
  dataset are not unobserved-because-illiquid, they are simply absent when they
  do not trade.

## 5. Consequence for the model

The training-distribution problem identified earlier is **real but differently
caused**. 53.9% of masked ticker positions show no price change from the previous
snapshot. Those are legitimate observations of genuine trades, not fiction — so
they cannot be filtered out as noise. But they still make `delta = 0` the
loss-minimising answer over half the time.

The `--supervise active` liveness filter added to `train_forecast.py` is therefore
**vacuous** (`mask` already implies volume > 0) and its mechanism counts are
unchanged from the unfiltered run: ladder n=426,061, mece n=64,717 in both. Only
its mechanism-membership component had any effect.

The right handling is not filtering but **stratified reporting**: score the model
against persistence separately on positions where the price moved and where it
did not. On non-movers persistence is exactly right and the model can only lose;
on movers persistence is uninformative and the model has room. A pooled ratio
averages those two regimes and hides both.

This became the project's standard practice and it is what made
`ladder-conclusion-overturned.md` possible — the frozen/moved stratification is
the same tool applied to the pair population instead of the node population.

## 6. Methodological note

This is the fifth claim in this project to survive until its weakest premise was
tested, and the second to rest on an assumption about the data rather than a
missing baseline. The pattern in `stgat-results-and-limitations.md` §5 extends:

> **Name the assumption that would have to be true, and measure it, before
> building a result on top of it.** For a baseline, that means the laziest
> alternative. For a dataset, it means what the columns actually contain.

**And the sequel, which is the lesson this document itself supplies.** Having
tested one assumption about the column (`mask` implies a fresh trade — true), it
went on to build a conclusion on a *second*, untested assumption about the same
column (a fresh trade implies a fair price — false). Disposing of one
data-quality objection is not disposing of the class. The full statement is:

> Enumerate the ways the data could produce this number without the phenomenon
> existing. Test them all before claiming the phenomenon. Ruling out one
> mechanism licenses nothing about the others.

For a last trade print, that enumeration is at minimum: is it recent, and which
side of the book is it on? This document answers the first. It took another week
to ask the second.
