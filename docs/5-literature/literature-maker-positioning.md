# Literature: market making in prediction markets (positioning)

Searched 2026-09-29, before any maker test-month result. Scope: maker vs
taker returns on Kalshi, market-making models for prediction markets,
replay simulators with fees, and learned models as adverse-selection filters.

## Closest work

**Bürgi, Deng & Whelan, "Makers and Takers: The Economics of the Kalshi
Prediction Market"** (UCD, January 2026; karlwhelan.com/Papers/Kalshi.pdf;
also GWU FORCPGM WP 2026-001).
- Transaction-level data, 2021 to April 2025: 46,282 contracts, 12,403 events,
  >300,000 prices.
- Makers earn higher returns than takers, but both show a favourite-longshot
  pattern: low-price contracts lose after fees, high-price contracts win more
  often and yield small positive returns.
- Aggregate returns by side over whoever was filled. No implementable
  strategy, no queue position, no new-entrant question.
- Relation here: the same kind of evidence as this project's May-June tape
  screen (makers +2.2% net, CI [+0.6, +3.6]); both show an edge exists in
  aggregate. This project asks whether a new entrant can capture it.
- **Tension to discuss.** The A6 maker winner sells YES at 85-99c (i.e. takes
  the longshot NO side as a maker). Under the favourite-longshot pattern,
  high-price YES buyers earn small positive returns, which works against
  that position; the maker's spread capture and fee advantage must outweigh
  it. A10's grid includes the bid side of the same band, so the development
  data, not this note, decides.

**Arora & Malpani, "PredictionMarketBench"** (arXiv 2602.00133, Jan 2026).
- Deterministic, event-driven replay of Kalshi order-book and trade data
  (crypto, weather, sports) with maker/taker semantics, fees and settlement
  risk; evaluates classical algorithms and LLM tool-calling agents.
- Simple strategies struggle against costs and settlement losses;
  fee-aware algorithmic strategies remain competitive in volatile episodes.
- Relation here: the nearest methodological analogue to
  `simulate_maker.py`. Differences to state: this project's simulator runs
  on the full trade tape with hourly quote candles (no depth), brackets queue
  position with optimistic / pessimistic / strict fill models, restricts to
  MECE legs, and pre-registers a single out-of-sample test.

**Feil & Nendel, "Optimal Market Making in Prediction Markets"** (arXiv
2607.17991, July 2026).
- Theory: stochastic control with the price as a conditional probability
  driven by a latent belief diffusion; HJB solution for optimal bid/ask under
  inventory and settlement risk; numerical illustration only, no tape backtest.
- Relation here: the theoretical frame for why quotes should depend on
  inventory, time to resolution and beliefs (cf. the inventory cap and A10's
  `min_ttc_h`). Cite as theory, not as empirical evidence.

**Dubach, "The Anatomy of a Decentralized Prediction Market"** (arXiv
2604.24366, Apr 2026).
- Polymarket tick-level order book, 30B events, 600 markets. Longshot spread
  premium; feed-inferred trade direction matches on-chain truth only ~59%,
  enough to flip the sign of effective half-spreads on many markets.
- Relation here: supports using Kalshi's recorded taker side (as this project
  does) rather than inferring direction; no strategy evaluation.

## Classical background

- Glosten & Milgrom (1985): adverse selection sets the spread. The S4 filter
  is an attempt to reduce exactly this cost.
- Avellaneda & Stoikov (2008): inventory-aware quoting. Motivation for the
  inventory caps.
- Learned models on limit order books: DeepLOB (Zhang, Zohren & Roberts,
  arXiv 1808.03668); deep RL market making (e.g. Guo et al., arXiv
  2305.15821); deep fill-probability estimation (Columbia, 2021). All on
  equity/crypto books, not prediction markets.

## Positioning (as of this search)

Not found in the searched literature:
1. a tape-driven simulation of a **new-entrant** maker on Kalshi with
   bracketed queue-position assumptions and the actual maker-fee schedule,
   selected on development months and tested once out of sample;
2. a **graph model over mutually exclusive outcome baskets** used as an
   adverse-selection filter (S4) or quote driver (S5) for a maker.

Phrase it as "to our knowledge" and cite PredictionMarketBench as the
closest simulator and Bürgi-Deng-Whelan as the closest empirical evidence.
The search was web-only and not exhaustive (no SSRN/Google Scholar full
sweep); a final check before submission is advisable.
