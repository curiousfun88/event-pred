"""Is the next-hour quoted-mid move predictable at all? Validation only."""
import numpy as np, polars as pl, glob
from sklearn.ensemble import HistGradientBoostingRegressor
TRAIN = ["2024-11","2024-12","2025-01","2025-02","2025-03","2025-04","2025-05"]; VAL = ["2025-06","2025-07"]
q = pl.concat([pl.read_parquet(f"data/quotes/by_month/quotes_{m}.parquet") for m in TRAIN + VAL + ["2025-08"]])
q = (q.select("ticker", pl.col("end_ts").cast(pl.Datetime("us")), "bid_close", "ask_close", "volume", "open_interest")
       .drop_nulls(["bid_close", "ask_close"]).unique(["ticker", "end_ts"]).sort(["ticker", "end_ts"]))
q = q.with_columns(((pl.col("bid_close") + pl.col("ask_close")) / 2).alias("mid"),
                   (pl.col("ask_close") - pl.col("bid_close")).alias("spr"),
                   ((pl.col("bid_close") > 0) & (pl.col("ask_close") < 1)).alias("two"))
mk = pl.concat([pl.read_parquet(p, columns=["ticker", "close_time"]) for p in glob.glob("data/markets/*/markets_*.parquet")]).unique("ticker")
mk = mk.with_columns(pl.col("close_time").dt.replace_time_zone(None).cast(pl.Datetime("us")))
q = q.join(mk, on="ticker", how="left")
def lag(col, h):  # value of col at end_ts - h hours (exact), same ticker
    s = q.select("ticker", (pl.col("end_ts") + pl.duration(hours=h)).alias("end_ts"), pl.col(col).alias(f"{col}_m{h}"), pl.col("two").alias(f"two_m{h}"))
    return s
d = q
for h in (1, 2):
    d = d.join(lag("mid", h), on=["ticker", "end_ts"], how="left")
nxt = q.select("ticker", (pl.col("end_ts") - pl.duration(hours=1)).alias("end_ts"), pl.col("mid").alias("mid_n"), pl.col("two").alias("two_n"))
d = d.join(nxt, on=["ticker", "end_ts"], how="left")
d = d.filter((pl.col("end_ts").dt.hour() % 2 == 0) & pl.col("two") & pl.col("two_n").fill_null(False))
d = d.with_columns((pl.col("mid_n") - pl.col("mid")).alias("y"),
                   pl.when(pl.col("two_m1").fill_null(False)).then(pl.col("mid") - pl.col("mid_m1")).otherwise(0.0).alias("dm1"),
                   pl.when(pl.col("two_m2").fill_null(False)).then(pl.col("mid") - pl.col("mid_m2")).otherwise(0.0).alias("dm2"),
                   ((pl.col("close_time") - pl.col("end_ts")).dt.total_seconds() / 3600).clip(0, 24 * 60).alias("ttc_h"),
                   pl.col("end_ts").dt.strftime("%Y-%m").alias("m"))
tr, va = d.filter(pl.col("m").is_in(TRAIN)), d.filter(pl.col("m").is_in(VAL))
yv = va["y"].to_numpy()
print(f"positions: train {tr.height:,}  val {va.height:,}")
a = np.abs(yv); sse = np.sort(yv ** 2)[::-1]
print(f"val target: {100*(a == 0).mean():.1f}% exactly zero | median |y| {np.median(a)*100:.2f}c | "
      f"top 1% of positions carry {100*sse[:len(sse)//100].sum()/sse.sum():.0f}% of the zero-move SSE | "
      f"top 0.1% carry {100*sse[:len(sse)//1000].sum()/sse.sum():.0f}%")
base = ["bid_close", "ask_close", "mid", "spr", "volume", "open_interest", "dm1", "dm2"]
for name, cols in (("quote features (as STGAT-B, no time-to-close)", base), ("+ hours to close", base + ["ttc_h"])):
    m = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=200,
                                      l2_regularization=1.0, random_state=0)
    m.fit(tr.select(cols).to_numpy(), tr["y"].to_numpy())
    p = m.predict(va.select(cols).to_numpy())
    print(f"GBM {name}: val MSE / zero-move = {((p - yv) ** 2).mean() / (yv ** 2).mean():.4f}")
x = va["dm1"].to_numpy(); al = (x @ yv) / (x @ x); print(f"oracle alpha*prev-hour move (fit on val): {((al*x - yv)**2).mean()/(yv**2).mean():.4f} (alpha {al:.3f})")
# where is the (in)predictability? near close vs far
for lo, hi in ((0, 6), (6, 48), (48, 1e9)):
    k = (va["ttc_h"].to_numpy() >= lo) & (va["ttc_h"].to_numpy() < hi)
    print(f"  ttc [{lo},{hi})h: {k.mean()*100:.0f}% of positions, {100*(yv[k]**2).sum()/(yv**2).sum():.0f}% of SSE")
