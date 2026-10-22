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


SPLIT_ARMS = tuple(ARM_NAMES)          # every ledgered arm; the page decides which it shows
MAIN_FROM_NS = int(dt.datetime(2026, 10, 16, 17, tzinfo=dt.timezone.utc).timestamp()) * 10**9   # L18: main result counts from here
# liq_traded re-derivation flags in entries before the median fix (paper_trader.hour_medians; deployed at the handover
# after 2026-10-20 ~16:00 UTC): a later round's check used a median over the active-events subset (host log 2026-10-20).
# The recorded fills are right; the flags are counted apart, never as issues. Entries from this hour on count in full.
LIQT_KNOWN_BEFORE = "20261021T00"
FULL_TO_NS = int(dt.datetime(2026, 10, 17, 5, tzinfo=dt.timezone.utc).timestamp()) * 10**9     # L19: last full-universe quoting hour


def settled_split(repo: Path, ents) -> list:
    """L18: settled-only net P&L per strategy on the 23 training series (main result) and on the full universe (L4),
    from the ledger's recorded fills and the paper trader's settlement cache. Descriptive; the verdicts come from the
    cut report. L20: an event counts once ALL its legs have settled (cut_report.settle_times), as in the cut report
    and the ledger, not leg by leg. L19: the full universe covers quoting hours S to FULL_TO_NS (17 Oct T05); later
    hours quote only the 23 series and count in the main result only."""
    import pickle
    mp_ = repo / "runs/live/paper/markets.pkl"
    if not mp_.exists() or not ents:
        return []
    markets = pickle.loads(mp_.read_bytes())
    sys.path.insert(0, str(repo / "stg_infra"))
    sys.path.insert(0, str(repo / "stg_infra/examples"))
    from fetch_kalshi_api_months import SERIES_A13
    from cut_report import settle_times
    a13 = set(SERIES_A13)
    settled_at = settle_times(markets)
    agg = {}
    for f in ents:
        e = json.loads(f.read_text())
        for a, rows in e.get("new_fills", {}).get("primary", {}).items():
            if a not in SPLIT_ARMS:
                continue
            for r in rows:
                ev, tk, side, price, qty, fee, cap, H = r
                res = markets.get(tk, {}).get("result")
                if res not in ("yes", "no") or settled_at.get(ev) is None:
                    continue
                pay = 100 if res == "yes" else 0
                net = ((pay - price) * qty if side > 0 else (price - pay) * qty) - fee
                full = H <= FULL_TO_NS
                for u in ((["train23"] if ev.split("-")[0] in a13 and H >= MAIN_FROM_NS else []) + (["full"] if full else [])
                          + (["full_same"] if full and H >= MAIN_FROM_NS else [])):
                    x = agg.setdefault((u, a), [0.0, 0.0, 0, set()])
                    x[0] += net / 100; x[1] += cap / 100; x[2] += 1; x[3].add(ev)
    return [{"universe": u, "arm": ARM_NAMES.get(a, a), "net_usd": round(x[0], 2), "capital_usd": round(x[1], 2),
             "return_pct": round(100 * x[0] / x[1], 2) if x[1] else None, "settled_fills": x[2], "events": len(x[3])}
            for (u, a), x in sorted(agg.items())]


RECOUNT_CACHE = "runs/live/paper/recount_l20.json"


def recount_rows(repo: Path, ents) -> tuple:
    """L20: the dashboard's hourly curves (rows: full universe; main_rows: L18 main result) recounted from the ledger's
    recorded fills with paper_ledger.recount_curve, the same function the cut report uses, instead of the totals
    stored in entries (which dropped repeated identical fills before the L20 fix). Open fills are marked at the
    logged hourly mids (runs/live/scores). Cached per ledger head and settlement cache. Returns (rows, main_rows)."""
    import pickle
    import polars as pl
    sys.path.insert(0, str(repo / "stg_infra"))
    sys.path.insert(0, str(repo / "stg_infra/examples"))
    import paper_ledger as pl_
    from cut_report import settle_times
    mp_ = repo / "runs/live/paper/markets.pkl"
    E = [json.loads(f.read_text()) for f in ents]
    key = f"{E[-1].get('hash')}:{mp_.stat().st_mtime_ns if mp_.exists() else 0}"
    cp = repo / RECOUNT_CACHE
    if cp.exists():
        c = json.loads(cp.read_text())
        if c.get("key") == key:
            return c["rows"], c["main_rows"]
    markets = pickle.loads(mp_.read_bytes()) if mp_.exists() else {}
    results = {tk: m.get("result") for tk, m in markets.items()}
    settled_at = settle_times(markets)
    st = json.loads((repo / "runs/live/paper/ledger/state.json").read_text())
    stamp = {int(e["H_ns"]): e["H"] for e in E}
    hours, main_hours = sorted(stamp), sorted(int(e["H_ns"]) for e in E if "main_result_l18" in e)
    fills = {}
    for e in E:
        for a, rows in e.get("new_fills", {}).get("primary", {}).items():
            fills.setdefault(("primary", a), []).extend(tuple(r) for r in rows)
    mid_tab = {}
    for f in sorted((repo / "runs/live/scores").glob("*_*.parquet")):
        if f.stem.split("_", 1)[1] > E[-1]["H"]:
            continue
        d = pl.read_parquet(f, columns=["ticker", "H_ns", "bid_c", "ask_c"])
        for tk, H, b, a in zip(d["ticker"].to_list(), d["H_ns"].to_list(), d["bid_c"].to_list(), d["ask_c"].to_list()):
            mid_tab[(tk, int(H))] = (b + a) / 2
    rc = pl_.recount_curve(fills, hours, results, settled_at, mid_tab, st["start_H"])
    rm = pl_.recount_curve(fills, main_hours, results, settled_at, mid_tab, st["start_H"],
                           keep=lambda k: pl_.in_main(pl_.as_fill(k, None)))
    rows = [{"H": stamp[H], "arm": ARM_NAMES.get(a, a), "total_usd": round(c["total_usd"], 2),
             "realised_usd": round(c["realised_usd"], 2), "unrealised_usd": round(c["unrealised_usd"], 2),
             "capital_usd": round(c["capital_usd"], 2), "fills": c["fills"]} for H in hours for (_, a), c in sorted(rc[H].items())]
    main_rows = [{"H": stamp[H], "arm": ARM_NAMES.get(a, a), "total_usd": round(c["total_usd"], 2),
                  "realised_usd": round(c["realised_usd"], 2), "capital_usd": round(c["capital_usd"], 2)}
                 for H in main_hours for (_, a), c in sorted(rm[H].items())]
    tmp = cp.with_suffix(".tmp"); tmp.write_text(json.dumps({"key": key, "rows": rows, "main_rows": main_rows})); tmp.replace(cp)
    return rows, main_rows


def build_summary(repo: Path) -> dict:
    """The public dashboard's data (site/summary.json): every ledger entry's cumulative figures per strategy (primary
    window, pessimistic fills) and the test's status. Read-only on the ledger. L20: the curves are recounted from the
    recorded fills (recount_rows); the totals stored in entries are used only if the recount fails."""
    d = repo / "runs/live/paper/ledger"
    ents = sorted((d / "entries").glob("*.json")) if (d / "entries").exists() else []
    rows, main_rows, issues, prejoin, rederive, last = [], [], 0, 0, 0, None
    for f in ents:
        e = json.loads(f.read_text())
        for x in e.get("verification") or []:
            # entries 10-16 T08-T10: liq_traded (L17, joined at T06) was compared on hours before it joined; nothing
            # recorded was missing (missing_now 0). A check artefact, fixed in paper_ledger.verify; counted apart.
            if x.get("arm") == "liq_traded" and x.get("missing_now") == 0:
                prejoin += 1
            elif x.get("arm") == "liq_traded" and str(e.get("H", f.stem)) < LIQT_KNOWN_BEFORE:
                rederive += 1
            else:
                issues += 1
        last = e
        for a, c in ((e.get("main_result_l18") or {}).get("cumulative") or {}).items():    # L18 main result over time
            main_rows.append({"H": e.get("H", f.stem), "arm": ARM_NAMES.get(a, a), "total_usd": round(c["total_usd"], 2),
                              "realised_usd": round(c["realised_usd"], 2), "capital_usd": round(c["capital_usd"], 2)})
        for a, c in e.get("cumulative", {}).get("primary", {}).items():
            rows.append({"H": e.get("H", f.stem), "arm": ARM_NAMES.get(a, a), "total_usd": round(c["total_usd"], 2),
                         "realised_usd": round(c["realised_usd"], 2), "unrealised_usd": round(c["unrealised_usd"], 2),
                         "capital_usd": round(c["capital_usd"], 2), "fills": c["fills"]})
    st = json.loads((d / "state.json").read_text()) if (d / "state.json").exists() else {}
    v = (last or {}).get("verdict") or {}
    settled = settled_split(repo, ents)
    source = "stored"
    if ents:
        try:
            rows, main_rows = recount_rows(repo, ents)
            source = "recounted from recorded fills (L20)"
        except Exception as e:                      # never let the dashboard stop the backup
            source = f"stored (recount failed: {e!r})"[:200]
    return {"generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "live_since": st.get("start_stamp"), "latest_entry": ents[-1].stem if ents else None, "entries": len(ents),
            "verification_issues": issues, "late_arm_prejoin_notes": prejoin,
            "liq_traded_rederivation_notes": rederive, "g2_settled_events": v.get("g2_events"),
            "latest_producer_hour": heartbeat(repo)["latest_producer_hour"], "settled": settled, "main_rows": main_rows,
            "rows": rows, "curve_source": source}


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


CORE = ("G2", "Linear", "Neural", "G", "Random (same share)", "Quote all")     # the dashboard's headline rows, in order
CORE_KEY = {"G2": "g2", "Linear": "lin2", "Neural": "mlp2", "G": "g", "Random (same share)": "rnd2", "Quote all": "cand"}


def result_table(settled, universe, arms=CORE) -> list:
    """One readable row per strategy for one universe of the settled split, in the dashboard's order (no settled
    position yet: net and return None)."""
    have = {r["arm"]: r for r in settled if r["universe"] == universe}
    return [{"strategy": a, "net_usd": have[a]["net_usd"] if a in have else None,
             "return_pct": have[a]["return_pct"] if a in have else None,
             "settled_fills": have[a]["settled_fills"] if a in have else 0, "events": have[a]["events"] if a in have else 0}
            for a in arms]


def by_day(main_rows, arms=CORE) -> list:
    """The main result's settled net P&L at the last ledger entry of each UTC day: the numbers behind the dashboard's
    settled-net chart, one row per day (Research Fleet shows no images)."""
    last = {}
    for r in main_rows:
        if r["arm"] in arms:
            last.setdefault(r["H"][:8], {}).setdefault(r["H"], {})[r["arm"]] = r["realised_usd"]
    out = []
    for d in sorted(last):
        H = max(last[d])
        out.append({"day": f"{d[:4]}-{d[4:6]}-{d[6:]}", "through_entry": H, **{a: last[d][H].get(a) for a in arms}})
    return out


def daily_record(repo: Path, day: str) -> dict:
    """The daily Research Fleet summary for UTC day `day` (YYYYMMDD), main result first: its table (settled only, as on
    the dashboard), G2 minus random, and settled net P&L by day; then status and the latest ledger entry's hash, which
    ties it to the hourly audit trail. Main result only: the full universe is on the dashboard and in the cut report."""
    sm = build_summary(repo)
    ents = sorted((repo / "runs/live/paper/ledger/entries").glob("*.json"))
    head = json.loads(ents[-1].read_text())["hash"] if ents else None
    main = result_table(sm["settled"], "train23")
    g2, rnd = (next(r["net_usd"] for r in main if r["strategy"] == a) for a in ("G2", "Random (same share)"))
    return {"day": day, "dashboard": "https://curiousfun88.github.io/event-pred-live/",
            "main_result": {"what": "G2 and baselines on the 23 backtested series, quoting hours from 2026-10-16 17:00 UTC "
                                    "(L18); settled positions only, pessimistic fills, net of fees",
                            "table": main,
                            "g2_minus_random_usd": round(g2 - rnd, 2) if g2 is not None and rnd is not None else None,
                            "settled_net_usd_by_day": by_day(sm["main_rows"])},
            "status": {"generated_utc": sm["generated_utc"], "live_since": sm["live_since"], "latest_entry": sm["latest_entry"],
                       "latest_entry_hash": head, "entries": sm["entries"], "verification_issues": sm["verification_issues"],
                       "curve_source": sm.get("curve_source")},
            "main_result_all_strategies": [r for r in sm["settled"] if r["universe"] == "train23"]}


def daily_body(rec: dict, site: str) -> dict:
    """FlowMesh job (same shape as the hourly records): metrics = the main result, net and return per strategy."""
    met = {}
    for r in rec["main_result"]["table"]:
        if r["return_pct"] is not None:
            met[f"main_{CORE_KEY[r['strategy']]}_net_usd"] = r["net_usd"]
            met[f"main_{CORE_KEY[r['strategy']]}_ret_pct"] = r["return_pct"]
    if rec["main_result"]["g2_minus_random_usd"] is not None:
        met["main_g2_minus_rnd2_usd"] = rec["main_result"]["g2_minus_random_usd"]
    code = (f"import json\nREC = json.loads({json.dumps(json.dumps(rec))})\nMET = json.loads({json.dumps(json.dumps(met))})\n\n\n"
            f"def main():\n    return {{'metrics': MET, 'output': REC}}\n")
    wf = {"apiVersion": "flowmesh/v1", "kind": "Task", "metadata": {"name": f"fwdtest-daily-{rec['day']}"},
          "spec": {"taskType": "python", "code": code}}
    return {"workflow": json.dumps(wf), "site": site}


def post_daily(repo: Path, pat: str, day: str, post=None) -> str:
    """Post the day's summary to the first site that accepts it (home, else office). Returns the job id or 'error: ...'."""
    rec = daily_record(repo, day)
    if post is None:
        import requests
        post = lambda body: requests.post("https://lum.id/api/v1/me/fleet/jobs", json=body,
                                          headers={"Authorization": f"Bearer {pat}"}, timeout=60)
    errs = []
    for site in ("home", "office"):
        try:
            r = post(daily_body(rec, site))
            if r.status_code in (200, 201, 202):
                return r.json()["data"]["id"]
            errs.append(f"{site}: HTTP {r.status_code}")
        except Exception as e:
            errs.append(f"{site}: {e!r}"[:120])
    return "error: " + " | ".join(errs)


def daily_due(now_utc: dt.datetime, posted: set) -> str | None:
    """The UTC day whose summary is due (yesterday, from 02:00 UTC once the ledger has caught up), unless posted."""
    if now_utc.hour < 2:
        return None
    day = (now_utc - dt.timedelta(days=1)).strftime("%Y%m%d")
    return None if day in posted else day


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


MARKETS_PKL, MARKETS_TXT = "runs/live/paper/markets.pkl", "runs/live/paper/markets.jsonl"


def export_markets(repo: Path, clone: Path) -> int:
    """2026-10-22: the paper trader's settlement cache, which a restore needs (without it every settled event counts
    as open), as one sorted JSON line per ticker so git stores only changed lines. Returns the number of tickers."""
    src = repo / MARKETS_PKL
    if not src.exists():
        return 0
    import pickle
    m = pickle.loads(src.read_bytes())
    dst = clone / MARKETS_TXT
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps({"ticker": t, **m[t]}, sort_keys=True) + "\n" for t in sorted(m))
    if not dst.exists() or dst.read_text() != text:
        dst.write_text(text)
    return len(m)


G2_ARCHIVE, G2_ARCHIVE_TXT = "runs/live/paper/g2_archive.json", "runs/live/paper/g2_archive.jsonl"


def export_g2_archive(repo: Path, clone: Path) -> int:
    """2026-10-22: the L10 archive of g2's fills, which the L7 category selection reads (without it the selection
    sees only recent weeks), as one sorted JSON line per fill. Returns the number of fills."""
    src = repo / G2_ARCHIVE
    if not src.exists():
        return 0
    rows = sorted(tuple(r) for r in json.loads(src.read_text()))
    dst = clone / G2_ARCHIVE_TXT
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(list(r)) + "\n" for r in rows)
    if not dst.exists() or dst.read_text() != text:
        dst.write_text(text)
    return len(rows)


def import_g2_archive(txt: Path) -> list:
    """The inverse of export_g2_archive: the archive as paper_trader writes it."""
    return [json.loads(l) for l in txt.read_text().splitlines() if l.strip()]


def import_markets(txt: Path) -> dict:
    """The inverse of export_markets: {ticker: row}."""
    out = {}
    for line in txt.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[r.pop("ticker")] = r
    return out


HC_URL_FILE = CFG / "hc_ping_url"     # 2026-10-22: Healthchecks.io dead man's switch (URL kept off GitHub)
HC_FRESH_MIN = 65                    # ping only while the producer's latest hour started at most this long ago


def health_ping(hb: dict, url_file: Path = HC_URL_FILE, get=None, now=None) -> str:
    """Ping the Healthchecks URL iff the producer's latest hour is fresh, so pings stop when the producer stops even
    while the keeper (and this backup) still run. Never raises. Returns what happened."""
    try:
        if not url_file.exists():
            return "no url"
        H = hb.get("latest_producer_hour")
        if not H:
            return "no producer hour"
        now = now or dt.datetime.now(dt.timezone.utc)
        age = (now - dt.datetime.strptime(H, "%Y%m%dT%H").replace(tzinfo=dt.timezone.utc)).total_seconds() / 60
        if age > HC_FRESH_MIN:
            return f"stale ({age:.0f} min): not pinged"
        if get is None:
            import urllib.request
            get = lambda u: urllib.request.urlopen(u, timeout=10).status
        status = get(url_file.read_text().strip())
        return f"pinged ({status})"
    except Exception as e:
        return f"ping failed: {e!r}"[:120]


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
        export_markets(repo, clone)
        export_g2_archive(repo, clone)
        write_summary(repo, clone)                       # the public dashboard's data (site/)
        publish_page(repo, clone)
        hb = heartbeat(repo)
        health_ping(hb)
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
    T = dt.datetime(2026, 10, 18, 1, 30, tzinfo=dt.timezone.utc)
    check("daily: not due before 02:00 UTC; due for yesterday after; not again once posted",
          daily_due(T, set()) is None and daily_due(T.replace(hour=3), set()) == "20261017"
          and daily_due(T.replace(hour=3), {"20261017"}) is None)
    with tempfile.TemporaryDirectory() as td2:
        repo2 = Path(td2)
        (repo2 / "runs/live/paper/ledger/entries").mkdir(parents=True)
        (repo2 / "runs/live/paper/ledger/entries/20261017T23.json").write_text(json.dumps({"H": "20261017T23", "hash": "abc"}))
        sent = []
        R = type("R", (), {"status_code": 202, "json": lambda self: {"data": {"id": "home:fm:wfl-d"}}})
        jid = post_daily(repo2, "pat", "20261017", post=lambda body: sent.append(body) or R())
        wf = json.loads(sent[0]["workflow"])
        check("daily: posted as fwdtest-daily-20261017 to home, carrying the ledger head hash",
              jid == "home:fm:wfl-d" and wf["metadata"]["name"] == "fwdtest-daily-20261017" and "abc" in wf["spec"]["code"])
    st_ = [{"universe": "train23", "arm": "G2", "net_usd": 10.0, "return_pct": 5.0, "settled_fills": 3, "events": 2},
           {"universe": "train23", "arm": "Random (same share)", "net_usd": -4.0, "return_pct": -2.0, "settled_fills": 2, "events": 1},
           {"universe": "full", "arm": "G2", "net_usd": -1.0, "return_pct": -1.0, "settled_fills": 1, "events": 1}]
    tb_ = result_table(st_, "train23")
    check("daily table: the six strategies in the dashboard's order; one with nothing settled shows None",
          [r["strategy"] for r in tb_] == list(CORE) and tb_[0]["net_usd"] == 10.0 and tb_[1]["net_usd"] is None
          and tb_[1]["events"] == 0 and result_table(st_, "full")[0]["net_usd"] == -1.0)
    mr_ = [{"H": "20261017T05", "arm": "G2", "realised_usd": 1.0}, {"H": "20261017T23", "arm": "G2", "realised_usd": 2.0},
           {"H": "20261017T23", "arm": "Linear", "realised_usd": 0.5}, {"H": "20261018T03", "arm": "G2", "realised_usd": 3.0},
           {"H": "20261018T03", "arm": "G2 W2", "realised_usd": 9.0}]
    bd_ = by_day(mr_)
    check("daily by-day: the last entry of each UTC day, settled net per strategy, other arms left out",
          [(r["day"], r["through_entry"], r["G2"], r["Linear"]) for r in bd_] == [("2026-10-17", "20261017T23", 2.0, 0.5),
                                                                                 ("2026-10-18", "20261018T03", 3.0, None)]
          and "G2 W2" not in bd_[0])
    rec_ = {"day": "20261017", "main_result": {"table": tb_, "g2_minus_random_usd": 14.0}}
    ns_ = {}
    exec(json.loads(daily_body(rec_, "home")["workflow"])["spec"]["code"], ns_)      # the job's own code, as Fleet runs it
    met_ = ns_["main"]()["metrics"]
    check(f"daily metrics: main result only (settled arms' net and return, G2 minus random; nothing for unsettled arms): {met_}",
          met_ == {"main_g2_net_usd": 10.0, "main_g2_ret_pct": 5.0, "main_rnd2_net_usd": -4.0, "main_rnd2_ret_pct": -2.0,
                   "main_g2_minus_rnd2_usd": 14.0})
    # L20: curves recounted from the recorded fills; an event is settled only when every leg is
    import pickle
    import polars as pl
    with tempfile.TemporaryDirectory() as td3:
        repo3 = Path(td3)
        (repo3 / "stg_infra").symlink_to(Path(__file__).resolve().parent)
        L = repo3 / "runs/live/paper/ledger"
        (L / "entries").mkdir(parents=True); (repo3 / "runs/live/scores").mkdir(parents=True)
        H = MAIN_FROM_NS; s1 = "20261016T17"
        ev, ev2 = "KXHIGHNY-26OCT17", "KXHIGHMIA-26OCT17"
        k = [ev, ev + "-B70", 1, 40, 1, 0.0, 40.0, H]                 # repeated: one order, two trades -> +60c each
        k2 = [ev2, ev2 + "-B88", -1, 30, 1, 0.0, 70.0, H]            # MIA: this leg settled, another leg not yet
        ev3 = "KXESOCCERGAME-26OCT18X"                               # not a training series, quoted after the L19 switch
        k3 = [ev3, ev3 + "-A", 1, 40, 1, 0.0, 60.0, FULL_TO_NS + 3600 * 10**9]
        (L / "entries" / f"{s1}.json").write_text(json.dumps({"H": s1, "H_ns": H, "hash": "h1", "main_result_l18": {},
                                                               "new_fills": {"primary": {"g2": [k, k, k2, k3]}},
                                                               "cumulative": {"primary": {"g2": {"total_usd": 0.6, "realised_usd": 0.6,
                                                                              "unrealised_usd": 0.0, "capital_usd": 0.4, "fills": 1}}}}))
        (L / "state.json").write_text(json.dumps({"start_H": H, "start_stamp": s1}))
        (repo3 / "runs/live/paper/markets.pkl").write_bytes(pickle.dumps({
            ev + "-B70": {"result": "yes", "settled_ns": H + 1}, ev2 + "-B88": {"result": "no", "settled_ns": H + 1},
            ev2 + "-B90": {"result": "", "settled_ns": None}, ev3 + "-A": {"result": "yes", "settled_ns": H + 1}}))
        pl.DataFrame({"ticker": [ev2 + "-B88"], "H_ns": [H], "bid_c": [20.0], "ask_c": [30.0]}).write_parquet(repo3 / f"runs/live/scores/one_{s1}.parquet")
        sm3 = build_summary(repo3)
        g2m = [r for r in sm3["main_rows"] if r["arm"] == "G2"][0]
        # NY: 2 x +60c realised; MIA open (one leg unsettled), sold at 30, marked at mid 25: -1*(25-30)*1 = +5c
        check(f"L20: dashboard curve counts the repeat and marks the open event (+$1.20 + $0.05; got {g2m['realised_usd']}, {g2m['total_usd']})",
              sm3["curve_source"].startswith("recounted") and abs(g2m["realised_usd"] - 1.2) < 1e-9 and abs(g2m["total_usd"] - 1.25) < 1e-9)
        t23 = [r for r in sm3["settled"] if r["universe"] == "train23" and r["arm"] == "G2"][0]
        check(f"L20: settled table counts NY (both fills) but not MIA until all its legs settle (got {t23['net_usd']}, {t23['events']} ev)",
              abs(t23["net_usd"] - 1.2) < 1e-9 and t23["events"] == 1 and t23["settled_fills"] == 2)
        fu = {r["universe"]: r for r in sm3["settled"] if r["arm"] == "G2"}
        check(f"L19: full universe and same-hours tables stop at 17 Oct T05 (a later settled fill is excluded; got "
              f"{fu['full']['net_usd']}, {fu['full_same']['net_usd']})",
              abs(fu["full"]["net_usd"] - 1.2) < 1e-9 and fu["full"]["events"] == 1 and abs(fu["full_same"]["net_usd"] - 1.2) < 1e-9)
        check("L20: the recount is cached and reused while the ledger and settlements are unchanged",
              (repo3 / RECOUNT_CACHE).exists() and recount_rows(repo3, sorted((L / "entries").glob("*.json")))[1] == sm3["main_rows"])
    with tempfile.TemporaryDirectory() as td4:
        repo4 = Path(td4)
        E4 = repo4 / "runs/live/paper/ledger/entries"; E4.mkdir(parents=True)
        fl = lambda arm, miss: {"window": "primary", "arm": arm, "missing_now": miss, "extra_now": 1}
        for stamp, v in (("20261016T08", [fl("liq_traded", 0)]), ("20261019T19", [fl("liq_traded", 3)]),
                         ("20261021T02", [fl("liq_traded", 2)]), ("20261019T20", [fl("g2", 1)])):
            (E4 / f"{stamp}.json").write_text(json.dumps({"H": stamp, "verification": v, "new_fills": {}}))
        sm4 = build_summary(repo4)
        check(f"check notes: pre-join and pre-fix liq_traded flags counted apart; g2 and post-fix flags are issues "
              f"(got {sm4['verification_issues']}, {sm4['late_arm_prejoin_notes']}, {sm4['liq_traded_rederivation_notes']})",
              (sm4["verification_issues"], sm4["late_arm_prejoin_notes"], sm4["liq_traded_rederivation_notes"]) == (2, 1, 1))
    import pickle
    with tempfile.TemporaryDirectory() as td3:
        r3, c3 = Path(td3) / "repo", Path(td3) / "clone"
        (r3 / "runs/live/paper").mkdir(parents=True)
        check("markets export: nothing to export without a cache", export_markets(r3, c3) == 0)
        m = {"EV-B-2": {"result": "", "status": "active", "close_ns": 5, "settled_ns": None},
             "EV-A-1": {"result": "yes", "status": "finalized", "close_ns": 3, "settled_ns": 4}}
        (r3 / MARKETS_PKL).write_bytes(pickle.dumps(m))
        n = export_markets(r3, c3)
        lines = (c3 / MARKETS_TXT).read_text().splitlines()
        check("markets export: one sorted line per ticker", n == 2 and lines[0].startswith('{"close_ns": 3') and "EV-A-1" in lines[0])
        check("markets export round-trips exactly", import_markets(c3 / MARKETS_TXT) == m)
        t0 = (c3 / MARKETS_TXT).stat().st_mtime_ns
        export_markets(r3, c3)
        check("markets export: unchanged cache leaves the file untouched", (c3 / MARKETS_TXT).stat().st_mtime_ns == t0)
    with tempfile.TemporaryDirectory() as td4:
        r4, c4 = Path(td4) / "repo", Path(td4) / "clone"
        (r4 / "runs/live/paper").mkdir(parents=True)
        check("g2 archive export: nothing without an archive", export_g2_archive(r4, c4) == 0)
        arch = [["EV-B", "EV-B-1", -1, 60, 2, 1, 40, 9], ["EV-A", "EV-A-1", 1, 40, 1, 0, 40, 5]]
        (r4 / G2_ARCHIVE).write_text(json.dumps(sorted(arch)))
        n = export_g2_archive(r4, c4)
        back = import_g2_archive(c4 / G2_ARCHIVE_TXT)
        check("g2 archive export: one line per fill, round-trips to the file paper_trader writes",
              n == 2 and len((c4 / G2_ARCHIVE_TXT).read_text().splitlines()) == 2
              and json.dumps(back) == (r4 / G2_ARCHIVE).read_text())
    with tempfile.TemporaryDirectory() as td5:
        uf = Path(td5) / "hc_ping_url"
        now5 = dt.datetime(2026, 10, 22, 7, 5, tzinfo=dt.timezone.utc)
        got = []
        get = lambda u: got.append(u) or 200
        check("health ping: no URL file, no ping", health_ping({"latest_producer_hour": "20261022T07"}, uf, get, now5) == "no url" and not got)
        uf.write_text("https://hc-ping.com/test-uuid\n")
        check("health ping: fresh producer hour pings the stored URL",
              health_ping({"latest_producer_hour": "20261022T06"}, uf, get, now5) == "pinged (200)" and got == ["https://hc-ping.com/test-uuid"])
        check("health ping: producer 2 h behind, no ping (the switch then fires)",
              health_ping({"latest_producer_hour": "20261022T05"}, uf, get, now5).startswith("stale") and len(got) == 1)
        def boom(u): raise OSError("network down")
        check("health ping: a network error never raises", health_ping({"latest_producer_hour": "20261022T07"}, uf, boom, now5).startswith("ping failed"))
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
