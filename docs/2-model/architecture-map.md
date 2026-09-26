# Codebase map: how the STGAT pipeline actually works

Written so you can verify things yourself rather than take anyone's word for
it. Every section ends with **Check it yourself** — a command you can run or
a specific line to open. Where something is a claim I have not personally
executed, it says so.

---

## 0. The one-line version

```
raw Kalshi parquet
   -> stg/          build a graph (nodes + typed edges per 2h snapshot)
   -> stg/bridge    freeze it into torch tensors, one file per month
   -> model/        chunk it, run the backbone, compute the loss
   -> train_forecast.py / score_forecast.py / evaluate_*.py
```

Dependencies point **one way only**: `stg/` knows nothing about `model/`, and
`model/` knows nothing about the evaluation scripts. The only thing crossing
every boundary is the **feature-slot contract** (§4), which is not enforced by
any type — it is just an integer index everyone agrees on.

**Check it yourself**
```bash
grep -rn "import model" stg/        # expect: nothing
grep -rn "import evaluate" model/   # expect: nothing
```

---

## 1. Layer 1 — `stg/`: building the graph

Eight files, ~890 lines. Pure numpy/networkx, no torch except in `bridge.py`.

| File | Purpose |
|---|---|
| `stg/core.py` | The data model: `NodeState`, `EdgeState`, `GraphSnapshot`, `SpatioTemporalGraph` and its tensor-export methods |
| `stg/bridge.py` | `to_torch_bundle()`: `SpatioTemporalGraph` -> `TorchGraphBundle` |
| `stg/nodes/kalshi.py` | Node builders: `KalshiTickerNodes`, `KalshiMeceBasketNodes`, `KalshiEventNodes` |
| `stg/edges/kalshi.py` | Edge builders: 6 classes, of which **2 are actually used** |
| `stg/util.py` | Three small helpers |

### The two node types

Everything downstream distinguishes them by the **last feature slot**:
`0.0` = ticker (a tradeable market), `1.0` = MECE basket hub (a synthetic
aggregator node). They share a width of `COMBINED_N_FEATURES = 10`, which is
`max(9, 6) + 1` — the ticker's 9 real features, the hub's 6, plus the type
indicator.

This is why **slot 0 means two different things**: `last_yes_price` on a
ticker, `sum_cents` on a hub. That is also why the training objective
supervises ticker nodes only.

### The edge types that matter

Only three keys are ever read downstream:

```
mece_leg_to_basket     leg  -> hub     (KalshiMeceHyperedges)
mece_basket_to_leg     hub  -> leg     (KalshiMeceHyperedges)
ladder_monotonic       leg_a -> leg_b  (KalshiLadderChainEdges, ONE direction)
```

`same_event`, `price_correlation`, `ticker_to_event`, `event_to_ticker` and
`semantic_topic` are produced by builder classes that **nothing in the current
pipeline instantiates**. They are leftovers from the earlier design.

**Check it yourself**
```bash
grep -rn "adjacency_by_type.get" model/ | sort -u
grep -rn "KalshiSemanticTopicEdges\|KalshiPriceCorrelationEdges" --include=*.py .
```
The second command should show only the class definitions and no callers.

---

## 2. Layer 2 — `model/`: the network

### `STGATBackbone.forward` (model/train.py)

Four stages, each `(T, N, *) -> (T, N, *)`:

```
features (T,N,10)
  -> standardize()                  subtract mean, divide std; the TYPE slot
                                    is neutralised so it passes through raw
  -> TypeSpecificProjection         (T,N,10) -> (T,N,D)
                                    blends a ticker projection and a hub
                                    projection using slot -1 as the weight
  -> TwoChannelSpatialAttention     (T,N,D) -> (T,N,D)   within each snapshot
  -> TemporalAttention              (T,N,D) -> (T,N,D)   across the chunk
  -> h_final
```

The head is applied **outside** the backbone:
`ResidualForecastHead(h_final, base_price)` -> `(T, N, H)`.

### The spatial layer

Two independent GATv2 channels, summed with a residual:

```
out[t, active] = h_active + mece_out + ladder_out
```

The MECE channel concatenates both directed edge lists into one `edge_index`
and runs a single convolution. The ladder channel symmetrises its one-way
edges and appends a direction indicator as an extra edge feature.

If a snapshot has no edges of a type, that channel contributes exactly zero
and the node keeps its input embedding. If a key is absent from the dict
entirely, `.get()` returns `None` and the channel is skipped for every `t` —
**this is what `--drop-edges` exploits.**

### The temporal layer

One causal mask per forward, built inline:

```python
causal = torch.tril(torch.ones(T, T, dtype=torch.bool, device=device))
```

applied as `scores.masked_fill(~valid, NEG_INF)` where
`valid = causal & key_valid` and `key_valid` removes each node's own
unobserved timesteps. There is an explicit NaN guard for rows where
everything is masked.

Nodes are processed in batches of 512 with gradient checkpointing, and
checkpointing is skipped under `no_grad` where it would only cost recompute.

### The head

```python
delta = self.net(h_final)                 # (T, N, H)
pred  = base_price.unsqueeze(-1) + delta
```

with the final `Linear` zero-initialised in both weight and bias. That is the
entire reason the model *starts* as persistence and every ratio in the results
is meaningful.

**Check it yourself**
```bash
python verify_pipeline.py --only residual_head -v      # asserts max|pred-price| == 0
python verify_pipeline.py --only no_lookahead -v       # perturbs the future, asserts the past is bit-identical
sed -n '295,305p' model/temporal_attention.py          # read the mask construction
```

---

## 3. Layer 3 — chunking, caching, and the training loop

### Why chunking exists

`TemporalAttention` builds a dense `(N, H, T, T)` score tensor. Over a full
multi-month range that is not computable. So the timeline is cut into chunks
of `chunk_len` snapshots (default 168, about two weeks).

The cut happens in **two separate steps, deliberately**:

1. `build_split_ranges()` cuts on split boundaries *and* month boundaries.
2. `chunk_ranges()` then cuts each already-homogeneous run to length.

Because step 2 only ever subdivides step 1's output, a chunk can never
straddle a train/val/test boundary. That is a guarantee by construction —
which is exactly why it is worth checking, since the guarantee lives in a
different file from the code relying on it.

### Why the month store exists

A dense `(T, N, F)` bundle grows with the **square** of calendar range,
because Kalshi churns ~15k new tickers a month while only ~700 are live at
once. One month is 0.2 GB; fourteen months would be 34.6 GB holding 121 MB of
real observations.

So each month is built and cached separately, and `MonthlyBundleStore` keeps
exactly one resident at a time. Chunks never span months, so materialising one
never needs two.

### The split

Defined once in `examples/data_windows.py` by string comparison:

```python
TRAIN_END = "2025-06"      # last month in train
VAL_END   = "2025-08"      # last month in val
# test = everything after
```

**This does not move when you add months.** Appending 2025-10 onward silently
classifies all of it as test. `check_split_integrity` now prints the
per-split snapshot counts and date ranges at startup for exactly this reason.

This is the file to change for the 2024-11 → 2025-11 window and the seven
expanding walk-forward folds (`split-design-correction.md`).

**Check it yourself**
```bash
python verify_pipeline.py --only chunks_disjoint -v
python -c "
import sys; sys.path.insert(0,'.')
from data_windows import split_for
for m in ['2025-05','2025-06','2025-07','2025-08','2025-09','2025-10','2026-01']:
    print(m, split_for(m))"
```

---

## 4. The feature-slot contract

This is the most important implicit contract in the codebase, and nothing
type-checks it.

**Ticker nodes** (type indicator `0.0`):

| Slot | Name | Used downstream by |
|---|---|---|
| 0 | `last_yes_price` (0-100c) | `true_prices()` — divides by 100 |
| 1 | `yes_vwap` | |
| 2 | `price_return` | |
| 3 | `price_std` | |
| 4 | `window_volume` | `VOLUME_SLOT` — liveness filter, participation cap |
| 5 | `net_flow` | `NET_FLOW_SLOT` — the maker fill model |
| 6 | `buy_ratio` | |
| 7 | `trade_intensity` | |
| 8 | `time_to_close` | **SECONDS**, 0 if past close |
| -1 | type indicator | everything, to tell ticker from hub |

Slot 8's unit is the one that has already cost time: `--min-ttc 24` is 24
*seconds*, not hours. Running it revealed that 15.9% of the evaluated PnL
population sat at `ttc == 0` — markets already past close.

**Basket hub nodes** (type indicator `1.0`):

| Slot | Name | Used downstream by |
|---|---|---|
| 0 | `sum_cents` | |
| 1 | `deviation` | |
| 2 | `legs_known` | |
| 3 | `legs_total` | `SLOT_LEGS_TOTAL` — coverage, completeness gate |
| 4 | `coverage_ratio` | |
| 5 | `freshness_ratio` | |
| 6-8 | padding, always 0 | |
| -1 | type indicator | |

**The risk.** `SLOT_LEGS_TOTAL = 3` is re-declared as a literal in at least
four files; `VOLUME_SLOT = 4` in three; `NET_FLOW_SLOT = 5` in three. A slot
reordering in `stg/nodes/kalshi.py` would have to be chased through roughly
ten files, and nothing would error — the numbers would just quietly change
meaning.

**Check it yourself**
```bash
grep -rn "SLOT_LEGS_TOTAL = \|VOLUME_SLOT = \|NET_FLOW_SLOT = " --include=*.py .
python verify_pipeline.py --only hub_slot     # if you add such a check
```
`model/run_guards.check_hub_slot` already validates slot 3 at training
startup: integer-valued, >= 2, and >= the number of leg edges into that hub.

---

## 5. Two incompatible checkpoint families

This is the gotcha most likely to waste an afternoon.

| | reconstruction era | forecasting era (current) |
|---|---|---|
| written by | `model/train.py: run_training()` | `train_forecast.py` |
| default dir | `runs/v1_reconstruction/` | `runs/v2_forecast/` |
| keys | `model`, `objective` (a state_dict) | `model`, `head`, `config`, `horizons`, `val_loss`, `selected_by` |
| head used | `MeceOutputHead` / `LadderOutputHead` | `ResidualForecastHead` |
| read by | `evaluate_arbitrage*.py`, `evaluate_price_discovery.py`, `evaluate_violation_prediction.py`, `evaluate_baselines.py` | `score_forecast.py`, `evaluate_mece_forecast_pnl.py`, `evaluate_mece_maker_pnl.py` |

They are not interchangeable. `evaluate_arbitrage_ladder.py` does
`objective.load_state_dict(ckpt["objective"])`, but a forecast checkpoint
stores `"objective": "horizon_forecast_residual"` — a *string*.

Note also: the three forecast evaluators default to `--checkpoint
runs/v2_mece/best.pt`, but `train_forecast.py --checkpoint-dir` defaults
to `runs/v2_forecast`. That coupling exists only in the flag defaults.

---

## 6. The evaluation layer

### `score_forecast.py`
Loads one checkpoint, scores one split, prints, exits. No tuning flags **by
design** — looking at test and then changing something puts test inside the
selection loop. It imports `_chunk_loss` from `train_forecast.py`, so training
and scoring cannot drift apart in what they compute.

This is the script to extend for the highest-priority open item: re-scoring
the existing checkpoint against **bid-side basket sums** rather than the mixed
last-print sum (`mece-graph-ablation-result.md` §5). It is a re-score, not a
retrain.

### `evaluate_mece_forecast_pnl.py`
The round-trip PnL script. Flow:

1. One forward pass per chunk, sliced to the chosen horizon.
2. Per basket-snapshot, build an **event** — but only if every declared leg is
   observed at both `t` and `t+h`:
   ```python
   if total <= 0 or int(both.sum()) < int(round(total)): continue
   ```
3. Fit one `alpha` over the whole split for the oracle.
4. Size the trade (`--contracts`, optionally capped by `--max-participation`);
   drop the event entirely if `C < 1.0`.
5. Compute costs **once per event, shared by every strategy** — this is what
   makes the comparison paired, and what makes the model-vs-control result
   provably cost-model invariant.
6. Book five strategies, each with its **own entry gate**:

| strategy | gate | direction |
|---|---|---|
| `model` | `abs(delta_pred) > threshold` | sign of `delta_pred` |
| `random` | *the same gate as model* | coin flip |
| `oracle_shrink` | `abs((alpha-1)*dev_t) > threshold` | sign of that |
| `always_revert` | `abs(dev_t) > threshold` | `-sign(dev_t)` |
| `static_arb` | `abs(dev_t) > threshold` | none: gross is `abs(dev_t)` |

`static_arb` pays `fee_in` and **one** spread crossing, not two, because it
settles rather than exits. That cost asymmetry — not a better signal — is why
it loses least.

### `evaluate_mece_settlement_pnl.py`
The hold-to-settlement variant, and the one the economics chapter is about.
Its `--spreads` default is now `mece_leg_spreads.parquet` (it used to be the
*ladder* results file, which contains only crypto/financials pairs, so zero
MECE legs matched and everything silently fell through to a global median from
a different mechanism). `warn_spread_coverage` now banners when under 50% of
legs are costed from a measured per-ticker or per-series spread. Three
robustness filters (`--min-leg-volume`, `--min-ttc`, `--exclude-families`)
default **off** so prior figures reproduce exactly.

### `examples/mece_spread_artefact_check.py`
The decisive economic test. Splits each leg's prints by `taker_side`
(`"yes"` = taker lifted the ask, `"no"` = sold into the bid; verified at a
median per-ticker gap of +3.82¢), reprices each basket four ways (last mixed /
ask / bid / mid), and reports the executable edge on the gated tail. Use
`--max-basket-span` to constrain the **cross-leg** print span (median 406
min); `--min-side-gap` constrains the within-leg gap and is a different
control.

### Diagnostics
`diagnose_*.py` are read-only, need no checkpoint, and each answers one
question. None writes a file; all print tables.

**Check it yourself**
```bash
grep -n "entry_threshold\|book_round_trip\|static_arb" evaluate_mece_forecast_pnl.py | head -20
python verify_pipeline.py --only bootstrap -v
```

---

## 7. Things that look wrong

Ordered by how much they matter. **Verified** = I ran it. **Reported** = found
by reading, and you should confirm before acting.

### a. `stg/builders/` and `stg/temporal/` do not exist here — VERIFIED

```
$ python -c "import stg.builders.builder"
ModuleNotFoundError: No module named 'stg.builders'
```

`build_combined_stgat_graph.py` and `run_real_training.py` both import
`GraphBuilder` and `FixedWindowTemporal` from those paths, so **neither can
run in this copy of the repo.** Since your cached bundles clearly got built at
some point, the most likely explanation is that this copy is partial rather
than that the code is broken. Confirm on your own machine:
```bash
ls stg/builders/ stg/temporal/
python -c "import stg.builders.builder, stg.temporal.strategies; print('ok')"
```
If they are missing there too, the graph-building half of your pipeline is
unreproducible and that needs fixing before anything else.

### b. Dead output heads in every forecasting checkpoint — VERIFIED

`STGATBackbone.__init__` unconditionally constructs `mece_head` and
`ladder_head`. The forecasting pipeline never calls them:

```
$ grep -c "mece_head\|ladder_head" train_forecast.py score_forecast.py \
      evaluate_mece_forecast_pnl.py model/forecast_objective.py
0  0  0  0
```

So their parameters are handed to `Adam` via `model.parameters()`, never
receive gradients, and are saved into every checkpoint as dead weights.
Harmless numerically; misleading if you report a parameter count.

### c. The backwards ladder docstring — REPORTED, still present

`stg/edges/kalshi.py`, in `KalshiLadderChainEdges`:

> "a ladder pair encodes a genuine ORDER relationship -- leg_a's threshold
> implies leg_b's (per however `build_valid_pairs()` sorted them)"

Read literally this puts `leg_a` at the *higher* strike, which is the opposite
of what the code does — `verify_ladder_direction.py` says the gap is
`price[edge_index[1]] - price[edge_index[0]]`, which is only a violation
measure if `edge_index[0]` is the **lower** strike. The same docstring also
cites `build_valid_pairs()` and `pairwise_monotonicity_taker_side_check_v2.py`,
neither of which exists.

Fix the prose, not the code — the code's convention is the validated one.

### d. Null ladder edge features become indistinguishable from real zeros — REPORTED

`KalshiLadderChainEdges` sets `features = None` when any requested column is
null. `sparse_edges_by_type` then substitutes a zero vector. Downstream that
reads as `same_side_yes_violation = 0.0` — a confident "no violation" rather
than "unknown".

The older dense export returned a `has_features` boolean for exactly this
distinction; the sparse structs have no equivalent and `TorchGraphBundle`
dropped it. Worth quantifying how many ladder edges are affected before
deciding whether it matters. Low priority now that the ladder line is closed.

### e. Possible `edge_dim` mismatch on the ladder channel — REPORTED, unverified

`ladder_conv` is built with `edge_dim = ladder_edge_feature_dim + 1 = 3`, but
`symmetrize_local_edges` returns an edge attribute of width **1** when
`features is None`. If that path is ever reached, PyG would error or
mis-shape. Whether it is reachable depends on the `feature_cols` actually
passed in production, which I could not trace here.

### f. Smaller things

- `KalshiEventNodes` has `N_FEATURES = 7` against everyone else's 10;
  registering it alongside another builder would crash in `np.vstack`.
- `nx.DiGraph` silently **overwrites** a parallel edge between the same
  ordered pair, including its `edge_type`. Not reachable with the current
  two-builder wiring; a trap if you add a third.
- `KalshiMeceBasketNodes._last_known_price` is never expired, while
  `KalshiTickerNodes` has documented cache expiry as "REQUIRED AT MULTI-MONTH
  SCALE, NOT OPTIONAL". The reasoning that forced expiry on one was never
  revisited for the other.
- `taker_fee_dollars` exists in **two versions** — `evaluate_arbitrage.py` uses
  a bare `ceil`, `evaluate_mece_forecast_pnl.py` adds a float-drift guard. Both
  are loaded into the same process when you run the MECE script. The difference
  is ~0.006% of a fee, but two functions with one name is a drift hazard.
- The ~18-line event-collection loop is copy-pasted between the taker and maker
  PnL scripts, with the `delta_pred` expression written two algebraically
  identical but separately maintained ways. This is the most likely place for
  the two to silently disagree about what an event is.
- `MOVE_EPS = 0.005` is declared independently in `model/forecast_objective.py`
  and `diagnose_ladder_conditional.py`, and a third time as `TICK/2` in
  `diagnose_staleness.py`. All equal today; nothing keeps them so.

---

## 8. Verify-it-yourself cheat sheet

```bash
# the whole correctness suite, plus proof each check can fail
python verify_pipeline.py --self-test

# one area at a time, with the measured numbers
python verify_pipeline.py --only causality -v
python verify_pipeline.py --only baselines -v

# what edge types does a cached month actually carry?
python -c "
import sys, torch; sys.path.insert(0,'.')
b = torch.load('cache/bundle_month_2025-05.pt', weights_only=False)
print('F =', b.features.shape, ' N =', len(b.node_ids), ' T =', len(b.timestamps))
print('edge types:', sorted(b.adjacency_by_type))"

# what does the split actually look like for the months you are loading?
python train_forecast.py --months 2025-05 2025-06 --epochs 0 2>&1 | head -30
#   read the SPLIT INTEGRITY, MONTH SCHEMA and BACKBONE WILL SEE lines

# confirm an ablation really ablates before trusting its table
python train_forecast.py --drop-edges ladder_monotonic mece_leg_to_basket \
    mece_basket_to_leg 2>&1 | grep "BACKBONE WILL SEE"
#   must print: NOTHING -- no spatial channel at all
```

---

## 9. Reading order, if you want to work through it

1. `stg/nodes/kalshi.py` — the feature slots. Everything else is downstream of
   this file's decisions.
2. `model/chunking.py` — the module docstring explains the split/chunk
   separation better than anything else in the repo.
3. `model/forecast_head.py` — small, and the zero-init is the keystone of the
   whole evaluation.
4. `model/forecast_objective.py` — where persistence, shrinkage and the
   moved/flat stratification are actually computed.
5. `train_forecast.py` `main()` — the loop that ties it together.
6. `evaluate_mece_forecast_pnl.py` from `# ---- pass 1` onward — how a
   prediction becomes a trade.
7. `examples/mece_spread_artefact_check.py` — why, economically, it does not.

The docstrings in this repo are unusually good and mostly explain *why*, not
*what*. Where a docstring and the code disagree, §7 lists the cases I found;
elsewhere, trust the code and fix the prose.

## 10. Conventions worth keeping

- Every new script gets `--self-test` exercising planted cases with known
  answers before it touches real data. This caught the ablation key bug, the
  keyword-matcher bug, and three bugs in the spread artefact check.
- Robustness filters default **off**, so prior figures reproduce exactly.
- Report both filtered and unfiltered; never silently replace one.
- Splits strictly forward in time.
- State predictions *before* measuring them. The overround prediction (+6.3¢
  from a 68.7% ask share) was written down before the measurement (+5.25¢),
  which is why it is the project's strongest piece of evidence.
