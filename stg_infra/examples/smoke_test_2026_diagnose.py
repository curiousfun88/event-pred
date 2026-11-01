# smoke_test_2026_diagnose.py -- exploratory diagnosis (2026-10-06) of why policy G earns on 2025-08..11 but not
# 2026-09-07..10-04. Analysis only: composes self-tested pieces (simulate_maker, maker_policy, smoke_test_2026).
# Output: logs/v2_forecast/smoke_test_2026_diagnosis.log.  Run from repo root, memory-capped.
"""Exploratory diagnosis: why policy G earns in Aug-Nov 2025 but not Sep 2026. Same simulator, pessimistic fills."""
import sys, pickle, collections, datetime as dt, numpy as np, polars as pl
sys.path.insert(0, "stg_infra"); sys.path.insert(0, "stg_infra/examples")
import simulate_maker as s, maker_policy as mp, live_signal_producer as lp, smoke_test_2026 as st
from policy_G_audit import fills as cached_fills, ev_ret, TEST, SCORES

WEATHER = {"KXHIGHAUS","KXHIGHCHI","KXHIGHDEN","KXHIGHLAX","KXHIGHMIA","KXHIGHNY","KXHIGHPHIL"}
ser = lambda e: e.split("-")[0]
def grp(x):
    return "weather" if x in WEATHER else ("index" if x in ("KXINX","KXNASDAQ100") else
           ("football" if x.endswith("GAME") else "other"))

# ---------- 2025 test: fills + predictions
G25 = cached_fills(s.Config(**{**mp.BROAD, "policy": SCORES, "policy_t": 1.0}), "pess", TEST)
A25 = cached_fills(s.Config(**mp.BROAD), "pess", TEST)
sc = pl.read_parquet(SCORES); P25 = {(t, h, sd): p for t, h, sd, p in sc.iter_rows()}
share25 = float((sc["pred"] > 1).mean())

# ---------- 2026: rebuild from the smoke-test cache
start = int(dt.datetime(2026, 9, 7, tzinfo=dt.timezone.utc).timestamp()) * 10**9
end = int(dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc).timestamp()) * 10**9
cache = lp.load_state("series.pkl", {})
raw = {}
for f in sorted(st.CACHE.glob(f"*_{start}_{end}.pkl")):
    x = f.name.split("_")[0]
    if x not in ("KXDOGE", "KXETH"): raw[x] = pickle.loads(f.read_bytes())
legs, events, charged = st.build(raw, {x: cache[x]["fee_type"] for x in raw})
months = ["2026-09", "2026-10"]
blob = pickle.loads(mp.model_path("G").read_bytes()); lookup = mp.category_lookup()
cand = []; s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months, record=cand)
cand = [c for c in cand if start <= int(c[2]) < end]
rows, keys = [], []
for ev, tk, H, sd, pr, b, a in cand:
    r = mp.quote_features(legs, events, charged, lookup, s.month_of(int(H)), ev, tk, int(H), int(sd), int(pr))
    if r is not None: rows.append(r); keys.append((tk, int(H), int(sd)))
pred = blob["model"].predict(mp.to_matrix(rows, blob["cats"])); P26 = dict(zip(keys, pred))
win = lambda fl: [f for f in fl if start <= int(f[9]) < end]
G26 = win(s.simulate(s.Config(**{**mp.BROAD, "policy": "x", "policy_t": 1.0}), "pess", legs, events, charged, months, policy_scores=P26))
A26 = win(s.simulate(s.Config(**mp.BROAD), "pess", legs, events, charged, months))
def arr(fl):
    return {k: np.array([f[i] for f in fl], dtype=object if k in ("event","ticker") else float)
            for i, k in enumerate(["event","ticker","side","price","qty","fee_c","net_c","capital_c","markout_c","hour_ns"])}
G26, A26 = arr(G26), arr(A26)

def r(F, sel=None):
    x = ev_ret(F, sel); return f"{x[0]:+6.2f}% [{x[2][0]:+6.2f},{x[2][1]:+6.2f}] fills {x[4]:>6,} ev {x[3]:>4}"

print("=" * 100); print("1. COMPOSITION AND PER-GROUP RETURNS (pessimistic): G and quote-everything (ALL)")
for nm, G, A in (("2025 Aug-Nov", G25, A25), ("2026 Sep 7-Oct 4", G26, A26)):
    gs = np.array([grp(ser(e)) for e in G["event"]]); as_ = np.array([grp(ser(e)) for e in A["event"]])
    print(f" {nm}:  G {r(G)}   ALL {r(A)}")
    for g in ("weather","index","football","other"):
        print(f"    {g:<9} G share of fills {np.mean(gs==g):5.1%}  G {r(G, gs==g)}   ALL {r(A, as_==g)}")

print("=" * 100); print("2. SEASONALITY: weather by month, 2025 (G / ALL)")
for F, nm in ((G25, "G"), (A25, "ALL")):
    mo = np.array([s.month_of(int(h)) for h in F["hour_ns"]]); w = np.array([ser(e) in WEATHER for e in F["event"]])
    print("   " + nm + ": " + " | ".join(f"{m} {ev_ret(F, w & (mo==m))[0]:+.2f}%" for m in TEST))

print("=" * 100); print("3. MARKET HARDER? quote-everything fills, by group")
for nm, A in (("2025", A25), ("2026", A26)):
    g = np.array([grp(ser(e)) for e in A["event"]])
    for gg in ("weather", "index", "all"):
        w = (g == gg) if gg != "all" else np.ones(len(g), bool)
        q = A["qty"][w]; mk = A["markout_c"][w].astype(float); ok = ~np.isnan(mk)
        print(f"   {nm} {gg:<8} fills/event {w.sum()/max(len(set(A['event'][w])),1):6.1f}  net c/contract {A['net_c'][w].sum()/q.sum():+.2f}  "
              f"markout c/contract {(mk[ok]).sum()/q[ok].sum():+.2f}  fee c/contract {A['fee_c'][w].sum()/q.sum():.2f}  "
              f"sell share {np.mean(A['side'][w]<0):.0%}  price<=15c {np.mean(A['price'][w]<=15):.0%}  >=85c {np.mean(A['price'][w]>=85):.0%}")
print("=" * 100); print("4. DOES THE RANKING STILL WORK? quote-everything fills by G-prediction decile: realised net c/contract")
for nm, A, P in (("2025", A25, P25), ("2026", A26, P26)):
    p = np.array([P.get((t, int(h), int(sd)), np.nan) for t, h, sd in zip(A["ticker"], A["hour_ns"], A["side"])], float)
    y = A["net_c"] / A["qty"]; ok = ~np.isnan(p)
    qs = np.quantile(p[ok], np.linspace(0, 1, 11))
    d = np.clip(np.searchsorted(qs, p[ok], side="right") - 1, 0, 9)
    print(f"   {nm} (matched {ok.mean():.0%}): " + " ".join(f"{y[ok][d==i].mean():+.1f}" for i in range(10))
          + f"   corr(pred, y) {np.corrcoef(p[ok], y[ok])[0,1]:+.3f}")
    print(f"        mean pred by decile:  " + " ".join(f"{p[ok][d==i].mean():+.1f}" for i in range(10)))

print("=" * 100); print("5. INPUT SHIFT: candidate features, 2026 vs 2025-09 (weather and all)")
legs5, events5, charged5 = s.load(["2025-09"], "mece")
c5 = []; s.simulate(s.Config(**mp.BROAD), "pess", legs5, events5, charged5, ["2025-09"], record=c5)
rows5 = []
for ev, tk, H, sd, pr, b, a in c5:
    x = mp.quote_features(legs5, events5, charged5, lookup, "2025-09", ev, tk, int(H), int(sd), int(pr))
    if x is not None: rows5.append(x)
p5 = blob["model"].predict(mp.to_matrix(rows5, blob["cats"]))
F = ["spread", "mid", "rel_price", "trades_24h", "dmid_24h", "n_legs", "n_quoted", "basket_sum", "charged"]
for nm, R, P in (("2025-09", rows5, p5), ("2026-09/10", rows, pred)):
    for gg in ("weather", "all"):
        idx = [i for i, x in enumerate(R) if gg == "all" or (x["cat"] == "Climate and Weather")]
        if not idx: continue
        M = np.array([[R[i][f] for f in F] for i in idx], float); pp = P[idx]
        med = " ".join(f"{f}={np.nanmedian(M[:, k]):.1f}" for k, f in enumerate(F))
        print(f"   {nm:<11} {gg:<8} n={len(idx):>7,} selected {np.mean(pp > 1):.0%}  median: {med}")
        print(f"   {'':<11} {'':<8} spread share 2c {np.mean(M[:,0]==2):.0%} 3-5c {np.mean((M[:,0]>=3)&(M[:,0]<=5)):.0%} 6c+ {np.mean(M[:,0]>=6):.0%}"
              f" | trades_24h=0 {np.mean(M[:,3]==0):.0%} | dmid missing {np.mean(np.isnan(M[:,4])):.0%}")
