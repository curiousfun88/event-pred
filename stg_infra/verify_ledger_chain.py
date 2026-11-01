"""
verify_ledger_chain.py

CHECK THE LIVE LEDGER'S HASH CHAIN (amendment L10) from its entry files alone, without the live system.

For each entry in hour order: recompute sha256 of the entry without its "hash" field, exactly as
paper_ledger.write_entry wrote it (json.dumps(sort_keys=True, default=float)), compare with the stored
"hash", and check that "prev_hash" equals the previous entry's hash (empty for the first). A changed,
removed or reordered entry breaks the chain at that point.

The entries are public in the off-site backup (amendment L16):
    git clone --depth 1 --filter=blob:none --sparse https://github.com/curiousfun88/event-pred-live.git live
    git -C live sparse-checkout set runs/live/paper/ledger/entries
    python stg_infra/verify_ledger_chain.py live/runs/live/paper/ledger/entries

Third-party timestamps (amendment L14) are checked separately with the OpenTimestamps client:
`ots verify <file>.ots` for any stamped record in runs/live/stamps/.

USAGE (from repo root):
    python stg_infra/verify_ledger_chain.py --self-test
    python stg_infra/verify_ledger_chain.py <entries dir>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paper_ledger import sha  # noqa: E402  (the ledger's own hash function)


def check_chain(entries_dir: Path) -> tuple[int, list]:
    """Returns (number of entries, list of problems). An empty list means the chain verifies."""
    files = sorted(Path(entries_dir).glob("*.json"))
    problems, prev = [], ""
    for p in files:
        e = json.loads(p.read_text())
        stored = e.pop("hash", None)
        if stored != sha(e):
            problems.append(f"{p.name}: hash does not match its contents")
        if e.get("prev_hash", "") != prev:
            problems.append(f"{p.name}: prev_hash does not match the previous entry")
        prev = stored or ""
    return len(files), problems


def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        prev = ""
        for i, H in enumerate(["20261015T19", "20261015T20", "20261015T21"]):
            e = {"H": H, "prev_hash": prev, "new_fills": {"primary": {"g2": [[f"EV{i}", "TK", 1, 49, 10, 0, 490, H]]}},
                 "value": 1.5 * i}
            e["hash"] = sha(e)
            (d / f"{H}.json").write_text(json.dumps(e, default=float))
            prev = e["hash"]
        n, pr = check_chain(d)
        check(f"a correct chain of 3 entries verifies ({n} entries, {len(pr)} problems)", n == 3 and not pr)
        p = d / "20261015T20.json"
        e = json.loads(p.read_text()); e["value"] = 99.0; p.write_text(json.dumps(e))
        n, pr = check_chain(d)
        check(f"an edited middle entry is caught ({pr})", any("T20.json: hash" in x for x in pr))
        p.unlink()
        n, pr = check_chain(d)
        check(f"a removed entry breaks the next link ({pr})", any("T21.json: prev_hash" in x for x in pr))
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    if "--self-test" in sys.argv:
        sys.exit(0 if self_test() else 1)
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    n, problems = check_chain(Path(sys.argv[1]))
    for x in problems:
        print("  PROBLEM", x)
    print(f"{n} entries, {len(problems)} problems: chain {'VERIFIES' if not problems else 'BROKEN'}")
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
