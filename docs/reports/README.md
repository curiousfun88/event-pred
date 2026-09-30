# Supervisor reports

In chronological order. These are the documents as sent and are not edited
afterwards; where a later finding changed a conclusion, the change is recorded
in [`../RESEARCH_LOG.md`](../RESEARCH_LOG.md#revisions).
Paths quoted inside them predate the 26 Sep 2026 reorganisation
(see [`../../runs/README.md`](../../runs/README.md) for old → new names).

| Date | Report | Covers | Questions put to supervisor |
|---|---|---|---|
| 26 Aug 2026 | [`week03_progress_report.md`](week03_progress_report.md) | Why the pairs-trading baseline (Sharpe 5.52) was spurious; Kalshi market-structure tiers; Direction-B feasibility checks | — |
| Week 5 | [`week05_consult_progress_update.docx`](week05_consult_progress_update.docx) | Ladder vs MECE by market structure; category data windows; classification validated against Kalshi's fields (98.5% / 97.5% precision) | Is precision-only validation enough? Is the validation approach sound? Is the overall methodology sound before building the STGAT? |
| 24 Sep 2026 | [`recess_week_consult.pdf`](recess_week_consult.pdf) | STGAT architecture; MECE 0.853× oracle on test; ladder negative result; PnL negative for four quantified reasons | Q1–7: does this meet the "beat baselines and show PnL" requirement; execution proxies; static arbitrage as a baseline; reporting gross edge; ladder's future |
| 26 Sep 2026 | [`data_window_memo.tex`](data_window_memo.tex) | Usable data is 2024-11..2025-11 (measured); 7-fold walk-forward proposal; overround finding and withdrawal of the profitability claim | Q1–6: walk-forward vs calendar span; 2022 backcast; including the thin period; basket-day as the unit; departmental window expectation; the reframed thesis shape |
| 1 Oct 2026 | [`2026-10-01_progress_update.tex`](2026-10-01_progress_update.tex) ([pdf](2026-10-01_progress_update.pdf)) | Learned maker policy profitable on test (+3.55%, CI +2.51 to +4.60%, pessimistic fills; strict not significant); STGAT adds nothing to it (-0.65 pp); other routes negative | Is a GBM policy enough or must the STGAT trade; is pessimistic-fill profitability acceptable; run a model benchmark? |

**Status:** replies to the Recess consult and the data-window memo are pending.
