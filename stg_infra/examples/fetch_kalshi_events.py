"""List settled Kalshi events + markets for given series and a close-date
window, in the candidates format match_polymarket_events.py reads
(ticker, event_ticker, title, yes_sub_title, close_time), and fetch hourly
quote candles for chosen tickers.

Used for the cross-venue pre-registration (docs/planning/
cross-venue-preregistration.md). Only listing metadata is fetched by
`events`; `candles` fetches prices for the matched legs only.

    python stg_infra/examples/fetch_kalshi_events.py --self-test
    python stg_infra/examples/fetch_kalshi_events.py events OUT.parquet --series KXEPLGAME ... \
        --close-from 2026-01-01 --close-to 2026-09-25
    python stg_infra/examples/fetch_kalshi_events.py candles MATCH.parquet OUT.parquet
"""
import sys, json, time, argparse, datetime as dt
import urllib.request, urllib.parse
from pathlib import Path

API = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "Mozilla/5.0 (research; event-pred)"}


class FetchFailed(Exception):
    """A request failed for a reason other than 'not found' (e.g. rate limit, timeout)."""


def get(path, params=None, tries=4):
    """JSON on success; {} on 404 (the resource genuinely does not exist here);
    raises FetchFailed on anything else after retries, so failures are never cached as 'no data'."""
    import urllib.error
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            wait = 10 * (k + 1) if e.code == 429 else 1.5 * (k + 1)
            if k == tries - 1:
                raise FetchFailed(f"{url[:120]}: {e}")
            time.sleep(wait)
        except Exception as e:
            if k == tries - 1:
                raise FetchFailed(f"{url[:120]}: {e}")
            time.sleep(1.5 * (k + 1))


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def list_events(series, close_from, close_to):
    """Settled markets of a series closing in [close_from, close_to). Kalshi keeps
    recently settled markets on /markets and moves older ones to
    /historical/markets, so both are listed (market-level; deduplicated)."""
    rows, seen = [], set()
    for path, extra in (("/markets", {"status": "settled"}), ("/historical/markets", {})):
        cursor = None
        while True:
            p = {"series_ticker": series, "limit": 1000, **extra}
            if cursor:
                p["cursor"] = cursor
            d = get(path, p)
            for m in d.get("markets", []):
                c = parse_ts(m.get("close_time"))
                if m["ticker"] in seen or not c or not (close_from <= c < close_to):
                    continue
                seen.add(m["ticker"])
                rows.append(dict(ticker=m["ticker"], event_ticker=m.get("event_ticker") or m["ticker"].rsplit("-", 1)[0],
                                 title=m.get("title") or "", yes_sub_title=m.get("yes_sub_title") or "",
                                 close_time=c, open_time=parse_ts(m.get("open_time")), result=m.get("result"),
                                 source=path))
            cursor = d.get("cursor")
            if not cursor or not d.get("markets"):
                break
            time.sleep(0.2)
    return rows


def candle_rows(ticker, candles):
    """Kalshi candlesticks -> (ticker, end_ts, bid_close, ask_close) in dollars;
    one-sided or missing quotes become None (never 0/1 placeholders)."""
    out = []
    for c in candles:
        yb, ya = c.get("yes_bid") or {}, c.get("yes_ask") or {}
        b = yb.get("close_dollars"); a = ya.get("close_dollars")
        b = float(b) if b not in (None, "") else None
        a = float(a) if a not in (None, "") else None
        if b is not None and b <= 0: b = None
        if a is not None and a >= 1: a = None
        out.append((ticker, int(c["end_period_ts"]), b, a))
    return out


LIVE_FROM = int(dt.datetime(2026, 8, 15, tzinfo=dt.timezone.utc).timestamp())   # live endpoint holds only recent markets


def fetch_candles(series, ticker, start, end):
    """Markets that closed before LIVE_FROM go straight to /historical (the live path 404s for them)."""
    rows, s = [], int(start)
    paths = ([f"/historical/markets/{ticker}/candlesticks", f"/series/{series}/markets/{ticker}/candlesticks"]
             if end < LIVE_FROM else
             [f"/series/{series}/markets/{ticker}/candlesticks", f"/historical/markets/{ticker}/candlesticks"])
    while s < end:
        e = min(s + 5000 * 3600, int(end))
        q = {"start_ts": s, "end_ts": e, "period_interval": 60}
        d = get(paths[0], q, tries=2)
        if not d.get("candlesticks"):
            d = get(paths[1], q, tries=2)
        rows += candle_rows(ticker, d.get("candlesticks", []))
        s = e
    return rows


def self_test():
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")
    print("SELF-TEST (candle parsing)")
    r = candle_rows("T", [
        {"end_period_ts": 3600, "yes_bid": {"close_dollars": "0.4500"}, "yes_ask": {"close_dollars": "0.4700"}},
        {"end_period_ts": 7200, "yes_bid": {"close_dollars": "0.0000"}, "yes_ask": {"close_dollars": "1.0000"}},
        {"end_period_ts": 10800, "yes_bid": {}, "yes_ask": {"close_dollars": "0.5000"}}])
    check("two-sided quote kept", r[0] == ("T", 3600, 0.45, 0.47))
    check("0/1 placeholders become None", r[1][2] is None and r[1][3] is None)
    check("missing bid becomes None", r[2][2] is None and r[2][3] == 0.5)
    check("timestamps parse with Z", parse_ts("2026-09-20T15:14:01Z").tzinfo is not None)
    print("SELF-TEST", "PASSED" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["events", "candles"])
    ap.add_argument("inp", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--series", nargs="+", default=[])
    ap.add_argument("--close-from", default="2026-01-01")
    ap.add_argument("--close-to", default="2026-09-25")
    ap.add_argument("--candidates", default="data/polymarket/kalshi_2026_candidates.parquet",
                    help="candles: where open/close times come from if MATCH lacks them")
    ap.add_argument("--cache-dir", default="data/kalshi_candles_cache")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    import polars as pl
    if a.cmd == "events":
        lo = dt.datetime.fromisoformat(a.close_from).replace(tzinfo=dt.timezone.utc)
        hi = dt.datetime.fromisoformat(a.close_to).replace(tzinfo=dt.timezone.utc)
        rows = []
        for s in a.series:
            r = list_events(s, lo, hi)
            print(f"{s}: {len(r)} markets in {len({x['event_ticker'] for x in r})} events", flush=True)
            rows += r
        pl.DataFrame(rows).write_parquet(a.inp)
        print(f"-> {a.inp}")
    else:
        m = pl.read_parquet(a.inp)
        if "close_time" not in m.columns:
            cand = pl.read_parquet(a.candidates).select(pl.col("ticker").alias("kalshi_ticker"), "open_time", "close_time")
            m = m.join(cand.unique("kalshi_ticker"), on="kalshi_ticker", how="left")
        # Resumable: one cache file per leg; a restart skips legs already fetched.
        cache = Path(a.cache_dir); cache.mkdir(parents=True, exist_ok=True)
        todo = [r for r in m.select("kalshi_ticker", "event_ticker", "open_time", "close_time").unique("kalshi_ticker").iter_rows(named=True)
                if not (cache / f"{r['kalshi_ticker']}.json").exists()]
        print(f"{m['kalshi_ticker'].n_unique()} legs; {len(todo)} to fetch ({a.workers} workers)", flush=True)

        def one(r):
            try:
                return _one(r)
            except FetchFailed as e:
                print(f"  FETCH FAILED (not cached, rerun to retry): {e}", flush=True)
                return -1

        def _one(r):
            series = r["event_ticker"].split("-")[0]
            cl = int(r["close_time"].timestamp())
            start = int(r["open_time"].timestamp()) if r["open_time"] else cl - 14 * 86400
            rows = fetch_candles(series, r["kalshi_ticker"], max(start, cl - 21 * 86400), cl + 3600)
            tmp = cache / f"{r['kalshi_ticker']}.json.tmp"
            tmp.write_text(json.dumps(rows)); tmp.rename(cache / f"{r['kalshi_ticker']}.json")
            return len(rows)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(a.workers) as ex:
            failed = 0
            for i, n in enumerate(ex.map(one, todo)):
                failed += n < 0
                if i % 200 == 0:
                    print(f"  {i} legs fetched", flush=True)
        if failed:
            raise SystemExit(f"{failed} legs failed to fetch (not cached); rerun to retry before using the output")
        rows = []
        for tk in m["kalshi_ticker"].unique().to_list():
            f = cache / f"{tk}.json"
            if f.exists():
                rows += [tuple(x) for x in json.loads(f.read_text())]
        pl.DataFrame(rows, schema={"ticker": pl.Utf8, "end_s": pl.Int64, "bid": pl.Float64, "ask": pl.Float64},
                     orient="row").write_parquet(a.out)
        print(f"{len(rows):,} candles -> {a.out}")


if __name__ == "__main__":
    main()
