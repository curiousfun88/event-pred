"""
select_signal_model.py

Amendment B3 (docs/planning/stgat-7-2-4-preregistration.md): choose the model
whose mid-move head supplies the S4/S5 signal. Validation only.

  A = the tuned defaults (quote inputs OFF), 4 final seeds  -- runs/tune/final_*_s{0..3}
  B = the same config with quote inputs ON, 4 seeds         -- runs/tune/b3_quotes_s{0..3}

For each run, the metric is val_mid_ratio (head MSE / zero-move MSE on the
validation months) AT THE EPOCH SAVED AS best.pt -- the checkpoint that would
actually be used, selected by val MECE as for every run. The seed mean is
compared: B is adopted if mean(B) <= 0.98 * mean(A); otherwise A stays the
signal model. The basket-forecasting model is A regardless.

    python stg_infra/select_signal_model.py --self-test
    python stg_infra/select_signal_model.py            # writes runs/tune/signal_model.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
MIN_GAIN = 0.02


def ratio_at_saved_epoch(history_rows, saved_epoch):
    for r in history_rows:
        if int(r["epoch"]) == int(saved_epoch):
            v = float(r["val_mid_ratio"])
            if v != v:
                raise ValueError(f"val_mid_ratio is NaN at epoch {saved_epoch}")
            return v
    raise ValueError(f"epoch {saved_epoch} not in history")


def decide(a_ratios, b_ratios, gain=MIN_GAIN):
    """'B' if mean(B) <= (1 - gain) * mean(A), else 'A'. Needs all seeds on both sides."""
    if not a_ratios or len(a_ratios) != len(b_ratios):
        raise ValueError(f"need the same, non-zero number of seeds: A={len(a_ratios)} B={len(b_ratios)}")
    ma, mb = sum(a_ratios) / len(a_ratios), sum(b_ratios) / len(b_ratios)
    return ("B" if mb <= (1 - gain) * ma + 1e-12 else "A"), ma, mb


def read_run(run_dir: Path):
    import torch
    sys.path.insert(0, str(_REPO / "stg_infra"))
    ck = torch.load(run_dir / "best.pt", weights_only=False, map_location="cpu")
    rows = list(csv.DictReader(open(run_dir / "history.csv")))
    return ratio_at_saved_epoch(rows, ck["epoch"]), int(ck["epoch"]), bool(ck.get("quote_features"))


def self_test() -> int:
    fails = 0

    def check(name, ok):
        nonlocal fails
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        fails += 0 if ok else 1

    rows = [{"epoch": "0", "val_mid_ratio": "1.01"}, {"epoch": "1", "val_mid_ratio": "0.97"}]
    check("reads the ratio at the SAVED epoch, not the best one", ratio_at_saved_epoch(rows, 0) == 1.01)
    check("B adopted when 2% better (0.98 vs 1.00)", decide([1.0] * 4, [0.98] * 4)[0] == "B")
    check("A kept when B is only 1% better", decide([1.0] * 4, [0.99] * 4)[0] == "A")
    check("A kept when B is worse", decide([1.0] * 4, [1.05] * 4)[0] == "A")
    check("seed means are compared", decide([1.0, 1.02], [0.97, 0.99])[0] == "B")
    try:
        decide([1.0] * 4, [0.9] * 3)
        check("missing seeds are an error", False)
    except ValueError:
        check("missing seeds are an error", True)
    try:
        ratio_at_saved_epoch([{"epoch": "0", "val_mid_ratio": "nan"}], 0)
        check("NaN ratio is an error", False)
    except ValueError:
        check("NaN ratio is an error", True)
    print(f"\nself-test: {'ALL PASS' if not fails else f'{fails} FAILURE(S)'}")
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--out", default="runs/tune/signal_model.json")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    tune = _REPO / "runs/tune"
    a_dirs = sorted(tune.glob("final_*_s[0-3]"))
    b_dirs = sorted(tune.glob("b3_quotes_s[0-3]"))
    a = [read_run(d) for d in a_dirs]
    b = [read_run(d) for d in b_dirs]
    if any(q for _, _, q in a) or not all(q for _, _, q in b):
        raise SystemExit("A must be quote-off and B quote-on")
    choice, ma, mb = decide([r for r, _, _ in a], [r for r, _, _ in b])
    for name, dirs, rs in (("A (quotes off)", a_dirs, a), ("B (quotes on)", b_dirs, b)):
        print(f"{name}: " + ", ".join(f"{d.name}@e{e} {r:.4f}" for d, (r, e, _) in zip(dirs, rs)))
    print(f"mean val_mid_ratio: A {ma:.4f}  B {mb:.4f}  -> signal model {choice} "
          f"(B needs <= {(1 - MIN_GAIN) * ma:.4f})")
    chosen = b_dirs if choice == "B" else a_dirs
    out = {"choice": choice, "mean_A": ma, "mean_B": mb,
           "checkpoints": [str((d / "best.pt").relative_to(_REPO)) for d in chosen]}
    (_REPO / args.out).write_text(json.dumps(out, indent=2))
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
