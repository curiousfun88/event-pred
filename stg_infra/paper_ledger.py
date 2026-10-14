"""
paper_ledger.py

LIVE PAPER-TRADING LEDGER (amendment L10) on top of paper_trader's engine.

Each round (hourly, in the producer's quiet minutes) the engine computes every arm's fills from
the live decisions and Kalshi's tape. The ledger then, for each completed hour not yet recorded:
  - appends one entry file  ledger/entries/<stamp>.json  holding that hour's NEW fills per window
    and arm, the events that settled since the previous round with each arm's realised P&L, and
    cumulative realised / unrealised (mark-to-market) / total P&L, capital and return per arm;
  - chains it: entry["prev_hash"] = previous entry's sha256, entry["hash"] = sha256 of the entry;
  - never rewrites an entry. Every round re-verifies all recorded fills against the recomputed
    ones; a mismatch is recorded in the new entry, never repaired.
Hours before the first ledgered hour (the live start S) are replay, kept out of the live totals.

P&L definitions (cents in files, USD in summaries):
  realised    net P&L after fees of live fills in events whose every leg has settled
  unrealised  open (unsettled) live fills marked at the latest mid: side*(mid - price)*qty - fee
  total       realised + unrealised; its change between rounds is the hourly P&L
  capital     capital committed by live fills (simulate_maker.fill_pnl's definition)

USAGE: called by paper_trader.cmd_run(ledger=True); `python stg_infra/paper_ledger.py --self-test`.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

H_NS = 3_600_000_000_000
MAIN_ARMS = ("g2", "rnd2", "cand", "g", "g2p", "rnd2p", "wide3", "liq", "lin2", "mlp2", "g2w1", "g2w2", "g2_sel")


def fill_key(f):
    """Identity of a fill that cannot change after the hour: (event, ticker, side, price, qty, fee, capital, H)."""
    return (str(f[0]), str(f[1]), int(f[2]), int(f[3]), int(f[4]), round(float(f[5]), 6), round(float(f[7]), 6), int(f[9]))


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=float).encode()).hexdigest()


def load_state(d: Path) -> dict:
    p = d / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def recorded_fills(d: Path) -> dict:
    """{(window, arm): set(fill_key)} from every entry written so far."""
    out = {}
    for p in sorted((d / "entries").glob("*.json")):
        e = json.loads(p.read_text())
        for w, arms in e.get("new_fills", {}).items():
            for arm, rows in arms.items():
                out.setdefault((w, arm), set()).update(tuple(r) for r in rows)
    return out


def verify(recorded: dict, fills_by: dict, upto_H: int) -> list:
    """Recorded fills must equal recomputed fills for hours <= upto_H. Returns mismatches (never repairs)."""
    bad = []
    for (w, arm), rec in recorded.items():
        now = {fill_key(f) for f in fills_by.get(w, {}).get(arm, []) if int(f[9]) <= upto_H}
        rec_h = {r for r in rec if r[7] <= upto_H}
        if now != rec_h:
            bad.append({"window": w, "arm": arm, "missing_now": len(rec_h - now), "extra_now": len(now - rec_h)})
    return bad


def pnl_state(live_fills, settled_events: set, mids: dict):
    """Realised, unrealised (cents), capital (cents), settled capital, fills, contracts for one arm's live fills."""
    real = unreal = cap = cap_settled = 0.0
    contracts = 0
    for f in live_fills:
        cap += float(f[7]); contracts += int(f[4])
        if f[0] in settled_events:
            real += float(f[6]); cap_settled += float(f[7])
        else:
            mid = mids.get(f[1])
            unreal += (int(f[2]) * (mid - int(f[3])) * int(f[4]) if mid is not None else 0.0) - float(f[5])
    return {"realised_usd": real / 100, "unrealised_usd": unreal / 100, "total_usd": (real + unreal) / 100,
            "capital_usd": cap / 100, "return_settled_pct": 100 * real / cap_settled if cap_settled else None,
            "fills": len(live_fills), "contracts": contracts}


def write_entry(d: Path, H: int, stamp: str, new_fills: dict, settlements: list, cumulative: dict, verdict: dict,
                verification: list, start_H: int, settled_events: list):
    """Append the entry for hour H and advance the chain. Refuses to overwrite."""
    st = load_state(d)
    (d / "entries").mkdir(parents=True, exist_ok=True)
    p = d / "entries" / f"{stamp}.json"
    if p.exists():
        raise RuntimeError(f"ledger entry {stamp} exists: entries are never rewritten")
    entry = {"H": stamp, "H_ns": H, "live_start": st.get("start_stamp") or stamp, "prev_hash": st.get("head", ""),
             "new_fills": {w: {a: [list(fill_key(f)) for f in fl] for a, fl in arms.items()} for w, arms in new_fills.items()},
             "settlements": settlements, "cumulative": cumulative, "verdict": verdict, "verification": verification}
    entry["hash"] = sha(entry)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, default=float))
    tmp.replace(p)
    st.update({"start_H": st.get("start_H", start_H), "start_stamp": st.get("start_stamp", stamp), "last_H": H,
               "last_stamp": stamp, "head": entry["hash"], "settled_events": sorted(settled_events)})
    (d / "state.json").write_text(json.dumps(st, indent=1))
    return entry


def round_update(d: Path, fills_by: dict, complete_H: int, settled_events: set, mids: dict, stamp_of, verdict_fn):
    """One ledger round. fills_by: {window: {arm: [fill tuples]}} recomputed from the live start or earlier;
    complete_H: latest hour whose window has closed and whose tape exists. Writes one entry per new hour."""
    st = load_state(d)
    start_H = st.get("start_H", complete_H)
    last_H = st.get("last_H", start_H - H_NS)
    rec = recorded_fills(d)
    bad = verify(rec, fills_by, last_H) if rec else []
    prev_settled = set(st.get("settled_events", []))
    written = []
    hours = list(range(last_H + H_NS, complete_H + H_NS, H_NS))
    for i, H in enumerate(hours):
        last = i == len(hours) - 1
        new = {w: {a: [f for f in fl if int(f[9]) == H] for a, fl in arms.items()} for w, arms in fills_by.items()}
        live = {w: {a: [f for f in fl if start_H <= int(f[9]) <= H] for a, fl in arms.items()} for w, arms in fills_by.items()}
        settle_now = settled_events if last else prev_settled
        settlements = []
        if last:
            for ev in sorted(settled_events - prev_settled):
                per = {w: {a: round(sum(float(f[6]) for f in fl if f[0] == ev) / 100, 4) for a, fl in arms.items()
                           if any(f[0] == ev for f in fl)} for w, arms in live.items()}
                if any(per.values()):
                    settlements.append({"event": ev, "realised_usd": per})
        cumulative = {w: {a: pnl_state(fl, settle_now, mids) for a, fl in arms.items()} for w, arms in live.items()}
        verdict = verdict_fn(live, settle_now) if last else {}
        e = write_entry(d, H, stamp_of(H), new, settlements, cumulative, verdict, bad if i == 0 else [], start_H,
                        settle_now)
        written.append(e)
    return written


def fleet_summary(entry: dict, window="primary") -> tuple:
    """(metrics, output) for the Research Fleet post: cumulative P&L of the main arms plus the entry hash."""
    cum = entry["cumulative"].get(window, {})
    met = {}
    for a in MAIN_ARMS:
        if a in cum:
            met[f"{a}_total_usd"] = round(cum[a]["total_usd"], 2)
            met[f"{a}_realised_usd"] = round(cum[a]["realised_usd"], 2)
    v = entry.get("verdict", {})
    for k in ("g2_lo_one_sided", "g2_minus_rnd2_lo_one_sided", "g2_return_settled_pct"):
        if isinstance(v.get(k), (int, float)) and v.get(k) == v.get(k):
            met[k] = round(float(v[k]), 4)
    out = {"H": entry["H"], "live_start": entry["live_start"], "entry_hash": entry["hash"], "prev_hash": entry["prev_hash"],
           "cumulative_primary": cum, "verdict": v, "settlements": len(entry["settlements"]),
           "verification_issues": entry["verification"]}
    return met, out


def post_fleet(entry: dict, pat: str, url="https://lum.id/api/v1/me/fleet/jobs") -> str:
    """Submit the round's summary as a FlowMesh job (Research Fleet stamps created_at). Never raises."""
    try:
        import requests
        met, out = fleet_summary(entry)
        code = (f"import json\nOUT = json.loads({json.dumps(json.dumps(out, default=float))})\n"
                f"MET = json.loads({json.dumps(json.dumps(met))})\n\n\ndef main():\n    return {{'metrics': MET, 'output': OUT}}\n")
        wf = {"apiVersion": "flowmesh/v1", "kind": "Task", "metadata": {"name": f"fwdtest-pnl-{entry['H']}"},
              "spec": {"taskType": "python", "code": code}}
        r = requests.post(url, json={"workflow": json.dumps(wf), "site": "office"},
                          headers={"Authorization": f"Bearer {pat}"}, timeout=60)
        return r.json()["data"]["id"] if r.status_code in (200, 201, 202) else f"error: HTTP {r.status_code}"
    except Exception as e:
        return f"error: {e!r}"[:300]


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    import tempfile
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    H0 = 1_000 * H_NS
    stamp = lambda H: f"h{H // H_NS}"
    # fill tuple: (event, ticker, side, price, qty, fee, net, capital, markout, H)
    f1 = ("E1", "E1-A", 1, 40, 10, 0.0, 600.0, 400.0, 0.0, H0)          # YES bought at 40, settles YES: +600c
    f2 = ("E2", "E2-A", -1, 70, 10, 5.0, -305.0, 300.0, 0.0, H0)         # YES sold at 70, open
    f3 = ("E1", "E1-B", 1, 30, 5, 0.0, -150.0, 150.0, 0.0, H0 + H_NS)    # later hour, settles NO
    vfn = lambda live, settled: {"g2_return_settled_pct": 1.0}
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        fills = {"primary": {"g2": [f1, f2]}}
        w1 = round_update(d, fills, H0, set(), {"E2-A": 60.0}, stamp, vfn)
        e1 = w1[0]
        check("first round starts the live record at the completed hour", e1["live_start"] == "h1000" and e1["prev_hash"] == "")
        c = e1["cumulative"]["primary"]["g2"]
        # unrealised: f1 open at mid None -> -fee 0; f2: -1*(60-70)*10 - 5 = +95c
        check(f"unrealised marks open fills at the mid net of fees (+$0.95, got {c['unrealised_usd']})", abs(c["unrealised_usd"] - 0.95) < 1e-9)
        check("nothing settled -> realised 0, total = unrealised", c["realised_usd"] == 0 and abs(c["total_usd"] - 0.95) < 1e-9)
        fills2 = {"primary": {"g2": [f1, f2, f3]}}
        w2 = round_update(d, fills2, H0 + H_NS, {"E1"}, {"E2-A": 65.0}, stamp, vfn)
        e2 = w2[0]
        check("second entry chains to the first", e2["prev_hash"] == e1["hash"])
        c2 = e2["cumulative"]["primary"]["g2"]
        check(f"settled event E1 realises +6.00 - 1.50 = +$4.50 (got {c2['realised_usd']})", abs(c2["realised_usd"] - 4.5) < 1e-9)
        check("open fill re-marked at the new mid (+$0.45)", abs(c2["unrealised_usd"] - 0.45) < 1e-9)
        check("the settlement is listed once, with the arm's realised P&L",
              e2["settlements"] == [{"event": "E1", "realised_usd": {"primary": {"g2": 4.5}}}])
        check("new fills of an entry are only that hour's", len(e2["new_fills"]["primary"]["g2"]) == 1)
        check("no verification issues when recomputed fills match", e2["verification"] == [])
        try:
            write_entry(d, H0, "h1000", {}, [], {}, {}, [], H0, [])
            refused = False
        except RuntimeError:
            refused = True
        check("an existing entry is never rewritten", refused)
        f1b = f1[:3] + (41,) + f1[4:]                                     # history changed: different price
        w3 = round_update(d, {"primary": {"g2": [f1b, f2, f3]}}, H0 + 2 * H_NS, {"E1"}, {"E2-A": 65.0}, stamp, vfn)
        check("a changed historical fill is flagged in the next entry, not repaired",
              w3[0]["verification"] and w3[0]["verification"][0]["arm"] == "g2"
              and json.loads((d / "entries" / "h1000.json").read_text())["hash"] == e1["hash"])
        w4 = round_update(d, {"primary": {"g2": [f1, f2, f3]}}, H0 + 5 * H_NS, {"E1"}, {}, stamp, vfn)
        check("missed rounds are caught up one entry per hour, in order",
              [e["H"] for e in w4] == ["h1003", "h1004", "h1005"] and w4[0]["prev_hash"] == w3[-1]["hash"])
        check("replay hours before the live start never enter the live totals",
              round_update(Path(td) / "x", {"primary": {"g2": [f1, f3]}}, H0 + H_NS, set(), {}, stamp, vfn)[0]
              ["cumulative"]["primary"]["g2"]["fills"] == 1)
        met, out = fleet_summary(w4[-1])
        check("fleet summary carries cumulative metrics and the entry hash",
              "g2_total_usd" in met and out["entry_hash"] == w4[-1]["hash"])
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    print(__doc__)
