"""
rebuild_markets_cache.py

Rebuild the paper trader's settlement cache (runs/live/paper/markets.pkl, markets_full.pkl) for every event the ledger
has a fill in, and every event in the L10 g2 archive (2026-10-22). The cache was not in the GitHub backup, so a sandbox restored from it starts empty; the
paper trader then refetches only the events still being quoted, and every older event with fills would count as
unsettled in the ledger's cumulative figures and on the dashboard. Run with the paper trader STOPPED, on the sandbox:

    python stg_infra/rebuild_markets_cache.py            # fetch from Kalshi, merge into any existing cache, write
    python stg_infra/rebuild_markets_cache.py --self-test

Rows are made by paper_trader.market_row, so they are exactly what the paper trader itself would cache. Existing rows
are kept unless the fresh fetch has the event, which replaces them (Kalshi's answer is newer).
"""
from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PAPER = REPO / "runs/live/paper"
sys.path.insert(0, str(REPO / "stg_infra"))


def ledger_events(entries_dir: Path) -> set:
    """Every event with a recorded fill in any window and arm (fill rows start with the event ticker)."""
    evs = set()
    for p in sorted(entries_dir.glob("*.json")):
        for arms in json.loads(p.read_text()).get("new_fills", {}).values():
            for rows in arms.values():
                evs.update(r[0] for r in rows)
    return evs


def archive_events(archive: Path) -> set:
    """Every event in the L10 g2 archive (2026-10-22: the L7 selection reads fills from before the ledger started,
    whose events are not in the ledger; a rebuild from the ledger alone left 373 of them unsettled and emptied the
    18-25 Oct selection)."""
    return {r[0] for r in json.loads(archive.read_text())} if archive.exists() else set()


def rebuild(events, cache: dict, full: dict, fetch, row, now_ns: int, say=print) -> tuple[dict, dict]:
    """fetch(ev) -> list of market dicts (all legs). Returns the updated (cache, full)."""
    for i, ev in enumerate(sorted(events)):
        for m in fetch(ev):
            cache[m["ticker"]] = row(m)
        full[ev] = now_ns
        if (i + 1) % 200 == 0:
            say(json.dumps({"events_fetched": i + 1, "of": len(events)}))
    return cache, full


def self_test() -> bool:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    d = Path(tempfile.mkdtemp())
    (d / "20261016T00.json").write_text(json.dumps({"new_fills": {"primary": {"g2": [["EV-A", "EV-A-X", 1, 40, 1, 0, 40, 0]],
                                                                             "rnd2": [["EV-B", "EV-B-Y", -1, 60, 1, 0, 40, 0]]},
                                                                 "alt": {"g2": [["EV-C", "EV-C-Z", 1, 10, 1, 0, 10, 0]]}}}))
    (d / "20261016T01.json").write_text(json.dumps({"new_fills": {"primary": {"g2": []}}}))
    evs = ledger_events(d)
    check("events from every entry, window and arm", evs == {"EV-A", "EV-B", "EV-C"})
    legs = {"EV-A": [{"ticker": "EV-A-X", "r": "yes"}, {"ticker": "EV-A-W", "r": "no"}],
            "EV-B": [{"ticker": "EV-B-Y", "r": ""}], "EV-C": [{"ticker": "EV-C-Z", "r": "no"}]}
    row = lambda m: {"result": m["r"]}
    cache = {"EV-B-Y": {"result": "yes"}, "OTHER-1": {"result": "no"}}
    cache, full = rebuild(evs, cache, {}, lambda ev: legs[ev], row, 7, say=lambda *a: None)
    check("every leg of every event cached, incl. legs without fills", set(legs["EV-A"][1].values()) & {"EV-A-W"}
          and cache["EV-A-W"] == {"result": "no"} and cache["EV-A-X"] == {"result": "yes"})
    check("a fresh fetch replaces an existing row", cache["EV-B-Y"] == {"result": ""})
    check("rows of other events are kept", cache["OTHER-1"] == {"result": "no"})
    check("full: every fetched event stamped", full == {"EV-A": 7, "EV-B": 7, "EV-C": 7})
    (d / "arch.json").write_text(json.dumps([["EV-OLD", "EV-OLD-1", 1, 5, 1, 0, 5, 0], ["EV-A", "EV-A-X", 1, 40, 1, 0, 40, 0]]))
    check("archive events: every event in the g2 archive, incl. ones before the ledger", archive_events(d / "arch.json") == {"EV-OLD", "EV-A"})
    check("archive events: none without an archive", archive_events(d / "absent.json") == set())
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import subprocess
    if subprocess.run(["pgrep", "-f", "paper_trader.py --loop"], capture_output=True).returncode == 0:
        sys.exit("the paper trader is running: stop it first (it would overwrite the cache at the end of its refresh)")
    import live_signal_producer as lp
    from paper_trader import market_row
    mp, fp = PAPER / "markets.pkl", PAPER / "markets_full.pkl"
    cache = pickle.loads(mp.read_bytes()) if mp.exists() else {}
    full = pickle.loads(fp.read_bytes()) if fp.exists() else {}
    evs = ledger_events(PAPER / "ledger/entries")
    arch = archive_events(PAPER / "g2_archive.json")
    print(json.dumps({"archive_only_events": len(arch - evs)}), flush=True)
    evs |= arch
    print(json.dumps({"events": len(evs), "cached_tickers_before": len(cache)}), flush=True)
    k = lp.Kalshi()
    t0 = time.time()
    cache, full = rebuild(evs, cache, full, lambda ev: list(k.pages("markets", "markets", event_ticker=ev, limit=1000)),
                          market_row, time.time_ns())
    final = sum(1 for m in cache.values() if m.get("result") in ("yes", "no"))
    for p, obj in ((mp, cache), (fp, full)):
        tmp = p.with_suffix(".tmp")
        tmp.write_bytes(pickle.dumps(obj))
        tmp.replace(p)
    print(json.dumps({"cached_tickers": len(cache), "settled_tickers": final, "events_stamped": len(full),
                      "api_calls": k.calls, "secs": round(time.time() - t0)}))


if __name__ == "__main__":
    main()
