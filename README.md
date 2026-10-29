# The Law of One Dollar: Machine Learning for Market Making in Kalshi Prediction Markets

Final Year Project (CP4101, NUS School of Computing). Code, pre-registrations and evidence for every result in the
report.

On Kalshi, many questions are listed as a **basket** of contracts, one per outcome, exactly one of which pays $1. The
legs' prices should therefore sum to $1, the *law of one dollar*. In traded prices they usually do not. The project
asks **where a learned model adds value over this constraint, and where the constraint suffices**, and follows the
answer from measurement to a live test:

1. The apparent violations are not mispricing. They are the bid-ask spread.
2. The opportunity is on the other side of the spread, in **market making**, and a learned policy that chooses
   which maker quotes to post earns a positive return out of sample.
3. Its edge decays within a year and is recovered by retraining.
4. The retrained policy is tested forward in a **pre-registered live paper-trading test**, with every hourly decision
   hash-chained into a public ledger.

**Reproducing any result: see [`REPRODUCE.md`](REPRODUCE.md)**, which maps every table and figure in the report to
its script and its committed evidence. `bash scripts/run_self_tests.sh` checks the code without any data.

## Research flow

| Step | Question | Answer | Report | Evidence |
|---|---|---|---|---|
| 1. Measurement | Do basket prices really break the law of one dollar? | **No.** 68.7% of trades are buyers paying the ask, which predicts last prices summing above $1 before it was measured: 92.5% of baskets do, by +5.25¢ (predicted +6.3¢). At quoted mids, two-sided baskets sum to $1 within 0.34¢. Selling a basket at its bids nets −0.07¢ before fees of 1.3-5.8¢ | Ch 3 | [`spread-artefact-finding.md`](docs/3-economics/spread-artefact-finding.md), [`quote_validation_test.log`](logs/v2_forecast/quote_validation_test.log) |
| 2. Forecasting (set aside) | Does a graph model of each family forecast better than the constraint? | Only near settlement. The STGAT scores 0.922× an optimal constraint-based oracle on the approved test, but shows no skill on unsettled positions and did not improve the trading policy | Appendix | [`runs/README.md`](runs/README.md), [`logs/v2_forecast/test_724/`](logs/v2_forecast/test_724/) |
| 3. Policy G | Can learning choose which maker quotes to post? | **Yes.** Gradient-boosted policy, pre-registered test Aug-Nov 2025: **+3.55%** on committed capital (95% CI +2.51 to +4.60) over 1,325 events, against −0.23% for random quotes at the same share and −0.34% for quoting everything | Ch 4-5 | [`policy_G_TEST.log`](logs/v2_forecast/policy_G_TEST.log), [`a16_baselines_2025.json`](results/maker/a16_baselines_2025.json) |
| 4. Decay and G2 | Does the edge last? | No: frozen G returned −1.41% in Sep 2026, after the market changed. Retrained G2, window chosen by a six-month walk-forward: +2.65% a month, positive in all six | Ch 4-5 | [`smoke_test_2026-09.log`](logs/v2_forecast/smoke_test_2026-09.log), [`l9_window_selection.json`](results/live/l9_window_selection.json) |
| 5. Live test | Does G2 make money on data it has never seen? | Running from 15 Oct 2026; interim cut 28 Oct, final 11 Nov. Tests: G2 profitable (H1) and ahead of random at the same share (H2) | Ch 6 | [live dashboard](https://curiousfun88.github.io/event-pred-live/), [public ledger](https://github.com/curiousfun88/event-pred-live) |

Every analysis that produced a reported result was pre-registered before its test data were examined, in dated
plans with numbered amendments: [STGAT test](docs/planning/stgat-7-2-4-preregistration.md),
[maker policy (A1-A16)](docs/planning/maker-simulator-preregistration.md),
[live test (L1-L20, notes 1-10)](docs/planning/lumid-forward-test-preregistration.md).

The work did not run in a straight line. Leaks were found and fixed (contracts replayed after they closed, and a
time-to-close input that revealed when events ended), headline numbers moved when they were, and a profitability
claim for taking dislocations was withdrawn. Every such revision is recorded in
[`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md).

## Repository layout

```
README.md               this overview
REPRODUCE.md            every report table and figure -> script -> committed evidence; how to rerun
docs/                   research documents (map: docs/REPO-LAYOUT.md)
  RESEARCH_LOG.md       chronology of the project and every revised conclusion
  SCRIPTS.md            index of every script, by phase
  planning/             the three pre-registrations
  1-detection/ ... 5-literature/   findings by question; reports/ = as sent to the supervisor
stg_infra/              all code; run from the repository root
  simulate_maker.py maker_policy.py   maker fill simulator and policy G
  examples/             analyses: measurement, retraining (retrain_g2.py), walk-forward, baselines, case studies
  live_signal_producer.py paper_trader.py paper_ledger.py cut_report.py   the live test
  train_forecast.py score_forecast.py model/ stg/   the STGAT and its graph library
  verify_*.py diagnose_*.py   synthetic checks and targeted investigations
scripts/                raw data download, month splitting, run_self_tests.sh
results/  logs/  runs/  result tables, console logs and training runs behind every reported figure (each has a README)
data/  cache*/          raw Kalshi data and tensor caches (local, not committed; see REPRODUCE.md)
```

Run every script from the repository root. Scripts written after the project adopted the convention take a
`--self-test` that checks planted cases with known answers before touching real data.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt      # the exact versions used (Python 3.12.3)
pip install -e ./stg_infra
bash scripts/run_self_tests.sh            # about 2-3 minutes, no data needed
```

Data download and the commands for each stage are in [`REPRODUCE.md`](REPRODUCE.md).

`CLAUDE.md` holds the project's working notes (state, open items and pitfalls found along the way).
