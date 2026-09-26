# Forecasting constraint dislocations in Kalshi prediction markets

Final Year Project (AI in Finance). A spatio-temporal graph attention network
(STGAT) is trained over two no-arbitrage constraints that hold on Kalshi by
construction:

- **MECE baskets** — a mutually exclusive, collectively exhaustive set of
  outcomes (exactly one leg resolves YES), so leg prices must sum to $1.
- **Threshold ladders** — "above X" contracts on one underlying, so prices
  must be monotone in the strike.

Both are routinely violated in traded prices. The published literature asks
whether such violations can be *detected*; this project asks whether they can
be *forecast*, and where a learned model adds value over the constraint itself.

> **Status (26 Sep 2026).** Five-month pilot complete; awaiting supervisor
> feedback on the [Recess Week consult](docs/reports/recess_week_consult.pdf)
> and the [data-window memo](docs/reports/data_window_memo.tex). The live
> handoff — established results, open items in priority order, known
> gotchas — is [`CLAUDE.md`](CLAUDE.md).

## Findings so far

| | Result | Evidence |
|---|---|---|
| MECE forecasting | **0.853×** the MSE of an optimal (hindsight-fitted) shrinkage oracle on held-out test; 0.851× on val | [`logs/v2_forecast/mece_test.log`](logs/v2_forecast/mece_test.log) |
| Source of the edge | Removing the graph collapses the margin: ~92% of it comes from the cross-sectional structure | [`runs/v2_mece_nograph`](runs/README.md) |
| Directional skill | Beats a coin-flip control with identical entries and costs; every CI excludes zero | [`logs/v2_forecast/mece_pnl_*.log`](logs/README.md) |
| Measurement | 92.5% of apparent basket deviation is the bid/ask overround, not mispricing | [`mece_spread_artefact_check.py`](stg_infra/examples/mece_spread_artefact_check.py) |
| Profitability | **Withdrawn.** No strategy is profitable net of Kalshi fees at executable prices | [data-window memo §5](docs/reports/data_window_memo.tex) |
| Ladders | Diagnosed negative control: the size of a correction is forecastable, its timing is not | [`diagnose_ladder_conditional.py`](stg_infra/diagnose_ladder_conditional.py) |

The full story, including every conclusion that was later overturned, is in
[`docs/RESEARCH_LOG.md`](docs/RESEARCH_LOG.md).

## Repository layout

```
CLAUDE.md               Living handoff: state, open items, gotchas, closed decisions
docs/
  RESEARCH_LOG.md       Chronology of the project + corrections/retractions
  SCRIPTS.md            Every script, what question it answers, inputs -> outputs
  reports/              Supervisor reports (Week 3, Week 5, Recess Week, data-window memo)
stg_infra/              Code (run everything from the repo root, see below)
  stg/                  Graph-construction library (installable package `stg`)
  model/                STGAT: backbone, heads, objectives, chunking, run guards
  examples/             Detection probes, naive baselines, data audits (Phase 1-2)
  train_*.py run_*.py   Training entry points
  score_*.py evaluate_*.py   Held-out scoring and PnL evaluation
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
(pilot: train May–Jun, val Jul–Aug, test Sep 2025).

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
