"""
lumid_sandbox_keeper.py

KEEPS THE SIGNAL PRODUCER RUNNING 24/7 IN LUMID SANDBOXES (plumbing; no change to what is scored
or published).

WHY. Lumid sandboxes expire after at most 24 h (docs: lum.id/docs/sandboxes.md). The producer
needs a machine that is always on; the home folder (/home/<user>) is network storage shared by
every sandbox of the user on one site and survives a sandbox's deletion, so code, venv, state
and logs carry over. The `office` site was used first because Kalshi throttles the `home` site's shared
outgoing address (every request 429 at 8/s, 2026-10-11) but not office's (80/80 at the producer's rate). Since
L13 (--bulk, ~400 calls an hour) a home cycle completes in ~9 min despite the throttling, so either site can host
it; ~/.lumid/site selects the site.

WHAT. Runs beside the producer in the sandbox, every CHECK_S seconds:
  1. watchdog: if no producer process is running here, start it (command in PRODUCER_CMD_FILE);
  2. renewal: when this sandbox has < LEAD_S left, at a quiet time (the current hour's cycle is
     logged and the minute is in QUIET_MIN..QUIET_MAX) -- or at any time once < LAST_CHANCE_S is
     left -- create a successor sandbox, stop the producer here, start keeper + producer in the
     successor over the SSH gateway (a plain `ssh gw@lum.id '<cmd>'` lands in the user's NEWEST
     running sandbox, i.e. the successor), confirm it is running there, then delete this one.
Every step is appended to LOG (shared home), so a handover can be audited afterwards.

FILES (shared home, never in the repo): ~/.lumid/sbx_pat (token with sandbox:sandboxes:write),
~/.lumid/sbx_key (SSH key on the Lumid account), ~/.lumid/producer_cmd (the producer command line).

USAGE (inside a sandbox, from the repo root):
    python stg_infra/lumid_sandbox_keeper.py --self-test
    python stg_infra/lumid_sandbox_keeper.py --run        # normally started by lumid_start.sh
    python stg_infra/lumid_sandbox_keeper.py --status
    python stg_infra/lumid_sandbox_keeper.py --handover-now   # test a handover between cycles
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

USER = "curiouslearner842"
HOME = Path(f"/home/{USER}")
REPO = HOME / "event-pred"
CFG = HOME / ".lumid"
# Each site has its own shared home, so ~/.lumid/site names the site this keeper runs on (default office).
# 2026-10-15: office down for over a day; home added as a second host (pinned image: the venv lives in the
# shared home and is bound to the image's Python).
SITES = {"office": {"api": "https://lum.id/sbx/office/api", "port": "31226", "spec": {}},
         "home": {"api": "https://lum.id/sbx/api", "port": "31223", "spec": {"image": "python:3.11"}}}


def site_conf(cfg_dir: Path = CFG) -> dict:
    f = cfg_dir / "site"
    name = f.read_text().strip() if f.exists() else "office"
    return {"name": name, **SITES[name]}


SITE = site_conf()
SITE_API = SITE["api"]
GW = ["-p", SITE["port"], "gw@lum.id"]
PAT_FILE, KEY_FILE, PRODUCER_CMD_FILE = CFG / "sbx_pat", CFG / "sbx_key", CFG / "producer_cmd"
PAPER_CMD_FILE = CFG / "paper_cmd"   # paper trader (L3/L7): started and watched iff this file exists
LOG = REPO / "logs/sbx_keeper.log"
RUNS = REPO / "runs/live/runs.jsonl"
START = REPO / "stg_infra/lumid_start.sh"
NAMES = ("prod-a", "prod-b")
SPEC = {"cpu": 2, "memory_gi": 8, "ttl_hours": 24, **SITE["spec"]}
CHECK_S = 300
LEAD_S = 3 * 3600            # start looking for a quiet moment 3 h before expiry
LAST_CHANCE_S = 45 * 60      # hand over regardless of the producer once this little is left
QUIET_MIN, QUIET_MAX = 40, 57


# ---------------------------------------------------------------- decisions (pure, self-tested)

def my_name(hostname: str) -> str:
    """Pod hostname is sbx-<user>-<name>."""
    pre = f"sbx-{USER}-"
    return hostname[len(pre):] if hostname.startswith(pre) else hostname


def successor_name(mine: str, existing) -> str | None:
    for n in NAMES:
        if n != mine and n not in existing:
            return n
    return None


def should_hand_over(now: float, expires_at: float, minute: int, hour_logged: bool) -> str | None:
    left = expires_at - now
    if left >= LEAD_S:
        return None
    if left < LAST_CHANCE_S:
        return "last chance"
    if hour_logged and QUIET_MIN <= minute <= QUIET_MAX:
        return "quiet"
    return None


def hour_logged(runs_lines, now_utc: dt.datetime) -> bool:
    stamp = now_utc.strftime("%Y%m%dT%H")
    for line in reversed(runs_lines[-50:]):
        try:
            if json.loads(line).get("H") == stamp:
                return True
        except ValueError:
            continue
    return False


# ---------------------------------------------------------------- side effects

def log(msg, **kw):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"t": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "host": socket.gethostname(),
           "msg": msg, **kw}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec), flush=True)


def api(method, path, body=None):
    import urllib.request
    req = urllib.request.Request(f"{SITE_API}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {PAT_FILE.read_text().strip()}",
                                          "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def ssh_gw(cmd, timeout=120):
    known = CFG / "known_hosts"
    return subprocess.run(["ssh", "-i", str(KEY_FILE), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
                           "-o", f"UserKnownHostsFile={known}", "-o", "StrictHostKeyChecking=accept-new",
                           *GW, cmd], capture_output=True, text=True, timeout=timeout)


def proc_pattern(script: str, py: str = None) -> str:
    """pgrep -f pattern for '<venv python> stg_infra/<script>' at the START of a command line only. 2026-10-15: the
    unanchored '[l]ive_signal_producer.py' matched an ssh shell whose text merely mentioned the script, and the
    watchdog took it for a running producer (start delayed 5 min)."""
    import re
    py = py or str(HOME / "venv/bin/python")
    return "^" + re.escape(py) + r" stg_infra/" + re.escape(script)


def _pids(script):
    r = subprocess.run(["pgrep", "-f", proc_pattern(script)], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split() if int(p) != os.getpid()]


def producer_pids():
    return _pids("live_signal_producer.py")


def paper_pids():
    return _pids("paper_trader.py --loop")


def start_paper():
    cmd = PAPER_CMD_FILE.read_text().strip()
    subprocess.Popen(["bash", "-c", f"cd {REPO} && exec {cmd} >> logs/paper_trader.log 2>&1"],
                     stdin=subprocess.DEVNULL, start_new_session=True)


def start_producer():
    cmd = PRODUCER_CMD_FILE.read_text().strip()
    subprocess.Popen(["bash", "-c", f"cd {REPO} && exec {cmd} >> logs/sbx_producer.log 2>&1"],
                     stdin=subprocess.DEVNULL, start_new_session=True)


def hand_over(me, rows, reason):
    succ = successor_name(me, {r["name"] for r in rows})
    if succ is None:
        log("handover blocked: no free successor name", existing=[r["name"] for r in rows])
        return False
    log("handover: creating successor", successor=succ, reason=reason)
    try:
        api("POST", "/sandboxes", {"name": succ, **SPEC})
    except Exception as e:
        if "409" in repr(e):    # 2026-10-13: Lumid allows two sandboxes per account; a third holder blocks this
            log("handover blocked: 409 Conflict (another sandbox holds the account's second slot?)",
                existing=[r["name"] for r in rows])
            return False
        raise
    for _ in range(60):
        time.sleep(10)
        row = next((r for r in api("GET", "/sandboxes")["sandboxes"] if r["name"] == succ), None)
        if row and row.get("phase") == "Running":
            break
    else:
        log("handover failed: successor not Running; deleting it, will retry", successor=succ)
        api("DELETE", f"/sandboxes/{succ}")
        return False
    for p in producer_pids() + paper_pids():
        os.kill(p, 15)
    log("producer (and paper trader) stopped here; starting in successor", successor=succ)
    r = ssh_gw(f"bash {START}")
    time.sleep(20)
    # "[l]ive..." matches the process but not this command line itself, which would otherwise
    # make pgrep report the check's own shell as a running producer/keeper
    chk = ssh_gw("hostname; pgrep -f '[l]ive_signal_producer.py' >/dev/null && echo PRODUCER_OK; "
                 "pgrep -f '[l]umid_sandbox_keeper.py --run' >/dev/null && echo KEEPER_OK")
    ok = f"sbx-{USER}-{succ}" in chk.stdout and "PRODUCER_OK" in chk.stdout and "KEEPER_OK" in chk.stdout
    if not ok:
        log("handover failed: successor not confirmed; restarting producer here", start=r.stdout[-300:],
            check=chk.stdout[-300:], err=chk.stderr[-300:])
        start_producer()
        return False
    log("handover confirmed; deleting this sandbox", successor=succ)
    api("DELETE", f"/sandboxes/{me}")
    return True


def run():
    me = my_name(socket.gethostname())
    log("keeper started", sandbox=me)
    while True:
        try:
            if not producer_pids():
                log("watchdog: producer not running; starting it")
                start_producer()
            if PAPER_CMD_FILE.exists() and not paper_pids():
                log("watchdog: paper trader not running; starting it")
                start_paper()
            rows = api("GET", "/sandboxes")["sandboxes"]
            mine = next((r for r in rows if r["name"] == me), None)
            if mine and mine.get("expires_at"):
                now = time.time()
                utc = dt.datetime.now(dt.timezone.utc)
                lines = RUNS.read_text().splitlines() if RUNS.exists() else []
                reason = should_hand_over(now, float(mine["expires_at"]), utc.minute, hour_logged(lines, utc))
                if reason and hand_over(me, rows, reason):
                    return
        except Exception as e:                      # never die: a dead keeper means a dead producer at expiry
            log("keeper error", error=repr(e)[:300])
        time.sleep(CHECK_S)


def status():
    rows = api("GET", "/sandboxes")["sandboxes"]
    for r in rows:
        left = (float(r["expires_at"]) - time.time()) / 3600 if r.get("expires_at") else float("nan")
        print(f"{r['name']:<10} {r.get('phase'):<10} expires in {left:5.1f} h")
    print("producer here:", producer_pids())
    print("paper trader here:", paper_pids(), "(enabled)" if PAPER_CMD_FILE.exists() else "(disabled: no paper_cmd)")


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    check("name from pod hostname", my_name(f"sbx-{USER}-prod-a") == "prod-a" and my_name("x") == "x")
    check("successor alternates prod-a / prod-b", successor_name("prod-a", {"prod-a"}) == "prod-b"
          and successor_name("prod-b", {"prod-b"}) == "prod-a")
    check("the first handover from a hand-made sandbox picks prod-a", successor_name("dev", {"dev"}) == "prod-a")
    check("no successor name free -> None", successor_name("dev", {"dev", "prod-a", "prod-b"}) is None)
    T = 1_000_000.0
    check("plenty of time -> no handover", should_hand_over(T, T + 5 * 3600, 45, True) is None)
    check("inside the lead window, quiet minute, hour logged -> quiet",
          should_hand_over(T, T + 2 * 3600, 45, True) == "quiet")
    check("inside the lead window but cycle not logged -> wait",
          should_hand_over(T, T + 2 * 3600, 45, False) is None)
    check("inside the lead window but minute 10 (cycle time) -> wait",
          should_hand_over(T, T + 2 * 3600, 10, True) is None)
    check("under 45 min left -> hand over regardless", should_hand_over(T, T + 30 * 60, 10, False) == "last chance")
    now = dt.datetime(2026, 10, 11, 15, 45, tzinfo=dt.timezone.utc)
    lines = [json.dumps({"H": "20261011T14"}), "not json", json.dumps({"H": "20261011T15"})]
    check("hour logged when runs.jsonl has this hour", hour_logged(lines, now))
    check("hour not logged when only the previous hour is", not hour_logged(lines[:2], now))
    import re
    pat = proc_pattern("live_signal_producer.py", "/home/u/venv/bin/python")
    check("watchdog pattern matches the producer process",
          re.search(pat, "/home/u/venv/bin/python stg_infra/live_signal_producer.py --loop --fleet") is not None)
    check("watchdog pattern ignores a shell that only mentions the script",
          re.search(pat, '/bin/sh -c echo "/home/u/venv/bin/python stg_infra/live_signal_producer.py" > cmd') is None)
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        check("no site file -> office (port 31226)", site_conf(Path(td))["port"] == "31226")
        (Path(td) / "site").write_text("home\n")
        sc = site_conf(Path(td))
        check("site file 'home' -> home API, port 31223, pinned python:3.11",
              sc["api"] == "https://lum.id/sbx/api" and sc["port"] == "31223" and sc["spec"] == {"image": "python:3.11"})
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--handover-now", action="store_true", help="test the handover once, now")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if a.run:
        run()
    elif a.status:
        status()
    elif a.handover_now:
        me = my_name(socket.gethostname())
        hand_over(me, api("GET", "/sandboxes")["sandboxes"], "manual test")
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
