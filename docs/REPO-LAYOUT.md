# Documentation layout

Research documents are grouped by the question they answer. For the order in
which they were written and what superseded what, read [`RESEARCH_LOG.md`](RESEARCH_LOG.md), which also records every revised
conclusion; for every script, [`SCRIPTS.md`](SCRIPTS.md).

✔ = in this repository  ·  = referenced by other documents, not yet added

```
docs/
├── RESEARCH_LOG.md               ✔   chronology, documents by phase, revisions
├── SCRIPTS.md                    ✔   every script by phase + investigation notes
├── REPO-LAYOUT.md                ✔   this map
├── superseded-findings-summary.md ✔   naive-phase survey (5 Sep); kept as the audit trail, do not cite
│
├── 1-detection/                      does the violation exist at all?
│   ├── mece-test-result.md                        ✔
│   ├── violation-prediction-result.md             ✔
│   ├── ladder-persistence-result.md               ✔
│   ├── ladder-conclusion-overturned.md            ✔
│   ├── staleness-correction.md                    ✔
│   └── taker-side-investigation-notes.md          ✔
│
├── 2-model/                          architecture, training, ablation
│   ├── architecture-map.md                        ✔
│   ├── stgat-forecasting-redesign.md              ✔
│   ├── stgat-results-and-limitations.md           ✔
│   ├── mece-graph-ablation-result.md              ✔
│   └── split-design-correction.md                 ✔
│
├── 3-economics/                      costs, execution, PnL
│   ├── spread-artefact-finding.md                 ✔  ← read this first
│   ├── settlement-arbitrage-result.md             ✔
│   ├── settlement-pnl-robustness.md               ✔
│   ├── pnl-scorecard.md                           ✔
│   ├── mece-pnl-result.md                         ✔
│   └── maker-execution-provisional.md             ✔
│
├── 4-data/                           window, coverage, composition
│   ├── data-window-liquidity-regime.md            ✔
│   ├── mece-yield-by-month.md                     ✔
│   └── mece-population-composition.md             ✔
│
├── 5-literature/
│   ├── literature-mece-positioning.md             ✔
│   ├── literature-ladder-positioning.md           ✔
│   ├── literature-architecture-positioning.md     ✔
│   └── literature-sample-periods.md               ✔
│
├── planning/
│   ├── four-week-plan-and-reframe.md              ✔
│   └── direction-b-feasibility-report.md          ·
│
└── reports/                          as sent to the supervisor (see reports/README.md)
    ├── week03_progress_report.md                  ✔   26 Aug 2026
    ├── week05_consult_progress_update.docx        ✔
    ├── recess_week_consult.pdf                    ✔   24 Sep 2026
    └── data_window_memo.tex                       ✔   26 Sep 2026
```

Documents refer to each other by bare filename (e.g. `split-design-correction.md`);
the tree above is where to find each one.

Outside `docs/`: result tables are in `results/`, training runs in `runs/` and
run logs in `logs/`, each with its own README.
