"""
score_mece_bidside.py

RE-SCORE A MECE CHECKPOINT AGAINST THE BID-SIDE BASKET SUM. ONCE PER SPLIT.

Protocol: runs/README.md, "Bid-side re-score of the causal checkpoints",
pre-registered before any result. Read it before changing anything here.

WHY. score_forecast.py's MECE term scores the basket sum of mixed LAST
PRINTS. ~92.5% of last-print basket deviation is the bid/ask overround
(68.7% of prints are ask-side), so beating the oracle there may be
forecasting which side the next print lands on, not where the partition is
priced. The seller of a basket trades at the bid, so the bid-side sum is the
executable target.

LEG BID. yes_price of the latest trade with taker_side == "no" (taker sold
into the bid; verified: median mean(yes)-mean(no) = +3.82c per ticker), at
or before the END of the snapshot window. Age = window end - that trade.
A trade print is not a live quote: the bid may have moved since. The recency
bound R limits that; it does not remove it.

TARGET at t+h: a leg settled by the end of window t+h takes its settlement
value (as whole_settle does); any other leg takes its bid at t+h.

FORECASTS of the bid-side sum at t+h:
  persistence  B(t)
  model        B(t) + (S_model(t) - S_last(t))   -- predicted CHANGE of the
               last-print sum applied to the bid level. Trade price =
               efficient price +/- half-spread (Roll 1984), so the half-
               spread cancels in the change if the spread is stable over h.
  oracle       1 + alpha * (B(t) - 1), alpha fitted on the scored sample.

POSITIONS. Exactly the basket-positions MechanismForecastObjective's
whole_settle rule scores under --supervise active; a reproduction guard
checks the last-print branch against that function chunk by chunk and
aborts on any mismatch. Bid-side eligibility then additionally needs every
leg not settled by its window end to have a bid of age <= R at t and t+h.

USAGE (from repo root):
    python stg_infra/score_mece_bidside.py --self-test
    python stg_infra/score_mece_bidside.py --checkpoint runs/v2_mece_causal_s0/best.pt \
        --cache cache_causal --split val
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import numpy as np

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent

R_PRIMARY_H = 1.0
R_SENSITIVITY_H = (0.5, 2.0)
N_BOOT = 2000
NS_PER_H = 3_600_000_000_000


# ---------------------------------------------------------------- pure parts

def bid_lookup(times_ns: np.ndarray, prices: np.ndarray, end_ns: int):
    """Latest bid print at or before end_ns -> (price, age_ns); (nan, inf) if none.
    times_ns must be sorted ascending."""
    j = int(np.searchsorted(times_ns, end_ns, side="right")) - 1
    if j < 0:
        return math.nan, math.inf
    return float(prices[j]), float(end_ns - times_ns[j])


def leg_value(bid, age, settled, settle_val):
    """A leg's bid-side value and the age that counts toward recency.
    Settled legs take the settlement value and never fail recency."""
    if settled:
        return float(settle_val), 0.0
    return bid, age


def bid_forecast(b_now, s_pred, s_now):
    """Model forecast of the bid-side sum: bid level + predicted last-print change."""
    return b_now + (s_pred - s_now)


def score_rows(rows: dict, sel: np.ndarray) -> dict:
    """MSE of model / persistence / oracle on the selected rows.
    rows: arrays b_now, b_tgt, b_model (bid side); returns sums too."""
    x = rows["b_now"][sel] - 1.0
    y = rows["b_tgt"][sel] - 1.0
    m = rows["b_model"][sel] - 1.0
    n = int(sel.sum())
    if n == 0:
        return {"n": 0}
    sxx, sxy, syy = float(x @ x), float(x @ y), float(y @ y)
    alpha = sxy / sxx if sxx > 0 else 1.0
    mse_m = float(((m - y) ** 2).mean())
    mse_p = float(((x - y) ** 2).mean())
    mse_o = (syy - 2 * alpha * sxy + alpha * alpha * sxx) / n
    return {"n": n, "model": mse_m, "persist": mse_p, "oracle": mse_o, "alpha": alpha,
            "vs_oracle": mse_m / mse_o if mse_o > 0 else math.nan,
            "vs_persist": mse_m / mse_p if mse_p > 0 else math.nan}


def score_last(rows: dict, sel: np.ndarray) -> dict:
    """Same, on the LAST-PRINT target (for the same-subset comparison)."""
    sub = {"b_now": rows["s_now"], "b_tgt": rows["s_tgt"], "b_model": rows["s_pred"]}
    return score_rows(sub, sel)


def cluster_bootstrap(rows: dict, sel: np.ndarray, n_boot=N_BOOT, seed=0):
    """95% CI of model/oracle by resampling clusters (events), alpha refit
    per resample. Returns (lo, hi, k)."""
    cl = rows["cluster"][sel]
    if cl.size == 0:
        return math.nan, math.nan, 0
    x = rows["b_now"][sel] - 1.0
    y = rows["b_tgt"][sel] - 1.0
    m = rows["b_model"][sel] - 1.0
    _, inv = np.unique(cl, return_inverse=True)
    k = int(inv.max()) + 1
    agg = np.zeros((k, 5))
    for col, v in enumerate(((m - y) ** 2, x * x, x * y, y * y, np.ones_like(x))):
        np.add.at(agg[:, col], inv, v)
    rng = np.random.default_rng(seed)
    w = rng.multinomial(k, np.full(k, 1.0 / k), size=n_boot).astype(float)  # (B, k)
    s = w @ agg                                                             # (B, 5)
    sm, sxx, sxy, syy = s[:, 0], s[:, 1], s[:, 2], s[:, 3]
    with np.errstate(divide="ignore", invalid="ignore"):
        so = syy - np.where(sxx > 0, sxy * sxy / sxx, 0.0)
        ratio = sm / so
    ratio = ratio[np.isfinite(ratio)]
    if ratio.size < 0.99 * n_boot:
        # Target constant (every leg settled -> sum exactly $1): the oracle
        # with alpha = 0 is exact and model/oracle is undefined, not large.
        return math.nan, math.nan, k
    lo, hi = np.percentile(ratio, [2.5, 97.5])
    return float(lo), float(hi), k


def series_of(cluster: str) -> str:
    """Basket series (family) from the hub id, e.g. 'MECE:KXHIGHNY-25JUL03' -> 'MECE:KXHIGHNY'.
    Known ex ante: a basket's family is fixed at listing."""
    return str(cluster).split("-")[0]


def family_oracle(rows: dict, sel: np.ndarray, n_boot=N_BOOT, seed=0) -> dict:
    """LAST-PRINT model vs a shrinkage oracle with one alpha PER SERIES x HORIZON
    (fitted on the scored sample, so optimistic), plus a 95% cluster bootstrap
    over events with every group alpha refit per resample."""
    x = rows["s_now"][sel] - 1.0
    y = rows["s_tgt"][sel] - 1.0
    m = rows["s_pred"][sel] - 1.0
    if x.size == 0:
        return {"n": 0}
    keys = np.array([f"{series_of(c)}|{h}" for c, h in zip(rows["cluster"][sel], rows["h"][sel])])
    _, gi = np.unique(keys, return_inverse=True)
    _, ci = np.unique(rows["cluster"][sel], return_inverse=True)
    k, G = int(ci.max()) + 1, int(gi.max()) + 1
    A = np.zeros((3, k, G))
    for j, v in enumerate((x * x, x * y, y * y)):
        np.add.at(A[j], (ci, gi), v)
    sse_m = np.zeros(k)
    np.add.at(sse_m, ci, (m - y) ** 2)

    def oracle_sse(sxx, sxy, syy):
        with np.errstate(divide="ignore", invalid="ignore"):
            return (syy - np.where(sxx > 0, sxy * sxy / np.where(sxx > 0, sxx, 1.0), 0.0)).sum(axis=-1)

    o = oracle_sse(A[0].sum(0), A[1].sum(0), A[2].sum(0))
    point = sse_m.sum() / o if o > 0 else math.nan
    rng = np.random.default_rng(seed)
    w = rng.multinomial(k, np.full(k, 1.0 / k), size=n_boot).astype(float)       # (B, k)
    ob = oracle_sse(w @ A[0], w @ A[1], w @ A[2])                                 # (B,)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = (w @ sse_m) / ob
    ratio = ratio[np.isfinite(ratio)]
    lo, hi = (np.percentile(ratio, [2.5, 97.5]) if ratio.size >= 0.99 * n_boot else (math.nan, math.nan))
    return {"n": int(x.size), "vs_oracle": point, "lo": float(lo), "hi": float(hi), "k": k, "groups": G}


def select(rows: dict, r_h: float, stratum: str = "all") -> np.ndarray:
    r_ns = r_h * NS_PER_H
    sel = (rows["age_now"] <= r_ns) & (rows["age_tgt"] <= r_ns)
    if stratum == "no_settled":
        sel &= ~rows["settled_any"]
    elif stratum == "some_settled":
        sel &= rows["settled_any"]
    return sel


# ---------------------------------------------------------------- self-test

def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    H = NS_PER_H
    t = np.array([2, 3, 5]) * H          # "no" prints only; "yes" prints never enter
    p = np.array([0.40, 0.42, 0.45])
    b, a = bid_lookup(t, p, 4 * H)
    check("bid = latest print before window end", b == 0.42 and a == 1 * H)
    b, a = bid_lookup(t, p, 5 * H)
    check("print exactly at window end counts", b == 0.45 and a == 0)
    b, a = bid_lookup(t, p, 1 * H)
    check("no print yet -> nan bid, infinite age", math.isnan(b) and a == math.inf)

    check("settled leg ignores its missing bid", leg_value(math.nan, math.inf, True, 1.0) == (1.0, 0.0))
    check("unsettled leg keeps bid and age", leg_value(0.3, 5.0, False, math.nan) == (0.3, 5.0))

    check("model forecast = bid level + predicted last-print change",
          abs(bid_forecast(0.95, 1.10, 1.05) - 1.00) < 1e-12)

    # x = B-1 = [0.1, 0.2], y = [0.05, 0.10] -> alpha 0.5, oracle exact
    rows = {"b_now": np.array([1.1, 1.2]), "b_tgt": np.array([1.05, 1.10]),
            "b_model": np.array([1.05, 1.10])}
    s = score_rows(rows, np.array([True, True]))
    check("oracle alpha fitted exactly", abs(s["alpha"] - 0.5) < 1e-12 and s["oracle"] < 1e-20)
    check("perfect model has zero error", s["model"] < 1e-20)
    rows["b_model"] = rows["b_now"].copy()
    s = score_rows(rows, np.array([True, True]))
    check("model == persistence -> ratio 1 vs persistence", abs(s["vs_persist"] - 1.0) < 1e-12)

    ages = {"age_now": np.array([0.5, 1.5, 0.2]) * H, "age_tgt": np.array([0.9, 0.1, 1.0]) * H,
            "settled_any": np.array([False, False, True])}
    check("recency: both ends must be <= R", select(ages, 1.0).tolist() == [True, False, True])
    check("strata split the eligible set",
          select(ages, 1.0, "no_settled").tolist() == [True, False, False]
          and select(ages, 1.0, "some_settled").tolist() == [False, False, True])

    rng = np.random.default_rng(1)
    n = 400
    x = rng.normal(0, 0.1, n)
    y = 0.5 * x + rng.normal(0, 0.02, n)
    rows = {"b_now": 1 + x, "b_tgt": 1 + y, "b_model": 1 + 0.5 * x,
            "cluster": np.repeat(np.arange(40), 10)}
    lo, hi, k = cluster_bootstrap(rows, np.ones(n, bool), n_boot=500)
    pt = score_rows(rows, np.ones(n, bool))["vs_oracle"]
    check(f"bootstrap: k = 40 clusters, CI [{lo:.3f},{hi:.3f}] brackets point {pt:.3f}",
          k == 40 and lo <= pt <= hi)

    rows = {"b_now": np.array([0.9, 1.1, 0.95]), "b_tgt": np.ones(3), "b_model": np.array([0.97, 1.02, 1.0]),
            "cluster": np.array(["a", "b", "c"])}
    s = score_rows(rows, np.ones(3, bool))
    lo, hi, k = cluster_bootstrap(rows, np.ones(3, bool), n_boot=200)
    check("settled-only target: oracle exact, ratio undefined (nan), no crash",
          s["oracle"] < 1e-20 and math.isnan(s["vs_oracle"]) and math.isnan(lo) and k == 3)

    # family oracle: two series, each exactly y = a_g * x -> per-group oracle is exact
    x = np.tile([0.1, -0.2, 0.05, 0.3], 10)
    ser = np.repeat(["MECE:A-1", "MECE:B-1"], 20)
    y = np.where(np.char.startswith(ser, "MECE:A"), 0.2, 0.9) * x
    fr = {"s_now": 1 + x, "s_tgt": 1 + y, "s_pred": 1 + 0.5 * x, "cluster": ser, "h": np.ones(40, int)}
    f = family_oracle(fr, np.ones(40, bool), n_boot=200)
    single = score_rows({"b_now": fr["s_now"], "b_tgt": fr["s_tgt"], "b_model": fr["s_pred"]}, np.ones(40, bool))
    check("family oracle exact when each series has its own alpha (0 error -> ratio undefined)",
          math.isnan(f["vs_oracle"]))
    check("family oracle: 2 groups, 2 clusters, beats single-alpha oracle",
          f["groups"] == 2 and f["k"] == 2 and single["oracle"] > 1e-6)
    check("series_of strips the event date", series_of("MECE:KXHIGHNY-25JUL03") == "MECE:KXHIGHNY")

    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


# ---------------------------------------------------------------- real run

def _load_bids(months):
    """ticker -> (sorted times_ns, prices 0-1) for taker_side == 'no' prints."""
    import polars as pl
    sys.path.insert(0, str(_THIS_DIR))
    from run_real_training import _parity_path
    frames = []
    for m in months:
        f = Path(_parity_path("trades", m))
        if not f.exists():
            print(f"  (no trades file for {m}; lookback skipped)")
            continue
        frames.append(pl.scan_parquet(f).filter(pl.col("taker_side") == "no")
                      .select("ticker", "created_time", "yes_price").collect())
    df = pl.concat(frames).sort(["ticker", "created_time"])
    out = {}
    for (tk,), g in df.group_by(["ticker"], maintain_order=True):
        out[tk] = (g["created_time"].cast(pl.Int64).to_numpy(),
                   g["yes_price"].cast(pl.Float64).to_numpy() / 100.0)
    return out


def _prev_month(m):
    y, mm = (int(v) for v in m.split("-"))
    return f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"


def _logged_scorer_mece(seed_log: Path):
    if not seed_log.exists():
        return None
    mt = re.search(r"mece: ([\d.]+) vs persist ([\d.]+)=.*?\(n=([\d,]+)\)", seed_log.read_text())
    return None if not mt else (float(mt.group(1)), float(mt.group(2)), int(mt.group(3).replace(",", "")))


def run(args) -> int:
    import torch
    sys.path.insert(0, str(_THIS_DIR))
    sys.path.insert(0, str(_THIS_DIR / "examples"))
    from model.chunking import build_split_ranges, chunk_ranges
    from model.forecast_head import ResidualForecastHead
    from model.forecast_objective import MechanismForecastObjective
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.train import STGATBackbone, true_prices
    from train_forecast import PILOT_MONTHS, WINDOW, _mece_context, _supervision_masks

    ck_path = Path(args.checkpoint)
    if not ck_path.is_absolute():
        ck_path = _REPO_ROOT / ck_path
    ck = torch.load(ck_path, weights_only=False, map_location="cpu")
    cfg = ck["config"]
    horizons = ck.get("horizons") or list(getattr(cfg, "horizons", (1, 2, 3, 6, 12)))

    print("=" * 96)
    print(f"BID-SIDE RE-SCORE: {ck_path.parent.name}/{ck_path.name} ON {args.split.upper()}")
    print("=" * 96)
    print(f"  checkpoint epoch {ck.get('epoch')}, horizons {horizons}, supervise active, rule whole_settle")
    if args.split == "test":
        print("  Held-out split, scored once under the pre-registered protocol. No retry.")

    cache = Path(args.cache)
    if not cache.is_absolute():
        cache = _REPO_ROOT / cache
    months = args.months or PILOT_MONTHS
    store = MonthlyBundleStore(build_month_paths(months, cache), verbose=False)
    chunks = [c for c in chunk_ranges(build_split_ranges(store.timestamps),
                                      chunk_len=cfg.chunk_len, min_chunk_len=4)
              if c.split == args.split]
    split_months = sorted({f"{ts.year}-{ts.month:02d}"
                           for c in chunks for ts in store.timestamps[c.start:c.end]})
    bid_months = sorted(set(split_months) | {_prev_month(split_months[0])})
    print(f"  split months {split_months}; bid prints loaded from {bid_months}")
    bids = _load_bids(bid_months)
    print(f"  {len(bids):,} tickers with bid prints\n")

    model = STGATBackbone(padded_feature_width=store.feature_width,
                          zero_input_slots=getattr(cfg, "zero_input_slots", ()),
                          zero_ladder_edge_features=getattr(cfg, "zero_ladder_edge_features", False),
                          embed_dim=cfg.embed_dim, n_heads=cfg.n_heads, max_len=cfg.chunk_len)
    head = ResidualForecastHead(embed_dim=cfg.embed_dim, horizons=horizons)
    model.load_state_dict(ck["model"], strict=True)
    head.load_state_dict(ck["head"], strict=True)
    model.eval()
    head.eval()
    objective = MechanismForecastObjective(horizons=horizons, huber_beta=getattr(cfg, "huber", 0.0) or 0.0,
                                           monitor_unweighted=True, mece_rule="whole_settle")

    cols = {k: [] for k in ("cluster", "h", "s_now", "s_tgt", "s_pred", "b_now", "b_tgt",
                            "age_now", "age_tgt", "settled_any",
                            "max_leg", "hours_to_close")}
    guard_sm = guard_sp = 0.0
    guard_n = 0
    with torch.no_grad():
        for pos, c in enumerate(chunks):
            ct = store.materialize_chunk(c)
            features, mask = ct["features"], ct["mask"]
            prices = true_prices(features)
            adj = ct["adjacency_by_type"]
            _, mask_sup = _supervision_masks(features, mask, adj, "active")
            pred = head(model(features, mask, adj), prices)
            ctx = _mece_context(ct, features)
            mece_adj = adj.get("mece_leg_to_basket")
            if ctx is None or mece_adj is None:
                raise SystemExit("chunk lacks settlement context or MECE edges -- wrong cache?")
            T = features.shape[0]
            ids = ct["node_ids"]
            end_ns = [int(np.datetime64(ts + WINDOW, "ns").astype(np.int64)) for ts in ct["timestamps"]]
            hub_n, settle, closed = ctx["hub_legs_total"], ctx["settle"], ctx["closed_by_end"]
            settle_np = settle.numpy()
            closed_np = closed.numpy()
            empty = (np.empty(0, np.int64), np.empty(0))
            for i, h in enumerate(horizons):
                # reproduction guard: the objective's own numbers for this chunk/horizon
                g_sm, g_sp, g_n, _, _ = objective._mece_terms_whole_settle(
                    pred, prices, mask_sup, mece_adj, i, h, T, ctx)
                my_sm = my_sp = 0.0
                my_n = 0
                for t in range(T - h):
                    e = mece_adj[t]
                    if e.edge_index.numel() == 0:
                        continue
                    leg, hub = e.edge_index[0], e.edge_index[1]
                    hubs, inv = torch.unique(hub, return_inverse=True)
                    k = hubs.numel()
                    ones = torch.ones_like(leg, dtype=pred.dtype)
                    n_linked = torch.zeros(k).index_add_(0, inv, ones)
                    whole = (n_linked == hub_n[t, hubs]) & (n_linked > 0)
                    settled = closed[t + h, leg] & ~torch.isnan(settle[leg])
                    priced = mask_sup[t + h, leg] & ~closed[t + h, leg]
                    ok = (mask_sup[t, leg] & (settled | priced)).to(pred.dtype)
                    full = whole & (torch.zeros(k).index_add_(0, inv, ok) == n_linked)
                    if not bool(full.any()):
                        continue
                    tgt_leg = torch.where(settled, torch.nan_to_num(settle[leg]), prices[t + h, leg])
                    s_pred = torch.zeros(k).index_add_(0, inv, pred[t, leg, i])
                    s_tgt = torch.zeros(k).index_add_(0, inv, tgt_leg)
                    s_now = torch.zeros(k).index_add_(0, inv, prices[t, leg])
                    my_sm += float(((s_pred[full] - s_tgt[full]) ** 2).sum())
                    my_sp += float(((s_now[full] - s_tgt[full]) ** 2).sum())
                    my_n += int(full.sum())

                    leg_np, inv_np = leg.numpy(), inv.numpy()
                    settled_np = settled.numpy()
                    for hb in full.nonzero(as_tuple=True)[0].tolist():
                        members = leg_np[inv_np == hb]
                        st_members = settled_np[inv_np == hb]
                        b_now = b_tgt = 0.0
                        age_now = age_tgt = 0.0
                        for lg, st_th in zip(members.tolist(), st_members.tolist()):
                            tb, pb = bids.get(ids[lg], empty)
                            st_t = bool(closed_np[t, lg]) and not math.isnan(settle_np[lg])
                            bv, ag = leg_value(*bid_lookup(tb, pb, end_ns[t]), st_t, settle_np[lg])
                            b_now += bv
                            age_now = max(age_now, ag)
                            bv, ag = leg_value(*bid_lookup(tb, pb, end_ns[t + h]), bool(st_th), settle_np[lg])
                            b_tgt += bv
                            age_tgt = max(age_tgt, ag)
                        cols["cluster"].append(ids[int(hubs[hb])])
                        cols["h"].append(h)
                        cols["s_now"].append(float(s_now[hb]))
                        cols["s_tgt"].append(float(s_tgt[hb]))
                        cols["s_pred"].append(float(s_pred[hb]))
                        cols["b_now"].append(b_now)
                        cols["b_tgt"].append(b_tgt)
                        cols["age_now"].append(age_now)
                        cols["age_tgt"].append(age_tgt)
                        cols["settled_any"].append(bool(st_members.any()))
                        # diagnostics only (--dump); never model inputs
                        cols["max_leg"].append(float(prices[t, torch.as_tensor(members)].max()))
                        closes = [ct["node_close"][lg] for lg in members.tolist() if ct["node_close"][lg] is not None]
                        cols["hours_to_close"].append(
                            (min(closes) - (ct["timestamps"][t] + WINDOW)).total_seconds() / 3600.0
                            if closes else math.nan)
                if my_n != g_n or not math.isclose(my_sm, float(g_sm), rel_tol=1e-5, abs_tol=1e-9) \
                        or not math.isclose(my_sp, float(g_sp), rel_tol=1e-5, abs_tol=1e-9):
                    raise SystemExit(f"REPRODUCTION GUARD FAILED chunk {pos} h={h}: "
                                     f"n {my_n} vs {g_n}, model {my_sm} vs {float(g_sm)}, "
                                     f"persist {my_sp} vs {float(g_sp)}")
                guard_sm += my_sm
                guard_sp += my_sp
                guard_n += my_n
            print(f"  chunk {pos + 1}/{len(chunks)} done, {len(cols['h']):,} basket-positions so far")
            del ct

    rows = {k: np.asarray(v) for k, v in cols.items()}
    rows["b_model"] = bid_forecast(rows["b_now"], rows["s_pred"], rows["s_now"])
    n_all = rows["h"].size
    if args.dump:
        np.savez(args.dump, **rows)
        print(f"  rows dumped to {args.dump}")

    print()
    print("-" * 96)
    print(f"  REPRODUCTION GUARD PASSED on every chunk and horizon: last-print MECE "
          f"{guard_sm / guard_n:.5f} vs persist {guard_sp / guard_n:.5f} (n={guard_n:,})")
    logged = _logged_scorer_mece(_REPO_ROOT / "logs/v2_forecast" / f"score_causal_{ck_path.parent.name.split('_')[-1]}.log")
    if args.split == "test" and logged:
        print(f"  score_forecast.py logged: {logged[0]:.5f} vs {logged[1]:.5f} (n={logged[2]:,})"
              f" -> {'MATCH' if logged[2] == guard_n and abs(logged[0] - guard_sm / guard_n) < 5e-6 else 'MISMATCH'}")

    print()
    print("=" * 96)
    print("LAST-PRINT HEADLINE BY STRATUM, all whole_settle positions, no bid filter")
    print("[ADDED AFTER VAL s0 WAS SEEN -- not pre-registered; a decomposition of the")
    print(" already-reported figure, used for no choice. See runs/README.md.]")
    print("=" * 96)
    for stratum, sel in (("all", np.ones(n_all, bool)), ("no_settled", ~rows["settled_any"]),
                         ("some_settled", rows["settled_any"])):
        sl = score_last(rows, sel)
        sub = {"b_now": rows["s_now"], "b_tgt": rows["s_tgt"], "b_model": rows["s_pred"],
               "cluster": rows["cluster"]}
        lo, hi, k = cluster_bootstrap(sub, sel)
        vo = "undefined (target constant $1)" if math.isnan(sl["vs_oracle"]) else \
            f"{sl['vs_oracle']:.3f}x  CI95 [{lo:.3f}, {hi:.3f}]"
        print(f"  {stratum:<12}: model/oracle {vo}  k={k:,} | model/persist {sl['vs_persist']:.3f}x | "
              f"alpha {sl['alpha']:.3f} | n={sl['n']:,} ({100.0 * sl['n'] / n_all:.1f}%)")

    print()
    print("=" * 96)
    print("UNSETTLED, LAST-PRINT, vs PER-SERIES x HORIZON ORACLE  [primary for the whole_unsettled")
    print(" retrain, pre-registered 2026-09-27; for earlier checkpoints: diagnostic only]")
    print("=" * 96)
    u = ~rows["settled_any"]
    f = family_oracle(rows, u)
    sl = score_last(rows, u)
    print(f"  model / family oracle : {f['vs_oracle']:.3f}x  CI95 [{f['lo']:.3f}, {f['hi']:.3f}]  "
          f"k={f['k']:,} baskets, {f['groups']} series x horizon groups, n={f['n']:,}")
    print(f"  model / single-alpha  : {sl['vs_oracle']:.3f}x (alpha {sl['alpha']:.3f})   "
          f"model / persistence {sl['vs_persist']:.3f}x")

    for r_h in (R_PRIMARY_H,) + R_SENSITIVITY_H:
        tag = "PRIMARY" if r_h == R_PRIMARY_H else "sensitivity (not used for any choice)"
        print()
        print("=" * 96)
        print(f"R = {r_h:g}h  [{tag}]")
        print("=" * 96)
        for stratum in ("all", "no_settled", "some_settled"):
            sel = select(rows, r_h, stratum)
            s = score_rows(rows, sel)
            if not s["n"]:
                print(f"  {stratum:<13}: no eligible positions")
                continue
            lo, hi, k = cluster_bootstrap(rows, sel)
            sl = score_last(rows, sel)
            cov = 100.0 * s["n"] / n_all
            if math.isnan(s["vs_oracle"]):
                print(f"  {stratum:<13}: target constant at $1 (all legs settled) -> oracle (alpha {s['alpha']:.3f}) "
                      f"is exact, model/oracle undefined | model/persist {s['vs_persist']:.3f}x | "
                      f"k={k:,} | n={s['n']:,} ({cov:.1f}% of whole_settle)")
                continue
            print(f"  {stratum:<13}: BID model/oracle {s['vs_oracle']:.3f}x  CI95 [{lo:.3f}, {hi:.3f}]  "
                  f"k={k:,} baskets | model/persist {s['vs_persist']:.3f}x | alpha {s['alpha']:.3f} | "
                  f"n={s['n']:,} ({cov:.1f}% of whole_settle)")
            print(f"  {'':<13}  last-print on same subset: model/oracle {sl['vs_oracle']:.3f}x, "
                  f"model/persist {sl['vs_persist']:.3f}x, alpha {sl['alpha']:.3f}")
        if r_h == R_PRIMARY_H:
            sel = select(rows, r_h)
            per_h = []
            for h in horizons:
                s = score_rows(rows, sel & (rows["h"] == h))
                if s["n"]:
                    per_h.append(f"h{h}: {s['vs_oracle']:.3f}x (n={s['n']:,})")
            print(f"  per-horizon (all): " + "  ".join(per_h))
            bn = rows["b_now"][sel]
            print(f"  mean bid-side basket sum at t: {bn.mean():.4f}  (last-print: {rows['s_now'][sel].mean():.4f})")
    print("\nexit: 0")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--checkpoint")
    ap.add_argument("--cache", default="cache_causal")
    ap.add_argument("--split", choices=["val", "test"])
    ap.add_argument("--months", nargs="+", default=None)
    ap.add_argument("--dump", default=None, help="save per-position rows (.npz) for diagnostics")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if not (args.checkpoint and args.split):
        ap.error("--checkpoint and --split are required (or --self-test)")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
