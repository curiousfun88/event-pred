# Negative results

Work that was done, measured and reported in earlier drafts of the report, but left out of the final report
(*The Law of One Dollar: Machine Learning for Market Making in Kalshi Prediction Markets*, submitted 3 November 2026),
which reports only the results that carry its argument. This file keeps them on record for accountability. Every
figure is the one the report's earlier drafts used, with the evidence behind it.

Contents:

1. [Routes tried before policy G](#1-routes-tried-before-policy-g)
2. [The STGAT forecasting model](#2-the-stgat-forecasting-model)
3. [Threshold ladders](#3-threshold-ladders)

**Disclosure that stays in the report.** G's test months (August to November 2025) had been used before, for the
rule-based makers of section 1. The report says so (Chapter 5, test setup) and points here. No design choice of G used
them.

---

## 1. Routes tried before policy G

Test months August to November 2025, pessimistic fills, net of fees. A return is net P&L divided by capital committed.
Intervals are 95% event-cluster bootstrap intervals. "Minus (2)" and "minus G" are differences in return, in
percentage points, from route (2) or from G on the same candidate orders.

| Route | Measure | Estimate | 95% interval | Fills | Reading |
|---|---|---|---|---|---|
| (1) Rule-based maker, best on training and validation | return | −10.62% | [−32.73, +13.35] | 1,852 | loses |
| (2) Rule-based maker, re-selected for robustness | return | +1.80% | [−48.49, +62.40] | 83 | too few fills to judge |
| (3) STGAT as a filter on (2) | minus (2) | 0.00 pp | [0.00, 0.00] | 83 | changed no order |
| (4) STGAT as the quoting rule | minus (2) | +22.41 pp | [−64.96, +101.30] | 49 | too few fills to judge |
| (5) G with STGAT forecasts as extra inputs | minus G | −0.65 pp | [−1.40, +0.09] | 35,759 | no improvement |

The rule-based makers were chosen on training and validation months and did not survive the test. The STGAT (section
2) did not help as a filter, as the quoting rule, or as extra inputs to G.

Evidence: `logs/v2_forecast/policy_GS_TEST.log`, `policy_GS_minus_G_test.log`, `policy_G_TEST.log`,
`logs/v2_forecast/test_724/maker.log`. Plan: `docs/planning/backup-plan-rule-based-maker.md`.

---

## 2. The STGAT forecasting model

**Question.** Before the market-making work, the project tested whether a model that sees each basket's constraint
forecasts basket prices better than the constraint alone. Away from settlement it did not, and its forecasts did not
improve the trading policy (routes (3) to (5) above).

**Related work.** Graph attention networks learn how much each node should attend to each neighbour (Veličković et
al., 2018), and spatio-temporal graph models combine a graph over entities with a model over time, first for traffic
forecasting (Yu, Yin & Zhu, 2018). In finance, a temporal graph attention network over graphs built from correlations
and volatility spillovers between eight stock indices forecasts volatility better than GARCH (Kumar, Umeorah & Alochukwu, 2024), and
dynamic and hypergraph models of relations between stocks improve stock-trend prediction (Pei, Zheng & Cartlidge, 2025; Tan et al.,
2025). There the links between assets must be estimated from data. In a family of event contracts they are given
by the constraint. To our knowledge, no earlier study used the constraint itself as the graph, or tested a model
against the best forecast the constraint allows.

**Model.** The market at each two-hour snapshot is a graph. Each contract is a leg node, and each MECE basket adds a
hub node linked to all its legs. Adjacent strikes of a threshold ladder are also linked. Each node carries ten
features from the trades in its window (last price, volume, order flow, and for a hub the basket's sum and the share
of legs that traded). Within each snapshot, a GATv2 attention layer per edge type (Brody, Alon & Yahav, 2022) combines
each node with its neighbours. Each node then attends over its own past two weeks (Vaswani et al., 2017), and a small
head forecasts each leg's price change over 2 to 24 hours. A basket's forecast deviation from $1 is the sum of its
legs' forecasts, minus 1.

**Evaluation.** The target values a leg at settlement if its market has closed by the horizon, so a basket that
settles within the horizon has a target deviation of exactly zero. Baselines: persistence (forecast the current
deviation *d*) and a shrinkage oracle (forecast α\* *d*, with α\* fitted on the test split itself, so optimistic by
construction). A per-series oracle fits one α\* per series and horizon. Each result is the model's mean squared error
divided by the baseline's; below 1 favours the model. Main split: training November 2024 to May 2025, validation June
to July 2025, test August to November 2025, fixed in a dated plan before training
(`docs/planning/stgat-7-2-4-preregistration.md`). A pilot split (training May to June 2025, validation July to August,
test September 2025) was used for development only. Four seeds, each scored once on 109,642 test positions from 1,025
baskets; intervals resample whole baskets (k = 1,025).

**Results.**

| Positions | Baseline | Mean of 4 seeds | Reading |
|---|---|---|---|
| All | persistence | 0.635 | clearly better |
| All | oracle | 0.922 | seeds 0.824–0.991, 1 of 4 significant |
| Unsettled (80%) | oracle | 0.991 | no advantage |
| Unsettled | per-series oracle | 1.091 | worse |
| All, at quoted bids | oracle | 2.54–2.86 (range over seeds) | every interval above 1 |
| Pilot (Sep 2025), with graph | oracle | 0.909 | |
| Pilot, without graph | oracle | 1.128 | the graph is needed |

The model beats persistence clearly and the oracle narrowly, and the advantage comes from baskets about to settle. On
those positions (20% of the total) the target is exactly zero: a model that recognises imminent settlement can forecast
it, but the oracle cannot, because its single α\* must also fit the positions that do not settle. On unsettled
positions the model adds nothing beyond the constraint and each series' own reversion, and at the quoted bids, the
prices a seller would receive, it has no skill.

On the pilot split, removing the graph made the model worse than the oracle. The graph's contribution is narrow: with
one spatial layer, each leg receives a learned function of its basket's summary features, and the hub's attention over
the legs reaches no forecast. Replacing every hub's updated representation with noise left every leg's forecast
unchanged (`stg_infra/examples/verify_hub_flow.py`).

The model chose when to enter a basket position better than a coin flip, by +$0.192 per trade at last-trade prices
(k = 312). At quoted prices it lost to never waiting, by −$0.96 per trade on every seed, so this timing skill has no
executable value.

**Leaks found and fixed.** The first pilot run scored 0.851 times the oracle because three inputs carried information
from the future: contracts replayed at frozen prices after they had closed, the time to close, and basket membership
decided with hindsight. The controls now in the report (Chapter 3, splits and leakage controls) removed all three, and
the pilot result became 0.909. The main test was built with these controls from the start. The replay leak also
produced a false negative for ladders (section 3).

**Why it was not used.** The constraint is a strong baseline, and the model beats it only where the answer is
mechanical: a basket about to settle must sum to $1. As a filter on a rule-based maker, as the quoting rule, and as
extra inputs to the learned policy, its forecasts did not improve the result (section 1).

Evidence: `logs/v2_forecast/test_724/forecast_s*.log`, `strata_s*.log`; `runs/README.md`;
`docs/2-model/stgat-results-and-limitations.md`, `docs/2-model/mece-graph-ablation-result.md`.

---

## 3. Threshold ladders

A threshold ladder lists contracts on one quantity at different strikes, such as "above 70°F" and "above 72°F". The
higher strike implies the lower one, so its price should not exceed the lower strike's. The STGAT can be scored on each
pair of adjacent strikes: its forecast of the gap between the two prices, against persistence and a shrinkage oracle
fitted on the test split, as for baskets.

**A false negative from replayed contracts.** The first scoring found no skill on ladders: the model's error against
the oracle was lowest before any training. The cause was in the data, not the model. At the shortest horizon, one
2-hour step, 85,222 of the 150,697 scored ladder pairs (57%) came from contracts lasting 1.5 hours or less. The 2-hour
grid never saw them live: they appeared only as copies replayed after the contracts had closed, 583 pairs whose prices
never moved. In all, 66% of scored pairs had a contract already closed by the forecast time. Persistence is exact on
such pairs, so any learned forecast could only lose. The rebuilt data, which never replay a contract after its close,
contain no such pairs.

**Re-scored on the rebuilt data.** On the test split, the four STGAT models score 0.982 to 0.993 times the oracle and
0.966 to 0.977 times persistence on 99,646 ladder pairs. On pairs whose prices moved, they score 0.991 to 1.004 times
the oracle, so one of the four loses. The models were trained and selected on baskets only, with no weight on ladder
forecasts and the ladder links' features set to zero. This removes the earlier negative result but is not a positive
one: with no weight on ladders in training there is no validation figure, and no confidence interval was computed.

**Why ladders were not taken further.** The lead over the oracle is under 2% on all pairs and under 1% on pairs that
moved. Ladders lasting less than 2 hours cannot be forecast on the 2-hour grid. The trading work concerns baskets,
where the constraint ties every leg to a fixed $1 total.

Evidence: `logs/v2_forecast/ladder_timing.log`, `ladder_timing_causal.log`;
`docs/1-detection/ladder-conclusion-overturned.md`, `docs/1-detection/ladder-persistence-result.md`.

---

## References

- Brody, S., Alon, U., & Yahav, E. (2022). How attentive are graph attention networks? *International Conference on
  Learning Representations (ICLR)*.
- Kumar, P. N., Umeorah, N., & Alochukwu, A. (2024). Dynamic graph neural networks for enhanced volatility prediction
  in financial markets. arXiv preprint.
- Pei, Y., Zheng, J., & Cartlidge, J. (2025). Dynamic graph representation with contrastive learning for financial
  market prediction: Integrating temporal evolution and static relations. *Proceedings of ICAART 2025*.
- Tan, P., Shi, C., Tu, D., & Xie, L. (2025). MaGNet: A Mamba dual-hypergraph network for stock prediction via
  temporal-causal and global relational learning. arXiv preprint.
- Vaswani, A., et al. (2017). Attention is all you need. *Advances in Neural Information Processing Systems 30*.
- Veličković, P., Cucurull, G., Casanova, A., Romero, A., Liò, P., & Bengio, Y. (2018). Graph attention networks.
  *International Conference on Learning Representations (ICLR)*.
- Yu, B., Yin, H., & Zhu, Z. (2018). Spatio-temporal graph convolutional networks: A deep learning framework for
  traffic forecasting. *Proceedings of IJCAI-18*.
