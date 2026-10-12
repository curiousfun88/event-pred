# NUS SoC compute cluster (Slurm)

For compute-heavy, batch jobs that are slow or run out of memory on the 7.8 GB WSL
machine: STGAT training (GPU), and grids of maker-policy fits (CPU job arrays).
**Not** for the live signal producer: Slurm jobs have time limits (see `sinfo`), the
cluster is not meant to host always-on services, and the Lumid token must not be
copied to a shared machine.

GPUs are requested as in the SoC Slurm quick-start guide: `--gpus=1` (any type, which
the job scripts use) or a type such as `--gpus=a100:1`, `t4` or `titan`. The job scripts
set no partition, so Slurm uses the default one. Check partitions, time limits and GPU
types with `sinfo` on the login node; the guide's "Slurm Info" page lists them too. The
models here are small, so queue time matters more than GPU size.

Useful commands: `squeue -u $USER` (your jobs), `scancel <jobid>`, `sacct -j <jobid>`
(finished jobs and exit codes). For an interactive debug shell, run `salloc --gpus=1`
then `srun --pty bash`, and `exit` both as soon as you are done: idle allocations
count against your fair-share priority.

## One-off setup

1. **Account.** Your SoC Unix account (`e1122519`) needs cluster access; check the
   SoC account portal (MySoC) or ask SoC technical services.
2. **SSH** (this machine's `~/.ssh/config` already has the entries): the login node
   `xlogin` is reached through the jump host `stujump`.

       ssh xlogin            # first time: accept both host keys, log in (password/2FA)

3. **Copy code only** (from the repo root). Never copy `data/`, `runs/live/`,
   `~/.lumid_pat`, `.git` or any key file:

       rsync -av --exclude '__pycache__/' --exclude '*.egg-info/' stg_infra cluster xlogin:~/event-pred/

   Training inputs (cached feature tables, `cache_causal/`, ...) go separately, one
   directory at a time, and only what a job reads.

4. **Environment** (on the login node, from `~/event-pred`):

       bash cluster/setup_env.sh
       VENV=/path/with/space/fyp-venv bash cluster/setup_env.sh   # if `quota -s` shows home is too small

   CUDA PyTorch is several GB. The login node caps memory, so `import torch` may fail
   there; that is not an install error. The smoke test checks it on a GPU node.

5. **Smoke test:**

       sbatch cluster/smoke.sbatch
       cat cluster/logs/fyp-smoke-*.out     # GPU name, a GATv2Conv step on the GPU, a GBM fit time

## Training the STGAT on a GPU

`train_forecast.py` takes `--device cpu|cuda|auto`. The default is `cpu`, so every
existing command (and every reported figure) is unchanged; on this laptop nothing changes.

    rsync -av cache_causal xlogin:~/event-pred/          # ~1 GB, the only input the default recipe reads
    sbatch --export=ALL,EXTRA="--epochs 2" cluster/train_forecast.sbatch   # timing test first
    tail -f cluster/logs/fyp-train-<jobid>.out           # look for "DEVICE: cuda (...)" and the per-epoch seconds
    rsync -av xlogin:~/event-pred/runs/gpu_test_s0/ runs/gpu_test_s0/

Compare the epoch time against a CPU epoch before moving real work over: the model
loops over snapshots in Python, so the GPU speed-up may be modest. GPU runs are not
bit-identical to CPU runs, so they go in new checkpoint dirs and are new runs.

## GBM tuning on a GPU

`stg_infra/examples/tune_gbm.py` fits the maker-policy grid with XGBoost (`--device cuda`
or `cpu`, default `cpu`). scikit-learn's model, the one G2 uses, has no GPU support; it is
kept as the CPU-only `hgb_a12` reference row.

    sbatch --export=ALL,MODE=bench cluster/tune_gbm.sbatch     # self-test + CPU vs GPU timing, synthetic data
    cat cluster/logs/fyp-tune-gbm-*.out

    # real grid: after the amendment sets AMENDMENT in tune_gbm.py
    .venv/bin/python stg_infra/examples/tune_gbm.py build      # on the laptop, memory-capped, ~2 h
    rsync -avR stg_infra cluster runs/tune_gbm/features.npz xlogin:~/event-pred/   # -R keeps the paths
    sbatch --array=0-74 cluster/tune_gbm.sbatch
    rsync -av xlogin:~/event-pred/runs/tune_gbm/results/ runs/tune_gbm/results/
    .venv/bin/python stg_infra/examples/tune_gbm.py summarise

Laptop reference (20 cores, synthetic 680k x 14): one A12-matched fit 12.8 s, 5-model bag 79 s.

## Running work

Job arrays: one task per (fold, setting) or (seed, variant), each writing its own
result file under `results/` on the cluster, then copy back:

    rsync -av xlogin:~/event-pred/results/<dir>/ results/<dir>/

Pre-registration rules apply unchanged: the grid, folds and selection rule are written
down before a job is submitted, and nothing reads a held-out window early.
