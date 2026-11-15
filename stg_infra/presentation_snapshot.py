"""
presentation_snapshot.py -- freeze the live test's results at the final presentation (17 Nov 2026, 06:00 UTC =
14:00 Singapore) as a permanent, read-only Lumid Dataset, and record its fingerprint in a Research Fleet job NAME.

Why: Research Fleet deletes job results after about 72 hours but keeps job names and timestamps; a Dataset on the
office site is stored read-only with no documented expiry. The snapshot is DESCRIPTIVE (the test as it stood at the
presentation); the pre-registered verdicts stay at the final cut (11 Nov).

Files uploaded, byte for byte as on this server at run time:
    summary.json              the dashboard's data (every strategy's settled net P&L, capital, return, events)
    ledger/entries/<H>.json   every hash-chained ledger entry (identical to the public event-pred-live repo)
    runs.jsonl                every hourly producer record, with the SHA-256 of that hour's files
    README.txt                what this is and how to verify it
    SHA256SUMS                sha256 of every file above
Then one Research Fleet job named fwdtest-snapshot-<label>_<key results>_ledger.<head hash>_sums.<sha256 of SHA256SUMS>.

    python stg_infra/presentation_snapshot.py --self-test
    python stg_infra/presentation_snapshot.py --label 20261117T06 --dry-run
    python stg_infra/presentation_snapshot.py --label 20261117T06 --rehearse     # throwaway dataset, deleted after
    python stg_infra/presentation_snapshot.py --label 20261117T06                # the real snapshot
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
from pathlib import Path

HOME = Path.home()
REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "runs/live"
SUMMARY = HOME / "live-backup/site/summary.json"
SBX = "https://lum.id/sbx/office/api"
FLEET = "https://lum.id/api/v1/me/fleet/jobs"
OUT = HOME / "snapshots"
# dashboard arm name -> short code used in the Fleet job name
ARMS = [("G2", "g2"), ("Random (same share)", "rnd2"), ("Quote all", "cand"), ("Linear", "lin2"),
        ("Neural", "mlp2"), ("G2 two-level", "g2p"), ("Random two-level", "rnd2p"), ("G2 selected categories", "g2sel"),
        ("G", "g"), ("G2 W1", "w1"), ("G2 W2", "w2"), ("Wide spreads", "wide3"), ("Liquid only", "liq"),
        ("Liquid (traded markets)", "liqt")]
NAME_MAX = 1000          # a 1,000-character job name was stored byte for byte (tested 2026-11-15)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def num(x) -> str:
    """Compact number for a job name: digits, '.', '-' only."""
    return f"{float(x):.2f}".rstrip("0").rstrip(".") if x is not None else "na"


def key_results(summary: dict, universe="train23") -> list:
    rows = {r["arm"]: r for r in summary.get("settled", []) if r.get("universe") == universe}
    return [(code, rows[a]) for a, code in ARMS if a in rows]


def job_name(label: str, results: list, ledger_head: str, sums_sha: str) -> str:
    parts = [f"{c}.n{num(r['net_usd'])}.r{num(r['return_pct'])}.e{int(r['events'])}" for c, r in results]
    name = f"fwdtest-snapshot-{label}_" + "_".join(parts) + f"_ledger.{ledger_head}_sums.{sums_sha}"
    if len(name) > NAME_MAX:                          # drop descriptive arms from the end, never the hashes or G2/random
        while len(name) > NAME_MAX and len(parts) > 3:
            parts.pop()
            name = f"fwdtest-snapshot-{label}_" + "_".join(parts) + f"_ledger.{ledger_head}_sums.{sums_sha}"
    return name


def build(label: str, live: Path, summary_path: Path, out_root: Path) -> dict:
    """Collect the files (bytes as on disk) and write them, with README and SHA256SUMS, to out_root/label."""
    files = {"summary.json": summary_path.read_bytes(), "runs.jsonl": (live / "runs.jsonl").read_bytes()}
    entries = sorted((live / "paper/ledger/entries").glob("*.json"))
    for f in entries:
        files[f"ledger/entries/{f.name}"] = f.read_bytes()
    head = json.loads(entries[-1].read_text())
    summary = json.loads(files["summary.json"])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    readme = (
        f"event-pred live forward test: snapshot {label} (taken {now})\n\n"
        "The live paper-trading test (G2 market maker on Kalshi MECE baskets) as it stood at the final presentation,\n"
        "17 November 2026, 14:00 Singapore time. DESCRIPTIVE: the pre-registered verdicts are at the final cut (fills\n"
        "before 11 Nov 2026, settled by 13 Nov).\n\n"
        "summary.json            the dashboard's data; 'settled' rows with universe 'train23' are the main result\n"
        "ledger/entries/<H>.json the hash-chained ledger: each entry's prev_hash is the previous entry's hash\n"
        "runs.jsonl              every hourly producer record, with the sha256 of that hour's score and signal files\n"
        "SHA256SUMS              sha256 of every file here\n\n"
        f"Ledger head: {head['H']} {head['hash']}\n"
        f"Ledger entries: {len(entries)}\n"
        f"Live start: {summary.get('live_since')}\n\n"
        "Verify: (1) `sha256sum -c SHA256SUMS` in this directory; (2) the sha256 of SHA256SUMS appears in the name of the\n"
        "Research Fleet job fwdtest-snapshot-<label>_..._sums.<sha256>; (3) the ledger entries are identical to\n"
        "github.com/curiousfun88/event-pred-live (runs/live/paper/ledger/entries), whose history and OpenTimestamps\n"
        "proofs fix when each entry existed.\n")
    files["README.txt"] = readme.encode()
    sums = "".join(f"{sha256(b)}  {p}\n" for p, b in sorted(files.items())).encode()
    files["SHA256SUMS"] = sums
    d = out_root / label
    for p, b in files.items():
        (d / p).parent.mkdir(parents=True, exist_ok=True)
        (d / p).write_bytes(b)
    results = key_results(summary)
    return {"dir": d, "files": files, "head": head, "sums_sha": sha256(sums), "results": results,
            "name": job_name(label, results, head["hash"], sha256(sums))}


def dataset_name(label: str, rehearse: bool = False) -> str:
    """Lumid dataset names: lowercase letters, digits, '.', '-', '_', starting alphanumeric, at most 64 characters."""
    import re
    name = re.sub(r"[^a-z0-9._-]", "-", f"event-pred-live-snapshot-{label}".lower()) + ("-rehearsal" if rehearse else "")
    return name[:64]


def upload(dataset: str, note: str, files: dict, sbx_pat: str, log, tries=4) -> bool:
    import requests
    H = {"Authorization": f"Bearer {sbx_pat}"}
    r = requests.post(f"{SBX}/datasets", json={"name": dataset, "note": note[:200]}, headers=H, timeout=60)
    if r.status_code not in (200, 201):
        log(f"create {dataset}: HTTP {r.status_code} {r.text[:200]}")
        return False
    ok = True
    for p, b in sorted(files.items()):
        for k in range(tries):
            try:
                r = requests.put(f"{SBX}/datasets/{dataset}/files/{p}", data=b, headers=H, timeout=120)
                if r.status_code == 200 and int(r.json().get("bytes", -1)) == len(b):
                    break
                err = f"HTTP {r.status_code} {r.text[:120]}"
            except Exception as e:
                err = repr(e)[:160]
            time.sleep(5 * (k + 1))
        else:
            log(f"upload FAILED {p}: {err}")
            ok = False
    listed = next((d for d in requests.get(f"{SBX}/datasets", headers=H, timeout=60).json().get("datasets", [])
                   if d["name"] == dataset), None)
    log(f"dataset {dataset}: listed {listed}")
    return ok and listed is not None and listed.get("files", 0) >= len(files)


def post_name(name: str, out: dict, pat: str, log) -> str:
    import requests
    code = (f"import json\nOUT = json.loads({json.dumps(json.dumps(out))})\n\n\n"
            f"def main():\n    return {{'metrics': {{}}, 'output': OUT}}\n")
    wf = {"apiVersion": "flowmesh/v1", "kind": "Task", "metadata": {"name": name},
          "spec": {"taskType": "python", "code": code}}
    for site in ("home", "office"):
        try:
            r = requests.post(FLEET, json={"workflow": json.dumps(wf), "site": site},
                              headers={"Authorization": f"Bearer {pat}"}, timeout=60)
            if r.status_code in (200, 201, 202):
                return r.json()["data"]["id"]
            log(f"fleet {site}: HTTP {r.status_code} {r.text[:120]}")
        except Exception as e:
            log(f"fleet {site}: {e!r}"[:200])
    return "error"


def self_test() -> bool:
    import tempfile
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        live = t / "live"
        (live / "paper/ledger/entries").mkdir(parents=True)
        (live / "runs.jsonl").write_text('{"H": "T1"}\n')
        for i, h in enumerate(["T1", "T2"]):
            (live / f"paper/ledger/entries/{h}.json").write_text(json.dumps({"H": h, "hash": f"{i:064x}", "prev_hash": None}))
        summ = t / "summary.json"
        summ.write_text(json.dumps({"live_since": "T0", "settled": [
            {"universe": "train23", "arm": "G2", "net_usd": 290.72, "return_pct": 1.99, "events": 373},
            {"universe": "train23", "arm": "Random (same share)", "net_usd": -430.59, "return_pct": -2.59, "events": 423},
            {"universe": "full", "arm": "G2", "net_usd": -1, "return_pct": -1, "events": 1}]}))
        b = build("TEST", live, summ, t / "out")
        sums = b["files"]["SHA256SUMS"].decode()
        check("files: summary, runs, both ledger entries, README, SHA256SUMS",
              sorted(b["files"]) == sorted(["summary.json", "runs.jsonl", "ledger/entries/T1.json",
                                            "ledger/entries/T2.json", "README.txt", "SHA256SUMS"]))
        check("SHA256SUMS lists every other file with its hash",
              all(f"{sha256(v)}  {p}" in sums for p, v in b["files"].items() if p != "SHA256SUMS"))
        check("files written to disk byte for byte",
              all((b["dir"] / p).read_bytes() == v for p, v in b["files"].items()))
        check("ledger head is the newest entry", b["head"]["H"] == "T2")
        check("main universe only (train23)", [c for c, _ in b["results"]] == ["g2", "rnd2"])
        n = b["name"]
        check("job name: label, results, ledger head hash and SHA256SUMS hash, safe characters, <= 1000",
              n.startswith("fwdtest-snapshot-TEST_g2.n290.72.r1.99.e373_rnd2.n-430.59.r-2.59.e423_ledger.")
              and n.endswith(f"_sums.{b['sums_sha']}") and len(n) <= NAME_MAX
              and all(ch.isalnum() or ch in "._-" for ch in n))
        import re
        dn = dataset_name("20261117T06")
        check("dataset name is lowercase and valid for Lumid", dn == "event-pred-live-snapshot-20261117t06"
              and re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", dn) and dataset_name("X", True).endswith("-rehearsal"))
        long = job_name("L", [(f"a{i}", {"net_usd": 1e6, "return_pct": 1.23, "events": 999}) for i in range(80)],
                        "h" * 64, "s" * 64)
        check("an over-long name drops trailing arms but keeps both hashes", len(long) <= NAME_MAX
              and long.endswith("_ledger." + "h" * 64 + "_sums." + "s" * 64))
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--label", default=dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H"))
    ap.add_argument("--dry-run", action="store_true", help="build the files and name; upload nothing")
    ap.add_argument("--rehearse", action="store_true", help="upload to a throwaway dataset, then delete it; no Fleet post")
    ap.add_argument("--retries", type=int, default=6, help="whole-run retries, 10 min apart")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    logf = OUT / f"snapshot_{a.label}.log"
    OUT.mkdir(parents=True, exist_ok=True)

    def log(msg):
        line = f"{dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        with logf.open("a") as f:
            f.write(line + "\n")
    b = build(a.label, LIVE, SUMMARY, OUT)
    log(f"built {len(b['files'])} files in {b['dir']}; ledger head {b['head']['H']}; SHA256SUMS {b['sums_sha']}")
    log(f"job name ({len(b['name'])} chars): {b['name']}")
    if a.dry_run:
        return
    sbx_pat = (HOME / ".lumid/sbx_pat").read_text().strip()
    pat = (HOME / ".lumid/lumid_pat").read_text().strip()
    dataset = dataset_name(a.label, a.rehearse)
    note = (f"Live test snapshot {a.label} UTC (final presentation). Read-only. Verify with SHA256SUMS; "
            f"its sha256 {b['sums_sha'][:16]}... is in Research Fleet job fwdtest-snapshot-{a.label}.")
    for attempt in range(1, a.retries + 1):
        ok = upload(dataset, note, b["files"], sbx_pat, log)
        if ok:
            break
        log(f"attempt {attempt} incomplete; retrying in 10 min")
        if attempt < a.retries:
            time.sleep(600)
    else:
        log("UPLOAD DID NOT COMPLETE")
    if a.rehearse:
        import requests
        r = requests.delete(f"{SBX}/datasets/{dataset}", headers={"Authorization": f"Bearer {sbx_pat}"}, timeout=60)
        log(f"rehearsal dataset deleted: HTTP {r.status_code} {r.text[:120]}")
        log(f"REHEARSAL {'OK' if ok else 'FAILED'}")
        return
    out = {"label": a.label, "dataset": f"office:/datasets/{dataset}", "ledger_head": b["head"]["H"],
           "ledger_hash": b["head"]["hash"], "sha256_SHA256SUMS": b["sums_sha"],
           "results_train23": {c: r for c, r in b["results"]}}
    for attempt in range(1, a.retries + 1):
        jid = post_name(b["name"], out, pat, log)
        log(f"fleet snapshot job: {jid}")
        if jid != "error":
            break
        time.sleep(600)
    log(f"SNAPSHOT {'DONE' if ok and jid != 'error' else 'INCOMPLETE'}: dataset {dataset}, job {jid}")


if __name__ == "__main__":
    main()
