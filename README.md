# Constraint structure, forecasting and market making in Kalshi event contracts

Final Year Project (AI in Finance). Kalshi lists families of contracts bound by
consistency constraints that hold by construction:

- **MECE baskets** — a mutually exclusive, collectively exhaustive set of
  outcomes (exactly one leg resolves YES), so leg prices must sum to $1.
- **Threshold ladders** — "above X" contracts on one underlying, so prices
  must be monotone in the strike.

Both appear to be violated in traded prices. The project asks **where a learned
model adds value over the constraint itself, and where the constraint
suffices**, at three levels: whether the apparent violations are real
(measurement), whether a spatio-temporal graph attention network (STGAT) over
the constraint graph forecasts better than the constraint (forecasting), and
whether learning yields a strategy that makes money after costs (trading),
tested forward in a pre-registered live paper-trading test.

> **Status (20 Oct 2026).** Live forward test running since 15 Oct 2026 on
> Lumid sandboxes, pre-registered in
> [`docs/planning/lumid-forward-test-preregistration.md`](docs/planning/lumid-forward-test-preregistration.md)
> (dated amendments L1–L20). Every hourly decision is hashed into a public
> ledger; results: **[live dashboard](https://curiousfun88.github.io/event-pred-live/)**.
> Interim cut 28 Oct 2026; report due 3 Nov 2026. The living handoff —
> established results, open items, gotchas — is [`CLAUDE.md`](CLAUDE.md).

## Findings

| | Result | Evidence |
|---|---|---|
| Measurement | Apparent basket deviation is microstructure, not mispricing: 92.5% of baskets sum above $1 (the one-sided overround pattern, +5.25¢ measured vs +6.3¢ predicted); with quoted books the print side carries 54% of the deviation (87% in two-sided baskets, whose mids sum to $1 within 0.34¢) and one-sided books most of the rest | [`spread-artefact-finding.md`](docs/3-economics/spread-artefact-finding.md), [research log §7](docs/RESEARCH_LOG.md) |
| Taking dislocations | **Not profitable, claim withdrawn.** Selling a basket at its quoted bids beats the $1 settlement in 1.8% of snapshots, by ~2¢, against taker fees of 1.3–5.8¢ | [`quote_validation_test.log`](logs/v2_forecast/quote_validation_test.log) |
| Forecasting (STGAT) | On the supervisor-approved 7/2/4 test (Aug–Nov 2025, 4 seeds): **0.922×** the MSE of an optimal constraint-based shrinkage oracle (seeds 0.824–0.991; 1 of 4 CIs excludes 1). The margin comes from baskets about to settle; on unsettled positions no skill beyond the constraint and series effects; no skill on bid-side prices | [`logs/v2_forecast/test_724/`](logs/v2_forecast/test_724/), [`stgat-7-2-4-preregistration.md`](docs/planning/stgat-7-2-4-preregistration.md) |
| Graph ablation and timing (pilot split) | The graph is what makes price-level forecasts competitive (no-graph 1.128× the oracle vs 0.909× with it); timing skill is mostly per-leg temporal. Timing beats a randomised control (+$0.192/trade, 4/4 seeds) but loses to entering at once at quoted prices | [`runs/README.md`](runs/README.md) |
| Learned maker policy G | Gradient-boosted policy choosing which maker quotes to post. Pre-registered test, Aug–Nov 2025: **+3.55%** net on committed capital (95% CI +2.51 to +4.60), +$3,748 over 1,325 events; random quotes at the same share −0.23%. Edge sits in selection, not in mispricing | [`policy_G_TEST.log`](logs/v2_forecast/policy_G_TEST.log), [`maker-simulator-preregistration.md`](docs/planning/maker-simulator-preregistration.md) |
| Decay and retraining | Frozen G on Sep 2026: −1.41%. Retrained G2, training window chosen on a six-fold walk-forward before going live: W3 +2.65%/month, positive in 6/6 months; beats random every month and the linear baseline at every posting share | [`l9_window_selection.json`](results/live/l9_window_selection.json), [`offline_baselines.json`](results/live/offline_baselines.json) |
| Live forward test | Running; results at the pre-registered cuts (28 Oct, 11 Nov 2026). Main result: G2 on the 23 series it was developed on (L18) | [dashboard](https://curiousfun88.github.io/event-pred-live/), [pre-registration](docs/planning/lumid-forward-test-preregistration.md) |
| Ladders | Exploratory only (not pre-registered): causal checkpoints 0.98–0.99× the oracle on test ladder pairs | [`ladder_timing_causal.log`](logs/v2_forecast/ladder_timing_causal.log) |

The full story, including every conclusion that was later overturned, is in
[`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md).

## Repository layout

```
CLAUDE.md               Living handoff: state, open items, gotchas, closed decisions
docs/                   Research documents; map in docs/REPO-LAYOUT.md
  RESEARCH_LOG.md       Chronology, every research document by phase, and revisions
  SCRIPTS.md            Every script by phase, plus investigation notes per thread
  1-detection/ 2-model/ 3-economics/ 4-data/ 5-literature/ planning/
  planning/             Pre-registrations: STGAT 7/2/4, maker simulator (A1-A16), live test (L1-L20)
  reports/              Supervisor reports (Weeks 3, 5, 9, Recess Week, data-window memo, live-test setup)
stg_infra/              Code (run everything from the repo root, see below)
  stg/                  Graph-construction library (installable package `stg`)
  model/                STGAT: backbone, heads, objectives, chunking, run guards
  examples/             Detection probes, baselines, data audits; maker retraining and walk-forward
                        (retrain_g2.py, tune_gbm.py, offline_baselines.py, train_baselines.py)
  train_*.py run_*.py   Training entry points
  score_*.py evaluate_*.py   Held-out scoring and PnL evaluation
  simulate_maker.py maker_policy.py   Maker fill simulator and the learned policy G
  live_signal_producer.py   Live test: hourly decisions on Lumid
  paper_trader.py paper_ledger.py   Live test: fills on Kalshi's tape, hash-chained ledger
  cut_report.py         Live test: results at a pre-registered cut
  live_backup.py lumid_sandbox_keeper.py live_dashboard/   Backup, sandbox renewal, public dashboard
  diagnose_*.py         Targeted investigations of specific results
  verify_*.py           Synthetic-data checks with known answers
scripts/                Raw data acquisition and month splitting
results/                Result tables written by the scripts (see results/README.md)
runs/                   Training runs: history committed, weights local (runs/README.md)
logs/                   Console output of every reported run (logs/README.md)
data/  cache/           Raw Kalshi data and per-month tensor cache (local, not committed)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ./stg_infra
```

Raw data is not in the repository. Place the monthly Kalshi files under
`data/{markets,trades}/{markets,trades}_kalshi_{even,odd}/{kind}_YYYY-MM.parquet`
(the layout produced by `scripts/data_split_by_month.py`).

## Reproducing the pipeline

All scripts resolve paths relative to the **repository root**; run them from there.

```bash
# 1. Identify the constraint populations (writes results/mece, results/ladder)
python stg_infra/examples/mece_sum_to_one_check.py
python stg_infra/examples/pairwise_monotonicity_taker_side_check_v2.py

# 2. Build the per-month graph cache (cache/bundle_month_*.pt); this also
#    trains the superseded v1 reconstruction model into runs/v1_reconstruction
python stg_infra/run_real_training.py --months 2025-05 2025-06 2025-07 2025-08 2025-09

# 3. Train the forecasting model (MECE-selected configuration)
python stg_infra/train_forecast.py --w-ladder 0 --supervise all --select-on mece \
    --checkpoint-dir runs/v2_mece

# 4. Score once on the held-out split, then evaluate trading
python stg_infra/score_forecast.py --checkpoint runs/v2_mece/best.pt --split test
python stg_infra/evaluate_mece_forecast_pnl.py --checkpoint runs/v2_mece/best.pt
```

Train/val/test boundaries live in one place,
[`stg_infra/examples/data_windows.py`](stg_infra/examples/data_windows.py)
(pilot: train May–Jun, val Jul–Aug, test Sep 2025). The commands above
reproduce the pilot pipeline; the causal reruns and the approved 7/2/4 split
are documented with their exact commands in [`runs/README.md`](runs/README.md)
and [`docs/planning/stgat-7-2-4-preregistration.md`](docs/planning/stgat-7-2-4-preregistration.md),
the maker policy in [`docs/planning/maker-simulator-preregistration.md`](docs/planning/maker-simulator-preregistration.md),
and the live test in [`docs/planning/lumid-forward-test-preregistration.md`](docs/planning/lumid-forward-test-preregistration.md).
Scripts written since the self-test convention carry a `--self-test` that checks planted cases with known answers.

## The `stg` graph library

`stg_infra/stg` is a strategy-pattern builder that turns trade/market tables
into a time-sliced graph; the STGAT consumes it through `stg.bridge.to_torch_bundle`.

```python
from stg.builders.builder import GraphBuilder
from stg.io.loaders import DatasetLoader
from stg.nodes.kalshi import KalshiTickerNodes
from stg.edges.kalshi import KalshiEventEdges
from stg.edges.strategies import KNNEdges, CompositeEdges
from stg.temporal.strategies import FixedWindowTemporal
from stg.strategies.post_process import AddSelfLoops, Symmetrise

markets = DatasetLoader("data/markets_*.parquet", sort_by="created_time").load()
trades  = DatasetLoader("data/trades_*.parquet").load()

stg = (
    GraphBuilder()
    .with_temporal(FixedWindowTemporal(every="1h"))
    .with_nodes(KalshiTickerNodes())
    .with_edges(CompositeEdges([KalshiEventEdges(weight=2.0), KNNEdges(k=5)]))
    .with_post_process(Symmetrise())
    .with_post_process(AddSelfLoops())
    .build(trades, auxiliary={"markets": markets})
)

feat = stg.feature_tensor_padded()   # (T, N, F) numpy
```

For large datasets, `DatasetLoader(...).scan()` pushes column selection and
filters down to Parquet, and `IncrementalGraphBuilder` builds out-of-core.
The STGAT's own graph wiring (MECE hub hyperedges + directed ladder chains) is
[`stg_infra/build_combined_stgat_graph.py`](stg_infra/build_combined_stgat_graph.py).
