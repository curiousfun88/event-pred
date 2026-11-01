# Documentation layout

Research documents are grouped by the question they answer. For the order in which they were written and what
superseded what, read [`RESEARCH_LOG.md`](RESEARCH_LOG.md), which also records every revised conclusion. For every
script, read [`SCRIPTS.md`](SCRIPTS.md). For the path from each report table to its evidence, read
[`../REPRODUCE.md`](../REPRODUCE.md).

Where each document sits in the report:

```
docs/
├── RESEARCH_LOG.md                    chronology, documents by phase, every revision
├── SCRIPTS.md                         every script by phase; report evidence map
├── REPO-LAYOUT.md                     this map
├── negative-results.md               work left out of the final report: STGAT, ladders, routes tried before G
├── superseded-findings-summary.md     naive-phase survey (5 Sep); kept as the audit trail, do not cite
├── sandbox-home-README.md             README placed on the live sandbox (operations of the live test)
│
├── planning/                          pre-registrations and plans                        Report
│   ├── maker-simulator-preregistration.md       policy G and G2, amendments A1-A16      Ch 4-5
│   ├── lumid-forward-test-preregistration.md    live test, amendments L1-L20, notes 1-10 Ch 6
│   ├── stgat-7-2-4-preregistration.md           STGAT approved test                     Appendix
│   ├── stamps/                                  OpenTimestamps proofs of the plans
│   ├── l4_candidate_pool.json                   live universe candidates (L4)
│   ├── backup-plan-rule-based-maker.md          contingency, not used
│   ├── cross-venue-preregistration.md           Kalshi-Polymarket idea, not run
│   ├── four-week-plan-and-reframe.md            plan of the reframe to market making
│   └── direction-b-feasibility-report.md        same text as reports/week03_progress_report.md
│
├── 1-detection/                       does the violation exist at all?
│   ├── mece-test-result.md                                                              Ch 3
│   ├── staleness-correction.md                                                          Ch 3 (data window)
│   ├── violation-prediction-result.md
│   ├── taker-side-investigation-notes.md
│   ├── ladder-persistence-result.md                                                     Appendix (ladders)
│   └── ladder-conclusion-overturned.md                                                  Appendix (ladders)
│
├── 2-model/                           the STGAT: architecture, training, ablation          Appendix
│   ├── architecture-map.md
│   ├── stgat-forecasting-redesign.md
│   ├── stgat-results-and-limitations.md
│   ├── mece-graph-ablation-result.md
│   └── split-design-correction.md
│
├── 3-economics/                       costs, execution, P&L
│   ├── spread-artefact-finding.md     ← the measurement finding; read this first           Ch 3
│   ├── fee-schedule-check.md, kalshi-fee-schedule.pdf   fees against the official schedule Ch 2
│   ├── maker-execution-provisional.md                                                   Ch 4 (background)
│   ├── settlement-arbitrage-result.md, settlement-pnl-robustness.md   taking dislocations; claim withdrawn
│   ├── pnl-scorecard.md, mece-pnl-result.md                           early P&L, superseded
│
├── 4-data/                            window, coverage, composition                        Ch 3
│   ├── data-window-liquidity-regime.md
│   ├── mece-yield-by-month.md
│   └── mece-population-composition.md
│
├── 5-literature/                      positioning against prior work                       Ch 2
│   ├── literature-mece-positioning.md, literature-maker-positioning.md
│   ├── literature-forecasting-trading-positioning.md, literature-architecture-positioning.md
│   ├── literature-ladder-positioning.md, literature-weather-positioning.md
│   └── literature-sample-periods.md
│
├── reports/                           as sent to the supervisor (see reports/README.md)
│   └── progress reports (weeks 3, 5, 9, recess), data-window memo, live-setup approval, paper drafts
│
└── fleet-guide/                       guide to Lumid's Research Fleet API (used for live timestamps)
```

Documents refer to each other by bare filename (e.g. `split-design-correction.md`); the tree above is where to find
each one.

Outside `docs/`: result tables are in `results/`, training runs in `runs/` and run logs in `logs/`, each with its own
README.
