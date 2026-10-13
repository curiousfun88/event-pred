"""
extract_a13_legs.py

COMPACT 2024-11..2025-11 LEGS FOR THE 23 A13 SERIES, so G2-W3's training rows (and
lin2, amendment L3) can be rebuilt on a Lumid sandbox without the 4.6 GB raw archive.

For each local month it runs retrain_g2.local_legs(month, SERIES_A13) -- the exact
loader G2-W3 was trained from -- and pickles (legs, events, charged table) to
runs/maker/a13_local/<month>.pkl. The fee closure is stored as a table
{(series, month): bool} over the 23 series; local months only ever call it with
their own month. retrain_g2.local_legs reads these files when A13_LOCAL_DIR is set.

USAGE (from repo root, one capped pass on the laptop):
    python stg_infra/examples/extract_a13_legs.py --self-test
    systemd-run --user --scope -p CPUQuota=50% -p MemoryMax=5800M nice -n 10 \
        .venv/bin/python stg_infra/examples/extract_a13_legs.py
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import pickle
import sys
from pathlib import Path

import numpy as np

_THIS = Path(__file__).resolve().parent
_REPO = _THIS.parents[1]
sys.path.insert(0, str(_REPO / "stg_infra"))
sys.path.insert(0, str(_THIS))

OUT = _REPO / "runs/maker/a13_local"


def charged_table(charged, series, months):
    return {(s_, m): bool(charged(s_, m)) for s_ in series for m in months}


def save(path, legs, events, table):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(pickle.dumps({"legs": legs, "events": events, "charged": table}, protocol=5))
    tmp.replace(path)
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def load(path):
    d = pickle.loads(Path(path).read_bytes())
    table = d["charged"]
    return d["legs"], d["events"], lambda series, month: table[(series, month)]   # KeyError, never a silent default


def summary(legs, events):
    return {"legs": len(legs), "events": len(events), "quote_rows": int(sum(len(L["e"]) for L in legs.values())),
            "trades": int(sum(len(L["tt"]) for L in legs.values()))}


def main_extract(months):
    import retrain_g2 as rg
    from fetch_kalshi_api_months import SERIES_A13
    man = {}
    for mo in months:
        legs, events, charged = rg.local_legs(mo, SERIES_A13)
        sha = save(OUT / f"{mo}.pkl", legs, events, charged_table(charged, SERIES_A13, [mo]))
        man[mo] = {**summary(legs, events), "sha1": sha}
        print(json.dumps({mo: man[mo]}), flush=True)
        del legs, events, charged
        gc.collect()
    p = OUT / "manifest.json"
    old = json.loads(p.read_text()) if p.exists() else {}
    p.write_text(json.dumps({**old, **man}, indent=1))


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    import tempfile
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    e = np.array([10, 20], np.int64)
    legs = {"A-1": {"event": "A", "series": "A", "yes": True, "close": 30, "e": e, "bid": np.array([0.4, np.nan]),
                    "ask": np.array([0.45, 0.5]), "tt": np.array([15], np.int64), "tp": np.array([0.41]),
                    "tc": np.array([3]), "ts": np.array([-1])},
            "A-2": {"event": "A", "series": "A", "yes": False, "close": None, "e": e[:1], "bid": np.array([0.5]),
                    "ask": np.array([0.6]), "tt": np.empty(0, np.int64), "tp": np.empty(0), "tc": np.empty(0),
                    "ts": np.empty(0)}}
    events = {"A": ["A-1", "A-2"]}
    fee = lambda s_, m: s_ == "A" and m >= "2025-03"
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "2025-03.pkl"
        save(p, legs, events, charged_table(fee, ["A", "B"], ["2025-02", "2025-03"]))
        L2, E2, ch = load(p)
        check("events round-trip", E2 == events)
        check("arrays round-trip exactly (NaN and dtypes kept)",
              all(np.array_equal(legs[t][k], L2[t][k], equal_nan=True) and legs[t][k].dtype == L2[t][k].dtype
                  for t in legs for k in ("e", "bid", "ask", "tt", "tp", "tc", "ts")))
        check("scalars round-trip (close None kept)", all(legs[t][k] == L2[t][k] for t in legs
                                                          for k in ("event", "series", "yes", "close")))
        check("fee table reproduces the closure", [ch("A", "2025-02"), ch("A", "2025-03"), ch("B", "2025-03")]
              == [False, True, False])
        try:
            ch("C", "2025-03"); miss = False
        except KeyError:
            miss = True
        check("unknown (series, month) raises, never defaults", miss)
        check("summary counts", summary(legs, events) == {"legs": 2, "events": 1, "quote_rows": 3, "trades": 1})
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    import retrain_g2 as rg
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--months", nargs="*", default=rg.LOCAL)
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    main_extract(a.months)


if __name__ == "__main__":
    main()
