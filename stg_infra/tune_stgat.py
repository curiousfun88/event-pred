"""
tune_stgat.py

PRE-REGISTERED STGAT TUNING CONTROLLER (docs/planning/stgat-7-2-4-preregistration.md §3).

Stages
  1. SCREEN  : the defaults first, then N sampled configurations, each for
               SCREEN_EPOCHS epochs, seed 0. A run is PRUNED at epochs 2 and 4 if
               its validation MECE is worse than the median of earlier runs at
               that epoch. EARLY EXIT: if none of the first 8 sampled configs
               beats the defaults' epoch-4 validation MECE by >= 2%, screening
               stops.
  2. PROMOTE : unless the stop rule fires (no config beats the defaults by >= 2%
               after screening), the top 4 are trained fresh to PROMOTE_EPOCHS
               epochs (patience 5, min improvement 0.5%). A fresh run to 20
               epochs is used rather than resuming: train_forecast.py has no
               resume, and a seeded fresh run is equivalent.
  3. FINAL   : the best configuration, 4 seeds, up to FINAL_EPOCHS epochs,
               patience 5, min improvement 0.5%.

The controller only ever passes TRAIN + VALIDATION months to train_forecast.py,
so no test-month bundle is loaded during tuning. Everything is resumable:
finished runs are recorded in runs/tune/results.jsonl and skipped on re-run.

USAGE (from repo root)
  python stg_infra/tune_stgat.py --self-test
  python stg_infra/tune_stgat.py --dry-run          # print the plan and commands
  python stg_infra/tune_stgat.py                     # run all stages
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
TRAIN_MONTHS = ["2024-11", "2024-12", "2025-01", "2025-02", "2025-03", "2025-04", "2025-05"]
VAL_MONTHS = ["2025-06", "2025-07"]
SPLIT = "2025-05,2025-07"
OUT = _REPO / "runs/tune"
SCREEN_EPOCHS, PROMOTE_EPOCHS, FINAL_EPOCHS = 6, 20, 40
N_SAMPLED, EARLY_EXIT_AFTER, PRUNE_EPOCHS = 16, 8, (2, 4)
MIN_GAIN = 0.02            # 2% better than the defaults
PATIENCE, MIN_DELTA = 5, 0.005
# Amendment B1.3: quote inputs {off, on} and the mid-move weight join the
# space. The defaults entry has quote inputs off, w_mid 1, and the mid-move
# head always present (S4 needs it).
DEFAULTS = {"embed_dim": 32, "n_heads": 4, "lr": 1e-3, "dropout": 0.0, "w_mece": 1.0,
            "quote_features": False, "w_mid": 1.0}
# Amendment B2: embed_dim {16, 32}, not {32, 64, 128}. Measured peak for one
# train step on the largest train chunk (2025-05, N=8,816): d32 4.6GB, d48
# 6.1GB, d64/d128 killed at the 5.8GB cap (est. ~8/~14GB) on a 7.8GB VM.
SPACE = {"embed_dim": [16, 32], "n_heads": [2, 4, 8], "lr": [3e-4, 1e-3, 3e-3],
         "dropout": [0.0, 0.1, 0.2], "w_mece": [0.5, 1.0, 2.0],
         "quote_features": [False, True], "w_mid": [0.5, 1.0, 2.0]}


# ---------------------------------------------------------------- pure pieces

def sample_configs(n: int, seed: int = 0):
    """n distinct configs from SPACE (heads must divide the hidden size), excluding the defaults."""
    rng = random.Random(seed)
    out, seen = [], {tuple(sorted(DEFAULTS.items()))}
    while len(out) < n:
        c = {k: rng.choice(v) for k, v in SPACE.items()}
        if c["embed_dim"] % c["n_heads"]:
            continue
        key = tuple(sorted(c.items()))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def name_of(c: dict) -> str:
    return (f"d{c['embed_dim']}_h{c['n_heads']}_lr{c['lr']:g}_do{c['dropout']:g}_wm{c['w_mece']:g}"
            f"_q{int(c['quote_features'])}_wmid{c['w_mid']:g}")


def should_prune(val_at_epoch: float, earlier_at_epoch: list) -> bool:
    """Median rule: prune if strictly worse than the median of earlier runs at this epoch."""
    return bool(earlier_at_epoch) and val_at_epoch > statistics.median(earlier_at_epoch)


def beats(val: float, ref: float, gain: float = MIN_GAIN) -> bool:
    return val <= ref * (1.0 - gain)


def read_history(run_dir: Path):
    """epoch -> val_mece from train_forecast's per-epoch history.csv."""
    f = run_dir / "history.csv"
    if not f.exists():
        return {}
    out = {}
    with open(f) as fh:
        for r in csv.DictReader(fh):
            try:
                out[int(r["epoch"])] = float(r["val_mece"])
            except (KeyError, ValueError):
                pass
    return out


# ---------------------------------------------------------------- running

def command(c: dict, epochs: int, seed: int, run_dir: Path):
    return [sys.executable, "-u", str(_REPO / "stg_infra/train_forecast.py"),
            "--cache", "cache_724", "--months", *TRAIN_MONTHS, *VAL_MONTHS, "--split", SPLIT,
            "--w-ladder", "0", "--supervise", "all", "--select-on", "mece",
            "--epochs", str(epochs), "--patience", str(PATIENCE), "--min-delta", str(MIN_DELTA),
            "--seed", str(seed), "--embed-dim", str(c["embed_dim"]), "--n-heads", str(c["n_heads"]),
            "--lr", str(c["lr"]), "--dropout", str(c["dropout"]), "--w-mece", str(c["w_mece"]),
            "--w-mid", str(c["w_mid"]), *(["--quote-features"] if c["quote_features"] else []),
            "--checkpoint-dir", str(run_dir)]


def load_done():
    f = OUT / "results.jsonl"
    done = {}
    if f.exists():
        for line in f.read_text().splitlines():
            r = json.loads(line)
            done[r["run"]] = r
    return done


def record(r: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "results.jsonl", "a") as fh:
        fh.write(json.dumps(r) + "\n")


def ablation_config(screened):
    """B1.4: the best quote-OFF configuration from the screen, or None unless
    the best quote-ON screened run beats the best quote-OFF one by >= 2%."""
    ok = [r for r in screened if r.get("best_val") is not None and r.get("status") == "done"]
    on = sorted((r for r in ok if r["config"].get("quote_features")), key=lambda r: r["best_val"])
    off = sorted((r for r in ok if not r["config"].get("quote_features")), key=lambda r: r["best_val"])
    if on and off and beats(on[0]["best_val"], off[0]["best_val"]):
        return off[0]["config"]
    return None


def run(c, epochs, seed, stage, prune_ref=None, dry=False):
    """Train one run, pruning via prune_ref(epoch, val) -> bool. Returns the result dict."""
    rid = f"{stage}_{name_of(c)}_s{seed}"
    done = load_done()
    if rid in done:
        return done[rid]
    run_dir = OUT / rid
    cmd = command(c, epochs, seed, run_dir)
    if dry:
        print("   ", " ".join(cmd[2:]))
        return {"run": rid, "config": c, "hist": {}, "status": "dry"}
    run_dir.mkdir(parents=True, exist_ok=True)
    log = open(run_dir / "train.log", "w")
    p = subprocess.Popen(cmd, cwd=_REPO, stdout=log, stderr=subprocess.STDOUT)
    status, checked = "done", set()
    while p.poll() is None:
        time.sleep(20)
        h = read_history(run_dir)
        for e in PRUNE_EPOCHS:
            if prune_ref and e in h and e not in checked:
                checked.add(e)
                if prune_ref(e, h[e]):
                    p.terminate()
                    p.wait()
                    status = f"pruned@{e}"
                    break
        if status != "done":
            break
    log.close()
    if status == "done" and p.returncode != 0:
        status = f"failed rc={p.returncode}"
    h = read_history(run_dir)
    r = {"run": rid, "stage": stage, "config": c, "seed": seed, "status": status,
         "hist": {str(k): v for k, v in h.items()}, "best_val": min(h.values()) if h else None}
    record(r)
    print(f"  {rid}: {status}, best val_mece {r['best_val']}", flush=True)
    return r


def main_run(dry: bool):
    print(f"TRAIN {TRAIN_MONTHS[0]}..{TRAIN_MONTHS[-1]} | VAL {VAL_MONTHS[0]}..{VAL_MONTHS[-1]} | "
          f"test months are never passed to training", flush=True)
    # ---- 1. SCREEN
    print("\n== SCREEN", flush=True)
    screened = []
    d = run(DEFAULTS, SCREEN_EPOCHS, 0, "screen", dry=dry)
    screened.append(d)
    d_e4 = (d["hist"].get(str(4)) if d["hist"] else None)

    def prune_ref(e, v):
        earlier = [r["hist"][str(e)] for r in screened if str(e) in r["hist"]]
        return should_prune(v, earlier)

    for i, c in enumerate(sample_configs(N_SAMPLED)):
        r = run(c, SCREEN_EPOCHS, 0, "screen", prune_ref=prune_ref, dry=dry)
        screened.append(r)
        if not dry and i + 1 == EARLY_EXIT_AFTER and d_e4 is not None:
            e4 = [x["hist"].get("4") for x in screened[1:] if x["hist"].get("4") is not None]
            if not any(beats(v, d_e4) for v in e4):
                print(f"  EARLY EXIT: none of the first {EARLY_EXIT_AFTER} configs beats the defaults' epoch-4 "
                      f"val_mece ({d_e4:.5f}) by {MIN_GAIN:.0%}", flush=True)
                break
    if dry:
        winner = DEFAULTS
    else:
        full = [r for r in screened if r["best_val"] is not None and r["status"] == "done"]
        full.sort(key=lambda r: r["best_val"])
        d_best = d["best_val"]
        if not any(beats(r["best_val"], d_best) for r in full if r["config"] != DEFAULTS):
            print("  STOP RULE: tuning not material (nothing beats the defaults by 2%); defaults go to FINAL",
                  flush=True)
            winner = DEFAULTS
        else:
            # ---- 2. PROMOTE
            print("\n== PROMOTE (top 4)", flush=True)
            prom = [run(r["config"], PROMOTE_EPOCHS, 0, "promote") for r in full[:4]]
            prom = [r for r in prom if r["best_val"] is not None]
            prom.sort(key=lambda r: r["best_val"])
            winner = prom[0]["config"]
    # ---- 3. FINAL
    print(f"\n== FINAL: {name_of(winner)} x 4 seeds", flush=True)
    finals = [run(winner, FINAL_EPOCHS, s, "final", dry=dry) for s in range(4)]
    # ---- 4. B1.4 ABLATION: does the book help? Only if the winner uses quote
    # inputs AND the screen shows them winning by >= 2%.
    ablation = None
    if not dry and winner.get("quote_features"):
        off = ablation_config(screened)
        if off is not None:
            print(f"\n== ABLATION (B1.4): best quote-off config {name_of(off)} x 4 seeds", flush=True)
            ablation = [run(off, FINAL_EPOCHS, s, "ablation") for s in range(4)]
        else:
            print("\n== ABLATION (B1.4) skipped: quote inputs did not win the screen by 2%", flush=True)
    if not dry:
        (OUT / "winner.json").write_text(json.dumps(
            {"config": winner, "runs": [f["run"] for f in finals],
             "ablation_runs": [a["run"] for a in ablation] if ablation else None}, indent=2))
        print(f"\nwinner and final checkpoints recorded in {OUT / 'winner.json'}")
    print("exit: 0")


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    s = sample_configs(16)
    check("16 distinct configs, defaults excluded",
          len({tuple(sorted(c.items())) for c in s}) == 16 and DEFAULTS not in s)
    check("heads always divide the hidden size", all(c["embed_dim"] % c["n_heads"] == 0 for c in s))
    check("sampling is reproducible", sample_configs(16) == s)
    check("prune when worse than the median of earlier runs", should_prune(0.0050, [0.0040, 0.0045, 0.0060]))
    check("keep when at or better than the median", not should_prune(0.0045, [0.0040, 0.0045, 0.0060]))
    check("never prune the first run (no earlier runs)", not should_prune(1.0, []))
    check("2% rule: 0.0049 (exactly 2% lower) beats 0.0050", beats(0.0049, 0.0050))
    check("2% rule: 0.00495 does not beat 0.0050", not beats(0.00495, 0.0050))
    cmd = command(DEFAULTS, 6, 0, Path("x"))
    months = cmd[cmd.index("--months") + 1: cmd.index("--split")]
    check("training is never given a test month (>= 2025-08)", max(months) == "2025-07" and "2025-08" not in months)
    check("split flag matches the 7/2/4 design", cmd[cmd.index("--split") + 1] == "2025-05,2025-07")
    check("defaults: quote inputs off, w_mid 1 (head present)",
          "--quote-features" not in cmd and cmd[cmd.index("--w-mid") + 1] == "1.0")
    qc = dict(DEFAULTS, quote_features=True, w_mid=2.0)
    qcmd = command(qc, 6, 0, Path("x"))
    check("quote-on config passes --quote-features and its w_mid",
          "--quote-features" in qcmd and qcmd[qcmd.index("--w-mid") + 1] == "2.0")
    check("both quote settings appear in the 16 sampled configs",
          {c["quote_features"] for c in s} == {False, True})
    check("run names distinguish quote on/off", name_of(qc) != name_of(dict(qc, quote_features=False)))

    def R(q, v):
        return {"config": dict(DEFAULTS, quote_features=q, lr=v), "best_val": v, "status": "done"}
    check("B1.4 ablation when quote-on wins the screen by >= 2%",
          ablation_config([R(True, 0.0049), R(False, 0.0050)])["quote_features"] is False)
    check("no ablation when the margin is < 2%", ablation_config([R(True, 0.00495), R(False, 0.0050)]) is None)
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    main_run(args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
