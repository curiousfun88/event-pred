"""
lumid_sandbox_keeper.py

KEEPS THE SIGNAL PRODUCER RUNNING 24/7 IN LUMID SANDBOXES (plumbing; no change to what is scored
or published).

WHY. Lumid sandboxes expire after at most 24 h (docs: lum.id/docs/sandboxes.md). The producer
needs a machine that is always on; the home folder (/home/<user>) is network storage shared by
every sandbox of the user on one site and survives a sandbox's deletion, so code, venv, state
and logs carry over. The `office` site is used because Kalshi throttles the `home` site's shared
outgoing address (every request 429, 2026-10-11) but not office's (80/80 at the producer's rate).

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
SITE_API = "https://lum.id/sbx/office/api"
GW = ["-p", "31226", "gw@lum.id"]
HOME = Path(f"/home/{USER}")
REPO = HOME / "event-pred"
CFG = HOME / ".lumid"
PAT_FILE, KEY_FILE, PRODUCER_CMD_FILE = CFG / "sbx_pat", CFG / "sbx_key", CFG / "producer_cmd"
LOG = REPO / "logs/sbx_keeper.log"
RUNS = REPO / "runs/live/runs.jsonl"
START = REPO / "stg_infra/lumid_start.sh"
NAMES = ("prod-a", "prod-b")
SPEC = {"cpu": 2, "memory_gi": 8, "ttl_hours": 24}
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


def producer_pids():
    r = subprocess.run(["pgrep", "-f", "[l]ive_signal_producer.py"], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split() if int(p) != os.getpid()]


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
    api("POST", "/sandboxes", {"name": succ, **SPEC})
    for _ in range(60):
        time.sleep(10)
        row = next((r for r in api("GET", "/sandboxes")["sandboxes"] if r["name"] == succ), None)
        if row and row.get("phase") == "Running":
            break
    else:
        log("handover failed: successor not Running; deleting it, will retry", successor=succ)
        api("DELETE", f"/sandboxes/{succ}")
        return False
    for p in producer_pids():
        os.kill(p, 15)
    log("producer stopped here; starting in successor", successor=succ)
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
