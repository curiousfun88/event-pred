# Run logs

Console output of every archived run, kept as the evidence behind reported
figures. Suffixes `_v2`, `_v3`, … are reruns after a fix, so the highest
suffix is the one to cite. Logs written before 26 Sep 2026 print the old
paths (`checkpoints_mece/…`, repo-root parquets); see
[`runs/README.md`](../runs/README.md) for the mapping.

## `v1_reconstruction/` — STGAT v1 (17–19 Sep 2026)

Unless noted, evaluations use `runs/v1_reconstruction/best.pt` (epoch 43, val loss 0.0301).

| Logs | Produced by | What it shows |
|---|---|---|
| `run_smoke.log` | `run_real_training.py` | First month-by-month cache build (May 2025) |
| `run_5mo.log`, `run_5mo_clean.log`, `run_5mo_v2.log` | `run_real_training.py` | 5-month training before and after validity filtering and standardisation |
| `run_5mo_e60.log` | `run_real_training.py` | **The v1 checkpoint** (50 epochs, best epoch 43) |
| `eval_val.log`, `eval_val_v2.log`, `eval_val_v3.log`, `baselines_val_v2.log`, `baselines_test_v2.log` | `evaluate_baselines.py` | Model vs no-learning baselines; `_v2` onwards uses the fair identical-positions protocol |
| `eval_arb_test.log`, `eval_arb_test_v2.log`, `eval_arb_final.log`, `eval_arb_final_v3.log`, `sweep_val*.log` | `evaluate_arbitrage.py` | MECE arbitrage vs naive rule (test), threshold sweeps on val. `eval_arb_test*` use an earlier checkpoint (epoch 19) |
| `ladder_val*.log`, `ladder_test*.log`, `ladder_test_exante.log`, `ladder_test_measured.log` | `evaluate_arbitrage_ladder.py` | Ladder arbitrage; `_measured` uses measured spreads |
| `spread_diag.log` | `diagnose_spreads.py` | Coverage of the measured-spread file |
| `persistence.log` | `diagnose_persistence.py` | Violation persistence on test |
| `staleness.log` | `diagnose_staleness.py` | Verdict: persistence is staleness |
| `price_discovery.log` | `evaluate_price_discovery.py` | Do stale legs move toward the model's value? |
| `violation_pred_test.log`, `vp_{val,test}_{h6,h12,conc,series,t2}.log` | `evaluate_violation_prediction.py` | Confirmed-violation prediction across horizons, concentration, per-series and threshold variants |

## `v2_forecast/` — STGAT v2 (19–20 Sep 2026)

| Logs | Produced by | What it shows |
|---|---|---|
| `forecast_smoke.log`, `train_forecast.log` | `train_forecast.py` | First forecast runs → `runs/v2_forecast` |
| `forecast_active.log`, `forecast_strat.log` | `train_forecast.py` | → `runs/v2_active`, `runs/v2_strat` |
| `forecast_mece.log` | `train_forecast.py` | **Headline training run** → `runs/v2_mece` |
| `mece_test.log` | `score_forecast.py` | **Held-out test, scored once:** 0.853× oracle, 0.819× persistence (n = 41,700) |
| `mece_pnl_test.log`, `mece_pnl_ci.log`, `mece_pnl_capped.log`, `mece_pnl_cap25.log` | `evaluate_mece_forecast_pnl.py` | Taker PnL and controls; cluster-bootstrap CIs; 10% and 25% participation caps |
| `maker_flow.log`, `maker_optimistic.log`, `maker_partial.log`, `maker_ctrl.log` | `evaluate_mece_maker_pnl.py` | Maker execution under flow / optimistic / partial-fill models; `_ctrl` adds controls |
| `mask_semantics.log` | `diagnose_mask_semantics.py` | 53.9% of masked positions are unchanged prices |
| `ladder_reversion.log` | `diagnose_ladder_reversion.py` | Pooled reversion by gap bucket (α ≈ 0.99) |
| `ladder_conditional.log`, `ladder_cond_test.log` | `diagnose_ladder_conditional.py` | Reversion conditional on a reprice (val, test) — overturns the random-walk reading |
| `coverage.log` | `diagnose_basket_coverage.py` | MECE basket coverage on test |
