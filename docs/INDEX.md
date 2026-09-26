# Document index

Every research document, in the order it was produced. Dates are creation
dates, so this reads as the actual chronology of the investigation rather
than a tidied-up narrative.

Read `CORRECTIONS.md` alongside this: several documents below were
superseded, and the index says so where that happened.

---

## Phase 1 — Does the arbitrage exist? (Sep 5)

Detection before modelling. No model is involved in any of these.

| document | what it establishes |
|---|---|
| `superseded-findings-summary.md` | The founding survey. Which no-arbitrage structures exist on Kalshi, how often they are violated, and at what magnitude. Contains one figure since superseded (see CORRECTIONS §6) |
| `planning/direction-b-feasibility-report.md` | Whether thin legs can be priced from their neighbours well enough to reach baskets a naive rule cannot see. Answer: estimation error was 1.49x the signal |
| `1-detection/taker-side-investigation-notes.md` | Early work on `taker_side` semantics. The same field later became the instrument that overturned the profitability claim |

Supporting code: `stg_infra/examples/mece_sum_to_one_check.py`,
`mece_family_audit.py`, `pairwise_monotonicity_*.py` (22 scripts).

## Phase 2 — Model design and the first results (Sep 18-19)

| document | what it establishes |
|---|---|
| `2-model/stgat-forecasting-redesign.md` | Why the task was reframed from classification to residual forecasting, and why the head is zero-initialised |
| `2-model/architecture-map.md` | Component-by-component map of the implementation, with a "check it yourself" command per section |
| `1-detection/violation-prediction-result.md` | Whether violations are predictable at all |
| `1-detection/mece-test-result.md` | MECE mechanism on the held-out split |
| `1-detection/ladder-persistence-result.md` | **Superseded** by `ladder-conclusion-overturned.md` |
| `1-detection/staleness-correction.md` | Stale prices were inflating measured deviations. The same class of error recurs in Phase 5 at basket level |
| `1-detection/ladder-conclusion-overturned.md` | **FINAL on the ladder.** Overturns the random-walk reading, then closes the mechanism anyway for a different and better-identified reason. Records three of its own sub-errors |
| `2-model/stgat-results-and-limitations.md` | Consolidated model results. Ladder sections superseded by the above |
| `2-model/mece-graph-ablation-result.md` | The graph supplies ~92% of the margin. The strongest architectural finding in the project |

## Phase 3 — Economics (Sep 19-26)

| document | what it establishes |
|---|---|
| `3-economics/mece-pnl-result.md` | First round-trip PnL. Negative after costs |
| `3-economics/pnl-scorecard.md` | Every strategy against every baseline, in one table |
| `3-economics/maker-execution-provisional.md` | Maker execution. **Provisional**: the fee shape is unverified against Kalshi's published schedule |
| `3-economics/settlement-arbitrage-result.md` | The hold-to-settlement reframe. Legs must sum to $1 at resolution, so a held position captures the deviation deterministically and pays one-way costs. Wording about "measured per-leg spreads" is corrected by the two documents below |
| `3-economics/settlement-pnl-robustness.md` | Filter sweep, the wrong-spread-table discovery, and a retraction of "the model worsens the profitable rule" |
| `3-economics/spread-artefact-finding.md` | **The central result.** 92.5% of the deviation is the overround; the executable edge is one tick; the profitability claim is withdrawn |

## Phase 4 — Data window (Sep 25-26)

Prompted by a supervisor's objection that the window was too short.

| document | what it establishes |
|---|---|
| `4-data/mece-population-composition.md` | The opportunity population is ~58% weather and ~24% sports above 5c, across four structurally distinct partition types. Not the 93% weather an earlier window suggested |
| `4-data/data-window-liquidity-regime.md` | Platform notional grew 369x across the archive. The binding constraint on the window is liquidity stationarity, not calendar availability |
| `4-data/mece-yield-by-month.md` | Usable basket-days per month across all 54 months. Two dense blocks around a 23-month trough whose apparent deviations are staleness |
| `2-model/split-design-correction.md` | Corrects a proposed split that tested on data earlier than the training window |

## Phase 5 — Positioning and planning

| document | what it establishes |
|---|---|
| `5-literature/literature-mece-positioning.md` | Three papers cover sum-to-one arbitrage; all are detection-only. The forecasting question appears unasked |
| `5-literature/literature-ladder-positioning.md` | Same for the ladder mechanism |
| `5-literature/literature-sample-periods.md` | Sample periods of the nearest work. Only one of three treats sum-to-one as a primary object; its window is 12 months |
| `5-literature/literature-architecture-positioning.md` | Where the architecture sits, and the citation licensing each departure from the paper it adapts |
| `planning/four-week-plan-and-reframe.md` | Current plan. v2; v1 was built around the withdrawn PnL headline |

---

## Code index

| location | contents |
|---|---|
| `stg_infra/stg/` | Graph construction from raw Kalshi data. `nodes/kalshi.py` defines the feature slots; `edges/kalshi.py` builds the adjacency types |
| `stg_infra/model/` | Architecture and training. `spatial_attention.py` reads three adjacency keys; `run_guards.py` holds assertions that make known bug classes impossible to repeat |
| `stg_infra/examples/` | One-off investigations, each self-contained with a docstring stating what would falsify it |
| `stg_infra/evaluate_*.py` | Economic evaluation |
| `stg_infra/diagnose_*.py` | Data and model diagnostics |
| `stg_infra/verify_*.py` | Correctness checks. `verify_pipeline.py` has 13 checks, each with a planted-bug counterpart proving it can fail |

Scripts with `--self-test` validate their own logic against synthetic data
with known answers before touching real data. Run that first; it is faster
than being wrong.
