"""
failover.py

Move the live test to the other Lumid site with one command, from the LAPTOP (2026-10-22, after the home-volume outage).
The laptop needs Lumid and GitHub only, not Kalshi.

    python stg_infra/failover.py --to office            # home has failed: move to office
    python stg_infra/failover.py --to home --dry-run    # show what would happen, change nothing
    python stg_infra/failover.py --self-test

Steps, each checked before the next; any failure stops the run and says what is left:
  1. the failed site: list its sandboxes; delete every one (prod-a, prod-b) so a recovering sandbox cannot run a second
     producer. If its API does not answer, stop unless --failed-unreachable-ok is given (then delete them later by hand).
  2. the target site: refuse if a keeper is already running there; delete leftover sandboxes; create prod-a
     (4 cores, 16 GB, 24 h); wait until Running.
  3. health: time a file read, a directory listing and a Python start-up on the target's home volume, and reach Kalshi
     and GitHub from it. On failure delete the sandbox and stop (this is the check that would have caught the hung home
     volume of 2026-10-22).
  4. keys: copy sbx_pat, sbx_key, lumid_pat, backup_key and hc_ping_url from the laptop into ~/.lumid (never via GitHub).
  5. restore: run stg_infra/restore_on_site.sh <target> in the sandbox (code and models from event-pred, live state from
     the event-pred-live backup, posted list, commands, self-tests).
  6. start the keeper (lumid_start.sh) and wait until the producer and paper trader are running.
Afterwards: record the move in the pre-registration's host log.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SITES = {"office": {"api": "https://lum.id/sbx/office/api", "port": "31226"},
         "home": {"api": "https://lum.id/sbx/api", "port": "31223"}}
SPEC = {"name": "prod-a", "image": "python:3.11", "cpu": 4, "memory_gi": 16, "ttl_hours": 24}
U = "curiouslearner842"
HOME = f"/home/{U}"
KEYS = {"sbx_pat": Path.home() / ".lumid_sbx_pat", "sbx_key": Path.home() / ".ssh/lumid_sbx_ed25519",
        "lumid_pat": Path.home() / ".lumid_pat", "backup_key": Path.home() / ".ssh/event_pred_live_backup",
        "hc_ping_url": Path.home() / ".lumid_hc_ping_url"}
SSH_KEY = Path.home() / ".ssh/lumid_sbx_ed25519"
# health limits: a healthy volume reads a small file in ~2 ms and starts Python with numpy in ~3.5 s
READ_MAX_MS, LIST_MAX_MS, PY_MAX_MS = 2000, 2000, 30000
HEALTH_CMD = (f"H={HOME}; t(){{ s=$(date +%s%N); \"$@\" >/dev/null 2>&1; r=$?; echo \"$(( ($(date +%s%N)-s)/1000000 )) $r\"; }}; "
              f"t cat $H/venv/bin/activate; t ls $H; t $H/venv/bin/python -c 'import numpy'; "
              "curl -s -o /dev/null -w '%{http_code}\\n' --max-time 20 "
              "https://api.elections.kalshi.com/trade-api/v2/exchange/status; "
              "curl -s -o /dev/null -w '%{http_code}\\n' --max-time 20 https://github.com")


class Stop(Exception):
    """A step failed: the run stops here with this message."""


# ---------------------------------------------------------------- the two ways of talking to Lumid

def api(site, method, path, body=None, pat=None):
    pat = pat or KEYS["sbx_pat"].read_text().strip()
    req = urllib.request.Request(SITES[site]["api"] + path, method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {pat}", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read() or b"{}")


def ssh(site, cmd, stdin=None, timeout=300):
    """Run cmd in the site's newest sandbox. Returns (returncode, stdout); a timeout returns (124, '')."""
    try:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", "-p", SITES[site]["port"],
                            "-i", str(SSH_KEY), "gw@lum.id", cmd], input=stdin, capture_output=True, timeout=timeout)
        return r.returncode, r.stdout.decode(errors="replace")
    except subprocess.TimeoutExpired:
        return 124, ""


# ---------------------------------------------------------------- decisions (pure, self-tested)

def other(site):
    return "home" if site == "office" else "office"


def judge_health(out: str) -> tuple[bool, str]:
    """HEALTH_CMD's output -> (healthy, reason). Lines: read ms rc, list ms rc, python ms rc, kalshi code, github code."""
    lines = [l.split() for l in out.strip().splitlines()]
    if len(lines) < 5:
        return False, f"health check incomplete ({len(lines)} of 5 lines): the home volume or network hung"
    (r_ms, r_rc), (l_ms, l_rc), (p_ms, p_rc) = [(int(a), int(b)) for a, b in lines[:3]]
    kalshi, github = lines[3][0], lines[4][0]
    if r_rc or l_rc or p_rc:
        return False, f"a home-volume command failed (rc {r_rc}, {l_rc}, {p_rc})"
    if r_ms > READ_MAX_MS or l_ms > LIST_MAX_MS or p_ms > PY_MAX_MS:
        return False, f"home volume too slow: read {r_ms} ms, list {l_ms} ms, Python {p_ms} ms"
    if kalshi != "200":
        return False, f"Kalshi not reachable from the sandbox (HTTP {kalshi})"
    if github != "200":
        return False, f"GitHub not reachable from the sandbox (HTTP {github})"
    return True, f"healthy: read {r_ms} ms, list {l_ms} ms, Python {p_ms} ms, Kalshi and GitHub 200"


# ---------------------------------------------------------------- the run

def run(to, failed_unreachable_ok=False, dry=False, api_=api, ssh_=ssh, sleep=time.sleep, say=print, keys=KEYS):
    frm = other(to)
    say(f"failover: {frm} -> {to}{' (dry run: nothing is changed)' if dry else ''}")
    missing = [k for k, p in keys.items() if not Path(p).exists()]
    if missing:
        raise Stop(f"laptop keys missing: {missing}")

    # 1. the failed site
    try:
        old = [s["name"] for s in api_(frm, "GET", "/sandboxes")["sandboxes"]]
    except Exception as e:
        if not failed_unreachable_ok:
            raise Stop(f"{frm}'s API does not answer ({e!r}). Its sandbox may come back and run a second producer. "
                       "Re-run with --failed-unreachable-ok to go on, then delete it by hand when the API answers.")
        say(f"1. {frm}: API unreachable; going on (delete its sandboxes by hand later)")
        old = []
    for name in old:
        say(f"1. {frm}: delete {name}")
        if not dry:
            api_(frm, "DELETE", f"/sandboxes/{name}")
    if not old:
        say(f"1. {frm}: no sandbox to delete")

    # 2. the target site
    rows = api_(to, "GET", "/sandboxes")["sandboxes"]
    if rows:
        rc, out = ssh_(to, "pgrep -f '[l]umid_sandbox_keeper.py --run' >/dev/null && echo KEEPER_RUNNING || echo none", timeout=60)
        if "KEEPER_RUNNING" in out:
            raise Stop(f"a keeper is already running on {to} ({[r['name'] for r in rows]}): nothing to fail over")
        for r in rows:
            say(f"2. {to}: delete leftover {r['name']}")
            if not dry:
                api_(to, "DELETE", f"/sandboxes/{r['name']}")
    say(f"2. {to}: create {SPEC['name']} ({SPEC['cpu']} cores, {SPEC['memory_gi']} GB, {SPEC['ttl_hours']} h)")
    if dry:
        say("   (dry run stops here)")
        return "dry-run"
    api_(to, "POST", "/sandboxes", SPEC)
    for _ in range(40):
        row = next((r for r in api_(to, "GET", "/sandboxes")["sandboxes"] if r["name"] == SPEC["name"]), None)
        if row and row.get("phase") == "Running":
            break
        sleep(15)
    else:
        api_(to, "DELETE", f"/sandboxes/{SPEC['name']}")
        raise Stop(f"{to}: the sandbox did not reach Running in 10 minutes; deleted it")
    say(f"2. {to}: running on {row.get('node')}")

    # 3. health
    rc, out = ssh_(to, HEALTH_CMD, timeout=120)
    ok, why = judge_health(out)
    say(f"3. health: {why}")
    if not ok:
        api_(to, "DELETE", f"/sandboxes/{SPEC['name']}")
        raise Stop(f"{to} is not healthy; deleted its sandbox. The live test is not running anywhere: try again later "
                   "or report the site to Lumid")

    # 4. keys
    for name, path in keys.items():
        rc, out = ssh_(to, f"mkdir -p {HOME}/.lumid && chmod 700 {HOME}/.lumid && cat > {HOME}/.lumid/{name} && "
                           f"chmod 600 {HOME}/.lumid/{name} && echo ok", stdin=Path(path).read_bytes(), timeout=60)
        if "ok" not in out:
            raise Stop(f"4. could not copy the key {name} (rc {rc})")
    say("4. keys copied (sbx_pat, sbx_key, lumid_pat, backup_key, hc_ping_url)")

    # 5. restore
    script = (REPO / "stg_infra/restore_on_site.sh").read_bytes()
    rc, out = ssh_(to, f"cat > /tmp/restore.sh && bash /tmp/restore.sh {to}", stdin=script, timeout=1500)
    for line in out.splitlines():
        say("   " + line)
    if rc != 0 or "restore done" not in out or "FAILED" in out or "MISSING" in out:
        raise Stop(f"5. restore did not finish cleanly (rc {rc}); the sandbox is left as it is for inspection")
    say("5. restore done")

    # 6. keeper
    rc, out = ssh_(to, f"bash {HOME}/event-pred/stg_infra/lumid_start.sh", timeout=60)
    say(f"6. {out.strip()}")
    for _ in range(20):
        sleep(15)
        rc, out = ssh_(to, "pgrep -f '[l]ive_signal_producer.py --loop' >/dev/null && echo P; "
                           "pgrep -f '[p]aper_trader.py --loop' >/dev/null && echo T", timeout=60)
        if "P" in out.split() and "T" in out.split():
            say(f"6. producer and paper trader running on {to}")
            break
    else:
        raise Stop("6. the keeper did not start the producer and paper trader within 5 minutes: check logs/sbx_keeper.log")
    say("done. Next: check that the next producer hour completes and that the backup resumes; record the move in the "
        "host log (docs/planning/lumid-forward-test-preregistration.md).")
    return "ok"


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")

    check("other(): home <-> office", other("home") == "office" and other("office") == "home")
    good = "3 0\n2 0\n3400 0\n200\n200\n"
    check("health: a normal volume and network pass", judge_health(good)[0])
    check("health: the 2026-10-22 hung volume (15 s read) fails",
          not judge_health("15221 0\n29439 0\n45000 0\n200\n200\n")[0])
    check("health: an incomplete check (volume hung mid-way) fails", not judge_health("15221 0\n")[0])
    check("health: Kalshi unreachable fails", not judge_health("3 0\n2 0\n3400 0\n000\n200\n")[0])
    check("health: GitHub unreachable fails", not judge_health("3 0\n2 0\n3400 0\n200\n503\n")[0])
    check("health: a failing command fails", not judge_health("3 0\n2 2\n3400 0\n200\n200\n")[0])

    tmp = Path(tempfile.mkdtemp())
    keys = {k: tmp / k for k in KEYS}
    for p in keys.values():
        p.write_text("secret")

    class World:
        """Fake Lumid: sandboxes per site, an API that may be down, a health output, a keeper flag."""
        def __init__(self, sbx, down=(), health=good, keeper_on=(), restore_ok=True):
            self.sbx, self.down, self.health, self.keeper_on, self.restore_ok = sbx, set(down), health, set(keeper_on), restore_ok
            self.calls = []

        def api(self, site, method, path, body=None):
            self.calls.append((site, method, path))
            if site in self.down:
                raise OSError("unreachable")
            if method == "GET":
                return {"sandboxes": [{"name": n, "phase": "Running", "node": "n1"} for n in self.sbx[site]]}
            if method == "DELETE":
                self.sbx[site].remove(path.rsplit("/", 1)[1])
            if method == "POST":
                self.sbx[site].append(body["name"])
            return {}

        def ssh(self, site, cmd, stdin=None, timeout=0):
            self.calls.append((site, "ssh", cmd[:20]))
            if "KEEPER_RUNNING" in cmd:
                return 0, "KEEPER_RUNNING" if site in self.keeper_on else "none"
            if cmd.startswith("H="):
                return 0, self.health
            if "restore.sh" in cmd:
                return (0, "6. checks\nrestore done; start nothing yet") if self.restore_ok else (1, "self-test FAILED")
            if "lumid_start" in cmd:
                self.keeper_on.add(site)
                return 0, "keeper started"
            if "pgrep -f '[l]ive" in cmd:
                return 0, "P\nT" if site in self.keeper_on else ""
            return 0, "ok"

    quiet = lambda *a: None
    w = World({"home": ["prod-b"], "office": []})
    res = run("office", api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys)
    check("success: the failed site's sandbox is deleted first, then office is created, checked, restored, started",
          res == "ok" and w.sbx["home"] == [] and w.sbx["office"] == ["prod-a"] and "office" in w.keeper_on
          and w.calls.index(("home", "DELETE", "/sandboxes/prod-b")) < w.calls.index(("office", "POST", "/sandboxes")))

    w = World({"home": ["prod-b"], "office": []}, down={"home"})
    try:
        run("office", api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys); r = "ran"
    except Stop:
        r = "stopped"
    check("failed site unreachable: stops before touching office (a second producer could appear)",
          r == "stopped" and w.sbx["office"] == [])
    w = World({"home": ["prod-b"], "office": []}, down={"home"})
    res = run("office", failed_unreachable_ok=True, api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys)
    check("... unless --failed-unreachable-ok: goes on", res == "ok" and "office" in w.keeper_on)

    w = World({"home": [], "office": ["prod-a"]}, keeper_on={"office"})
    try:
        run("office", api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys); r = "ran"
    except Stop:
        r = "stopped"
    check("a keeper already running on the target: stops, deletes nothing there",
          r == "stopped" and w.sbx["office"] == ["prod-a"])

    w = World({"home": ["prod-a"], "office": []}, health="15221 0\n29439 0\n")
    try:
        run("office", api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys); r = "ran"
    except Stop:
        r = "stopped"
    check("unhealthy target: its new sandbox is deleted, no keys copied, nothing started",
          r == "stopped" and w.sbx["office"] == [] and "office" not in w.keeper_on
          and not any(c[1] == "ssh" and c[2].startswith("mkdir") for c in w.calls))

    w = World({"home": [], "office": []}, restore_ok=False)
    try:
        run("office", api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys); r = "ran"
    except Stop:
        r = "stopped"
    check("restore fails: stops before starting the keeper", r == "stopped" and "office" not in w.keeper_on)

    w = World({"home": ["prod-b"], "office": []})
    res = run("office", dry=True, api_=w.api, ssh_=w.ssh, sleep=lambda s: None, say=quiet, keys=keys)
    check("dry run: deletes and creates nothing", res == "dry-run" and w.sbx == {"home": ["prod-b"], "office": []})

    keys2 = dict(keys, backup_key=tmp / "absent")
    try:
        run("office", api_=World({"home": [], "office": []}).api, ssh_=lambda *a, **k: (0, ""), say=quiet, keys=keys2); r = "ran"
    except Stop:
        r = "stopped"
    check("a laptop key missing: stops before any action", r == "stopped")
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", choices=sorted(SITES))
    ap.add_argument("--failed-unreachable-ok", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if not a.to:
        ap.error("--to is required")
    try:
        run(a.to, a.failed_unreachable_ok, a.dry_run)
    except Stop as e:
        print(f"STOPPED: {e}")
        sys.exit(2)


if __name__ == "__main__":
    main()
