"""
fleet_backfill.py -- post to Research Fleet the hourly records whose live post failed (2026-10-14 on: Lumid's office
job service down). Producer hours come from runs.jsonl (lines whose `fleet_job` is an error); ledger heads from the
ledger's entries/. Each is posted as the producer and ledger would have posted it (same job names), to the first site
that accepts it (office, else home), marked `backfilled_utc`. Research Fleet's created_at on these is the backfill
time, not the hour: they complete the record, and the hour's timing is proven by its OpenTimestamps record (L14).
Already-backfilled names are kept in DONE so a rerun posts nothing twice.

2026-11-15 fix (re-post loop):
- Research Fleet deletes a job's result and logs after about 3-4 days, while the job itself (name, status,
  created_at) stays. The old check re-posted every job whose RESULT could no longer be read, so expired jobs were
  re-posted every hour. Now a posted job is checked once by its STATUS: `succeeded` (or still running) counts as
  posted for good; only a job that `failed`, or that the service no longer knows, is re-posted. Checked names are
  kept in VERIFIED so each job is checked once.
- DONE is saved after every successful post, so a run cut short (the keeper's 30-min timeout) never forgets what
  it posted.
- Each run stops after --budget-s seconds (default 900) and carries on at the next run.
- runs/live/FLEET_BACKFILL_OFF switches the backfill off.

    python stg_infra/fleet_backfill.py --self-test
    python stg_infra/fleet_backfill.py --runs RUNS.jsonl --ledger LEDGER_DIR --pat-file ~/.lumid_pat [--dry-run]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

_THIS = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS))
DONE = _THIS.parent / "runs/live/fleet_backfilled.json"
VERIFIED = _THIS.parent / "runs/live/fleet_verified.json"
OFF = _THIS.parent / "runs/live/FLEET_BACKFILL_OFF"
RETRIES = _THIS.parent / "runs/live/fleet_retries.json"
MAX_REPOSTS = 2      # a job that keeps failing (e.g. a Lumid worker down) is re-posted at most this often


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


def live_posted_pnl(paper_log_lines) -> set:
    """Ledger heads the paper trader posted live (its log line {"ledger": {"entries_written": [...], "fleet_job": id}}):
    the live ledger posts only the newest entry of each round, so only that name is already on Research Fleet."""
    out = set()
    for line in paper_log_lines:
        if '"ledger"' not in line:
            continue
        try:
            d = json.loads(line).get("ledger") or {}
        except ValueError:
            continue
        w = d.get("entries_written") or []
        if w and str(d.get("fleet_job", "")).split(":")[0] in ("office", "home"):
            out.add(f"fwdtest-pnl-{w[-1]}")
    return out


def anchor_job(entry: dict, hash_chars: int = 64) -> tuple:
    """(key, workflow body) for the hourly anchor of the newest ledger entry. Research Fleet deletes a job's result
    after about 3-4 days but keeps its name, status and created_at, so the ledger hash goes INTO the name: the name
    alone then proves, permanently, that the ledger had this head at that time (every entry carries its predecessor's
    hash, so one anchor fixes every earlier entry). The key (without the hash) records it in DONE."""
    key = f"fwdtest-anchor-{entry['H']}"
    name = f"{key}-{entry['hash'][:hash_chars]}"
    out = {"H": entry["H"], "entry_hash": entry["hash"], "prev_hash": entry.get("prev_hash"),
           "note": "name carries the ledger head hash; github.com/curiousfun88/event-pred-live"}
    code = (f"import json\nOUT = json.loads({json.dumps(json.dumps(out))})\n\n\n"
            f"def main():\n    return {{'metrics': {{}}, 'output': OUT}}\n")
    wf = {"apiVersion": "flowmesh/v1", "kind": "Task", "metadata": {"name": name},
          "spec": {"taskType": "python", "code": code}}
    return key, {"workflow": json.dumps(wf), "site": "home"}


def job_state(status_code: int, body: dict) -> str:
    """'ok' (the job ran or is still running: posted for good, even if its result has since expired), 'lost' (the
    job failed, or the service no longer knows it: re-post), 'unknown' (cannot tell now: check again next run)."""
    if status_code == 200:
        st = str((body.get("data") or {}).get("status", "")).lower()
        if st == "failed":
            return "lost"
        return "ok" if st else "unknown"
    if status_code == 404:
        return "lost"
    return "unknown"


def repost_or_give_up(lost: list, retries: dict, max_reposts: int = MAX_REPOSTS) -> tuple:
    """Split failed jobs into (re-post now, give up). Each name is re-posted at most `max_reposts` times, so a
    Lumid outage that fails every job cannot turn into an hourly re-post loop. `retries` is updated."""
    again, give_up = [], []
    for n in lost:
        if retries.get(n, 0) < max_reposts:
            retries[n] = retries.get(n, 0) + 1
            again.append(n)
        else:
            give_up.append(n)
    return again, give_up


def to_check(done_ids: dict, verified: set) -> list:
    """Posted names not yet checked (a job id is needed to check; names posted before ids were kept are not)."""
    return [n for n, jid in done_ids.items() if jid and n not in verified]


def run(runs_lines, entries, post_hour, post_entry, done: set, dry=False, on_ok=None, budget_s=None, clock=time.time):
    """Post what is missing, oldest first. `on_ok(name, result)` is called after each successful post (to save
    progress at once). Stops when `budget_s` seconds have passed; the rest is posted at the next run."""
    stamp = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    t_end = None if budget_s is None else clock() + budget_s
    log = []
    todo = [(f"fwdtest-hour-{d['H']}", "hour", d) for d in missing_hours(runs_lines)]
    todo += [(f"fwdtest-pnl-{e['H']}", "pnl", e) for e in entries]
    for name, kind, x in todo:
        if name in done:
            continue
        if t_end is not None and clock() >= t_end:
            log.append((name, "deferred: time budget used"))
            break
        if dry:
            res = "dry-run"
        elif kind == "hour":
            res = post_hour({**x, "backfilled_utc": stamp, "live_fleet_job": x.get("fleet_job")})
        else:
            res = post_entry(x)
        log.append((name, res))
        if not str(res).startswith("error") and not dry:
            done.add(name)
            if on_ok:
                on_ok(name, res)
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
    posted, saved = [], []
    done = set()
    log = run(lines, [{"H": "T2"}], lambda r: posted.append(r) or "home:fm:x", lambda e: "home:fm:y", done,
              on_ok=lambda n, r: saved.append(n))
    check("posts T2, T4 and the ledger entry; records marked backfilled with the live error kept",
          [n for n, _ in log] == ["fwdtest-hour-T2", "fwdtest-hour-T4", "fwdtest-pnl-T2"]
          and posted[0]["backfilled_utc"] and posted[0]["live_fleet_job"] == "error: HTTP 502")
    check("progress is saved after each successful post, not only at the end",
          saved == ["fwdtest-hour-T2", "fwdtest-hour-T4", "fwdtest-pnl-T2"])
    log2 = run(lines, [{"H": "T2"}], lambda r: "home:fm:x", lambda e: "home:fm:y", done)
    check("a rerun posts nothing twice", log2 == [])
    d2 = set()
    run(lines, [], lambda r: "error: home: HTTP 502", lambda e: "x", d2)
    check("a failed post is retried on the next run", d2 == set())
    t = iter([0, 0, 5, 20, 20, 20])
    d3 = set()
    log3 = run(lines, [{"H": "T2"}], lambda r: "home:fm:x", lambda e: "home:fm:y", d3, budget_s=10,
               clock=lambda: next(t))
    check("the time budget stops the run and leaves the rest for the next run",
          [n for n, _ in log3] == ["fwdtest-hour-T2", "fwdtest-hour-T4", "fwdtest-pnl-T2"]
          and log3[-1][1].startswith("deferred") and d3 == {"fwdtest-hour-T2", "fwdtest-hour-T4"})
    check("expired result but job succeeded: posted for good, never re-posted",
          job_state(200, {"data": {"status": "succeeded"}}) == "ok")
    check("job failed, or no longer known: re-posted",
          job_state(200, {"data": {"status": "failed"}}) == "lost" and job_state(404, {}) == "lost")
    check("service error: cannot tell, check again next run", job_state(502, {}) == "unknown")
    plog = [json.dumps({"ledger": {"entries_written": ["T5", "T6"], "fleet_job": "home:fm:wfl-z"}}),
            json.dumps({"ledger": {"entries_written": ["T7"], "fleet_job": "error: home: HTTP 502"}}),
            json.dumps({"ledger": {"entries_written": [], "fleet_job": None}}), "noise"]
    check("live-posted ledger heads only (T6, not T5 nor the failed T7)", live_posted_pnl(plog) == {"fwdtest-pnl-T6"})
    rt = {}
    a1, g1 = repost_or_give_up(["x", "y"], rt, 2)
    a2, g2 = repost_or_give_up(["x"], rt, 2)
    a3, g3 = repost_or_give_up(["x"], rt, 2)
    check("a failing job is re-posted at most twice, then given up",
          a1 == ["x", "y"] and a2 == ["x"] and a3 == [] and g3 == ["x"] and rt == {"x": 2, "y": 1})
    k, body = anchor_job({"H": "T9", "hash": "ab" * 32, "prev_hash": "cd" * 32})
    wf = json.loads(body["workflow"])
    check("anchor: key without hash, name with the full ledger head hash, posted to home",
          k == "fwdtest-anchor-T9" and wf["metadata"]["name"] == "fwdtest-anchor-T9-" + "ab" * 32
          and body["site"] == "home" and "ab" * 32 in wf["spec"]["code"])
    check("only posted jobs with an id that were not yet checked are checked",
          to_check({"a": "id1", "b": "id2", "c": None}, {"a"}) == ["b"])
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--runs")
    ap.add_argument("--ledger")
    ap.add_argument("--pat-file", default="~/.lumid_pat")
    ap.add_argument("--done", default=str(DONE))
    ap.add_argument("--verified", default=str(VERIFIED))
    ap.add_argument("--budget-s", type=float, default=900.0)
    ap.add_argument("--no-anchor", action="store_true", help="do not post the hourly ledger-head anchor")
    ap.add_argument("--paper-log", default=str(_THIS.parent / "logs/paper_trader.log"),
                    help="paper trader log: ledger heads it posted live are not posted again")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if OFF.exists() and not a.dry_run:
        print(json.dumps({"posted": 0, "failed": 0, "note": f"backfill switched off ({OFF.name})"}))
        return
    import requests
    import live_signal_producer as lp
    import paper_ledger as pl_
    t0 = time.time()
    pat = Path(a.pat_file).expanduser().read_text().strip()
    donep, verp = Path(a.done), Path(a.verified)
    raw = json.loads(donep.read_text()) if donep.exists() else {}
    done_ids = raw if isinstance(raw, dict) else {n: None for n in raw}
    verified = set(json.loads(verp.read_text())) if verp.exists() else set()
    retp = Path(a.done).with_name(RETRIES.name)
    retries = json.loads(retp.read_text()) if retp.exists() else {}
    H = {"Authorization": f"Bearer {pat}"}

    def save():
        if a.dry_run:
            return
        donep.parent.mkdir(parents=True, exist_ok=True)
        donep.write_text(json.dumps(done_ids, indent=0))
        verp.write_text(json.dumps(sorted(verified), indent=0))
        retp.write_text(json.dumps(retries, indent=0))

    # 1. Check each posted job once, by status. Half the budget at most, so posting still gets time.
    lost = []
    for name in to_check(done_ids, verified):
        if time.time() - t0 > a.budget_s / 2:
            break
        try:
            r = requests.get(f"{lp.FLEET_URL}/{done_ids[name]}", headers=H, timeout=30)
            st = job_state(r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {})
        except Exception:
            st = "unknown"
        if st == "ok":
            verified.add(name)
        elif st == "lost":
            lost.append(name)
    again, give_up = repost_or_give_up(lost, retries)
    for name in again:
        print(json.dumps({"job": name, "result": f"job failed or no longer known; re-posting ({retries[name]})"}))
        done_ids.pop(name)
    for name in give_up:
        verified.add(name)          # failed MAX_REPOSTS times: kept as posted (its name and timestamp stand), not retried
        print(json.dumps({"job": name, "result": "failed again; not re-posted (limit reached)"}))
    save()

    # 2. Post what is missing, saving after each success. Heads the paper trader posted live count as posted.
    plp = Path(a.paper_log)
    live = live_posted_pnl(plp.read_text(errors="replace").splitlines()) if plp.exists() else set()
    done = set(done_ids) | live

    def on_ok(name, res):
        done_ids[name] = res
        verified.discard(name)
        save()
    post_hour = lambda rec: lp.post_fleet(rec, lambda body: requests.post(
        lp.FLEET_URL, json=body, headers={"Authorization": f"Bearer {pat}"}, timeout=60))
    post_entry = lambda e: pl_.post_fleet(e, pat)
    entries = missing_entries((Path(a.ledger) / "entries").glob("*.json")) if a.ledger else []
    left = max(0.0, a.budget_s - (time.time() - t0))
    log = run(Path(a.runs).read_text().splitlines(), entries, post_hour, post_entry, done, a.dry_run,
              on_ok=on_ok, budget_s=left)
    # 3. Anchor the newest ledger entry once (its hash in the job name survives Research Fleet's result expiry).
    if not a.no_anchor and entries and not a.dry_run:
        key, body = anchor_job(entries[-1])
        if key not in done_ids:
            try:
                r = requests.post(lp.FLEET_URL, json=body, headers=H, timeout=60)
                res = r.json()["data"]["id"] if r.status_code in (200, 201, 202) else f"error: HTTP {r.status_code}"
            except Exception as e:
                res = f"error: {e!r}"[:200]
            log.append((key, res))
            if not str(res).startswith("error"):
                on_ok(key, res)
    for n, r in log:
        print(json.dumps({"job": n, "result": r}))
    print(json.dumps({"posted": sum(1 for _, r in log if not str(r).startswith(("error", "dry", "deferred"))),
                      "failed": sum(1 for _, r in log if str(r).startswith("error")),
                      "deferred": any(str(r).startswith("deferred") for _, r in log),
                      "checked_ok": len(verified), "reposting_lost": len(lost)}))


if __name__ == "__main__":
    main()
