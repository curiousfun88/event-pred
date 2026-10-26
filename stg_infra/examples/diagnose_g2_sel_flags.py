"""Why does the ledger check flag extra g2_sel fills from entry 2026-10-25 T15 on? (diagnostic, changes nothing)

From 20261025T15 every ledger round flags `g2_sel` with missing_now 0 and extra_now 4/7/2/4 (primary, primary_opt,
primary_strict, sensitivity): the re-derivation finds g2_sel fills that the ledger never recorded. Each round
recomputes the L7 walk-forward selection (paper_trader.walk_forward_selection) from three inputs that can change
between rounds:
  1. the G2 fill archive (g2_archive_update; a union over rounds),
  2. the markets cache (settlement results and times; refreshed for active events only),
  3. the category map: the L4 pool plus the series of the round's ACTIVE candidates (cmd_run's cat_of), so a series
     outside the pool (weather) has a category only while one of its events is active.
If the recomputed selection for a fold gains a category part-way through its trading week, that category's fills in
hours already recorded are 'extra'.

This replays the selection at every commit of the off-site backup repo (curiousfun88/event-pred-live, one commit per
backup run) that touched the archive, the markets cache or the tape, with the inputs as they were at that commit:
  - live-like map: pool + categories of the series whose events had a candidate in the 4 days to the newest tape hour,
  - fixed map (control): pool + the first category ever logged for each series,
and prints every commit where the fold's selection changes, which input changed, and how many g2 fills in the fold's
trading week before that commit fall in the newly selected categories (comparable with extra_now for `primary`).

Second check (--check-correction): the 2026-10-22 correction (ledger/corrections/correction_g2_sel_20261022.json)
lists the g2_sel fills omitted from entries 20261021T15..T05. A ledger round re-derives only events with a candidate in
the ACTIVE_DAYS (4) days to its newest hour, so once a corrected event leaves that window its omitted fills are no
longer re-derived, and the flag shows a SUBSET of the corrected fills. The dashboard counts a flag as covered only if
it equals the FULL corrected count, so such a subset is counted as an issue. This predicts, for every flagged entry,
the corrected fills still re-derived (events with a candidate in [H - 4 days, H]) and compares with extra_now.

Run (needs a full-history clone; blobs are fetched on demand):
  git clone --filter=blob:none https://github.com/curiousfun88/event-pred-live.git <dir>
  .venv/bin/python stg_infra/examples/diagnose_g2_sel_flags.py --repo <dir> --since 2026-10-24T22:00 --fold 2
  .venv/bin/python stg_infra/examples/diagnose_g2_sel_flags.py --repo <dir> --check-correction
  .venv/bin/python stg_infra/examples/diagnose_g2_sel_flags.py --self-test
"""
import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "stg_infra"))
import paper_trader as pt          # noqa: E402  (selection code used unchanged)
import paper_ledger as pl_         # noqa: E402

PAPER = "runs/live/paper"
POOL = ROOT / "docs/planning/l4_candidate_pool.json"
H_NS = 3600 * 10**9


def git(repo, *args) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def commits(repo, since, until):
    """[(sha, unix time)] oldest first, commits touching the selection's inputs."""
    out = git(repo, "log", "--reverse", "--format=%H %ct", f"--since={since}", *( [f"--until={until}"] if until else []),
              "--", f"{PAPER}/g2_archive.jsonl", f"{PAPER}/markets.jsonl", f"{PAPER}/tape").decode().split()
    return [(out[i], int(out[i + 1])) for i in range(0, len(out), 2)]


def inputs_at(repo, sha):
    """The selection's inputs as stored at one backup commit."""
    arch = [tuple(json.loads(l)) for l in git(repo, "show", f"{sha}:{PAPER}/g2_archive.jsonl").decode().splitlines() if l]
    markets = {}
    for l in git(repo, "show", f"{sha}:{PAPER}/markets.jsonl").decode().splitlines():
        if l:
            m = json.loads(l)
            markets[m["ticker"]] = m
    names = git(repo, "ls-tree", "--name-only", sha, f"{PAPER}/tape/", "runs/live/scores/").decode().split()
    tape = sorted(n.split("trades_")[1].split(".")[0] for n in names if "/tape/trades_" in n)
    scores = sorted(n.split("one_")[1].split(".")[0] for n in names if "/scores/one_" in n)
    return {"arch": arch, "markets": markets, "tape": tape, "scores": scores}


_SCORE_CACHE = {}


def score_rows(repo, sha, hour):
    """(event, cat, H_ns) rows of one producer hour's candidates (files never change once written)."""
    if hour not in _SCORE_CACHE:
        import polars as pl
        raw = git(repo, "show", f"{sha}:runs/live/scores/one_{hour}.parquet")
        d = pl.read_parquet(io.BytesIO(raw), columns=["event", "cat", "H_ns"])
        _SCORE_CACHE[hour] = list(zip(d["event"].to_list(), d["cat"].to_list(), d["H_ns"].to_list()))
    return _SCORE_CACHE[hour]


def live_like_map(pool_cat, rows, last_hour_ns, active_days=pt.ACTIVE_DAYS):
    """cmd_run's cat_of: the pool, then each active event's series -> its logged category (first seen)."""
    lo = last_hour_ns - active_days * 24 * H_NS
    active = {ev for ev, _, h in rows if h >= lo}
    m = dict(pool_cat)
    for ev, c, _ in rows:
        if ev in active:
            m.setdefault(ev.split("-")[0], c)
    return m


def fixed_map(pool_cat, rows):
    m = dict(pool_cat)
    for ev, c, _ in rows:
        m.setdefault(ev.split("-")[0], c)
    return m


def selection(arch, markets, cat_map, in_primary, fold):
    """The fold's selection exactly as paper_trader computes it, for the given inputs and category map."""
    fills = [pl_.as_fill(k, markets.get(k[1], {}).get("result")) for k in arch]
    cat_f = lambda f: cat_map.get(str(f[0]).split("-")[0], "?")
    folds = pt.walk_forward_selection(fills, pt.settled_at_all(markets, fills), cat_f, in_primary)
    return folds[fold - 1], fills, cat_f


def explain(prev, cur, fold, in_primary):
    """Which input changed between two snapshots, restricted to what the fold's selection window can see.
    prev/cur: {"arch", "markets", "map"}. Returns a dict of the differences (empty lists = no change)."""
    lo, hi = pt.ns_of(pt.FOLDS[fold - 1][0]), pt.ns_of(pt.FOLDS[fold - 1][1])
    def window_keys(s):
        return {k for k in s["arch"] if lo <= int(k[7]) < hi}
    def settled(s, keys):
        fills = [pl_.as_fill(k, s["markets"].get(k[1], {}).get("result")) for k in keys]
        sa = pt.settled_at_all(s["markets"], fills)
        return {e for e, t in sa.items() if t is not None and t <= hi}
    kp, kc = window_keys(prev), window_keys(cur)
    series = {str(k[0]).split("-")[0] for k in kc}
    return {"archive_added": len(kc - kp), "archive_removed": len(kp - kc),
            "settled_added": sorted(settled(cur, kc) - settled(prev, kp)),
            "settled_removed": sorted(settled(prev, kp) - settled(cur, kc)),
            "category_changed": sorted((se, prev["map"].get(se, "?"), cur["map"].get(se, "?")) for se in series
                                       if prev["map"].get(se, "?") != cur["map"].get(se, "?"))}


def newly_selected_fills(fills, cat_f, gained, fold, before_ns, in_primary):
    """g2 fills in the fold's trading week, before `before_ns`, in categories the selection gained."""
    lo = pt.ns_of(pt.FOLDS[fold - 1][2])
    return [f for f in fills if lo <= int(f[9]) < before_ns and in_primary(f) and cat_f(f) in gained]


def run(repo, since, until, fold):
    pool = json.loads(POOL.read_text())
    pool_cat = {x["series"]: x["cat"] for x in pool["series"]}
    prim = pt.universes(pool, set())["primary_L4"]
    in_primary = lambda f: prim(f[1], str(f[0]).split("-")[0], None)
    cs = commits(repo, since, until)
    print(json.dumps({"commits": len(cs), "since": since, "until": until, "fold": fold, "fold_def": pt.FOLDS[fold - 1]}))
    prev = {}
    for sha, t in cs:
        x = inputs_at(repo, sha)
        if not x["tape"]:
            continue
        rows = [r for h in x["scores"] for r in score_rows(repo, sha, h)]
        last = pt.ns_of(x["tape"][-1])
        maps = {"live": live_like_map(pool_cat, rows, last), "fixed": fixed_map(pool_cat, rows)}
        for name, cmap in maps.items():
            fd, fills, cat_f = selection(x["arch"], x["markets"], cmap, in_primary, fold)
            sel = set(fd["selected"])
            p = prev.get(name)
            if p is None or sel != p["sel"]:
                rec = {"commit": sha[:10], "time_utc": pt.stamp_of(t * 10**9), "map": name, "newest_tape": x["tape"][-1],
                       "selected": sorted(sel),
                       "table": {c: {"events": r["events"], "ret": round(r["ret"], 4)} for c, r in fd["table"].items()}}
                if p is not None:
                    gained = sel - p["sel"]
                    rec["gained"], rec["lost"] = sorted(gained), sorted(p["sel"] - sel)
                    rec["why"] = explain({**p["x"], "map": p["map"]}, {**x, "map": cmap}, fold, in_primary)
                    rec["g2_fills_now_selected_before_this_commit"] = len(
                        newly_selected_fills(fills, cat_f, gained, fold, t * 10**9, in_primary))
                print(json.dumps(rec), flush=True)
            prev[name] = {"sel": sel, "x": {"arch": x["arch"], "markets": x["markets"]}, "map": cmap}
    for name in ("live", "fixed"):
        if name in prev:
            print(json.dumps({"final": name, "selected": sorted(prev[name]["sel"])}))


def last_candidate_ns(rows):
    """{event: newest H_ns at which it had a logged candidate}."""
    out = {}
    for ev, _, h in rows:
        out[ev] = max(out.get(ev, 0), int(h))
    return out


def expected_extra(correction, H_ns, last_cand, active_days=pt.ACTIVE_DAYS):
    """Per window: how many corrected fills a round whose newest hour is H_ns still re-derives (their event had a
    candidate in the ACTIVE_DAYS days to H_ns)."""
    lo = H_ns - active_days * 24 * H_NS
    return {w: sum(1 for f in fl if last_cand.get(str(f[0]), 0) >= lo) for w, fl in correction["fills_by_window"].items()}


def check_correction(repo):
    """Every g2_sel flag after the corrected entries, against the corrected fills still re-derived."""
    sha = git(repo, "rev-parse", "HEAD").decode().strip()
    d = "runs/live/paper/ledger"
    corr = json.loads(git(repo, "show", f"{sha}:{d}/corrections/correction_g2_sel_20261022.json"))
    hi = corr["entries"][1]
    names = git(repo, "ls-tree", "--name-only", sha, f"{d}/entries/", "runs/live/scores/").decode().split()
    scores = sorted(n.split("one_")[1].split(".")[0] for n in names if "/scores/one_" in n)
    last_cand = last_candidate_ns([r for h in scores for r in score_rows(repo, sha, h)])
    n_match = n_flags = 0
    for n in sorted(x for x in names if "/entries/" in x):
        e = json.loads(git(repo, "show", f"{sha}:{n}"))
        H = str(e.get("H", Path(n).stem))
        flags = {x["window"]: x for x in e.get("verification") or [] if x.get("arm") == "g2_sel"}
        if H <= hi or not flags:
            continue
        exp = expected_extra(corr, pt.ns_of(H), last_cand)
        got = {w: (x.get("missing_now"), x.get("extra_now")) for w, x in flags.items()}
        match = all(got.get(w, (0, 0)) == (0, exp[w]) for w in exp if exp[w] or w in got)
        n_flags += 1
        n_match += match
        print(json.dumps({"entry": H, "match": match, "expected_extra": exp,
                          "flag_missing_extra": {w: list(v) for w, v in got.items()}}))
    print(json.dumps({"flagged_entries_after_correction": n_flags, "explained_by_correction_subset": n_match}))


def self_test() -> bool:
    ok = True

    def check(name, cond):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + name)

    fold = 2
    s_lo, s_hi, t_lo, _ = (pt.ns_of(v) for v in pt.FOLDS[fold - 1])
    in_primary = lambda f: True
    # 20 events of series SERX, each one profitable fill in the selection window, settled before its end
    arch, markets = [], {}
    for i in range(20):
        ev, tk = f"SERX-E{i}", f"SERX-E{i}-A"
        arch.append((ev, tk, -1, 40, 10, 0.0, 400.0, s_lo + i * H_NS))           # sold YES at 40c, settles NO
        markets[tk] = {"result": "no", "settled_ns": s_lo + (i + 1) * H_NS}
    arch.append(("SERX-T1", "SERX-T1-A", -1, 40, 10, 0.0, 400.0, t_lo + 2 * H_NS))   # 1 fill in the trading week
    with_x, without_x = {"SERX": "Climate and Weather"}, {}

    fd, fills, cat_f = selection(arch, markets, with_x, in_primary, fold)
    check("category known: SERX's category is selected (20 events, positive)", fd["selected"] == ["Climate and Weather"])
    fd0, _, _ = selection(arch, markets, without_x, in_primary, fold)
    check("category unknown: the same fills fall in '?', which is also selected (the flip is in the NAME)",
          fd0["selected"] == ["?"])
    check("so g2_sel's trading-week fill changes category with the map",
          len(newly_selected_fills(fills, cat_f, {"Climate and Weather"}, fold, t_lo + 10 * H_NS, in_primary)) == 1)
    # map flip attributed to the category map
    w = explain({"arch": arch, "markets": markets, "map": without_x}, {"arch": arch, "markets": markets, "map": with_x},
                fold, in_primary)
    check("explain: map flip -> category_changed only",
          w["category_changed"] == [("SERX", "?", "Climate and Weather")] and not w["settled_added"]
          and w["archive_added"] == 0)
    # late settlement: one event unsettled before, settled (before the window's end) after -> settled_added
    m_late = dict(markets); m_late["SERX-E5-A"] = {"result": None, "settled_ns": None}
    w = explain({"arch": arch, "markets": m_late, "map": with_x}, {"arch": arch, "markets": markets, "map": with_x},
                fold, in_primary)
    check("explain: late settlement record -> settled_added == ['SERX-E5']", w["settled_added"] == ["SERX-E5"]
          and not w["category_changed"])
    # 19 settled events: below MIN_EVENTS, nothing selected; the 20th settling selects it
    fd19, _, _ = selection(arch, m_late, with_x, in_primary, fold)
    check("19 settled events -> nothing selected (MIN_EVENTS 20)", fd19["selected"] == [])
    # archive growth in the window -> archive_added
    arch2 = arch + [("SERX-E0", "SERX-E0-A", +1, 30, 10, 0.0, 300.0, s_lo + 3 * H_NS)]
    w = explain({"arch": arch, "markets": markets, "map": with_x}, {"arch": arch2, "markets": markets, "map": with_x},
                fold, in_primary)
    check("explain: new archived fill in the window -> archive_added == 1", w["archive_added"] == 1)
    # live-like map: a series is known only while one of its events is active (4 days to the newest hour)
    rows = [("SERX-E0", "Climate and Weather", s_lo)]
    check("live-like map: series known while its event is active",
          live_like_map({}, rows, s_lo + 24 * H_NS).get("SERX") == "Climate and Weather")
    check("live-like map: series unknown once its events are older than 4 days",
          "SERX" not in live_like_map({}, rows, s_lo + 5 * 24 * H_NS))
    check("fixed map: always known", fixed_map({}, rows).get("SERX") == "Climate and Weather")
    # correction subset: two events, one leaves the 4-day window
    H0 = pt.ns_of("20261021T15")
    corr = {"fills_by_window": {"primary": [("A-1", "A-1-x", 1, 30, 1, 0.0, 30.0, H0)] * 3
                                + [("B-1", "B-1-x", 1, 30, 1, 0.0, 30.0, H0)] * 2}}
    lc = {"A-1": H0, "B-1": H0 + 3 * 24 * H_NS}
    check("correction subset: both events active -> full count", expected_extra(corr, H0 + 2 * 24 * H_NS, lc) == {"primary": 5})
    check("correction subset: A inactive after 4 days -> only B's fills",
          expected_extra(corr, H0 + 5 * 24 * H_NS, lc) == {"primary": 2})
    check("correction subset: both inactive -> 0", expected_extra(corr, H0 + 8 * 24 * H_NS, lc) == {"primary": 0})
    check("last candidate per event", last_candidate_ns([("A-1", "c", 5), ("A-1", "c", 9), ("B-1", "c", 2)])
          == {"A-1": 9, "B-1": 2})
    print("SELF-TEST " + ("PASSED" if ok else "FAILED"))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", help="full-history clone of event-pred-live")
    ap.add_argument("--since", default="2026-10-24T22:00:00Z")
    ap.add_argument("--until", default=None)
    ap.add_argument("--fold", type=int, default=2)
    ap.add_argument("--check-correction", action="store_true",
                    help="compare every g2_sel flag after the 22 Oct correction with the corrected fills still re-derived")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if not a.repo:
        ap.error("--repo is required (or --self-test)")
    if a.check_correction:
        check_correction(Path(a.repo))
    else:
        run(Path(a.repo), a.since, a.until, a.fold)


if __name__ == "__main__":
    main()
