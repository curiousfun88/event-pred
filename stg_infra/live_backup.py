"""
live_backup.py -- hourly off-site copy of the live test's records (amendment L16), so that if the Lumid site holding
the shared home goes down, the ledger can continue from its last entry on another host.

WHAT. Copies into a clone of the backup repo (git@github.com:curiousfun88/event-pred-live.git) the files needed to
resume and to re-verify: runs/live/runs.jsonl, runs/live/stamps/, runs/live/scores/, runs/live/paper/ledger/,
runs/live/paper/tape/, logs/sbx_keeper.log, plus heartbeat.json (UTC time, latest producer hour, latest ledger entry,
host). Not copied (large or rebuilt): the trade store pickles (a cold-start hour rebuilds them), signal payloads
(derived from the scores), the market cache (refetched). Commits only when something changed; pushes with a deploy key
that can write to that repo only. Never raises into its caller: a GitHub outage must not touch the live test.

    python stg_infra/live_backup.py --self-test
    python stg_infra/live_backup.py --once          # inside the sandbox
    python stg_infra/live_backup.py --loop          # every 10 min (the keeper calls run_once itself from L16 on)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

USER = "curiouslearner842"
HOME = Path(f"/home/{USER}")
REPO = HOME / "event-pred"
CFG = HOME / ".lumid"
CLONE = HOME / "live-backup"
REMOTE = "git@github.com:curiousfun88/event-pred-live.git"
ITEMS = ["runs/live/runs.jsonl", "runs/live/stamps", "runs/live/scores", "runs/live/paper/ledger",
         "runs/live/paper/tape", "logs/sbx_keeper.log"]


def heartbeat(repo: Path) -> dict:
    """{utc, host, latest producer hour, latest ledger entry} from the live files."""
    latest_H = None
    runs = repo / "runs/live/runs.jsonl"
    if runs.exists():
        for line in reversed(runs.read_text().splitlines()[-50:]):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if "H" in d and "sha256" in d:
                latest_H = d["H"]
                break
    ent = sorted((repo / "runs/live/paper/ledger/entries").glob("*.json")) if (repo / "runs/live/paper/ledger/entries").exists() else []
    return {"utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "host": socket.gethostname(),
            "latest_producer_hour": latest_H, "latest_ledger_entry": ent[-1].stem if ent else None,
            "ledger_entries": len(ent)}


def sync(repo: Path, clone: Path, items=ITEMS) -> int:
    """Copy each item (file or directory) from repo into clone, replacing files whose size or mtime differ;
    returns the number of files copied. Never deletes from the clone (the backup only grows)."""
    n = 0
    for it in items:
        src = repo / it
        if not src.exists():
            continue
        files = [src] if src.is_file() else [p for p in src.rglob("*") if p.is_file() and not p.name.endswith(".tmp")]
        for f in files:
            dst = clone / f.relative_to(repo)
            st = f.stat()
            if dst.exists() and dst.stat().st_size == st.st_size and int(dst.stat().st_mtime) == int(st.st_mtime):
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            n += 1
    return n


def ssh_env(key) -> dict:
    """Environment for git over ssh with the backup deploy key only."""
    return {**os.environ, "GIT_SSH_COMMAND": (f"ssh -i {key} -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=20 "
                                               f"-o UserKnownHostsFile={CFG / 'known_hosts_github'} -o StrictHostKeyChecking=accept-new")}


def git(clone: Path, *args, key=None, timeout=120):
    return subprocess.run(["git", "-C", str(clone), *args], capture_output=True, text=True, timeout=timeout,
                          env=ssh_env(key) if key else None)


def run_once(repo: Path = REPO, clone: Path = CLONE, remote: str = REMOTE, key=None, push=True) -> dict:
    """One backup: clone if needed, sync, write heartbeat, commit if changed, push. Returns a status dict."""
    key = key or (CFG / "backup_key")
    try:
        if not (clone / ".git").exists():
            r = subprocess.run(["git", "clone", "-q", remote, str(clone)], capture_output=True, text=True, timeout=300,
                               env=ssh_env(key))
            if r.returncode != 0:
                return {"ok": False, "step": "clone", "err": r.stderr[-300:]}
            git(clone, "config", "user.name", "event-pred live backup")
            git(clone, "config", "user.email", "live-backup@users.noreply.github.com")
        copied = sync(repo, clone)
        hb = heartbeat(repo)
        hbp = clone / "heartbeat.json"
        old = json.loads(hbp.read_text()) if hbp.exists() else {}
        keys = ("latest_producer_hour", "latest_ledger_entry", "ledger_entries", "host")
        if any(old.get(k) != hb[k] for k in keys):       # rewritten only on news: about one commit an hour
            hbp.write_text(json.dumps(hb, indent=1) + "\n")
        git(clone, "add", "-A")
        if git(clone, "diff", "--cached", "--quiet").returncode == 0:
            return {"ok": True, "changed": False, "copied": copied, **hb}
        c = git(clone, "commit", "-q", "-m", f"backup {hb['utc']} producer {hb['latest_producer_hour']} ledger {hb['latest_ledger_entry']}")
        if c.returncode != 0:
            return {"ok": False, "step": "commit", "err": c.stderr[-300:]}
        if push:
            p = git(clone, "push", "-q", "origin", "HEAD", key=key)
            if p.returncode != 0:
                return {"ok": False, "step": "push", "err": p.stderr[-300:], "copied": copied}
        return {"ok": True, "changed": True, "copied": copied, **hb}
    except Exception as e:
        return {"ok": False, "step": "exception", "err": repr(e)[:300]}


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        repo, clone, remote = td / "repo", td / "clone", td / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
        seed = td / "seed"
        subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
        (seed / "README.md").write_text("x\n")
        for a in (["config", "user.name", "t"], ["config", "user.email", "t@t"], ["add", "-A"], ["commit", "-q", "-m", "init"],
                  ["push", "-q", "origin", "HEAD:main"]):
            subprocess.run(["git", "-C", str(seed), *a], check=True, capture_output=True)
        (repo / "runs/live/paper/ledger/entries").mkdir(parents=True)
        (repo / "runs/live/scores").mkdir(parents=True)
        (repo / "runs/live/state").mkdir(parents=True)
        (repo / "runs/live/runs.jsonl").write_text(json.dumps({"H": "20261016T03", "sha256": {}}) + "\n" + json.dumps({"info": "w"}) + "\n")
        (repo / "runs/live/paper/ledger/entries/20261016T02.json").write_text("{}")
        (repo / "runs/live/scores/one_20261016T03.parquet").write_bytes(b"p")
        (repo / "runs/live/state/trades2.pkl").write_bytes(b"big")
        (repo / "runs/live/paper/ledger/state.json.tmp").write_text("partial")
        r1 = run_once(repo, clone, str(remote), key=td / "nokey")
        check(f"first backup clones, copies, commits and pushes ({r1})", r1.get("ok") and r1.get("changed"))
        check("heartbeat names the latest producer hour and ledger entry",
              r1.get("latest_producer_hour") == "20261016T03" and r1.get("latest_ledger_entry") == "20261016T02")
        check("the trade store and half-written .tmp files are not copied",
              not (clone / "runs/live/state").exists() and not (clone / "runs/live/paper/ledger/state.json.tmp").exists())
        log = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline", "main"], capture_output=True, text=True).stdout
        check("the push reached the remote", "backup " in log)
        (repo / "runs/live/scores/one_20261016T04.parquet").write_bytes(b"q")
        r2 = run_once(repo, clone, str(remote), key=td / "nokey")
        check("a new hour's file is backed up", r2.get("ok") and (clone / "runs/live/scores/one_20261016T04.parquet").exists())
        r_same = run_once(repo, clone, str(remote), key=td / "nokey")
        check("nothing new -> no commit (the heartbeat is not rewritten)", r_same.get("ok") and r_same.get("changed") is False)
        r3 = run_once(repo, clone, "does-not-matter", key=td / "nokey", push=False)
        check("an unreachable remote or failure never raises", isinstance(r3, dict))
        bad = run_once(repo, td / "clone2", str(td / "missing.git"), key=td / "nokey")
        check("a clone failure is reported, not raised", bad.get("ok") is False and bad.get("step") == "clone")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.once:
        print(json.dumps(run_once()))
    elif a.loop:
        while True:
            print(json.dumps(run_once()), flush=True)
            time.sleep(600)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
