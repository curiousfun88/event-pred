"""Exploratory (development months only): does public Spotify streaming data
predict Kalshi's "top song on Spotify US on day D" (KXSPOTIFYD) better than
the market price?

Data: kworb.net (free, public). The US totals page gives track ids and names;
each track page gives its daily US chart position and streams.

Timing (conservative): the chart for date C is treated as public only from
C+1 20:00 UTC (16:00 ET), later than Spotify's usual release. Each event is
evaluated at one snapshot, H = D 22:00 UTC, using charts for dates <= D-1
and Kalshi's quotes at H.

Model: softmax within the basket over a*log(streams_C + 1) + b*growth(C-1 ->
C), with C the latest public chart date. (a, b) are fitted leave-one-month-out
(the scored month never fitted). Market: Kalshi mids at H normalised within
the basket. Blend: logit-linear pool of model and market, weight fitted
leave-one-month-out.
Reported: winner log-loss (model / market / blend), and a taker rule: buy a
leg when model_p - ask >= edge; P&L = 1{win}*100 - ask - fee, one trade per
leg; CI resampling events.

    python stg_infra/examples/spotify_us_check.py --self-test
    python stg_infra/examples/spotify_us_check.py kworb     # build name map, fetch track pages (cached)
    python stg_infra/examples/spotify_us_check.py analyse
"""
import sys, re, json, time, math, argparse, difflib, datetime as dt
from pathlib import Path
import numpy as np

KW = "https://kworb.net/spotify"
UA = {"User-Agent": "Mozilla/5.0 (research; event-pred)"}
DIR = Path("data/spotify_kworb")
CAND = Path("data/polymarket/spotify_us_dev_candidates.parquet")
CANDLES = Path("data/polymarket/spotify_us_dev_candles.parquet")
PUBLISH_LAG_S = 44 * 3600          # chart for date C public from C 00:00 UTC + 44h = C+1 20:00 UTC
SNAP_HOUR_UTC = 22


def taker_fee_c(p_c):
    p = p_c / 100.0
    return math.ceil(round(0.07 * p * (1 - p) * 100, 6))


def get(url):
    import urllib.request
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:
            if k == 2:
                print(f"  GET FAILED {url}: {e}", flush=True)
                return ""
            time.sleep(2 * (k + 1))


def norm_song(s):
    s = (s or "").lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)            # drop (feat. ...), (with ...)
    s = re.sub(r"\bfeat\.?.*$|\bft\.?.*$|\bwith .*$", " ", s)
    s = s.replace("’", "'")
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_totals(html):
    """US totals page -> {track_id: (title, total_us_streams)}; the title is the track link's own text."""
    import html as H
    out = {}
    for row in re.findall(r"<tr>(.*?)</tr>", html, re.S):
        m = re.search(r'href="\.\./track/([A-Za-z0-9]+)\.html">([^<]+)</a>', row)
        if not m:
            continue
        nums = re.findall(r"<td>([\d,]+)</td>", row)
        total = int(nums[-1].replace(",", "")) if nums else 0
        out.setdefault(m.group(1), (H.unescape(m.group(2)).strip(), total))
    return out


def parse_track(html):
    """Track page -> {date 'YYYY/MM/DD': (us_pos, us_streams)} for days on the US chart.
    Column order comes from the header row, so 'US' is located, not assumed."""
    rows = re.findall(r"<tr>(.*?)</tr>", html, re.S)
    if not rows:
        return {}
    hdr = [re.sub(r"<[^>]+>", "", c).strip() for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", rows[0], re.S)]
    if "US" not in hdr:
        return {}
    j = hdr.index("US")
    out = {}
    for r in rows[1:]:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)
        if len(cells) <= j:
            continue
        date = re.sub(r"<[^>]+>", "", cells[0]).strip()
        c = re.sub(r"<[^>]+>", " ", cells[j])
        m = re.search(r"(\d+)\s*\(\s*([\d,]+)\s*\)", c)
        if m and re.match(r"\d{4}/\d{2}/\d{2}", date):
            out[date] = (int(m.group(1)), int(m.group(2).replace(",", "")))
    return out


def match_songs(kalshi_names, totals):
    """Kalshi song name -> kworb track id, by normalised title. Several tracks with the same
    title: take the one with the most US streams only if it has >= 3x the runner-up (the
    dominant version), else leave unmatched. Fuzzy matches need ratio >= 0.9 and a clear lead."""
    titles = {tid: norm_song(v[0]) for tid, v in totals.items()}
    total = {tid: v[1] for tid, v in totals.items()}
    out = {}
    for name in kalshi_names:
        n = norm_song(name)
        if not n:
            continue
        exact = sorted((tid for tid, tt in titles.items() if tt == n), key=lambda x: -total[x])
        if len(exact) == 1 or (len(exact) > 1 and total[exact[0]] >= 3 * max(total[exact[1]], 1)):
            out[name] = exact[0]; continue
        if len(exact) > 1:
            continue
        sc = sorted(((difflib.SequenceMatcher(None, n, tt).ratio(), tid) for tid, tt in titles.items()), reverse=True)
        if sc and sc[0][0] >= 0.9 and (len(sc) == 1 or sc[1][0] < sc[0][0] - 0.02):
            out[name] = sc[0][1]
    return out


# ---------------------------------------------------------------- model
def features(streams_by_song, songs, snap_ts):
    """Latest public chart date C (publication lag applied) and per-song (log streams C, growth)."""
    feats = []
    for s in songs:
        hist = streams_by_song.get(s, {})
        pub = sorted(d for d in hist if d + PUBLISH_LAG_S <= snap_ts)
        if not pub:
            feats.append((0.0, 0.0)); continue
        c = pub[-1]
        s_c = hist[c][1]
        s_p = hist.get(c - 86400, (None, 0))[1]
        feats.append((math.log(s_c + 1), math.log(s_c + 1) - math.log(s_p + 1) if s_p else 0.0))
    return np.array(feats)


def softmax_probs(F, w):
    z = F @ w
    z = z - z.max()
    e = np.exp(z)
    return e / e.sum()


def fit(events, w0=(1.0, 0.0)):
    """Maximise the winner log-likelihood over events [(F, win_idx)]; Nelder-Mead on 2 params."""
    from scipy.optimize import minimize
    def nll(w):
        return -sum(math.log(max(softmax_probs(F, w)[k], 1e-9)) for F, k in events)
    return minimize(nll, np.array(w0), method="Nelder-Mead").x


def pool(p_model, p_mkt, lam):
    """Logarithmic pool within a basket."""
    z = lam * np.log(np.clip(p_model, 1e-6, 1)) + (1 - lam) * np.log(np.clip(p_mkt, 1e-6, 1))
    e = np.exp(z - z.max())
    return e / e.sum()


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST")
    html = ("<table><tr><th>Date</th><th>Global</th><th>US</th></tr>"
            "<tr><td>2025/02/19</td><td>3 (5,000,000)</td><td>1 (2,500,123)</td></tr>"
            "<tr><td>2025/02/20</td><td>4 (4,000,000)</td><td>--</td></tr></table>")
    p = parse_track(html)
    check("track page: US column located by header", p == {"2025/02/19": (1, 2500123)})
    check("song norm drops feat/with", norm_song("luther (with sza)") == "luther" and norm_song("tv off (feat. lefty gunplay)") == "tv off")
    tot = parse_totals('<tr><td><a href="../track/a.html">luther (with sza)</a></td><td>10</td><td>900</td></tr>'
                       '<tr><td><a href="../track/b.html">Die With A Smile</a></td><td>10</td><td>800</td></tr>'
                       '<tr><td><a href="../track/c.html">tv off</a></td><td>10</td><td>700</td></tr>'
                       '<tr><td><a href="../track/d.html">Abracadabra</a></td><td>10</td><td>900</td></tr>'
                       '<tr><td><a href="../track/e.html">Abracadabra</a></td><td>10</td><td>100</td></tr>'
                       '<tr><td><a href="../track/f.html">Again</a></td><td>10</td><td>500</td></tr>'
                       '<tr><td><a href="../track/g.html">Again</a></td><td>10</td><td>400</td></tr>')
    m = match_songs(["luther (with sza)", "Die With A Smile", "Unknown Song", "Abracadabra", "Again"], tot)
    check("name match: exact titles map, unknown stays unmatched", m.get("luther (with sza)") == "a" and "Unknown Song" not in m)
    check("duplicate titles: dominant version (9x) taken, close versions (1.25x) left unmatched",
          m.get("Abracadabra") == "d" and "Again" not in m)
    d0 = int(dt.datetime(2025, 2, 19, tzinfo=dt.timezone.utc).timestamp())
    hist = {"x": {d0: (1, 1000), d0 + 86400: (1, 2000)}, "y": {d0: (2, 500), d0 + 86400: (2, 400)}}
    snap = d0 + 86400 + PUBLISH_LAG_S - 1          # 2/20 chart not yet public
    F = features(hist, ["x", "y", "z"], snap)
    check("publication lag: latest public chart is 2/19", abs(F[0, 0] - math.log(1001)) < 1e-9 and F[2, 0] == 0.0)
    rng = np.random.default_rng(0)
    evs = []
    for _ in range(300):
        F = np.c_[rng.normal(10, 1, 5), rng.normal(0, 0.1, 5)]
        k = int(rng.choice(5, p=softmax_probs(F, np.array([2.0, 0.0]))))
        evs.append((F, k))
    w = fit(evs)
    check(f"fit recovers planted weight a=2 ({w[0]:.2f})", abs(w[0] - 2.0) < 0.4)
    check("pool lam=1 -> model, lam=0 -> market",
          np.allclose(pool(np.array([.7, .3]), np.array([.2, .8]), 1), [.7, .3]) and
          np.allclose(pool(np.array([.7, .3]), np.array([.2, .8]), 0), [.2, .8]))
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


# ---------------------------------------------------------------- commands
def cmd_kworb():
    import polars as pl
    DIR.mkdir(parents=True, exist_ok=True)
    tf = DIR / "us_daily_totals.html"
    if not tf.exists():
        tf.write_text(get(f"{KW}/country/us_daily_totals.html"))
    totals = parse_totals(tf.read_text())
    c = pl.read_parquet(CAND)
    names = sorted(set(c["yes_sub_title"].to_list()))
    m = match_songs(names, totals)
    print(f"{len(names)} distinct Kalshi song names; matched {len(m)} to kworb tracks")
    for n in names:
        if n not in m:
            print(f"  unmatched: {n!r}")
    (DIR / "name_map.json").write_text(json.dumps(m, indent=1))
    for i, tid in enumerate(sorted(set(m.values()))):
        f = DIR / f"{tid}.html"
        if not f.exists():
            f.write_text(get(f"{KW}/track/{tid}.html")); time.sleep(1.0)
    print("track pages cached in", DIR)


def cmd_analyse():
    import polars as pl
    m = json.loads((DIR / "name_map.json").read_text())
    hist = {}
    for name, tid in m.items():
        f = DIR / f"{tid}.html"
        if f.exists():
            h = parse_track(f.read_text())
            hist[name] = {int(dt.datetime.strptime(d, "%Y/%m/%d").replace(tzinfo=dt.timezone.utc).timestamp()): v
                          for d, v in h.items()}
    c = pl.read_parquet(CAND)
    k = pl.read_parquet(CANDLES)
    quotes = {}
    for tk, h, b, a in zip(k["ticker"], k["end_s"], k["bid"], k["ask"]):
        quotes.setdefault(tk, {})[int(h)] = (b, a)
    events = []
    for (ev,), g in c.group_by(["event_ticker"], maintain_order=True):
        day = dt.datetime.strptime(ev.split("-")[1], "%y%b%d").replace(tzinfo=dt.timezone.utc)
        snap = int((day + dt.timedelta(hours=SNAP_HOUR_UTC)).timestamp())
        g = g.filter(pl.col("close_time").dt.epoch("s") > snap)
        if g.height < 2 or (g["result"] == "yes").sum() != 1:
            continue
        songs, tks, win = g["yes_sub_title"].to_list(), g["ticker"].to_list(), g["result"].to_list().index("yes")
        if songs[win] not in hist:
            continue                                   # winner unmapped: skip (reported)
        mid, ask = [], []
        for t in tks:
            q = quotes.get(t, {}).get(snap)
            b, a = (q if q else (None, None))
            b = b if (b is not None and b > 0) else 0.0
            a = a if (a is not None and a < 1) else None
            mid.append((b + (a if a is not None else b)) / 2)
            ask.append(a)
        if sum(mid) <= 0:
            continue
        F = features(hist, songs, snap)
        events.append(dict(ev=ev, month=ev.split("-")[1][:5], F=F, win=win,
                           mkt=np.array(mid) / sum(mid), ask=ask))
    print(f"DEVELOPMENT MONTHS ONLY: {len(events)} usable events (snapshot {SNAP_HOUR_UTC}:00 UTC on day D)")
    months = sorted({e["month"] for e in events})
    for e in events:
        e["model"] = None
    for mo in months:
        tr = [(e["F"], e["win"]) for e in events if e["month"] != mo]
        w = fit(tr)
        for e in events:
            if e["month"] == mo:
                e["model"] = softmax_probs(e["F"], w)
    lams = np.linspace(0, 1, 21)
    for mo in months:
        tr = [e for e in events if e["month"] != mo]
        best = min(lams, key=lambda l: -sum(math.log(max(pool(e["model"], e["mkt"], l)[e["win"]], 1e-9)) for e in tr))
        for e in events:
            if e["month"] == mo:
                e["blend"] = pool(e["model"], e["mkt"], best); e["lam"] = best
    ll = lambda key: np.array([-math.log(max(e[key][e["win"]], 1e-9)) for e in events])
    evn = np.array([e["ev"] for e in events])
    print(f"\nwinner log-loss (lower is better), mean over events:")
    for key in ("mkt", "model", "blend"):
        print(f"  {key:<6}: {ll(key).mean():.4f}")
    d = ll("blend") - ll("mkt")
    rng = np.random.default_rng(0); idx = rng.integers(0, len(d), size=(4000, len(d)))
    lo, hi = np.percentile(d[idx].mean(1), [2.5, 97.5])
    print(f"  blend - market: {d.mean():+.4f}  CI95 [{lo:+.4f}, {hi:+.4f}]  (negative = data adds information)")
    print(f"  pooling weight on the model (per held-out month): {sorted({round(e['lam'], 2) for e in events})}")
    print(f"  market favourite wins: {np.mean([np.argmax(e['mkt']) == e['win'] for e in events]):.1%}; "
          f"model favourite wins: {np.mean([np.argmax(e['model']) == e['win'] for e in events]):.1%}")
    print("\ntaker rule: buy a leg when blend_p - ask >= edge (one trade per leg, at the snapshot)")
    for edge in (5, 10, 20):
        pnl, g = [], []
        for e in events:
            for j, a in enumerate(e["ask"]):
                if a is None:
                    continue
                ac = round(a * 100)
                if e["blend"][j] * 100 - ac >= edge:
                    pnl.append((100 if j == e["win"] else 0) - ac - taker_fee_c(ac)); g.append(e["ev"])
        pnl, g = np.array(pnl, float), np.array(g)
        if len(pnl) == 0:
            print(f"  edge {edge:>2}c: no trades"); continue
        _, inv = np.unique(g, return_inverse=True); kk = inv.max() + 1
        s = np.bincount(inv, weights=pnl, minlength=kk); cn = np.bincount(inv, minlength=kk)
        b = np.random.default_rng(0).integers(0, kk, size=(4000, kk))
        lo, hi = np.percentile(s[b].sum(1) / cn[b].sum(1), [2.5, 97.5])
        print(f"  edge {edge:>2}c: {len(pnl):>4} trades in {kk:>3} events  mean {pnl.mean():+6.2f}c/contract  CI95 [{lo:+.2f}, {hi:+.2f}]")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["kworb", "analyse"])
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    {"kworb": cmd_kworb, "analyse": cmd_analyse}[a.cmd]()


if __name__ == "__main__":
    main()
