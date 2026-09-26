"""
verify_pipeline.py

END-TO-END CORRECTNESS CHECK FOR THE FORECASTING PIPELINE.

WHY THIS EXISTS. Every bug this project has actually hit produced numbers
that looked plausible. None of them crashed. A silently wrong ablation, a
training weight leaking into a reported baseline, a one-sided confidence
interval printed as "inconclusive", a metric that was computed and printed
but never written to a file -- each ran to completion and returned a table
somebody nearly believed. Exit code 0 is not evidence of correctness, so
this script supplies some.

WHAT IT CHECKS. Invariants that must hold for the RESULTS to mean what the
write-up says they mean, not merely for the code to run:

  causality      the model cannot see the future, tested by perturbation
  architecture   the residual head starts exactly at persistence
  ablation       dropping edges actually changes what the backbone reads
  baselines      the shrinkage oracle is optimal and never beaten by
                 persistence; persistence is exactly zero on flat targets
  reporting      training weights never reach a reported metric
  identities     frozen ladder pairs contribute exactly zero persistence
                 error; basket fee arithmetic matches its closed form
  statistics     the cluster bootstrap has ~95% null coverage and real
                 power; a confidence interval below zero reads as WORSE
  splits         chunks are disjoint, homogeneous and chronological

HOW IT IS ITSELF VALIDATED. A check that has never been seen to fail is
not evidence, it is decoration. Run with --self-test and every check is
re-run against a deliberately broken version of the thing it tests; the
check is only credited if it FAILS there. The summary reports how many
checks are mutation-covered, and a check without a mutation is labelled as
such rather than quietly counted as proven.

USAGE
    python verify_pipeline.py              # run the suite
    python verify_pipeline.py --self-test  # also prove each check can fail
    python verify_pipeline.py -v           # show details for passing checks

Exits non-zero if anything fails. Uses synthetic data only: no cache, no
checkpoint, no network. Runs in seconds.
"""
from __future__ import annotations

import argparse
import math
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional

import contextlib
import io
import os

import torch

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
sys.path.insert(0, str(_THIS / "examples"))

torch.manual_seed(0)


@contextlib.contextmanager
def quiet():
    """The backbone logs per-snapshot progress, which is useful in training
    and noise here. Suppress it so the PASS/FAIL report stays readable."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield

# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    group: str
    fn: Callable[[], str]
    mutation: Optional[Callable[[], str]] = None
    why: str = ""


CHECKS: List[Check] = []


def check(group: str, name: str, why: str = ""):
    def deco(fn):
        CHECKS.append(Check(name=name, group=group, fn=fn, why=why))
        return fn
    return deco


def mutation_for(name: str):
    """Register the planted-bug counterpart of a check. The suite asserts
    the named check FAILS when this mutation is active."""
    def deco(fn):
        for c in CHECKS:
            if c.name == name:
                c.mutation = fn
                return fn
        raise KeyError(f"mutation registered for unknown check {name!r}")
    return deco


# ---------------------------------------------------------------------------
# synthetic fixtures
# ---------------------------------------------------------------------------

F_WIDTH = 10
SLOT_PRICE = 0
SLOT_TYPE = -1


@dataclass
class Edges:
    """Mirrors stg.bridge.SparseSnapshotEdgesT."""
    edge_index: torch.Tensor
    weight: torch.Tensor
    features: Optional[torch.Tensor]


def make_edges(pairs, fe=2):
    if not pairs:
        ei = torch.zeros((2, 0), dtype=torch.long)
        return Edges(ei, torch.zeros(0), torch.zeros((0, fe)))
    ei = torch.tensor(pairs, dtype=torch.long).t().contiguous()
    return Edges(ei, torch.ones(ei.shape[1]), torch.ones((ei.shape[1], fe)))


def synthetic_chunk(T=20, n_legs=8, n_hubs=2, seed=0, freeze_ladder=False):
    """A small graph with known structure.

    Legs 0..3 form basket hub `n_legs`; legs 4..7 form hub `n_legs+1`.
    Ladder chain 0 -> 1 -> 2. Prices are a bounded random walk on 0-100c.
    With freeze_ladder the ladder legs never reprice, which is the
    condition the frozen-pair identity is about.
    """
    g = torch.Generator().manual_seed(seed)
    N = n_legs + n_hubs
    feats = torch.zeros(T, N, F_WIDTH)
    walk = 50.0 + torch.cumsum(
        torch.randn(T, n_legs, generator=g) * 3.0, dim=0).clamp(5, 95)
    if freeze_ladder:
        walk[:, :3] = torch.tensor([40.0, 30.0, 20.0])
    feats[:, :n_legs, SLOT_PRICE] = walk
    feats[:, :n_legs, 4] = 100.0                      # window_volume > 0
    feats[:, n_legs:, SLOT_TYPE] = 1.0                # hub marker
    feats[:, n_legs:, 3] = 4.0                        # legs_total
    mask = torch.ones(T, N, dtype=torch.bool)

    mece = [make_edges([(i, n_legs) for i in range(4)] +
                       [(i, n_legs + 1) for i in range(4, 8)]) for _ in range(T)]
    ladder = [make_edges([(0, 1), (1, 2)]) for _ in range(T)]
    return {"features": feats, "mask": mask,
            "adjacency_by_type": {"mece_leg_to_basket": mece,
                                  "ladder_monotonic": ladder}}


def build_model(embed_dim=8, n_heads=2, max_len=64, horizons=(1, 2)):
    from model.train import STGATBackbone
    from model.forecast_head import ResidualForecastHead
    with quiet():
        m = STGATBackbone(padded_feature_width=F_WIDTH, embed_dim=embed_dim,
                          n_heads=n_heads, max_len=max_len)
    m.fit_standardization(torch.zeros(F_WIDTH), torch.ones(F_WIDTH))
    h = ResidualForecastHead(embed_dim=embed_dim, horizons=list(horizons))
    m.eval(); h.eval()
    return m, h


# ===========================================================================
# 1. CAUSALITY
# ===========================================================================

@check("causality", "no_lookahead_in_temporal_attention",
       "A forecast that can see t+1 is not a forecast. This is the single "
       "failure that would invalidate every number in the report.")
def _c_causality():
    from model.train import true_prices
    ct = synthetic_chunk(T=16)
    m, head = build_model()
    f, mask, adj = ct["features"], ct["mask"], ct["adjacency_by_type"]

    with quiet(), torch.no_grad():
        h_a = m(f, mask, adj)
        f2 = f.clone()
        t0 = 8
        # Detonate the future. Nothing at or before t0 may notice.
        f2[t0 + 1:, :, SLOT_PRICE] = 99.0
        f2[t0 + 1:, :, 1:4] += 500.0
        h_b = m(f2, mask, adj)

    drift_past = float((h_a[:t0 + 1] - h_b[:t0 + 1]).abs().max())
    drift_future = float((h_a[t0 + 1:] - h_b[t0 + 1:]).abs().max())
    assert drift_past == 0.0, (
        f"states at t<={t0} moved by {drift_past:.3e} when only t>{t0} changed: "
        f"the temporal mask leaks the future")
    assert drift_future > 0.0, (
        "perturbing the future changed nothing at all -- the perturbation "
        "never reached the model, so this check proves nothing")
    return f"past drift {drift_past:.1e} (must be 0), future drift {drift_future:.3f} (must be >0)"


@mutation_for("no_lookahead_in_temporal_attention")
def _m_causality():
    """Let every timestep attend to every other, future included.

    The mask is built inline in TemporalAttention.forward as
    torch.tril(...), so the mutation is applied where it is CONSUMED:
    _attend_batch receives an all-True matrix instead.
    """
    import model.temporal_attention as ta
    cls = ta.TemporalAttention
    orig = cls._attend_batch
    cls._attend_batch = lambda self, h, m, pos, causal: orig(
        self, h, m, pos, torch.ones_like(causal))
    try:
        _c_causality()
    finally:
        cls._attend_batch = orig
    return "causal mask replaced by all-ones"


# ===========================================================================
# 2. ARCHITECTURE
# ===========================================================================

@check("architecture", "residual_head_starts_at_persistence",
       "The zero-init residual head is what lets the model be compared to "
       "persistence at all: it must START as persistence exactly.")
def _c_residual_init():
    from model.train import true_prices
    ct = synthetic_chunk(T=12)
    m, head = build_model()
    prices = true_prices(ct["features"])
    with quiet(), torch.no_grad():
        h = m(ct["features"], ct["mask"], ct["adjacency_by_type"])
        pred = head(h, prices)
    dev = float((pred - prices.unsqueeze(-1)).abs().max())
    assert dev == 0.0, (
        f"at initialisation the head deviates from the observed price by "
        f"{dev:.3e}; the final layer is not zero-initialised, so the model "
        f"does not start at the persistence baseline")
    return f"max |pred - price| = {dev:.1e} across all horizons"


@mutation_for("residual_head_starts_at_persistence")
def _m_residual_init():
    """Perturb the head's final layer, as a non-zero init would."""
    from model.forecast_head import ResidualForecastHead
    orig = ResidualForecastHead.forward
    ResidualForecastHead.forward = lambda self, h, base, clamp=False: (
        orig(self, h, base, clamp) + 1e-3)
    try:
        _c_residual_init()
    finally:
        ResidualForecastHead.forward = orig
    return "head offset by 1e-3"


@check("architecture", "ablation_actually_ablates",
       "A --drop-edges run that silently drops nothing produces a complete, "
       "plausible ablation table for an unchanged model. This happened.")
def _c_ablation():
    ct = synthetic_chunk(T=12)
    m, _ = build_model()
    f, mask, adj = ct["features"], ct["mask"], ct["adjacency_by_type"]
    keys = set(adj)
    with quiet(), torch.no_grad():
        full = m(f, mask, adj)
        none_ = m(f, mask, {})
        fake = m(f, mask, {k: v for k, v in adj.items() if k not in {"leg_to_hub"}})
    d_real = float((full - none_).abs().max())
    d_fake = float((full - fake).abs().max())
    assert d_real > 0.0, (
        "removing every edge type changed the backbone output by exactly 0: "
        "the graph is not being read at all")
    assert d_fake == 0.0, (
        "dropping a NON-EXISTENT key changed the output, which is impossible "
        "and means keys are being matched loosely")
    return (f"dropping real edges moves output by {d_real:.3f}; dropping a "
            f"non-existent key moves it by {d_fake:.1e}; keys={sorted(keys)}")


# ===========================================================================
# 3. BASELINES
# ===========================================================================

@check("baselines", "shrinkage_oracle_is_optimal",
       "The oracle is the baseline every headline ratio is quoted against. "
       "If its alpha is not the argmin, the comparison is not what it says.")
def _c_shrink_optimal():
    from model.forecast_objective import _shrinkage_mse
    g = torch.Generator().manual_seed(7)
    x = torch.randn(4000, generator=g)
    y = 0.83 * x + 0.10 * torch.randn(4000, generator=g)
    sxx, sxy, syy, n = float((x * x).sum()), float((x * y).sum()), float((y * y).sum()), x.numel()
    mse, alpha = _shrinkage_mse(sxx, sxy, syy, n)

    grid = torch.linspace(0.0, 2.0, 2001)
    best = min(float(((y - a * x) ** 2).mean()) for a in grid)
    assert mse <= best + 1e-9, (
        f"fitted alpha={alpha:.4f} gives MSE {mse:.8f}, but a grid search "
        f"found {best:.8f}: the closed form is not the minimiser")
    assert abs(alpha - 0.83) < 0.02, (
        f"planted alpha was 0.83, recovered {alpha:.4f}")
    return f"recovered alpha {alpha:.4f} (planted 0.83); MSE {mse:.8f} <= grid best {best:.8f}"


@mutation_for("shrinkage_oracle_is_optimal")
def _m_shrink_optimal():
    """Bias the fitted alpha, as a wrong normalisation would."""
    import model.forecast_objective as fo
    orig = fo._shrinkage_mse
    fo._shrinkage_mse = lambda sxx, sxy, syy, n: (
        (lambda m, a: ((syy - 2 * 0.5 * sxy + 0.5 ** 2 * sxx) / n, 0.5))(*orig(sxx, sxy, syy, n)))
    try:
        _c_shrink_optimal()
    finally:
        fo._shrinkage_mse = orig
    return "alpha forced to 0.5"


@check("baselines", "shrinkage_never_worse_than_persistence",
       "alpha=1 IS persistence and lies inside the feasible set, so the "
       "oracle can never lose to it. If it does, one of them is mis-scored.")
def _c_shrink_dominates():
    from model.forecast_objective import _shrinkage_mse
    g = torch.Generator().manual_seed(11)
    worst = 0.0
    for trial in range(40):
        x = torch.randn(600, generator=g)
        a_true = float(torch.rand(1, generator=g)) * 1.6
        y = a_true * x + 0.4 * torch.randn(600, generator=g)
        sxx, sxy, syy, n = float((x * x).sum()), float((x * y).sum()), float((y * y).sum()), x.numel()
        mse, _ = _shrinkage_mse(sxx, sxy, syy, n)
        persist = float(((y - x) ** 2).mean())
        worst = max(worst, mse - persist)
    assert worst <= 1e-9, (
        f"on at least one draw the shrinkage oracle scored {worst:.3e} WORSE "
        f"than persistence, which is impossible since alpha=1 is available")
    return f"over 40 random draws, max (shrink - persistence) = {worst:.2e}"


@check("baselines", "persistence_is_exactly_zero_on_flat_targets",
       "The whole moved/flat stratification rests on this. If persistence "
       "is not exactly 0 on unchanged prices, the pooled ratio argument "
       "in the report is wrong.")
def _c_persist_flat():
    from model.forecast_objective import MechanismForecastObjective
    from model.train import true_prices
    T, N = 10, 4
    feats = torch.zeros(T, N, F_WIDTH)
    feats[:, :, SLOT_PRICE] = 42.0          # never moves
    mask = torch.ones(T, N, dtype=torch.bool)
    is_ticker = feats[..., SLOT_TYPE] == 0.0
    prices = true_prices(feats)
    obj = MechanismForecastObjective(horizons=[1], w_ladder=0.0, w_mece=0.0)
    pred = prices.unsqueeze(-1) + 0.01      # model is wrong on purpose
    out = obj.compute_loss(pred, prices, mask, is_ticker)
    assert out["persistence"] == 0.0, (
        f"persistence MSE on perfectly flat prices is {out['persistence']:.3e}, "
        f"not exactly 0")
    assert out["loss"].item() > 0, "the deliberately wrong model scored 0 too"
    return f"persistence = {out['persistence']:.1e} on {out['n']:,} flat positions"


# ===========================================================================
# 4. REPORTING
# ===========================================================================

@check("reporting", "training_weight_never_reaches_reported_metric",
       "The mover weight once multiplied the REPORTED persistence baseline "
       "as well as the loss, tripling it and turning a true 1.070x into a "
       "logged 0.996x. It survived three runs.")
def _c_weight_leak():
    from model.forecast_objective import MechanismForecastObjective
    from model.train import true_prices
    ct = synthetic_chunk(T=14, seed=3)
    prices = true_prices(ct["features"])
    mask = ct["mask"]
    is_ticker = ct["features"][..., SLOT_TYPE] == 0.0
    pred = (prices.unsqueeze(-1) + 0.004).expand(-1, -1, 2).contiguous()
    lad = ct["adjacency_by_type"]["ladder_monotonic"]
    mece = ct["adjacency_by_type"]["mece_leg_to_basket"]

    def metrics(w):
        obj = MechanismForecastObjective(horizons=[1, 2], ladder_supervise="weighted",
                                         moved_weight=w, monitor_unweighted=True)
        out = obj.compute_loss(pred, prices, mask, is_ticker,
                               ladder_adj=lad, mece_adj=mece)
        return out["mechanisms"]["ladder"]

    a, b = metrics(1.0), metrics(9.0)
    for field in ("model", "persistence", "n"):
        assert a[field] == b[field], (
            f"reported ladder {field} changed from {a[field]} to {b[field]} when "
            f"--moved-weight went 1 -> 9. The weight belongs to the LOSS only; "
            f"a reported baseline that moves with a training hyper-parameter "
            f"is not a baseline")
    return (f"ladder model/persistence identical at w=1 and w=9 "
            f"({a['persistence']:.6f}, n={a['n']:,})")


@mutation_for("training_weight_never_reaches_reported_metric")
def _m_weight_leak():
    """Reintroduce the historical bug: scale the reported metric by w."""
    import model.forecast_objective as fo
    cls = fo.MechanismForecastObjective
    orig = cls.compute_loss

    def leaky(self, *a, **k):
        out = orig(self, *a, **k)
        w = getattr(self, "moved_weight", 1.0)
        m = out.get("mechanisms", {}).get("ladder")
        if m:
            m["persistence"] *= w
        return out

    cls.compute_loss = leaky
    try:
        _c_weight_leak()
    finally:
        cls.compute_loss = orig
    return "reported persistence scaled by moved_weight"


# ===========================================================================
# 5. ARITHMETIC IDENTITIES
# ===========================================================================

@check("identities", "frozen_ladder_pairs_contribute_zero_persistence",
       "This identity is what overturned the ladder conclusion: a pooled "
       "alpha of 0.99 was untradedness, not dynamics.")
def _c_frozen():
    from model.forecast_objective import MechanismForecastObjective
    from model.train import true_prices
    ct = synthetic_chunk(T=14, seed=5, freeze_ladder=True)
    prices = true_prices(ct["features"])
    is_ticker = ct["features"][..., SLOT_TYPE] == 0.0
    pred = prices.unsqueeze(-1).expand(-1, -1, 1).contiguous()
    obj = MechanismForecastObjective(horizons=[1], w_mece=0.0, monitor_unweighted=True)
    out = obj.compute_loss(pred, prices, ct["mask"], is_ticker,
                           ladder_adj=ct["adjacency_by_type"]["ladder_monotonic"])
    lad = out["mechanisms"]["ladder"]
    assert lad["n"] > 0, "no ladder pairs were scored; the fixture is wrong"
    assert lad["persistence"] == 0.0, (
        f"ladder persistence on pairs whose legs never reprice is "
        f"{lad['persistence']:.3e}, not exactly 0. gap(t+h) == gap(t) must "
        f"hold identically for frozen pairs")
    return f"persistence = {lad['persistence']:.1e} over {lad['n']:,} frozen pair-positions"


@check("identities", "basket_fee_closed_form",
       "The claim that round-trip fees are ~2*0.07*C*(1-1/N) and nearly "
       "price-independent underpins the whole break-even argument.")
def _c_fees():
    from evaluate_mece_forecast_pnl import taker_fee_dollars
    C = 100.0
    for p in (5.0, 27.0, 50.0, 73.0, 95.0):
        want = 0.07 * C * (p / 100.0) * (1 - p / 100.0)
        got = taker_fee_dollars(p, C)
        assert got >= want - 1e-9, f"fee at {p}c is {got}, below the formula {want}"
        assert got - want < 0.01, f"fee at {p}c is {got}, far above the formula {want}"

    worst = 0.0
    for N in (2, 3, 4, 5, 8):
        for skew in (0.0, 0.3, 0.6):
            # float64: sum p(1-p) == 1 - sum p^2 is an EXACT identity, and
            # float32 rounding alone breaks a 1e-9 assertion on it.
            legs = torch.full((N,), 1.0 / N, dtype=torch.float64)
            if N > 1:
                legs[0] += skew * (1 - 1.0 / N)
                legs[1:] -= skew * (1 - 1.0 / N) / (N - 1)
            legs = legs.clamp(0.01, 0.99)
            legs = legs / legs.sum()
            lhs = float((legs * (1 - legs)).sum())
            rhs = 1.0 - float((legs ** 2).sum())
            assert abs(lhs - rhs) < 1e-9, f"sum p(1-p) != 1 - sum p^2 at N={N}"
            worst = max(worst, abs(lhs - (1 - 1.0 / N)))
    assert worst < 0.5, "the (1 - 1/N) approximation is wildly off"
    return (f"per-leg fee matches 0.07*C*p(1-p) at 5 prices; identity "
            f"sum p(1-p) = 1 - sum p^2 exact; max drift from (1-1/N) = {worst:.3f}")


# ===========================================================================
# 6. STATISTICS
# ===========================================================================

@check("statistics", "bootstrap_null_coverage",
       "Two identical strategies must not look different. Under-coverage "
       "here would manufacture significance everywhere in the PnL tables.")
def _c_boot_null():
    from evaluate_mece_forecast_pnl import Book, _gap_bootstrap
    g = torch.Generator().manual_seed(21)
    covered = 0
    trials = 60
    for t in range(trials):
        a, b = Book("a"), Book("b")
        for i in range(400):
            bk = f"basket{i % 40}"
            v = float(torch.randn(1, generator=g)) * 5.0
            a.add(v, 0.0, 0.0, bk)
            b.add(v, 0.0, 0.0, bk)     # identical: the true gap is exactly 0
        _, lo, hi = _gap_bootstrap(a, b, n_boot=400, seed=t)
        if lo <= 0.0 <= hi:
            covered += 1
    rate = covered / trials
    assert rate >= 0.90, (
        f"null coverage {rate:.0%} over {trials} trials, well below 95%: the "
        f"interval is too narrow and every PnL comparison is over-confident")
    return f"null coverage {rate:.0%} over {trials} trials (identical books)"


@check("statistics", "bootstrap_has_power",
       "An interval that never excludes zero would report every real effect "
       "as inconclusive. Coverage alone does not establish usefulness.")
def _c_boot_power():
    from evaluate_mece_forecast_pnl import Book, _gap_bootstrap
    g = torch.Generator().manual_seed(33)
    detected = 0
    trials = 30
    for t in range(trials):
        a, b = Book("a"), Book("b")
        for i in range(400):
            bk = f"basket{i % 40}"
            v = float(torch.randn(1, generator=g)) * 5.0
            a.add(v + 2.0, 0.0, 0.0, bk)      # planted +$2 edge
            b.add(v, 0.0, 0.0, bk)
        _, lo, hi = _gap_bootstrap(a, b, n_boot=400, seed=t)
        if lo > 0.0:
            detected += 1
    rate = detected / trials
    assert rate >= 0.90, (
        f"a planted +$2.00 per-trade edge was detected in only {rate:.0%} of "
        f"{trials} trials")
    return f"planted +$2.00 edge detected in {rate:.0%} of {trials} trials"


@check("statistics", "verdict_is_three_way",
       "An interval entirely below zero is evidence of the OPPOSITE, not an "
       "absence of evidence. The two-branch version has been written twice.")
def _c_verdict():
    from model.run_guards import verdict
    cases = {(-5.04, -2.58): "worse", (0.9, 3.1): "beats",
             (-1.0, 2.0): "inconclusive", (float("nan"), 1.0): "undefined"}
    for (lo, hi), want in cases.items():
        got = verdict(lo, hi)
        assert got == want, f"verdict({lo}, {hi}) = {got!r}, expected {want!r}"
    return "beats / worse / inconclusive / undefined all correct"


@mutation_for("verdict_is_three_way")
def _m_verdict():
    """Reinstate the two-branch verdict that mislabels a negative CI."""
    import model.run_guards as rg
    orig = rg.verdict
    rg.verdict = lambda lo, hi: "beats" if lo > 0 else "inconclusive"
    try:
        _c_verdict()
    finally:
        rg.verdict = orig
    return "two-branch verdict restored"


# ===========================================================================
# 7. SPLITS
# ===========================================================================

@check("splits", "chunks_disjoint_homogeneous_chronological",
       "A chunk straddling a split boundary trains on held-out data. This "
       "is the failure that would invalidate every result at once.")
def _c_splits():
    from model.chunking import build_split_ranges, chunk_ranges
    from model.run_guards import check_split_integrity
    ts = []
    for month in ("2025-05", "2025-06", "2025-07", "2025-08", "2025-09"):
        y, mo = int(month[:4]), int(month[5:])
        ts += [datetime(y, mo, 1) + timedelta(hours=2 * i) for i in range(30)]
    ranges = build_split_ranges(ts)
    chunks = chunk_ranges(ranges, chunk_len=12, min_chunk_len=4)
    check_split_integrity(ts, chunks, verbose=False)

    seen = [0] * len(ts)
    for c in chunks:
        for i in range(c.start, c.end):
            seen[i] += 1
    assert all(v == 1 for v in seen), (
        f"{sum(1 for v in seen if v != 1)} snapshots are covered "
        f"{set(seen) - {1}} times instead of exactly once")
    splits = sorted({c.split for c in chunks})
    return f"{len(chunks)} chunks, every snapshot covered exactly once, splits={splits}"


@mutation_for("chunks_disjoint_homogeneous_chronological")
def _m_splits():
    """Make chunk_ranges emit an overlapping duplicate chunk."""
    import model.chunking as ch
    orig = ch.chunk_ranges

    def broken(ranges, chunk_len, min_chunk_len=1):
        out = orig(ranges, chunk_len, min_chunk_len)
        if len(out) > 1:
            out.append(out[0])          # duplicate coverage
        return out

    ch.chunk_ranges = broken
    try:
        _c_splits()
    finally:
        ch.chunk_ranges = orig
    return "duplicate chunk injected"


@mutation_for("ablation_actually_ablates")
def _m_ablation():
    """Make the backbone ignore the adjacency argument entirely -- the
    shape of the bug where --drop-edges changes nothing."""
    from model.train import STGATBackbone
    orig = STGATBackbone.forward
    STGATBackbone.forward = lambda self, f, mask, adj: orig(self, f, mask, {})
    try:
        _c_ablation()
    finally:
        STGATBackbone.forward = orig
    return "adjacency ignored by the backbone"


@mutation_for("shrinkage_never_worse_than_persistence")
def _m_shrink_dominates():
    """Force a deliberately bad alpha so the oracle can lose to persistence."""
    import model.forecast_objective as fo
    orig = fo._shrinkage_mse

    def bad(sxx, sxy, syy, n):
        a = 1.9
        return ((syy - 2 * a * sxy + a * a * sxx) / n, a)

    fo._shrinkage_mse = bad
    try:
        _c_shrink_dominates()
    finally:
        fo._shrinkage_mse = orig
    return "alpha forced to 1.9"


@mutation_for("persistence_is_exactly_zero_on_flat_targets")
def _m_persist_flat():
    """Contaminate the reported persistence baseline by a hair."""
    import model.forecast_objective as fo
    cls = fo.MechanismForecastObjective
    orig = cls.compute_loss

    def contaminated(self, *a, **k):
        out = orig(self, *a, **k)
        out["persistence"] = out["persistence"] + 1e-12
        return out

    cls.compute_loss = contaminated
    try:
        _c_persist_flat()
    finally:
        cls.compute_loss = orig
    return "persistence offset by 1e-12"


@mutation_for("frozen_ladder_pairs_contribute_zero_persistence")
def _m_frozen():
    """Break the frozen-pair identity in the reported ladder baseline."""
    import model.forecast_objective as fo
    cls = fo.MechanismForecastObjective
    orig = cls.compute_loss

    def contaminated(self, *a, **k):
        out = orig(self, *a, **k)
        m = out.get("mechanisms", {}).get("ladder")
        if m:
            m["persistence"] += 1e-9
        return out

    cls.compute_loss = contaminated
    try:
        _c_frozen()
    finally:
        cls.compute_loss = orig
    return "ladder persistence offset by 1e-9"


@mutation_for("basket_fee_closed_form")
def _m_fees():
    """Use the wrong fee rate, as a mis-transcribed schedule would."""
    import evaluate_mece_forecast_pnl as E
    orig = E.taker_fee_dollars
    E.taker_fee_dollars = lambda p, c: orig(p, c) * 1.5
    try:
        _c_fees()
    finally:
        E.taker_fee_dollars = orig
    return "fee rate inflated 1.5x"


@mutation_for("bootstrap_null_coverage")
def _m_boot_null():
    """Return an interval far too narrow: manufactured significance."""
    import evaluate_mece_forecast_pnl as E
    orig = E._gap_bootstrap
    E._gap_bootstrap = lambda a, b, n_boot=2000, seed=0: (
        (lambda pt, lo, hi: (pt, pt + 0.05, pt + 0.06))(*orig(a, b, n_boot, seed)))
    try:
        _c_boot_null()
    finally:
        E._gap_bootstrap = orig
    return "interval narrowed and shifted off zero"


@mutation_for("bootstrap_has_power")
def _m_boot_power():
    """Return an interval so wide nothing is ever significant."""
    import evaluate_mece_forecast_pnl as E
    orig = E._gap_bootstrap
    E._gap_bootstrap = lambda a, b, n_boot=2000, seed=0: (
        (lambda pt, lo, hi: (pt, -100.0, 100.0))(*orig(a, b, n_boot, seed)))
    try:
        _c_boot_power()
    finally:
        E._gap_bootstrap = orig
    return "interval widened to +/-100"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------

GREEN, RED, YEL, DIM, OFF = "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[0m"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("--self-test", action="store_true",
                    help="also run each check against a planted bug and require "
                         "that it FAILS. A check that cannot fail proves nothing.")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print the measured detail for passing checks too")
    ap.add_argument("--only", default=None, help="substring filter on check names")
    args = ap.parse_args()

    todo = [c for c in CHECKS if not args.only or args.only in c.name]
    if not todo:
        print(f"--only {args.only!r} matched no checks. Available:")
        for c in CHECKS:
            print(f"    [{c.group}] {c.name}")
        sys.exit(2)
    width = max(len(c.name) for c in todo) + 2

    failures, mut_missing, mut_broken = [], [], []
    group = None
    print("=" * 96)
    print("PIPELINE VERIFICATION" + (" (with mutation self-test)" if args.self_test else ""))
    print("=" * 96)

    for c in todo:
        if c.group != group:
            group = c.group
            print(f"\n{group.upper()}")
        try:
            detail = c.fn()
            ok, msg = True, detail
        except AssertionError as e:
            ok, msg = False, str(e).strip()
        except Exception as e:                         # noqa: BLE001
            ok, msg = False, f"{type(e).__name__}: {e}\n" + traceback.format_exc(limit=3)

        tag = f"{GREEN}PASS{OFF}" if ok else f"{RED}FAIL{OFF}"
        print(f"  {tag}  {c.name:<{width}}", end="")
        if not ok:
            failures.append((c, msg))
            print(f"\n        {RED}{msg}{OFF}")
            if c.why:
                print(f"        {DIM}why it matters: {c.why}{OFF}")
        elif args.verbose:
            print(f"\n        {DIM}{msg}{OFF}")
        else:
            print()

        if args.self_test:
            if c.mutation is None:
                mut_missing.append(c.name)
                print(f"        {YEL}no mutation test: this check is unproven{OFF}")
            else:
                try:
                    c.mutation()
                except (AssertionError, SystemExit):
                    # SystemExit is how model/run_guards signals a violation,
                    # so it counts as the check having fired.
                    print(f"        {DIM}mutation caught: the check does fail on a planted bug{OFF}")
                except Exception as e:                 # noqa: BLE001
                    mut_broken.append((c.name, f"{type(e).__name__}: {e}"))
                    print(f"        {YEL}mutation errored: {type(e).__name__}: {e}{OFF}")
                else:
                    mut_broken.append((c.name, "check PASSED under a planted bug"))
                    print(f"        {RED}MUTATION NOT CAUGHT: the check passes even when "
                          f"the thing it tests is broken{OFF}")

    print("\n" + "=" * 96)
    n = len(todo)
    if failures:
        print(f"{RED}{len(failures)} of {n} checks FAILED{OFF}")
        for c, _ in failures:
            print(f"    - {c.name}  [{c.group}]")
    else:
        print(f"{GREEN}all {n} checks passed{OFF}")

    if args.self_test:
        covered = sum(1 for c in todo if c.mutation is not None)
        print(f"mutation coverage: {covered}/{n} checks have a planted-bug counterpart")
        if mut_missing:
            print(f"{YEL}unproven (no mutation): {', '.join(mut_missing)}{OFF}")
            print(f"{DIM}  These checks passed, but nothing shows they CAN fail.{OFF}")
        if mut_broken:
            print(f"{RED}broken mutations:{OFF}")
            for nm, why in mut_broken:
                print(f"    - {nm}: {why}")
    print("=" * 96)

    sys.exit(1 if (failures or mut_broken) else 0)


if __name__ == "__main__":
    main()