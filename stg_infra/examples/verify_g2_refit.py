import sys, pickle, json, numpy as np
sys.path[:0] = ["stg_infra", "stg_infra/examples"]
import retrain_g2 as rg, maker_policy as mp
from sklearn.ensemble import HistGradientBoostingRegressor
rows, ys = rg.training_rows("W3", "G2")
frozen = pickle.loads(open("runs/maker/policy_G2_W3_model.pkl", "rb").read())
cats = sorted({r["cat"] for r in rows}); f = rg.feats("G2")
X = rg.matrix("G2", rows, cats)
refit = HistGradientBoostingRegressor(**mp.HP, categorical_features=[x == "cat_i" for x in f]).fit(X, np.array(ys))
pf, pr = frozen["model"].predict(rg.matrix("G2", rows, frozen["cats"])), refit.predict(X)
out = {"n_rows": len(ys), "cats_equal": cats == frozen["cats"], "n_iter_frozen": int(frozen["model"].n_iter_),
       "n_iter_refit": int(refit.n_iter_), "max_abs_pred_diff_c": float(np.max(np.abs(pf - pr))),
       "identical_predictions": bool(np.array_equal(pf, pr)),
       "post_decisions_agree": float(np.mean((pf > 1) == (pr > 1)))}
print(json.dumps(out))
