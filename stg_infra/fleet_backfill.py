"""
fleet_backfill.py -- post to Research Fleet the hourly records whose live post failed (2026-10-14 on: Lumid's office
job service down). Producer hours come from runs.jsonl (lines whose `fleet_job` is an error); ledger heads from the
ledger's entries/. Each is posted as the producer and ledger would have posted it (same job names), to the first site
that accepts it (office, else home), marked `backfilled_utc`. Research Fleet's created_at on these is the backfill
time, not the hour: they complete the record, and the hour's timing is proven by its OpenTimestamps record (L14).
Already-backfilled names are kept in DONE so a rerun posts nothing twice.

    python stg_infra/fleet_backfill.py --self-test
    python stg_infra/fleet_backfill.py --runs RUNS.jsonl --ledger LEDGER_DIR --pat-file ~/.lumid_pat [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
DONE = _THIS.parent / "runs/live/fleet_backfilled.json"


def missing_hours(runs_lines):
    """Producer summaries whose live Research Fleet post failed (or was never attempted), oldest first."""
    out = []
    for line in runs_lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if "H" in d and "sha256" in d and not str(d.get("fleet_job", "error")).split(":")[0] in ("office", "home"):
            out.append(d)
    return out


def missing_entries(entry_files):
    """Ledger entries (all are posted once by the live ledger; the failed ones are re-posted)."""
    return [json.loads(Path(f).read_text()) for f in sorted(entry_files)]


def unreadable(done_ids: dict, readable) -> list:
    """Names whose posted job's result cannot be read back (home has accepted jobs and then lost their contents)."""
    return [name for name, jid in done_ids.items() if not readable(jid)]


def run(runs_lines, entries, post_hour, post_entry, done: set, dry=False):
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    log = []
    for d in missing_hours(runs_lines):
        name = f"fwdtest-hour-{d['H']}"
        if name in done:
            continue
        rec = {**d, "backfilled_utc": stamp, "live_fleet_job": d.get("fleet_job")}
        res = "dry-run" if dry else post_hour(rec)
        log.append((name, res))
        if not str(res).startswith("error") and not dry:
            done.add(name)
    for e in entries:
        name = f"fwdtest-pnl-{e['H']}"
        if name in done:
            continue
        res = "dry-run" if dry else post_entry(e)
        log.append((name, res))
        if not str(res).startswith("error") and not dry:
            done.add(name)
    return log


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    lines = [json.dumps({"H": "T1", "sha256": {}, "fleet_job": "office:fm:wfl-a"}),
             json.dumps({"H": "T2", "sha256": {}, "fleet_job": "error: HTTP 502"}),
             json.dumps({"info": "waiting"}), "not json",
             json.dumps({"H": "T3", "sha256": {}, "fleet_job": "home:fm:wfl-b"}),
             json.dumps({"H": "T4", "sha256": {}})]
    check("missing: failed and never-attempted hours only (T2, T4)", [d["H"] for d in missing_hours(lines)] == ["T2", "T4"])
    posted = []
    done = set()
    log = run(lines, [{"H": "T2"}], lambda r: posted.append(r) or "home:fm:x", lambda e: "home:fm:y", done)
    check("posts T2, T4 and the ledger entry; records marked backfilled with the live error kept",
          [n for n, _ in log] == ["fwdtest-hour-T2", "fwdtest-hour-T4", "fwdtest-pnl-T2"]
          and posted[0]["backfilled_utc"] and posted[0]["live_fleet_job"] == "error: HTTP 502")
    log2 = run(lines, [{"H": "T2"}], lambda r: "home:fm:x", lambda e: "home:fm:y", done)
    check("a rerun posts nothing twice", log2 == [])
    d2 = set()
    run(lines, [], lambda r: "error: home: HTTP 502", lambda e: "x", d2)
    check("a failed post is retried on the next run", d2 == set())
    check("unreadable: only posted jobs whose result cannot be read are re-posted",
          unreadable({"a": "id1", "b": "id2", "c": None}, lambda j: j != "id2") == ["b"])
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--runs")
    ap.add_argument("--ledger")
    ap.add_argument("--pat-file", default="~/.lumid_pat")
    ap.add_argument("--done", default=str(DONE))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import requests
    import live_signal_producer as lp
    import paper_ledger as pl_
    pat = Path(a.pat_file).expanduser().read_text().strip()
    donep = Path(a.done)
    raw = json.loads(donep.read_text()) if donep.exists() else {}
    done_ids = raw if isinstance(raw, dict) else {n: None for n in raw}
    H = {"Authorization": f"Bearer {pat}"}

    def readable(jid):
        if not jid:
            return True                                   # posted before ids were kept: not re-checked
        try:
            r = requests.get(f"{lp.FLEET_URL}/{jid}", params={"view": "result"}, headers=H, timeout=60)
            outs = r.json().get("data", {}).get("outputs") or [{}]
            return r.status_code == 200 and not outs[0].get("error")
        except Exception:
            return True                                   # cannot tell now: try again next run
    for name in unreadable(done_ids, readable):
        print(json.dumps({"job": name, "result": "unreadable after posting; re-posting"}))
        done_ids.pop(name)
    done = set(done_ids)
    post_hour = lambda rec: lp.post_fleet(rec, lambda body: requests.post(
        lp.FLEET_URL, json=body, headers={"Authorization": f"Bearer {pat}"}, timeout=60))
    post_entry = lambda e: pl_.post_fleet(e, pat)
    entries = missing_entries((Path(a.ledger) / "entries").glob("*.json")) if a.ledger else []
    log = run(Path(a.runs).read_text().splitlines(), entries, post_hour, post_entry, done, a.dry_run)
    if not a.dry_run:
        for n, r in log:
            if not str(r).startswith(("error", "dry")):
                done_ids[n] = r
        donep.parent.mkdir(parents=True, exist_ok=True)
        donep.write_text(json.dumps(done_ids, indent=0))
    for n, r in log:
        print(json.dumps({"job": n, "result": r}))
    print(json.dumps({"posted": sum(1 for _, r in log if not str(r).startswith(("error", "dry"))),
                      "failed": sum(1 for _, r in log if str(r).startswith("error"))}))


if __name__ == "__main__":
    main()
