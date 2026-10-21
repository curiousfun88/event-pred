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


MAIN_FROM_STAMP = "20261016T17"     # L18: the main result counts quoting hours from here
MAIN_FROM_NS = 1792170000 * 10**9    # 2026-10-16 17:00 UTC


def in_main(f) -> bool:
    """L18 main result: a fill on one of the 23 backtested series, quoted from MAIN_FROM on."""
    from fetch_kalshi_api_months import SERIES_A13
    return int(f[9]) >= MAIN_FROM_NS and str(f[0]).split("-")[0] in set(SERIES_A13)


def fill_key(f):
    """Identity of a fill that cannot change after the hour: (event, ticker, side, price, qty, fee, capital, H)."""
    return (str(f[0]), str(f[1]), int(f[2]), int(f[3]), int(f[4]), round(float(f[5]), 6), round(float(f[7]), 6), int(f[9]))


def sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=float).encode()).hexdigest()


def load_state(d: Path) -> dict:
    p = d / "state.json"
    return json.loads(p.read_text()) if p.exists() else {}


def recorded_fills(d: Path) -> dict:
    """{(window, arm): [fill_key, ...]} from every entry written so far. A LIST, not a set: one order filled by
    several trades in its hour gives identical keys, each a real fill (L20; a set kept one of them)."""
    out = {}
    for p in sorted((d / "entries").glob("*.json")):
        e = json.loads(p.read_text())
        for w, arms in e.get("new_fills", {}).items():
            for arm, rows in arms.items():
                out.setdefault((w, arm), []).extend(tuple(r) for r in rows)
    return out


def arm_since(d: Path) -> dict:
    """{(window, arm): H_ns of the first entry that records the arm} (an arm added mid-test, L17, starts later)."""
    out = {}
    for p in sorted((d / "entries").glob("*.json")):
        e = json.loads(p.read_text())
        for w, arms in e.get("new_fills", {}).items():
            for arm in arms:
                out.setdefault((w, arm), int(e["H_ns"]))
    return out


def verify(recorded: dict, fills_by: dict, upto_H: int, events=None, start_H=None, since=None) -> list:
    """Recorded fills must equal recomputed fills for hours in [start_H, upto_H], for the events recomputed this
    round (`events`; None = all). Hours before start_H are never recorded (reference only), so they are not
    compared (2026-10-15 fix: they were, and every pre-start fill showed as 'extra'). Returns mismatches."""
    from collections import Counter
    bad = []
    lo0 = start_H if start_H is not None else -1
    for (w, arm), rec in recorded.items():
        lo = max(lo0, (since or {}).get((w, arm), lo0))     # 2026-10-16: an arm is compared from the hour it joined
        now = Counter(fill_key(f) for f in fills_by.get(w, {}).get(arm, []) if lo <= int(f[9]) <= upto_H)
        rec_h = Counter(r for r in rec if r[7] <= upto_H and (events is None or r[0] in events))
        if now != rec_h:                                     # L20: counts compared too, not only distinct keys
            bad.append({"window": w, "arm": arm, "missing_now": sum((rec_h - now).values()),
                        "extra_now": sum((now - rec_h).values())})
    return bad


def as_fill(key, result):
    """Fill tuple (simulator layout) from a ledger key and its leg's settlement result ('yes'/'no'/None):
    net = simulate_maker.fill_pnl's gross minus fee; unsettled legs carry net 0 (only marked, never realised)."""
    ev, tk, side, price, qty, fee, cap, H = key
    if result in ("yes", "no"):
        pay = 100 if result == "yes" else 0
        gross = (pay - price) * qty if side > 0 else (price - pay) * qty
        net = gross - fee
    else:
        net = 0.0
    return (ev, tk, side, price, qty, fee, float(net), cap, float("nan"), H)


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
                verification: list, start_H: int, settled_events: list, main_result: dict = None):
    """Append the entry for hour H and advance the chain. Refuses to overwrite."""
    st = load_state(d)
    (d / "entries").mkdir(parents=True, exist_ok=True)
    p = d / "entries" / f"{stamp}.json"
    if p.exists():
        raise RuntimeError(f"ledger entry {stamp} exists: entries are never rewritten")
    entry = {"H": stamp, "H_ns": H, "live_start": st.get("start_stamp") or stamp, "prev_hash": st.get("head", ""),
             "new_fills": {w: {a: [list(fill_key(f)) for f in fl] for a, fl in arms.items()} for w, arms in new_fills.items()},
             "settlements": settlements, "cumulative": cumulative, "verdict": verdict, "verification": verification}
    if main_result is not None:      # L18: the main result (23 series, hours from MAIN_FROM), primary window
        entry["main_result_l18"] = {"universe": "train23", "from": MAIN_FROM_STAMP, "cumulative": main_result}
    entry["hash"] = sha(entry)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(entry, default=float))
    tmp.replace(p)
    st.update({"start_H": st.get("start_H", start_H), "start_stamp": st.get("start_stamp", stamp), "last_H": H,
               "last_stamp": stamp, "head": entry["hash"], "settled_events": sorted(settled_events)})
    tmp_st = d / "state.json.tmp"                    # atomic: a sandbox deleted mid-write never leaves a torn state
    tmp_st.write_text(json.dumps(st, indent=1)); tmp_st.replace(d / "state.json")
    return entry


def round_update(d: Path, fills_by: dict, complete_H: int, settled_events: set, mids: dict, stamp_of, verdict_fn,
                 results=None, events=None):
    """One ledger round. fills_by: {window: {arm: [fill tuples]}} recomputed this round for `events` (None = every
    event); complete_H: latest hour whose window has closed and whose tape exists; results: {ticker: 'yes'/'no'/None}.
    Cumulative figures come from the ledger's own recorded fills plus this round's new hours, valued with `results`,
    so events no longer recomputed still realise their P&L when they settle. Writes one entry per new hour."""
    st = load_state(d)
    start_H = st.get("start_H", complete_H)
    last_H = st.get("last_H", start_H - H_NS)
    rec = recorded_fills(d)
    bad = verify(rec, fills_by, last_H, events, start_H, arm_since(d)) if rec else []
    prev_settled = set(st.get("settled_events", []))
    res = results or {}
    value = lambda key: as_fill(key, res.get(key[1]))
    keys = {(w, a) for w, arms in fills_by.items() for a in arms} | set(rec)
    written = []
    hours = list(range(last_H + H_NS, complete_H + H_NS, H_NS))
    for i, H in enumerate(hours):
        last = i == len(hours) - 1
        new = {w: {a: [f for f in fl if int(f[9]) == H] for a, fl in arms.items()} for w, arms in fills_by.items()}
        live = {}
        for w, a in keys:
            old = [value(k) for k in rec.get((w, a), ()) if start_H <= k[7] <= last_H]
            fresh = [value(fill_key(f)) for f in fills_by.get(w, {}).get(a, []) if last_H < int(f[9]) <= H and int(f[9]) >= start_H]
            live.setdefault(w, {})[a] = old + fresh
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
        main = {a: pnl_state([f for f in fl if in_main(f)], settle_now, mids) for a, fl in live.get("primary", {}).items()}
        e = write_entry(d, H, stamp_of(H), new, settlements, cumulative, verdict, bad if i == 0 else [], start_H,
                        settle_now, main)
        written.append(e)
        for w, arms in new.items():                         # this hour is now recorded
            for a, fl in arms.items():
                rec.setdefault((w, a), []).extend(fill_key(f) for f in fl)
        last_H = H
    return written


def recount_curve(keys_by: dict, hours, results: dict, settled_at: dict, mid_tab: dict, start_H: int,
                  keep=None, lag=2 * H_NS) -> dict:
    """L20: cumulative P&L per hour recomputed from the recorded fill keys (every repeat counted), instead of the
    figures stored in the entries. Hour H is valued as the ledger round for H normally runs, at the end of hour H+1:
    fills quoted in [start_H, H]; realised = events settled by H + lag; open fills marked at the ticker's latest
    logged mid at or before H (none: -fee), as in pnl_state. keys_by: {(window, arm): [key]}; mid_tab: {(ticker,
    H_ns): mid_c}; keep: optional key filter (e.g. the L18 main result). Returns {H: {(window, arm): figures}}."""
    tick = sorted({k[1] for ks in keys_by.values() for k in ks})
    ti = {t: i for i, t in enumerate(tick)}
    upd = {}
    for (t, h), m in mid_tab.items():
        if t in ti and m is not None and m == m:
            upd.setdefault(int(h), []).append((ti[t], float(m)))
    arr = {}
    for wa, ks in keys_by.items():
        ks = [k for k in ks if int(k[7]) >= start_H and (keep is None or keep(k))]
        if not ks:
            continue
        F = [as_fill(k, results.get(k[1])) for k in ks]
        arr[wa] = {"H": np.array([int(k[7]) for k in ks]), "side": np.array([k[2] for k in ks], float),
                   "price": np.array([k[3] for k in ks], float), "qty": np.array([k[4] for k in ks], float),
                   "fee": np.array([k[5] for k in ks], float), "cap": np.array([k[6] for k in ks], float),
                   "net": np.array([f[6] for f in F], float), "ti": np.array([ti[k[1]] for k in ks]),
                   "st": np.array([settled_at[k[0]] if settled_at.get(k[0]) is not None else np.inf for k in ks], float)}
    latest = np.full(len(tick), np.nan)
    pending = sorted(upd)
    out, j = {}, 0
    for H in sorted(hours):
        while j < len(pending) and pending[j] <= H:
            for i, m in upd[pending[j]]:
                latest[i] = m
            j += 1
        row = {}
        for wa, a in arr.items():
            m = a["H"] <= H
            done = m & (a["st"] <= H + lag)
            op = m & ~done
            mid = latest[a["ti"][op]]
            unreal = float(np.sum(np.where(np.isnan(mid), 0.0, a["side"][op] * (mid - a["price"][op]) * a["qty"][op]) - a["fee"][op]))
            real = float(a["net"][done].sum())
            row[wa] = {"realised_usd": real / 100, "unrealised_usd": unreal / 100, "total_usd": (real + unreal) / 100,
                       "capital_usd": float(a["cap"][m].sum()) / 100, "fills": int(m.sum())}
        out[H] = row
    return out


def fleet_summary(entry: dict, window="primary") -> tuple:
    """(metrics, output) for the Research Fleet post. Metrics: the main result's settled net P&L per arm and G2 minus
    random, named as in the daily record (main_<arm>_net_usd). Full-universe totals, mark-to-market and the verdict
    statistics (computed on the full universe) stay in the output, with the entry hash."""
    cum = entry["cumulative"].get(window, {})
    v = entry.get("verdict", {})
    mr = (entry.get("main_result_l18") or {}).get("cumulative", {})
    met = {f"main_{a}_net_usd": round(mr[a]["realised_usd"], 2) for a in MAIN_ARMS if a in mr}
    if "g2" in mr and "rnd2" in mr:
        met["main_g2_minus_rnd2_usd"] = round(mr["g2"]["realised_usd"] - mr["rnd2"]["realised_usd"], 2)
    out = {"H": entry["H"], "live_start": entry["live_start"], "entry_hash": entry["hash"], "prev_hash": entry["prev_hash"],
           "cumulative_primary": cum, "main_result_l18": entry.get("main_result_l18"), "verdict": v, "settlements": len(entry["settlements"]),
           "verification_issues": entry["verification"]}
    return met, out


FLEET_SITES = ("home", "office")   # 2026-10-21: home first, the site the account's Research Fleet view shows


def post_fleet(entry: dict, pat: str, url="https://lum.id/api/v1/me/fleet/jobs") -> str:
    """Submit the round's summary as a FlowMesh job (Research Fleet stamps created_at). Never raises."""
    try:
        import requests
        met, out = fleet_summary(entry)
        code = (f"import json\nOUT = json.loads({json.dumps(json.dumps(out, default=float))})\n"
                f"MET = json.loads({json.dumps(json.dumps(met))})\n\n\ndef main():\n    return {{'metrics': MET, 'output': OUT}}\n")
        wf = {"apiVersion": "flowmesh/v1", "kind": "Task", "metadata": {"name": f"fwdtest-pnl-{entry['H']}"},
              "spec": {"taskType": "python", "code": code}}
        errs = []
        for site in FLEET_SITES:
            try:
                r = requests.post(url, json={"workflow": json.dumps(wf), "site": site},
                                  headers={"Authorization": f"Bearer {pat}"}, timeout=60)
                if r.status_code in (200, 201, 202):
                    return r.json()["data"]["id"]
                errs.append(f"{site}: HTTP {r.status_code}")
            except Exception as e:
                errs.append(f"{site}: {e!r}"[:120])
        return "error: " + " | ".join(errs)
    except Exception as e:
        return f"error: {e!r}"[:300]


# ---------------------------------------------------------------- self-test

def ots_stamp(rec: dict, path: Path, run=None) -> str:
    """L14: write `rec` (JSON) to `path` and submit it to the public OpenTimestamps calendars (`ots stamp`
    -> path.ots). Independent of Lumid; never fatal. Returns "ok" or "error: ..."."""
    import subprocess
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, sort_keys=True))
    run = run or (lambda cmd: subprocess.run(cmd, capture_output=True, text=True, timeout=90))
    try:
        r = run([str(Path(sys.executable).parent / "ots"), "stamp", str(path)])
        ok = r.returncode == 0 and Path(str(path) + ".ots").exists()
        return "ok" if ok else f"error: rc={r.returncode} {(r.stderr or '')[-200:]}"
    except Exception as e:
        return f"error: {e!r}"[:240]


def self_test() -> bool:
    import tempfile
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    with tempfile.TemporaryDirectory() as td:
        def fake(cmd):
            Path(cmd[-1] + ".ots").write_bytes(b"x")
            return type("R", (), {"returncode": 0, "stderr": ""})()
        r = ots_stamp({"H": "20261015T12", "entry_hash": "ab"}, Path(td) / "ledger_20261015T12.json", run=fake)
        check("L14: ledger head stamped (record written, .ots present)", r == "ok" and (Path(td) / "ledger_20261015T12.json.ots").exists())
        def boom(cmd):
            raise OSError("offline")
        check("L14: ledger stamping failure is reported, never raised", ots_stamp({"H": "x"}, Path(td) / "x.json", run=boom).startswith("error"))
    k_pre = ("E", "T", 1, 40, 10, 0.0, 400.0, 100)
    k_in = ("E", "T", 1, 40, 10, 0.0, 400.0, 200)
    f = lambda k: (k[0], k[1], k[2], k[3], k[4], k[5], 0.0, k[6], float("nan"), k[7])
    rec = {("primary", "g"): {k_in}}
    check("verify: a fill before the ledger's start is not compared (not 'extra')",
          verify(rec, {"primary": {"g": [f(k_pre), f(k_in)]}}, 300, None, start_H=200) == [])
    f9 = lambda ev, H: (ev, ev + "-A", 1, 40, 10, 0.0, 0.0, 400.0, float("nan"), H)
    check("L18 main result: a 23-series fill from 16 Oct 17:00 UTC counts; earlier, or another series, does not",
          in_main(f9("KXMLSGAME-26OCT17ABC", MAIN_FROM_NS)) and not in_main(f9("KXMLSGAME-26OCT17ABC", MAIN_FROM_NS - 1))
          and not in_main(f9("KXESOCCERGAME-26OCT17X", MAIN_FROM_NS)))
    ent = {"H": "20261017T01", "live_start": "20261015T19", "hash": "h", "prev_hash": "p", "settlements": [], "verification": [],
           "cumulative": {"primary": {"g2": {"total_usd": -1.0, "realised_usd": -2.0, "unrealised_usd": 1.0, "capital_usd": 9.0}}},
           "main_result_l18": {"universe": "train23", "from": MAIN_FROM_STAMP,
                               "cumulative": {"g2": {"total_usd": 3.0, "realised_usd": 2.5, "unrealised_usd": 0.5, "capital_usd": 4.0}}}}
    met, outd = fleet_summary(ent)
    check("L18 main result carried in the Research Fleet record (metrics and output)",
          met.get("main_g2_net_usd") == 2.5 and outd["main_result_l18"]["from"] == "20261016T17")
    check("Fleet metrics: main-result settled net only (no full-universe, mark-to-market or verdict metrics)",
          met == {"main_g2_net_usd": 2.5} and outd["cumulative_primary"]["g2"]["total_usd"] == -1.0)
    ent2 = dict(ent, main_result_l18={"cumulative": {"g2": {"realised_usd": 2.5, "total_usd": 3.0},
                                                     "rnd2": {"realised_usd": -1.25, "total_usd": -1.0}}})
    import types
    tried = []

    def fake_post(url, json=None, headers=None, timeout=None):
        tried.append(json["site"])
        return types.SimpleNamespace(status_code=502 if json["site"] == "home" else 202,
                                     json=lambda: {"data": {"id": "office:fm:wfl-z"}})
    real_requests = sys.modules.get("requests")
    sys.modules["requests"] = types.SimpleNamespace(post=fake_post)
    try:
        jid = post_fleet(ent, "pat")
    finally:
        if real_requests is not None:
            sys.modules["requests"] = real_requests
        else:
            del sys.modules["requests"]
    check("Fleet post: home tried first, office as backup (2026-10-21)", tried == ["home", "office"] and jid == "office:fm:wfl-z")
    check("Fleet metrics: G2 minus random from the settled main result (+$3.75)",
          fleet_summary(ent2)[0] == {"main_g2_net_usd": 2.5, "main_rnd2_net_usd": -1.25, "main_g2_minus_rnd2_usd": 3.75})
    k_late = ("E", "T", 1, 40, 10, 0.0, 400.0, 300)
    rec2 = {("primary", "new_arm"): {k_late}}
    check("verify: an arm that joined later is not compared on hours before it joined",
          verify(rec2, {"primary": {"new_arm": [f(k_in), f(k_late)]}}, 300, None, start_H=200, since={("primary", "new_arm"): 300}) == [])
    check("verify: ... but a change after it joined is still reported",
          verify(rec2, {"primary": {"new_arm": [f(k_in)]}}, 300, None, start_H=200, since={("primary", "new_arm"): 300}) != [])
    check("verify: a recorded fill missing from the recomputation is still reported",
          verify(rec, {"primary": {"g": [f(k_pre)]}}, 300, None, start_H=200) != [])


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
        res = {"E1-A": "yes", "E1-B": "no", "E2-A": None}
        w1 = round_update(d, fills, H0, set(), {"E2-A": 60.0}, stamp, vfn, results=res)
        e1 = w1[0]
        check("first round starts the live record at the completed hour", e1["live_start"] == "h1000" and e1["prev_hash"] == "")
        c = e1["cumulative"]["primary"]["g2"]
        # unrealised: f1 open at mid None -> -fee 0; f2: -1*(60-70)*10 - 5 = +95c
        check(f"unrealised marks open fills at the mid net of fees (+$0.95, got {c['unrealised_usd']})", abs(c["unrealised_usd"] - 0.95) < 1e-9)
        check("nothing settled -> realised 0, total = unrealised", c["realised_usd"] == 0 and abs(c["total_usd"] - 0.95) < 1e-9)
        fills2 = {"primary": {"g2": [f1, f2, f3]}}
        w2 = round_update(d, fills2, H0 + H_NS, {"E1"}, {"E2-A": 65.0}, stamp, vfn, results=res)
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
        w3 = round_update(d, {"primary": {"g2": [f1b, f2, f3]}}, H0 + 2 * H_NS, {"E1"}, {"E2-A": 65.0}, stamp, vfn, results=res)
        check("a changed historical fill is flagged in the next entry, not repaired",
              w3[0]["verification"] and w3[0]["verification"][0]["arm"] == "g2"
              and json.loads((d / "entries" / "h1000.json").read_text())["hash"] == e1["hash"])
        w4 = round_update(d, {"primary": {"g2": [f1, f2, f3]}}, H0 + 5 * H_NS, {"E1"}, {}, stamp, vfn, results=res)
        check("missed rounds are caught up one entry per hour, in order",
              [e["H"] for e in w4] == ["h1003", "h1004", "h1005"] and w4[0]["prev_hash"] == w3[-1]["hash"])
        check("replay hours before the live start never enter the live totals",
              round_update(Path(td) / "x", {"primary": {"g2": [f1, f3]}}, H0 + H_NS, set(), {}, stamp, vfn, results=res)[0]
              ["cumulative"]["primary"]["g2"]["fills"] == 1)
        # E2 is no longer recomputed (dropped from the active set) and settles later: still realised from the ledger
        res2 = {**res, "E2-A": "no"}
        w5 = round_update(d, {"primary": {"g2": []}}, H0 + 6 * H_NS, {"E1", "E2"}, {}, stamp, vfn, results=res2, events=set())
        c5 = w5[0]["cumulative"]["primary"]["g2"]
        check(f"a recorded fill of an event no longer recomputed realises when it settles (+$4.50 + $6.95, got {c5['realised_usd']})",
              abs(c5["realised_usd"] - (4.5 + 6.95)) < 1e-9 and c5["unrealised_usd"] == 0)
        check("verification covers only the events recomputed this round (none flagged for dropped events)",
              w5[0]["verification"] == [])
        check("as_fill values a settled key with the simulator's formula (YES sold at 70, settles NO: +$7.00 - fee)",
              as_fill(("E", "T", -1, 70, 10, 5.0, 300.0, 0), "no")[6] == 695.0 and as_fill(("E", "T", 1, 40, 10, 0.0, 400.0, 0), None)[6] == 0.0)
        met, out = fleet_summary(w4[-1])
        check("fleet summary carries the cumulative breakdown and the entry hash",
              "g2" in out["cumulative_primary"] and out["entry_hash"] == w4[-1]["hash"])

    # L20: one order filled by two trades in its hour = two identical fills, both real
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        Hm, ev = MAIN_FROM_NS, "KXHIGHNY-26OCT17"                          # a main-result fill (23 series, from 16 Oct 17:00)
        g = (ev, ev + "-B70", 1, 40, 1, 0.0, 60.0, 40.0, 0.0, Hm)          # YES bought at 40, 1 contract, settles YES: +60c
        res = {ev + "-B70": "yes"}
        w1 = round_update(d, {"primary": {"g2": [g, g]}}, Hm, set(), {}, stamp, vfn, results=res)
        check("L20: both identical fills are written to the entry", len(w1[0]["new_fills"]["primary"]["g2"]) == 2)
        check("L20: recorded_fills keeps the repeat", len(recorded_fills(d)[("primary", "g2")]) == 2)
        w2 = round_update(d, {"primary": {"g2": [g, g]}}, Hm + H_NS, {ev}, {}, stamp, vfn, results=res)
        c2 = w2[0]["cumulative"]["primary"]["g2"]
        check(f"L20: a later round counts both recorded fills (realised +$1.20, 2 fills; got {c2['realised_usd']}, {c2['fills']})",
              abs(c2["realised_usd"] - 1.2) < 1e-9 and c2["fills"] == 2 and w2[0]["verification"] == [])
        check(f"L20: the main-result block counts both too (got {w2[0]['main_result_l18']['cumulative']['g2']['fills']})",
              w2[0]["main_result_l18"]["cumulative"]["g2"]["fills"] == 2)
        w3 = round_update(d, {"primary": {"g2": [g]}}, Hm + 2 * H_NS, {ev}, {}, stamp, vfn, results=res)
        check(f"L20: verify reports a lost repeat (recorded 2, recomputed 1: {w3[0]['verification']})",
              w3[0]["verification"] == [{"window": "primary", "arm": "g2", "missing_now": 1, "extra_now": 0}])

    # L20 recount: hand-computed curve. Keys (event, ticker, side, price, qty, fee, capital, H).
    kA = ("E1", "E1-A", 1, 40, 1, 1.0, 40.0, H0)                       # bought at 40, fee 1c; E1 settles YES at H0+3h
    kB = ("E2", "E2-A", -1, 70, 2, 0.0, 60.0, H0 + H_NS)               # sold 2 at 70; E2 never settles
    kC = ("X9", "X9-A", 1, 50, 1, 0.0, 50.0, H0)                       # filtered out by keep
    keys_by = {("primary", "g2"): [kA, kA, kB, kC]}
    mt = {("E1-A", H0): 45.0, ("E2-A", H0 + H_NS): 60.0, ("E2-A", H0 + 3 * H_NS): 80.0}
    rc = recount_curve(keys_by, [H0, H0 + H_NS, H0 + 3 * H_NS], {"E1-A": "yes"}, {"E1": H0 + 3 * H_NS, "E2": None}, mt, H0,
                       keep=lambda k: k[0] != "X9")
    r0, r1, r3 = (rc[h][("primary", "g2")] for h in (H0, H0 + H_NS, H0 + 3 * H_NS))
    # H0: two kA open, marked at 45: 2*(45-40)*1 - 2*1 = +8c; settled-by lag: E1 settles H0+3h > H0+2h -> open
    check(f"L20 recount, H0: both repeats marked at the mid net of fees (+$0.08, 2 fills; got {r0['total_usd']}, {r0['fills']})",
          abs(r0["total_usd"] - 0.08) < 1e-9 and r0["fills"] == 2 and r0["realised_usd"] == 0)
    # H0+1h: E1 settled by H0+3h <= H0+1h+2h -> realised 2*(60-1) = 118c; kB open at 60: -1*(60-70)*2 = +20c
    check(f"L20 recount, H0+1h: E1 realised within the lag (+$1.18), kB marked (+$0.20) (got {r1['realised_usd']}, {r1['unrealised_usd']})",
          abs(r1["realised_usd"] - 1.18) < 1e-9 and abs(r1["unrealised_usd"] - 0.20) < 1e-9 and r1["fills"] == 3)
    # H0+3h: kB re-marked at 80: -1*(80-70)*2 = -20c
    check(f"L20 recount, H0+3h: an open fill takes the latest mid at or before the hour (-$0.20; got {r3['unrealised_usd']})",
          abs(r3["unrealised_usd"] + 0.20) < 1e-9 and abs(r3["capital_usd"] - 1.4) < 1e-9)
    rn = recount_curve({("primary", "g2"): [kB]}, [H0 + H_NS], {}, {}, {}, H0)[H0 + H_NS][("primary", "g2")]
    check("L20 recount: an open fill with no logged mid carries only -fee (0 here)", rn["unrealised_usd"] == 0 and rn["fills"] == 1)
    check("L20 recount: fills before the live start are left out",
          ("primary", "g2") not in recount_curve({("primary", "g2"): [kA]}, [H0], {}, {}, {}, H0 + H_NS)[H0])
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    print(__doc__)
