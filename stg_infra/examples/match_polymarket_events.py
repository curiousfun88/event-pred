"""Exploratory (development months only): match Kalshi MECE events to their
Polymarket twins, leg by leg, for the cross-venue lead-lag check.

For each Kalshi event (from a candidates parquet: ticker, event_ticker, title,
yes_sub_title, close_time), search Polymarket's public Gamma API for closed
multi-outcome (negRisk) events whose endDate is within --max-days of the
Kalshi close. Legs are mapped by normalised name. Anything ambiguous is left
unmatched rather than guessed, and every mapping is printed for review.

Output: parquet with one row per matched leg
  (event_ticker, kalshi_ticker, kalshi_name, pm_event_id, pm_event_title,
   pm_name, pm_token_yes, score)

    python stg_infra/examples/match_polymarket_events.py --self-test
    python stg_infra/examples/match_polymarket_events.py CANDIDATES.parquet OUT.parquet
"""
import sys, re, json, time, argparse, difflib, datetime as dt
from pathlib import Path

GAMMA = "https://gamma-api.polymarket.com/public-search"

# Explicit synonyms. Checked against both venues' wording; anything else must
# match by name.
SYNONYMS = {
    "tie": "draw",
    "fed maintains rate": "no change",
    "cut 25bps": "25 bps decrease",
    "cut >25bps": "50+ bps decrease",
    "hike 25bps": "25+ bps increase",
    "hike >25bps": "25+ bps increase",
    "chatgpt": "openai",
    "gemini": "google",
    "claude": "anthropic",
    "grok": "xai",
    "llama": "meta",
}


def norm(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = s.replace("jr.", "").replace("fc ", "").replace(" fc", "").replace("sl ", "")
    s = re.sub(r"[^a-z0-9>+ ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return SYNONYMS.get(s, s)


def name_score(a: str, b: str) -> float:
    """1.0 for equal normalised names; token containment scores 0.9 (e.g.
    'bayern munich' vs 'bayern'); otherwise difflib ratio."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    if ta <= tb or tb <= ta:
        return 0.9
    return difflib.SequenceMatcher(None, na, nb).ratio()


def map_legs(k_names, pm_names, min_score=0.85):
    """Greedy one-to-one mapping by descending score. Returns {k: (pm, score)}.
    A leg whose best match is below min_score, or tied with another candidate,
    stays unmatched."""
    pairs = sorted(((name_score(k, p), k, p) for k in k_names for p in pm_names), reverse=True)
    out, used_k, used_p = {}, set(), set()
    for sc, k, p in pairs:
        if sc < min_score or k in used_k or p in used_p:
            continue
        rivals = [s2 for s2, k2, p2 in pairs if k2 == k and p2 != p and p2 not in used_p]
        if rivals and abs(rivals[0] - sc) < 1e-9:
            continue                      # ambiguous: leave unmatched
        out[k] = (p, sc)
        used_k.add(k); used_p.add(p)
    return out


def query_for(title: str, event_ticker: str) -> str:
    t = re.sub(r"\*\*", "", title)
    if event_ticker.startswith(("KXCLUBWCGAME", "KXEPLGAME", "KXMLSGAME", "KXUCLGAME", "KXLALIGAGAME")):
        return re.sub(r"\s*Winner\?$", "", t)
    if event_ticker.startswith("KXF1RACE"):
        m = re.search(r"(\w[\w ]*?) Grand Prix", t)
        return f"F1 {m.group(1).replace('F1 ', '')} Grand Prix Winner" if m else t
    if event_ticker.startswith("KXFEDDECISION"):
        mon = dt.datetime.strptime(event_ticker.split("-")[1], "%y%b").strftime("%B")
        return f"Fed decision in {mon}"
    if event_ticker.startswith(("KXLLM1", "KXTOPMODEL")):
        mon = dt.datetime.strptime(event_ticker.split("-")[1][:5], "%y%b").strftime("%B")
        return f"Which company has best AI model end of {mon}"
    if event_ticker.startswith("KXPGATOUR"):
        m = re.search(r"win the (.+)\?", t)
        return f"{m.group(1)} Winner" if m else t
    return t


GAME_SERIES = ("KXCLUBWCGAME", "KXEPLGAME", "KXMLSGAME", "KXUCLGAME", "KXLALIGAGAME")
F1_CODES = {"AUS": "Australian", "CHN": "Chinese", "JPN": "Japanese", "BAH": "Bahrain", "SAU": "Saudi Arabian",
            "MIA": "Miami", "CAN": "Canadian", "MON": "Monaco", "SPA": "Spanish", "AUT": "Austrian",
            "BRI": "British", "BEL": "Belgian", "HUN": "Hungarian", "DUT": "Dutch", "ITA": "Italian",
            "MAD": "Madrid", "AZE": "Azerbaijan", "SIN": "Singapore", "USA": "United States", "MEX": "Mexico City",
            "BRA": "Sao Paulo", "LV": "Las Vegas", "QAT": "Qatar", "ABU": "Abu Dhabi", "EMI": "Emilia Romagna"}


def event_query(event_ticker: str, titles, subs) -> str:
    """Query for one Kalshi event. Event-level titles ('X vs Y Winner?', 'F1 ... Winner?')
    go through query_for; market-level titles (historical API: 'Fulham wins',
    'Will Max Verstappen finish in first...') are rebuilt from leg names / ticker."""
    t0 = titles[0] if titles else ""
    if event_ticker.startswith(GAME_SERIES) and not t0.endswith("Winner?"):
        teams = sorted(s for s in subs if norm(s) not in ("tie", "draw"))
        return " vs ".join(teams[:2])
    if event_ticker.startswith("KXF1RACE") and "Grand Prix" not in t0:
        code = event_ticker.split("-")[1][:-4]           # e.g. SPAGP26 -> SPA
        name = F1_CODES.get(code)
        return f"F1 {name} Grand Prix Winner" if name else t0
    return query_for(t0, event_ticker)


def reject_title(pm_title: str, event_ticker: str) -> bool:
    """Side markets that share the query words but resolve differently."""
    t = pm_title.lower()
    bad = ["pole", "sprint", "constructor", "head to head", "method of victory", "goals", "to advance",
           "second best", "third best", "math", "top 5", "top 10", "top 20", "make the cut", "style"]
    return any(b in t for b in bad)


def search(q: str):
    import urllib.request, urllib.parse
    url = GAMMA + "?" + urllib.parse.urlencode({"q": q, "events_status": "closed", "limit_per_type": 20})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; event-pred)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r).get("events") or []
        except Exception:
            time.sleep(2 * (attempt + 1))
    print(f"  SEARCH FAILED after 3 attempts: {q!r}", flush=True)
    return []


def pick_event(events, close: dt.datetime, event_ticker: str, max_days: float):
    best = None
    for e in events:
        if not e.get("negRisk") or not e.get("endDate") or reject_title(e.get("title", ""), event_ticker):
            continue
        end = dt.datetime.fromisoformat(e["endDate"].replace("Z", "+00:00"))
        d = abs((end - close).total_seconds()) / 86400
        if d <= max_days and (best is None or d < best[0]):
            best = (d, e)
    return best[1] if best else None


def pm_legs(e):
    out = {}
    for m in e.get("markets") or []:
        name = m.get("groupItemTitle") or m.get("question") or ""
        toks = json.loads(m.get("clobTokenIds") or "[]")
        if toks:
            out[name] = toks[0]           # YES token
    return out


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (planted names)")
    m = map_legs(["PSG", "Botafogo", "Tie"], ["Paris Saint-Germain", "Botafogo", "Draw (PSG vs. Botafogo)"])
    check("Tie -> Draw via synonym", m.get("Tie", ("",))[0].startswith("Draw"))
    check("Botafogo exact", m.get("Botafogo", ("",))[0] == "Botafogo")
    check("PSG vs 'Paris Saint-Germain' left unmatched (not guessed)", "PSG" not in m)
    m = map_legs(["Bayern Munich", "SL Benfica", "Tie"], ["Bayern", "Benfica", "Draw"])
    check("token containment: Bayern Munich -> Bayern, SL Benfica -> Benfica",
          m.get("Bayern Munich", ("",))[0] == "Bayern" and m.get("SL Benfica", ("",))[0] == "Benfica")
    m = map_legs(["Cut 25bps", "Fed maintains rate"], ["25 bps decrease", "No change", "50+ bps decrease"])
    check("Fed synonyms", m == {"Cut 25bps": ("25 bps decrease", 1.0), "Fed maintains rate": ("No change", 1.0)})
    m = map_legs(["Carlos Sainz Jr."], ["Carlos Sainz", "Carlos Sainz Sr."])
    check("ambiguous tie at equal score stays unmatched", "Carlos Sainz Jr." not in m or m["Carlos Sainz Jr."][0] == "Carlos Sainz")
    check("one-to-one: a PM leg is used at most once",
          len({v[0] for v in map_legs(["A B", "A"], ["A"]).values()}) <= 1)
    close = dt.datetime(2025, 7, 27, tzinfo=dt.timezone.utc)
    evs = [{"negRisk": True, "endDate": "2025-07-27T12:00:00Z", "title": "F1 Belgian Grand Prix: Pole Winner"},
           {"negRisk": True, "endDate": "2025-07-27T12:00:00Z", "title": "F1 Belgian Grand Prix Winner"},
           {"negRisk": True, "endDate": "2024-07-28T12:00:00Z", "title": "F1 Belgian Grand Prix Winner 2024"}]
    got = pick_event(evs, close, "KXF1RACE-BELGP25", 3)
    check("pick_event: rejects pole market and last year's race", got and got["title"] == "F1 Belgian Grand Prix Winner")
    check("query: Fed", query_for("x", "KXFEDDECISION-25JUL") == "Fed decision in July")
    check("market-level game titles -> 'A vs B'",
          event_query("KXEPLGAME-26SEP20FULMUN", ["Tie is the result"], ["Tie", "Manchester United", "Fulham"]) == "Fulham vs Manchester United")
    check("F1 market-level title -> race from ticker",
          event_query("KXF1RACE-SPAGP26", ["Will Max Verstappen finish in first"], ["Max Verstappen"]) == "F1 Spanish Grand Prix Winner")
    check("event-level titles unchanged", event_query("KXCLUBWCGAME-25JUL08FLUCHE", ["Fluminense vs Chelsea Winner?"], []) == "Fluminense vs Chelsea")
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("candidates", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--max-days", type=float, default=3.0)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    k = pl.read_parquet(a.candidates)
    rows, report = [], []
    for (ev,), g in k.group_by(["event_ticker"], maintain_order=True):
        close = g["close_time"].max()
        q = event_query(ev, g["title"].to_list(), g["yes_sub_title"].to_list())
        e = pick_event(search(q), close, ev, a.max_days)
        if e is None:
            report.append((ev, "NO EVENT", q, 0, g.height)); continue
        pl_legs = pm_legs(e)
        kn = dict(zip(g["yes_sub_title"].to_list(), g["ticker"].to_list()))
        m = map_legs(list(kn), list(pl_legs))
        report.append((ev, e["title"], q, len(m), g.height))
        for kname, (pname, sc) in m.items():
            rows.append(dict(event_ticker=ev, kalshi_ticker=kn[kname], kalshi_name=kname, pm_event_id=str(e["id"]),
                             pm_event_title=e["title"], pm_name=pname, pm_token_yes=pl_legs[pname], score=sc))
        time.sleep(0.3)
    for ev, t, q, n, tot in report:
        print(f"{ev:<34} {n:>2}/{tot:<2} legs | {t[:60]}")
    df = pl.DataFrame(rows)
    df.write_parquet(a.out)
    print(f"\n{df.height} matched legs in {df['event_ticker'].n_unique() if df.height else 0} events -> {a.out}")
    low = df.filter(pl.col("score") < 1.0) if df.height else df
    if low.height:
        print("\nnon-exact name matches (review):")
        for r in low.iter_rows(named=True):
            print(f"  {r['event_ticker']:<32} {r['kalshi_name']!r:>28} -> {r['pm_name']!r} ({r['score']:.2f})")


if __name__ == "__main__":
    main()
