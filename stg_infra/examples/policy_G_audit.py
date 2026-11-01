"""Post-test audit of the learned maker policy G (maker pre-registration A12).
Diagnostics only: nothing here changes G or its reported result.

  A. Label timing: training fills (2024-11..2025-05) are labelled by settlement. How many settle AFTER the training
     window, and do test-month (2025-08..11) events appear in the training fills? If so, G's test P&L is re-computed
     on events never seen in training.
  B. Concentration of G's test P&L: by month, category and event (top-10 share, share of events positive).
  C. Random-selection control: post the same share of candidate orders as G, chosen at random (5 seeds),
     in the same simulator. G must beat it for the model's selection to matter.
  D. What G selects: side, price band and spread of its fills vs quote-everything.

    python stg_infra/examples/policy_G_audit.py
"""
import sys, json, collections
import numpy as np
sys.path.insert(0, "stg_infra"); sys.path.insert(0, "stg_infra/examples")
import simulate_maker as s
import maker_policy as mp

TRAIN = mp.TRAIN
TEST = ["2025-08", "2025-09", "2025-10", "2025-11"]
SCORES = "runs/maker/policy_G_scores_2025-08_2025-11.parquet"


def fills(cfg, model, months):
    return dict(np.load(f"runs/maker/cache/{s.cache_key(cfg, model, months)}.fills.npz", allow_pickle=True))


def ev_ret(F, sel=None):
    """Return (% on capital), net $, CI by event, events, fills for a subset of fills."""
    sel = np.ones(len(F["net_c"]), bool) if sel is None else sel
    d = collections.defaultdict(lambda: [0.0, 0.0])
    for e, n, c in zip(F["event"][sel], F["net_c"][sel], F["capital_c"][sel]):
        d[e][0] += n; d[e][1] += c
    A = np.array(list(d.values()))
    if len(A) == 0:
        return np.nan, 0.0, (np.nan, np.nan), 0, 0
    idx = np.random.default_rng(0).integers(0, len(A), size=(4000, len(A)))
    S = A[idx].sum(1)
    r = 100 * S[:, 0] / S[:, 1]
    return 100 * A[:, 0].sum() / A[:, 1].sum(), A[:, 0].sum() / 100, tuple(np.percentile(r, [2.5, 97.5])), len(A), int(sel.sum())


def main():
    import polars as pl
    from diagnose_basket_composition import category_of
    G = s.Config(**{**mp.BROAD, "policy": SCORES, "policy_t": 1.0})
    Fg = fills(G, "pess", TEST)
    Ftr = dict(np.load(f"runs/maker/cache/{mp.BROAD_KEY_DEV}.fills.npz", allow_pickle=True))
    mo_tr = np.array([s.month_of(int(h)) for h in Ftr["hour_ns"]])
    trm = np.isin(mo_tr, TRAIN)
    mk = pl.scan_parquet("data/markets/markets_kalshi/*.parquet").select("event_ticker", "close_time").collect()
    ev_close = dict(mk.group_by("event_ticker").agg(pl.col("close_time").max()).iter_rows())

    print("POST-TEST AUDIT OF LEARNED POLICY G (diagnostics only; G and its reported result are unchanged)")
    base = ev_ret(Fg)
    print(f"\nreference: G test, pessimistic: ret {base[0]:+.2f}%  CI [{base[2][0]:+.2f}, {base[2][1]:+.2f}]  net ${base[1]:+.2f}  events {base[3]}  fills {base[4]}")

    # A. label timing
    tr_events = set(Ftr["event"][trm])
    closes = [ev_close.get(e) for e in tr_events]
    late = [e for e, c in zip(tr_events, closes) if c is not None and c.strftime("%Y-%m") > "2025-05"]
    into_test = [e for e, c in zip(tr_events, closes) if c is not None and c.strftime("%Y-%m") >= "2025-08"]
    n_late_fills = int(np.isin(Ftr["event"][trm], late).sum()); n_test_fills = int(np.isin(Ftr["event"][trm], into_test).sum())
    print("\nA. LABEL TIMING")
    print(f"  training fills: {trm.sum():,} in {len(tr_events):,} events")
    print(f"  events settling after the training window (after 2025-05): {len(late)} ({n_late_fills:,} training fills, {n_late_fills / trm.sum():.2%})")
    print(f"  events settling inside the TEST window (2025-08 or later): {len(into_test)} ({n_test_fills:,} training fills, {n_test_fills / trm.sum():.2%})")
    overlap = set(Fg["event"]) & tr_events
    print(f"  G test events also present in training fills: {len(overlap)} of {len(set(Fg['event']))}")
    if overlap:
        sel = ~np.isin(Fg["event"], list(overlap))
        r = ev_ret(Fg, sel)
        print(f"  G test on events NEVER seen in training: ret {r[0]:+.2f}%  CI [{r[2][0]:+.2f}, {r[2][1]:+.2f}]  net ${r[1]:+.2f}  events {r[3]}  fills {r[4]}")
        for e in sorted(overlap)[:10]:
            print(f"    overlap event: {e}  (closes {ev_close.get(e)})")

    # B. concentration
    print("\nB. CONCENTRATION OF G's TEST P&L")
    mo_g = np.array([s.month_of(int(h)) for h in Fg["hour_ns"]])
    for m in TEST:
        r = ev_ret(Fg, mo_g == m)
        print(f"  {m}: ret {r[0]:+6.2f}%  CI [{r[2][0]:+6.2f}, {r[2][1]:+6.2f}]  net ${r[1]:+9.2f}  events {r[3]:>4}  fills {r[4]:>6,}")
    c = pl.read_parquet("results/data_audit/kalshi_series_categories.parquet")
    lookup = dict(zip(c["series_ticker"].to_list(), c["category"].to_list()))
    cat = np.array([category_of(e.split("-")[0], lookup) for e in Fg["event"]])
    for k in sorted(set(cat), key=lambda k: -abs(Fg["net_c"][cat == k].sum())):
        r = ev_ret(Fg, cat == k)
        print(f"  {k:<22}: ret {r[0]:+6.2f}%  net ${r[1]:+9.2f}  events {r[3]:>4}  fills {r[4]:>6,}")
    by_ev = collections.defaultdict(float)
    for e, n in zip(Fg["event"], Fg["net_c"]):
        by_ev[e] += n
    v = np.array(sorted(by_ev.values(), reverse=True))
    print(f"  top-10 events carry ${v[:10].sum() / 100:+.2f} of ${v.sum() / 100:+.2f} ({v[:10].sum() / v.sum():.0%}); "
          f"events positive: {np.mean(v > 0):.0%}; without the top-10 events: ${v[10:].sum() / 100:+.2f}")

    # C. random-selection control
    print("\nC. RANDOM-SELECTION CONTROL (same share of candidates posted as G, chosen at random)")
    import polars as pl2
    sc = pl2.read_parquet(SCORES)
    share = float((sc["pred"] > 1.0).mean())
    print(f"  G posts {share:.1%} of {sc.height:,} scored candidate orders")
    legs, events, charged = s.load(TEST, "mece")
    keys = list(zip(sc["ticker"].to_list(), sc["hour_ns"].to_list(), sc["side"].to_list()))
    rets = []
    for seed in range(5):
        rng = np.random.default_rng(seed)
        pol = {(k[0], int(k[1]), int(k[2])): (2.0 if u < share else 0.0) for k, u in zip(keys, rng.random(len(keys)))}
        cfg = s.Config(**{**mp.BROAD, "policy": "random", "policy_t": 1.0})
        fl = s.simulate(cfg, "pess", legs, events, charged, TEST, policy_scores=pol)
        r = s.summarise(fl)
        rets.append(r["ret"])
        print(f"  random seed {seed}: ret {r['ret']:+.2f}%  CI [{r['lo']:+.2f}, {r['hi']:+.2f}]  net ${r['net_c'] / 100:+.2f}  fills {r['fills']:,}")
    print(f"  random mean {np.mean(rets):+.2f}%  vs G {base[0]:+.2f}%")

    # D. what G selects
    print("\nD. WHAT G SELECTS (fills, pessimistic, test)")
    Fb = fills(s.Config(**mp.BROAD), "pess", TEST)
    for nm, F in (("quote everything", Fb), ("G", Fg)):
        side, price = F["side"], F["price"]
        fav = price >= 85; long = price <= 15
        print(f"  {nm:<17} sell share {np.mean(side < 0):.0%} | price <=15c {np.mean(long):.0%}, 15-85c {np.mean(~fav & ~long):.0%}, >=85c {np.mean(fav):.0%}")
    for sd, nm in ((1, "buy YES"), (-1, "sell YES")):
        for lo, hi in ((1, 15), (16, 84), (85, 99)):
            sel = (Fg["side"] == sd) & (Fg["price"] >= lo) & (Fg["price"] <= hi)
            if sel.sum():
                r = ev_ret(Fg, sel)
                print(f"    G {nm:<8} {lo:>2}-{hi:<2}c: fills {r[4]:>6,}  ret {r[0]:+6.2f}%  net ${r[1]:+9.2f}")


if __name__ == "__main__":
    main()
