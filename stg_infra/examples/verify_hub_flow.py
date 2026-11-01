"""
verify_hub_flow.py

Checks two properties of the one-spatial-layer STGAT, used to describe it in the report (Chapter 5):

  A. In the MECE channel, every edge whose target is a LEG has attention weight exactly 1 in every head: a leg's
     only basket neighbour is its hub.
  B. The hub's updated representation never reaches a leg's forecast: replacing every hub row of the spatial
     layer's output with random noise leaves every leg's forecast bit-identical. Positive control: the same noise
     on one leg's row changes that leg's forecast.

    python stg_infra/examples/verify_hub_flow.py --self-test     # synthetic graph, random weights
    python stg_infra/examples/verify_hub_flow.py --checkpoint runs/tune/final_d32_h4_lr0.001_do0_wm1_q0_wmid1_s0/best.pt
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import torch

_THIS = Path(__file__).resolve()
sys.path.insert(0, str(_THIS.parents[1]))
sys.path.insert(0, str(_THIS.parent))
REPO = _THIS.parents[2]


def leg_attention(model, features, mask, adj, t):
    """Attention weights of MECE edges into leg nodes at snapshot t: (alphas into legs, alphas into hubs)."""
    from model.sparse_utils import to_local_edge_index
    with torch.no_grad():
        h0 = model.projection(model.standardize(features))
    active = mask[t].nonzero(as_tuple=True)[0]
    parts = [to_local_edge_index(adj[k][t].edge_index, active)
             for k in ("mece_leg_to_basket", "mece_basket_to_leg") if adj.get(k) and adj[k][t].edge_index.numel()]
    if not parts:
        return None, None
    ei = torch.cat(parts, dim=1)
    with torch.no_grad():
        _, (ei_att, alpha) = model.spatial.mece_conv(h0[t, active], ei, return_attention_weights=True)
    is_hub = features[t, active, -1] > 0.5
    tgt = ei_att[1]
    return alpha[~is_hub[tgt]], alpha[is_hub[tgt]]


def forecasts(model, head, features, mask, adj, noise_rows=None, seed=0):
    """Leg forecasts (T, N, H); optionally replace the spatial output at noise_rows (a (T, N) bool) with noise."""
    from model.train import true_prices
    handle = None
    if noise_rows is not None:
        g = torch.Generator().manual_seed(seed)

        def hook(_m, _inp, out):
            out = out.clone()
            out[noise_rows] = torch.randn(int(noise_rows.sum()), out.shape[-1], generator=g) * 5.0
            return out
        handle = model.spatial.register_forward_hook(hook)
    try:
        with torch.no_grad():
            return head(model(features, mask, adj), true_prices(features))
    finally:
        if handle:
            handle.remove()


def run_checks(model, head, features, mask, adj, say=print) -> bool:
    T = features.shape[0]
    is_hub = (features[..., -1] > 0.5) & mask
    is_leg = (features[..., -1] < 0.5) & mask
    ok = True
    # A
    n_leg_edges = n_hub_edges = 0
    max_dev = 0.0
    hub_non_one = 0
    for t in range(T):
        a_leg, a_hub = leg_attention(model, features, mask, adj, t)
        if a_leg is None:
            continue
        n_leg_edges += a_leg.shape[0]
        n_hub_edges += a_hub.shape[0]
        if a_leg.numel():
            max_dev = max(max_dev, float((a_leg - 1.0).abs().max()))
        hub_non_one += int((a_hub < 1 - 1e-6).any(dim=1).sum())
    a_ok = n_leg_edges > 0 and max_dev < 1e-6
    say(f"  A. MECE edges into legs: {n_leg_edges:,}, max |alpha - 1| = {max_dev:.2e} -> {'PASS' if a_ok else 'FAIL'}")
    say(f"     (edges into hubs: {n_hub_edges:,}, of which {hub_non_one:,} have some head with alpha < 1: "
        f"the hub's attention is genuinely spread over its legs)")
    ok &= a_ok
    # B
    base = forecasts(model, head, features, mask, adj)
    hub_noise = forecasts(model, head, features, mask, adj, noise_rows=is_hub)
    leg_diff = float((hub_noise - base)[is_leg].abs().max())
    hub_diff = float((hub_noise - base)[is_hub].abs().max()) if is_hub.any() else 0.0
    b_ok = leg_diff == 0.0 and hub_diff > 0.0
    say(f"  B. noise on every hub row after the spatial layer: max change in a LEG forecast = {leg_diff:.3g} "
        f"(over {int(is_leg.sum()):,} leg-snapshots), in a hub's own output = {hub_diff:.3g} -> {'PASS' if b_ok else 'FAIL'}")
    ok &= b_ok
    # control
    t_c, n_c = [int(x) for x in is_leg.nonzero()[0]]
    one = torch.zeros_like(is_leg)
    one[t_c, n_c] = True
    ctrl = forecasts(model, head, features, mask, adj, noise_rows=one)
    c_diff = float((ctrl - base)[t_c, n_c].abs().max())
    c_ok = c_diff > 0.0
    say(f"  control: the same noise on one LEG row changes that leg's forecast by {c_diff:.3g} -> "
        f"{'PASS (the test can detect an effect)' if c_ok else 'FAIL'}")
    return ok & c_ok


def synthetic():
    """Two snapshots, one basket (hub + 3 legs) and a 2-leg ladder, random features."""
    from model.train import STGATBackbone
    from model.forecast_head import ResidualForecastHead

    class E:
        def __init__(self, ei, n_feat=2):
            self.edge_index = torch.tensor(ei, dtype=torch.long).reshape(2, -1)
            self.weight = torch.ones(self.edge_index.shape[1])
            self.features = torch.zeros(self.edge_index.shape[1], n_feat)
    T, N, F = 2, 6, 10
    torch.manual_seed(0)
    x = torch.rand(T, N, F)
    x[..., -1] = 0.0
    x[:, 0, -1] = 1.0                          # node 0 = hub; 1-3 basket legs; 4-5 ladder legs
    mask = torch.ones(T, N, dtype=torch.bool)
    adj = {"mece_leg_to_basket": [E([[1, 2, 3], [0, 0, 0]])] * T,
           "mece_basket_to_leg": [E([[0, 0, 0], [1, 2, 3]])] * T,
           "ladder_monotonic": [E([[4], [5]])] * T}
    model = STGATBackbone(padded_feature_width=F, embed_dim=8, n_heads=2, max_len=8)
    head = ResidualForecastHead(embed_dim=8, horizons=(1, 2))
    torch.nn.init.normal_(head.net[-1].weight)  # non-zero head, so forecasts depend on the representation
    model.eval(); head.eval()
    return model, head, x, mask, adj


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--checkpoint")
    ap.add_argument("--cache", default="cache_724")
    ap.add_argument("--months", nargs="+", default=["2025-08"])
    a = ap.parse_args()
    if a.self_test:
        print("SELF-TEST (synthetic graph, random weights)")
        ok = run_checks(*synthetic())
        print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
        sys.exit(0 if ok else 1)
    from data_windows import set_split
    from model.chunking import build_split_ranges, chunk_ranges
    from model.month_store import MonthlyBundleStore, build_month_paths
    from model.train import STGATBackbone
    from model.forecast_head import ResidualForecastHead
    ck = torch.load(REPO / a.checkpoint, weights_only=False, map_location="cpu")
    if ck.get("split"):
        set_split(*ck["split"])
    cfg = ck["config"]
    store = MonthlyBundleStore(build_month_paths(a.months, REPO / a.cache), verbose=False,
                               exclude_prefixes=["KXMVE"])
    chunk = [c for c in chunk_ranges(build_split_ranges(store.timestamps), chunk_len=cfg.chunk_len, min_chunk_len=4)
             if c.split == "test"][0]
    ct = store.materialize_chunk(chunk)
    model = STGATBackbone(padded_feature_width=store.feature_width,
                          zero_input_slots=getattr(cfg, "zero_input_slots", ()),
                          zero_ladder_edge_features=getattr(cfg, "zero_ladder_edge_features", False),
                          embed_dim=cfg.embed_dim, n_heads=cfg.n_heads, max_len=cfg.chunk_len)
    model.load_state_dict(ck["model"], strict=True)
    head = ResidualForecastHead(embed_dim=cfg.embed_dim, horizons=ck.get("horizons") or [1, 2, 3, 6, 12])
    head.load_state_dict(ck["head"], strict=True)
    model.eval(); head.eval()
    print(f"checkpoint {a.checkpoint} (epoch {ck.get('epoch')}), test chunk of {a.months}: "
          f"T={ct['features'].shape[0]} snapshots, N={ct['features'].shape[1]} nodes")
    ok = run_checks(model, head, ct["features"], ct["mask"], ct["adjacency_by_type"])
    print("ALL CHECKS PASSED" if ok else "SOME CHECK FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
