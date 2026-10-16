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


ARM_NAMES = {"g2": "G2", "g": "G", "lin2": "Linear", "mlp2": "Neural", "rnd2": "Random (same share)", "cand": "Quote all",
             "wide3": "Wide spreads", "liq": "Liquid only", "liq_traded": "Liquid (traded markets)", "g2p": "G2 two-level",
             "rnd2p": "Random two-level", "g2w1": "G2 W1", "g2w2": "G2 W2", "g2_sel": "G2 selected categories"}


PAGE = "stg_infra/live_dashboard/index.html"


def publish_page(repo: Path, clone: Path) -> bool:
    """Copy the dashboard page to the backup repo's root (GitHub Pages serves it) and keep .nojekyll there."""
    src, dst = repo / PAGE, clone / "index.html"
    (clone / ".nojekyll").touch()
    if not src.exists() or (dst.exists() and dst.read_bytes() == src.read_bytes()):
        return False
    shutil.copy2(src, dst)
    return True


def build_summary(repo: Path) -> dict:
    """The public dashboard's data (site/summary.json): every ledger entry's cumulative figures per strategy (primary
    window, pessimistic fills) and the test's status. Read-only on the ledger."""
    d = repo / "runs/live/paper/ledger"
    ents = sorted((d / "entries").glob("*.json")) if (d / "entries").exists() else []
    rows, issues, last = [], 0, None
    for f in ents:
        e = json.loads(f.read_text())
        issues += len(e.get("verification") or [])
        last = e
        for a, c in e.get("cumulative", {}).get("primary", {}).items():
            rows.append({"H": e.get("H", f.stem), "arm": ARM_NAMES.get(a, a), "total_usd": round(c["total_usd"], 2),
                         "realised_usd": round(c["realised_usd"], 2), "unrealised_usd": round(c["unrealised_usd"], 2),
                         "capital_usd": round(c["capital_usd"], 2), "fills": c["fills"]})
    st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
    v = (last or {}).get("verdict") or {}
    return {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "live_since": st.get("start_stamp"), "latest_entry": ents[-1].stem if ents else None, "entries": len(ents),
            "verification_issues": issues, "g2_settled_events": v.get("g2_events"),
            "latest_producer_hour": heartbeat(repo)["latest_producer_hour"], "rows": rows}


def write_summary(repo: Path, clone: Path) -> bool:
    """Write site/summary.json if the ledger part changed (atomic). Returns True if it was rewritten."""
    out = clone / "site/summary.json"
    new = build_summary(repo)
    if out.exists():
        old = json.loads(out.read_text())
        if all(old.get(k) == new.get(k) for k in new if k != "generated_utc"):
            return False
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp"); tmp.write_text(json.dumps(new)); tmp.replace(out)
    return True


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
        write_summary(repo, clone)                       # the public dashboard's data (site/)
        publish_page(repo, clone)
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
            # 2026-10-16: a commit made on GitHub (the alert workflow) left the clone behind and every push was refused
            # for 5.5 h; take remote changes first (the backup never edits files GitHub-side commits touch)
            br = git(clone, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
            git(clone, "pull", "-q", "--rebase", "origin", br, key=key)
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
        other = td / "other"                             # someone commits on the remote (as the web editor does)
        subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
        (other / ".github").mkdir(); (other / ".github/alert.yml").write_text("x\n")
        for a_ in (["config", "user.name", "u"], ["config", "user.email", "u@u"], ["add", "-A"], ["commit", "-q", "-m", "web edit"], ["push", "-q", "origin", "HEAD:main"]):
            subprocess.run(["git", "-C", str(other), *a_], check=True, capture_output=True)
        (repo / "runs/live/scores/one_20261016T05.parquet").write_bytes(b"r")
        r4 = run_once(repo, clone, str(remote), key=td / "nokey")
        log2 = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline", "main"], capture_output=True, text=True).stdout
        check(f"a commit made on the remote does not block the next backup ({r4.get('ok')})",
              r4.get("ok") and "web edit" in log2 and log2.splitlines()[0].split(" ", 1)[1].startswith("backup "))
        sm = json.loads((clone / "site/summary.json").read_text())
        check("summary for the public dashboard: entries, status and the latest producer hour",
              sm["entries"] == 1 and sm["latest_entry"] == "20261016T02" and sm["latest_producer_hour"] == "20261016T03")
        check("summary unchanged when the ledger is unchanged (no needless commit)", write_summary(repo, clone) is False)
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
    ap.add_argument("--summary-loop", action="store_true", help="only rewrite site/summary.json every 5 min (no git)")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.once:
        print(json.dumps(run_once()))
    elif a.summary_loop:
        while True:
            try:
                write_summary(REPO, CLONE)
            except Exception as e:
                print(json.dumps({"summary_error": repr(e)[:200]}), flush=True)
            time.sleep(300)
    elif a.loop:
        while True:
            print(json.dumps(run_once()), flush=True)
            time.sleep(600)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
