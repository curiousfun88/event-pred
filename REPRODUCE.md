# Reproducing the report

This file maps every result in the FYP report (*The Law of One Dollar: Machine Learning for Market Making in
Kalshi Prediction Markets*) to the code that produced it and the committed evidence it came from. Run everything
from the repository root; all paths are root-relative.

Reproduction works at three levels, from cheapest to most complete:

| Level | Needs | Time | What it shows |
|---|---|---|---|
| **1. Self-tests** | the code only | minutes | each script gets planted cases with known answers right |
| **2. Evidence trail** | the repository only | none | every reported number is in a committed log or result file, written by a named script (map below) |
| **3. Full rerun** | raw Kalshi data (about 5 GB) | hours per stage | the logs and result files are regenerated from the data |

The live forward test is a fourth case: its decisions were made in real time and cannot be rerun, but they are
hash-chained and publicly timestamped, so anyone can check that the record was not changed (see
[Live test](#live-test-chapter-6)).

## Environment

Python 3.12.3. Install the package versions the reported runs used, then the graph library:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt     # exact versions; requirements.txt gives lower bounds
pip install -e ./stg_infra
```

Version that matters most: scikit-learn 1.8.0 (`HistGradientBoostingRegressor`, the policies G and G2).

## Level 1: self-tests

```bash
bash scripts/run_self_tests.sh            # every script with a --self-test; prints PASS/FAIL per script
```

Scripts written after the project adopted the convention carry a `--self-test` that checks planted cases with known
answers before touching real data (69 scripts, about 2-3 minutes in all). Older exploratory scripts from the detection phase do not.

## Level 3: data

Raw data is not committed (about 5 GB). Everything comes from Kalshi's public interface, which needs no account. The
Jun 2021 - Nov 2025 archive is a public, pre-collected dataset: Jon Becker's
[prediction-market-analysis](https://github.com/Jon-Becker/prediction-market-analysis) (Kalshi markets and trades
collected 23-25 Nov 2025, same schema as `data/{markets,trades}`). Download it from there to reproduce exactly.
Everything later was fetched by this project's own scripts.

| Data | Fetch with | Lands in |
|---|---|---|
| Every market and trade, Jun 2021 - Nov 2025 | Becker's dataset (above), or re-crawl with `scripts/fetch_kalshi_data.py`; then `scripts/data_split_by_month.py` | `data/{markets,trades}/{markets,trades}_kalshi_{even,odd}/{kind}_YYYY-MM.parquet` |
| Hourly quotes (best bid and ask), MECE legs, Jul - Sep 2025 | `stg_infra/fetch_quote_candles.py` | `data/quotes/` |
| The 23 series, Dec 2025 - Sep 2026, with hourly quotes and every trade | `stg_infra/fetch_kalshi_api_months.py` | `data/kalshi_candles_cache/`, `runs/` caches |

Kalshi may revise or remove old records, so a fresh download can differ slightly from the one used. The reported
figures are the committed logs.

## Pipeline by report chapter

### Data and measurement (Chapter 3)

```bash
python stg_infra/examples/mece_yield_by_month.py                 # data window: usable baskets per month
python stg_infra/examples/mece_sum_to_one_check.py               # identify MECE baskets from outcomes
python stg_infra/diagnose_basket_composition.py                  # population composition
python stg_infra/examples/ask_side_share.py --year 2025          # the order-flow prediction (68.7% ask-side)
python -m stg_infra.examples.mece_spread_artefact_check          # the overround test (last prints)
python -m stg_infra.examples.mece_spread_artefact_check --max-basket-span 60 --gate-threshold 10   # executable reading
python stg_infra/fetch_quote_candles.py --cache cache_causal     # quoted top of book
python stg_infra/diagnose_quote_candles.py --split test          # bid, ask and mid basket sums
python stg_infra/examples/report_figures_ch4.py --out ../fyp-report/figures
```

### Policy G, 2025 (Chapters 4 and 5)

```bash
python stg_infra/maker_policy.py train                           # fit G on Nov 2024 - May 2025
python stg_infra/examples/policy_G_validate.py run               # pre-registered test, Aug - Nov 2025
python stg_infra/examples/policy_G_audit.py                      # by month, category, fill model
python stg_infra/examples/baselines_2025.py train && python stg_infra/examples/baselines_2025.py test
python stg_infra/examples/case_study_2025.py --simulate-random && python stg_infra/examples/case_study_2025.py --report
```

### Decay and retraining, 2026 (Chapters 4 and 5)

```bash
python stg_infra/fetch_kalshi_api_months.py --months 2026-08 2026-07 2026-06 2026-05 2026-04 2026-03 2026-02 2026-01 2025-12
python stg_infra/examples/smoke_test_2026.py --start 2026-09-07 --end 2026-10-05   # frozen G a year later
python stg_infra/examples/retrain_g2.py train W1     # likewise W2, W3; add --design G2P for G2 two-level
python stg_infra/examples/retrain_g2.py validate     # September 2026 validation and window selection
python stg_infra/examples/select_g2_window.py        # six-fold walk-forward
python stg_infra/examples/offline_baselines.py       # baselines and matched shares on the same folds
python stg_infra/examples/tune_gbm.py build && python stg_infra/examples/tune_gbm.py summarise   # sensitivity (fit runs per task)
python stg_infra/examples/ablate_g2.py run           # input ablation and threshold
python stg_infra/examples/wf_risk_2026.py            # risk of W3's scheme
python stg_infra/examples/shortcut_vs_simulator.py --window W3   # fill-level score against the simulator
```

Heavy jobs were run under a memory cap on an 8 GB laptop, e.g.
`systemd-run --user --scope -p MemoryMax=5G .venv/bin/python <script>`.

### Live test (Chapter 6)

The live system ran `stg_infra/live_signal_producer.py` (hourly decisions) and `stg_infra/paper_trader.py` (fills on
Kalshi's trade tape and the ledger). Its record is in the public backup repository
[`curiousfun88/event-pred-live`](https://github.com/curiousfun88/event-pred-live). To check it and recompute the results:

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/curiousfun88/event-pred-live.git live
git -C live sparse-checkout set runs/live/paper/ledger/entries
python stg_infra/verify_ledger_chain.py live/runs/live/paper/ledger/entries      # hash chain
python stg_infra/cut_report.py --cut 2026-10-28T00 --settle-by 2026-10-30T00 --out results/live/cut_interim.json
python stg_infra/report_numbers.py --cut-json results/live/cut_interim.json --out ../fyp-report/generated/numbers.tex
```

`cut_report.py` needs a full copy of `runs/live` (ledger, settlement cache, logged scores); see its docstring.
Third-party timestamps are checked with the OpenTimestamps client (`ots verify` on any file in `runs/live/stamps/`).

### STGAT and ladders (Appendices)

The forecasting model's runs, exact commands and seeds are in [`runs/README.md`](runs/README.md) and
[`docs/planning/stgat-7-2-4-preregistration.md`](docs/planning/stgat-7-2-4-preregistration.md); the approved test is
`stg_infra/run_test_724.sh`. These need a GPU and the per-month graph cache (`cache_724/`, about 4.5 GB, built by
the run).

## Evidence map: every table and figure

Each table in the report also carries a `% source:` comment naming these files.

| Report | Item | Script | Evidence (committed) |
|---|---|---|---|
| Ch 3 | `tab:splits` | `stg_infra/examples/data_windows.py` (pilot); pre-registrations (main, policy) | `docs/planning/` |
| Ch 3 | data window, composition | `mece_yield_by_month.py`, `diagnose_basket_composition.py` | `docs/4-data/mece-yield-by-month.md`, `mece-population-composition.md` |
| Ch 3 | order-flow prediction (68.7%) | `ask_side_share.py` | `logs/v2_forecast/ask_side_share_by_month_2025.log` |
| Ch 3 | `tab:measurements`, `fig:overround` | `mece_spread_artefact_check.py`, `report_figures_ch4.py` | `docs/3-economics/spread-artefact-finding.md`, `logs/v2_forecast/report_figures_ch4.log` |
| Ch 3 | `tab:basket-sums`, `fig:basket-sums` | `fetch_quote_candles.py`, `diagnose_quote_candles.py`, `report_figures_ch4.py` | `logs/v2_forecast/quote_validation_test.log` (validation: `_val.log`) |
| Ch 3 | `tab:executable` | `mece_spread_artefact_check.py --max-basket-span 60 --gate-threshold 10`; quotes as above | `logs/v2_forecast/mece_spread_artefact_span60.log`, `quote_validation_test.log` |
| Ch 3 | `fig:basket-example` | illustrative numbers, not data | -- |
| Ch 4 | `tab:fill-models`, `tab:policy-g-features`, `tab:policy-g-hp` | `simulate_maker.py`, `maker_policy.py` | `docs/planning/maker-simulator-preregistration.md` |
| Ch 4 | `tab:retrain-designs`, `tab:retrain-plus-features`, `tab:retrain-windows` | `retrain_g2.py` | `logs/v2_forecast/g2_W{1,2}_train_validate.log`, `g2_W3_final_selection.log` |
| Ch 4 | fill-level score against the simulator | `shortcut_vs_simulator.py` | `logs/v2_forecast/shortcut_vs_simulator_W3_sep2026.log` |
| Ch 5 | `tab:maker-G`, `tab:maker-g-month`, `tab:maker-g-category` | `policy_G_validate.py test`, `policy_G_audit.py`, `baselines_2025.py` | `logs/v2_forecast/policy_G_TEST.log`, `policy_G_audit.log`, `a16_test.log` |
| Ch 5 | `tab:metrics` | definitions; computed by `baselines_2025.py`, `cut_report.py` | -- |
| Ch 5 | `tab:maker-baselines`, `tab:maker-mechanism`, `tab:maker-calibration` | `baselines_2025.py` | `results/maker/a16_baselines_2025.json`, `a16_metrics_2025.json` |
| Ch 5 | `tab:case-2025`, `tab:case-2025-events`, `fig:case-2025` | `case_study_2025.py` | `results/maker/case_study_2025.json` |
| Ch 5 | `tab:retrain-validation`, `tab:case-regime` | `smoke_test_2026.py`, `retrain_g2.py validate` | `logs/v2_forecast/smoke_test_2026-09.log`, `g2_W3_final_selection.log` |
| Ch 5 | `tab:retrain-wf`, `tab:g2-vs-linear`, `tab:retrain-matched` | `select_g2_window.py`, `offline_baselines.py` | `results/live/l9_window_selection.json`, `offline_baselines.json` |
| Ch 5 | `tab:retrain-risk` | `wf_risk_2026.py` | `results/live/wf_risk_2026.json` |
| Ch 5 | `tab:ablation`, `tab:ablation-inputs`, `tab:threshold` | `ablate_g2.py` (rows also from the tables above) | `results/maker/ablation_g2_2026.json` |
| Ch 5 | `tab:g2-sensitivity`, `tab:retrain-sensitivity` | `tune_gbm.py`, `offline_baselines.py` | `logs/v2_forecast/tune_gbm_a15_summary.log`, `results/live/mlp_sensitivity.json`, `lin_sensitivity.json` |
| Ch 6 | `tab:live-arms`, `tab:live-windows` | -- | `docs/planning/lumid-forward-test-preregistration.md` |
| Ch 6 | `tab:live-main`, `tab:live-tests`, `tab:live-fills`; App. C tables | `cut_report.py`, `report_numbers.py` | `results/live/cut_interim.json` (written at the interim cut) |
| Ch 6 | `tab:live-case` | `live_case_study.py` | `results/live/case_study_20261025.json` |
| Ch 6 | `fig:live-equity`; day-cluster paragraph | `live_equity_curve.py`, `live_day_breakdown.py` | `logs/v2_forecast/live_equity_curve_interim.log`, `logs/v2_forecast/live_day_breakdown_interim.log` |
| Ch 6 | G2 against the linear policy (note 10) | `live_matched_share.py` | `results/live/note10_matched_share_interim.json` |
| App. A | `tab:amendments`, `tab:notes` | -- | the three pre-registrations in `docs/planning/` |
| App. B | `fig:architecture`, `tab:incidents`, `tab:missing-hours` | live system code | `docs/planning/lumid-forward-test-preregistration.md` (L12-L20) |
| App. C | `tab:weather-rule` | `retrain_g2.py`, L11 split | `results/live/l11_weather_split.json` |
| App. E | `tab:maker-failed` | `run_test_724.sh` (A10), `policy_G_validate.py test GS` | `logs/v2_forecast/test_724/maker.log`, `policy_GS_TEST.log` |
| App. | `tab:forecast-main` (STGAT) | `run_test_724.sh`, `score_forecast.py` | `logs/v2_forecast/test_724/forecast_s*.log`, `strata_s*.log` |
| App. H | `tab:universe` | `smoke_test_2026.py` | `logs/v2_forecast/smoke_test_2026-09.log`, `universe_leg_counts_2026-09.log` |

Single numbers quoted in the text are typed once in the report's `numbers_offline.tex`, each with its source file in
a comment; the live numbers are generated into `generated/numbers.tex` by `report_numbers.py`.

## What cannot be reproduced exactly

- **Live decisions.** They depend on the hour they were made. They are not rerun; the hash chain and timestamps show
  they were not changed afterwards.
- **STGAT training on a GPU** is not bit-for-bit deterministic. Four seeds are reported for that reason.
- **Kalshi data revisions.** A fresh download may differ slightly from the archive used (see Data).
