"""
report_numbers.py

LIVE-TEST NUMBERS FOR THE REPORT: reads one cut report (cut_report.py --out, e.g. results/live/cut_interim.json) and
writes LaTeX macros, one per reported number, so the report's text and tables never carry a hand-copied live figure.
The report is frozen at the pre-registered interim cut; this runs once against a provisional cut while drafting and
once on the real cut.

Macros (all from the cut report's headline block; `primary` = pessimistic fills, the verdict stream):
  meta            \\CutLiveStart \\CutTime \\CutSettleBy \\CutHours \\CutSource
  main result     \\Main<Stream><Arm><Field>   every arm on the L18 main result (descriptive except G2)
                  Field: Net Return Events SettledFills CILo CIHi EventClusters DayCILo DayCIHi DayClusters
  G2 verdicts     \\Main<Stream>GTwoOneSided \\Main<Stream>GTwoDayOneSided
  G2 - random     \\Main<Stream>GTwoMinusRandom{,Lo,Hi,OneSided,DayLo,DayHi,DayOneSided}   (return points)
  main risk       \\MainRisk<Arm><Field> (pessimistic): Sharpe MaxDrawdown MaxDrawdownPct ProfitableDays TopTenShare
                  PeakCapital Days; \\BenchIndexReturn \\BenchTBillReturn \\BenchIndexSource (main result's dates)
  weather (L11)   \\Main<Arm>{Weather,NonWeather}<Field> (pessimistic, within the main result); \\MainGTwoWeatherProfitShare
  full, all arms  \\Full<Stream><Arm><Field> for every arm (L19 hours)
  full universe   \\Full<Stream>GTwo<Field>, \\Full<Stream>GTwoMinusRandom...  (L19 hours), and \\FullSame... (same
                  hours as the main result)
Stream: '' (pessimistic), Strict, Opt, Sens (as-executed order window). Money '+\\$1,234.56', returns '+9.3\\%',
counts '1,055', a missing or NaN value 'n/a'.

USAGE (from repo root):
    python stg_infra/report_numbers.py --self-test
    python stg_infra/report_numbers.py --cut-json results/live/cut_interim.json --out ../fyp-report/generated/numbers.tex
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ARMS = {"g2": "GTwo", "lin2": "Linear", "mlp2": "Neural", "g": "GFrozen", "rnd2": "Random", "cand": "QuoteAll",
        "g2w1": "GTwoWOne", "g2w2": "GTwoWTwo", "g2_sel": "GTwoSel", "g2p": "GTwoTwoLevel", "rnd2p": "RandomTwoLevel",
        "wide3": "WideSpreads", "liq": "Liquid", "liq_traded": "LiquidTraded"}
STREAMS = {"primary": "", "primary_strict": "Strict", "primary_opt": "Opt", "sensitivity": "Sens"}
MAIN = "train23 (L18 main result, hours from 2026-10-16 17:00 UTC)"
FULL_PREFIX = "full universe (L19"
SAME_PREFIX = "full universe, same hours"


def _bad(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def money(v) -> str:
    if _bad(v):
        return "n/a"
    return ("+" if v > 0 else "\\(-\\)" if v < 0 else "") + f"\\${abs(v):,.2f}"


def pct(v, d=1) -> str:
    if _bad(v):
        return "n/a"
    s = f"{abs(v):.{d}f}"
    return ("+" if v > 0 and float(s) else "\\(-\\)" if v < 0 and float(s) else "") + s + "\\%"


def pts(v, d=1) -> str:
    """A signed difference in return points (no unit; the text says 'percentage points')."""
    return "n/a" if _bad(v) else pct(v, d)[:-2]


def count(v) -> str:
    return "n/a" if _bad(v) else f"{int(v):,}"


def stamp_text(s: str) -> str:
    """'20261028T00' -> '28 Oct 2026, 00:00 UTC'."""
    t = dt.datetime.strptime(s, "%Y%m%dT%H")
    return f"{t.day} {t:%b %Y}, {t:%H}:00 UTC"


def arm_fields(m: dict) -> dict:
    ci, cd = m.get("ci") or {}, m.get("ci_day_clusters") or {}
    return {"Net": money(m.get("net_usd")), "Return": pct(m.get("return_pct")), "Events": count(m.get("events", 0)),
            "SettledFills": count(m.get("settled_fills", 0)), "CILo": pct(ci.get("lo95")), "CIHi": pct(ci.get("hi95")),
            "EventClusters": count(ci.get("clusters")), "DayCILo": pct(cd.get("lo95")), "DayCIHi": pct(cd.get("hi95")),
            "DayClusters": count(cd.get("clusters")), "OneSided": pct(ci.get("lo_one_sided")),
            "DayOneSided": pct(cd.get("lo_one_sided")),
            "Capital": "n/a" if _bad(m.get("capital_usd")) else f"\\${m['capital_usd']:,.0f}"}


def diff_fields(d: dict) -> dict:
    e, y = (d or {}).get("event") or {}, (d or {}).get("day") or {}
    return {"": pts(e.get("diff")), "Lo": pts(e.get("lo95")), "Hi": pts(e.get("hi95")), "OneSided": pts(e.get("lo_one_sided")),
            "DayLo": pts(y.get("lo95")), "DayHi": pts(y.get("hi95")), "DayOneSided": pts(y.get("lo_one_sided"))}


def risk_fields(r: dict) -> dict:
    sh = r.get("sharpe")
    share = lambda v: "n/a" if _bad(v) else f"{100 * v:.0f}\\%"
    return {"Sharpe": "n/a" if _bad(sh) else (("\\(-\\)" if sh < 0 else "") + f"{abs(sh):.1f}"),
            "MaxDrawdown": "n/a" if _bad(r.get("max_drawdown_usd")) else f"\\${r['max_drawdown_usd']:,.2f}",
            "MaxDrawdownPct": share(None if _bad(r.get("max_drawdown_pct_of_peak_capital")) else r["max_drawdown_pct_of_peak_capital"] / 100),
            "ProfitableDays": share(r.get("profitable_days_share")),
            # a share of profit: undefined for a strategy that made none, shown as a dash (the caption says so)
            "TopTenShare": "--" if r and _bad(r.get("top10_event_share")) else share(r.get("top10_event_share")),
            "PeakCapital": "n/a" if _bad(r.get("peak_open_capital_usd")) else f"\\${r['peak_open_capital_usd']:,.2f}",
            "Days": count(r.get("tradedate_days")) if r else "n/a"}


def macros(rep: dict, source: str) -> dict:
    """{macro name: LaTeX text} for one cut report."""
    out = {"CutLiveStart": stamp_text(dt.datetime.fromisoformat(rep["live_start"]).strftime("%Y%m%dT%H")),
           "CutTime": stamp_text(rep["cut"]), "CutSettleBy": stamp_text(rep["settle_by"]), "CutHours": count(rep["hours"]),
           "CutSource": source}
    for w, S in STREAMS.items():
        H = rep["headline"].get(w)
        if not H:
            continue
        main = H[MAIN]
        for a, X in ARMS.items():
            for f, v in arm_fields(main.get("arms", {}).get(a, {})).items():
                out[f"Main{S}{X}{f}"] = v
        g = main.get("g2", {})
        out[f"Main{S}GTwoOneSided"] = pct((g.get("ci") or {}).get("lo_one_sided"))
        out[f"Main{S}GTwoDayOneSided"] = pct((g.get("ci_day_clusters") or {}).get("lo_one_sided"))
        for f, v in diff_fields(main.get("g2_minus_rnd2")).items():
            out[f"Main{S}GTwoMinusRandom{f}"] = v
        for prefix, P in ((FULL_PREFIX, "Full"), (SAME_PREFIX, "FullSame")):
            u = next((v for k, v in H.items() if k.startswith(prefix)), None)
            if u is None:
                continue
            for f, v in arm_fields(u.get("g2", {})).items():
                out[f"{P}{S}GTwo{f}"] = v
            for f, v in diff_fields(u.get("g2_minus_rnd2")).items():
                out[f"{P}{S}GTwoMinusRandom{f}"] = v
    for w, S in STREAMS.items():           # every arm on the full universe (L19 hours), 2026-10-26
        u = next((v for k, v in (rep["headline"].get(w) or {}).items() if k.startswith(FULL_PREFIX)), None) or {}
        for a, X in ARMS.items():
            if a == "g2":                      # \\Full<Stream>GTwo... already come from the verdict block
                continue
            for f, v in arm_fields(u.get("arms", {}).get(a, {})).items():
                out[f"Full{S}{X}{f}"] = v
    main_p = (rep["headline"].get("primary") or {}).get(MAIN, {})
    for a, X in ARMS.items():             # L11 weather / non-weather within the main result, pessimistic, 2026-10-26
        sp = (main_p.get("arms", {}).get(a, {}) or {}).get("splits") or {}
        for nm, N in (("weather", "Weather"), ("non_weather", "NonWeather")):
            for f, v in arm_fields(sp.get(nm, {})).items():
                out[f"Main{X}{N}{f}"] = v
    g2a = main_p.get("arms", {}).get("g2", {}) or {}
    wn, tn = ((g2a.get("splits") or {}).get("weather") or {}).get("net_usd"), g2a.get("net_usd")
    out["MainGTwoWeatherProfitShare"] = ("n/a" if _bad(wn) or _bad(tn) or tn <= 0 else f"{100 * wn / tn:.0f}\\%")
    for a, X in ARMS.items():
        for f, v in risk_fields((main_p.get("arms", {}).get(a, {}) or {}).get("risk") or {}).items():
            out[f"MainRisk{X}{f}"] = v
    bmk = rep.get("benchmarks_main") or {}
    out["BenchIndexReturn"] = pct(bmk.get("index_return_pct"))
    out["BenchTBillReturn"] = pct(bmk.get("tbill_return_pct"), 2)
    out["BenchIndexSource"] = (bmk.get("index_source") or "n/a").replace("&", "\\&")
    bad = [k for k in out if not re.fullmatch(r"[A-Za-z]+", k)]
    if bad:
        raise ValueError(f"macro names must be letters only: {bad}")
    return out


def render(ms: dict, header: list) -> str:
    lines = [f"% {h}" for h in header] + [""]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in sorted(ms.items())]
    return "\n".join(lines) + "\n"


def main_run(cut_json: Path, out: Path):
    raw = cut_json.read_bytes()
    rep = json.loads(raw)
    src = f"{cut_json.name}, sha256 {hashlib.sha256(raw).hexdigest()[:12]}"
    ms = macros(rep, src.replace("_", "\\_"))
    header = ["generated by event-pred stg_infra/report_numbers.py -- do not edit by hand",
              f"source: {cut_json} (sha256 {hashlib.sha256(raw).hexdigest()})",
              f"cut {rep['cut']}, settle-by {rep['settle_by']}, generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC"]
    out.write_text(render(ms, header))
    print(json.dumps({"macros": len(ms), "out": str(out), "G2 main": [ms.get("MainGTwoNet"), ms.get("MainGTwoReturn")]}))


# ---------------------------------------------------------------- self-test

def self_test() -> bool:
    ok = True

    def check(msg, c):
        nonlocal ok
        ok &= bool(c)
        print(f"  [{'PASS' if c else 'FAIL'}] {msg}")

    check("money: sign, thousands, two decimals", (money(1234.5), money(-5.0), money(0.0), money(None))
          == ("+\\$1,234.50", "\\(-\\)\\$5.00", "\\$0.00", "n/a"))
    check("pct: sign, one decimal; a value rounding to 0.0 has no sign; NaN -> n/a",
          (pct(9.32), pct(-5.88), pct(-0.04), pct(float("nan"))) == ("+9.3\\%", "\\(-\\)5.9\\%", "0.0\\%", "n/a"))
    check("pts: signed return points without the % sign", (pts(9.916), pts(-0.62)) == ("+9.9", "\\(-\\)0.6"))
    check("count: thousands separator", (count(1055), count(3)) == ("1,055", "3"))
    check("stamp text", stamp_text("20261028T00") == "28 Oct 2026, 00:00 UTC")
    ci = {"ret": 4.0, "clusters": 21, "lo95": -6.39, "hi95": 14.76, "lo_one_sided": -4.59}
    cd = {"ret": 4.0, "clusters": 3, "lo95": -15.7, "hi95": 11.0, "lo_one_sided": -7.9}
    g2 = {"net_usd": 101.04, "capital_usd": 1084.0, "return_pct": 9.32, "fills": 596, "settled_fills": 365, "events": 29,
          "ci": ci, "ci_day_clusters": cd}
    rnd = {"net_usd": -99.75, "return_pct": -5.15, "settled_fills": 300, "events": 35, "ci": {}, "ci_day_clusters": {}}
    diff = {"event": {"diff": 14.47, "lo95": 3.1, "hi95": 25.0, "lo_one_sided": 4.9},
            "day": {"diff": 14.47, "lo95": -2.0, "hi95": 30.0, "lo_one_sided": 0.5}}
    head = {MAIN: {"g2": g2, "g2_minus_rnd2": diff, "arms": {"g2": g2, "rnd2": rnd}},
            "full universe (L19: quoting hours S to 2026-10-17 T05)": {"g2": {"net_usd": -760.34, "return_pct": -6.11,
                                                                              "events": 876, "settled_fills": 5512},
                                                                       "arms": {"rnd2": {"net_usd": -900.0, "return_pct": -8.0}}},
            "full universe, same hours as the main result (descriptive; ...)": {"g2": {"net_usd": -197.03, "return_pct": -6.08}}}
    g2["splits"] = {"weather": {"net_usd": 75.0, "return_pct": 12.0, "events": 20, "settled_fills": 200, "ci": {}},
                    "non_weather": {"net_usd": 26.04, "return_pct": 5.0, "events": 9, "settled_fills": 165, "ci": {}}}
    g2["risk"] = {"tradedate_days": 12, "peak_open_capital_usd": 1234.5, "sharpe": 3.456, "max_drawdown_usd": 40.0,
                  "max_drawdown_pct_of_peak_capital": 3.24, "profitable_days_share": 0.75, "top10_event_share": 0.62}
    rep = {"cut": "20261028T00", "settle_by": "20261030T00", "live_start": "2026-10-15T19:00:00+00:00", "hours": 300,
           "benchmarks_main": {"index_return_pct": 1.234, "tbill_return_pct": 0.12, "index_source": "FRED SP500 (price index, no dividends)"},
           "headline": {"primary": head, "primary_strict": {MAIN: {"g2": g2, "arms": {"g2": {**g2, "net_usd": 50.0}}}}}}
    ms = macros(rep, "planted.json")
    check("main result: G2 net, return, events, event-cluster CI and k", (ms["MainGTwoNet"], ms["MainGTwoReturn"],
          ms["MainGTwoEvents"], ms["MainGTwoCILo"], ms["MainGTwoCIHi"], ms["MainGTwoEventClusters"], ms["MainGTwoDayClusters"])
          == ("+\\$101.04", "+9.3\\%", "29", "\\(-\\)6.4\\%", "+14.8\\%", "21", "3"))
    check("main result: random from the every-arm block; an arm absent from the cut is n/a, not zero",
          ms["MainRandomNet"] == "\\(-\\)\\$99.75" and ms["MainNeuralNet"] == "n/a" and ms["MainNeuralEvents"] == "0")
    check("verdicts: G2 one-sided bounds and G2 minus random (return points)",
          (ms["MainGTwoOneSided"], ms["MainGTwoMinusRandom"], ms["MainGTwoMinusRandomOneSided"], ms["MainGTwoMinusRandomDayLo"])
          == ("\\(-\\)4.6\\%", "+14.5", "+4.9", "\\(-\\)2.0"))
    check("committed capital, whole dollars; absent -> n/a", (ms["MainGTwoCapital"], ms["MainNeuralCapital"]) == ("\\$1,084", "n/a"))
    check("every arm gets its one-sided bounds (descriptive outside G2); absent -> n/a",
          (ms["MainRandomOneSided"], ms["MainNeuralOneSided"]) == ("n/a", "n/a") and ms["MainGTwoDayOneSided"] == "\\(-\\)7.9\\%")
    check("fill models: the strict stream gets its own prefix", ms["MainStrictGTwoNet"] == "+\\$50.00")
    check("full universe (L19) and same hours", (ms["FullGTwoNet"], ms["FullGTwoReturn"], ms["FullSameGTwoNet"])
          == ("\\(-\\)\\$760.34", "\\(-\\)6.1\\%", "\\(-\\)\\$197.03"))
    check("meta: cut, settle-by and live start in words",
          (ms["CutTime"], ms["CutSettleBy"], ms["CutLiveStart"], ms["CutHours"])
          == ("28 Oct 2026, 00:00 UTC", "30 Oct 2026, 00:00 UTC", "15 Oct 2026, 19:00 UTC", "300"))
    check("main risk: Sharpe, drawdown and its share of peak capital, profitable days, top-10 share, days; absent arm n/a",
          (ms["MainRiskGTwoSharpe"], ms["MainRiskGTwoMaxDrawdown"], ms["MainRiskGTwoMaxDrawdownPct"], ms["MainRiskGTwoProfitableDays"],
           ms["MainRiskGTwoTopTenShare"], ms["MainRiskGTwoDays"], ms["MainRiskNeuralSharpe"])
          == ("3.5", "\\$40.00", "3\\%", "75\\%", "62\\%", "12", "n/a"))
    rl = macros({**rep, "headline": {"primary": {MAIN: {**head[MAIN], "arms": {"g2": g2, "rnd2": {**rnd, "risk": {
        "tradedate_days": 12, "top10_event_share": float("nan")}}}}}}}, "planted.json")
    check("top-10 share of a losing strategy is a dash, not n/a", rl["MainRiskRandomTopTenShare"] == "--")
    check("weather split within the main result, and weather's share of G2's net (75 / 101.04 = 74%)",
          (ms["MainGTwoWeatherNet"], ms["MainGTwoNonWeatherReturn"], ms["MainGTwoWeatherProfitShare"], ms["MainRandomWeatherNet"])
          == ("+\\$75.00", "+5.0\\%", "74\\%", "n/a"))
    check("full universe, every arm: random from the arms block; G2 keeps the verdict block's macros",
          (ms["FullRandomNet"], ms["FullRandomReturn"], ms["FullGTwoNet"]) == ("\\(-\\)\\$900.00", "\\(-\\)8.0\\%", "\\(-\\)\\$760.34"))
    check("benchmarks over the main result's dates", (ms["BenchIndexReturn"], ms["BenchTBillReturn"])
          == ("+1.2\\%", "+0.12\\%"))
    check("every macro name is letters only and unique", all(re.fullmatch(r"[A-Za-z]+", k) for k in ms))
    txt = render(ms, ["test"])
    check("render: one \\newcommand per macro, sorted", txt.count("\\newcommand") == len(ms) and "\\newcommand{\\MainGTwoNet}{+\\$101.04}" in txt)
    import shutil
    import subprocess
    import tempfile
    if shutil.which("pdflatex"):
        with tempfile.TemporaryDirectory() as td:
            Path(td, "n.tex").write_text(txt)
            Path(td, "t.tex").write_text("\\documentclass{article}\\begin{document}\\input{n.tex}"
                                         "\\MainGTwoNet{} \\MainGTwoReturn{} \\MainRandomNet{} \\FullGTwoReturn{} \\CutTime\\end{document}\n")
            r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "-halt-on-error", "t.tex"], cwd=td, capture_output=True, text=True)
            check("the generated file compiles in LaTeX", r.returncode == 0)
    print("SELF-TEST PASSED" if ok else "SELF-TEST FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--cut-json", type=Path, help="cut_report.py --out file")
    ap.add_argument("--out", type=Path, help="numbers .tex file to write")
    a = ap.parse_args()
    if a.self_test:
        sys.exit(0 if self_test() else 1)
    if not (a.cut_json and a.out):
        ap.error("--cut-json and --out are required")
    main_run(a.cut_json, a.out)


if __name__ == "__main__":
    main()
