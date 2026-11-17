"""Step 3: does a small model on top of the router's scores pick the right target more often?"""
import json
import sys
import warnings

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold

from trivium import config, policy

warnings.filterwarnings("ignore")
cfg = config.load(config.config_path())
rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
QS = list(cfg["questions"])
OPTS = {q: list(cfg["questions"][q]["options"]) for q in QS}
TIER = {"local": 0, "fast": 1, "mid": 2, "frontier": 3, "max": 4}


def target_of(choices):
    return policy.decide(cfg, {q: {"choice": c, "p": 1.0} for q, c in choices.items()}).target


def rank(t):
    return TIER[cfg["targets"][t]["tier"]]


expected = np.array([target_of(r["expect"]) for r in rows])
logp = {q: np.log(np.clip([[r["probs"][q][o] for o in OPTS[q]] for r in rows], 1e-9, 1)) for q in QS}
allx = np.hstack([logp[q] for q in QS])
label = {q: np.array([r["expect"][q] for r in rows]) for q in QS}


def baseline(weights):
    out = []
    for r in rows:
        answers = policy.summarize(r["probs"], config.temperatures(cfg, "semif"), weights)
        out.append(policy.decide(cfg, answers).target)
    return np.array(out)


def fit_predict(kind, tr, te):
    if kind == "target":
        m = LogisticRegression(C=1.0, max_iter=2000).fit(allx[tr], expected[tr])
        return m.predict(allx[te])
    preds = {}
    for q in QS:
        x = logp[q] if kind == "own" else allx
        preds[q] = LogisticRegression(C=1.0, max_iter=2000).fit(x[tr], label[q][tr]).predict(x[te])
    return np.array([target_of({q: preds[q][i] for q in QS}) for i in range(len(te))])


def report(name, pred, idx):
    right = (pred == expected[idx]).mean()
    weak = sum(rank(p) < rank(e) for p, e in zip(pred, expected[idx]))
    strong = sum(rank(p) > rank(e) for p, e in zip(pred, expected[idx]))
    print(f"  {name:<34} right {right:6.1%}   too weak {weak:3d}   too strong {strong:3d}   (n={len(idx)})")


WEIGHTS = {"difficulty": {"moderate": 3, "hard": 2}}
test = np.array([i for i, r in enumerate(rows) if r["set"] == "calibration-100" and r["split"] == "test"])
train = np.array([i for i in range(len(rows)) if i not in set(test)])
base, weighted = baseline({}), baseline(WEIGHTS)
MODELS = [("per question, own scores", "own"), ("per question, all scores", "all"), ("direct to target", "target")]

print(f"{len(rows)} prompts. Held-out 28 (models fitted on the other {len(train)}):")
report("router as shipped", base[test], test)
report("router + option weights", weighted[test], test)
for name, kind in MODELS:
    report(name, fit_predict(kind, train, test), test)

print("\nAll prompts, 5-fold cross-validation repeated 10 times (every prompt is tested out of fold):")
n = len(rows)
report("router as shipped", base, np.arange(n))
report("router + option weights", weighted, np.arange(n))
folds = list(RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=0).split(allx, label["difficulty"]))
for name, kind in MODELS:
    rights, weak, strong = [], 0, 0
    for tr, te in folds:
        pred = fit_predict(kind, tr, te)
        rights.append((pred == expected[te]).sum())
        weak += sum(rank(p) < rank(e) for p, e in zip(pred, expected[te]))
        strong += sum(rank(p) > rank(e) for p, e in zip(pred, expected[te]))
    per_repeat = np.array(rights).reshape(10, 5).sum(axis=1) / n
    print(f"  {name:<34} right {per_repeat.mean():6.1%} (min {per_repeat.min():.1%}, max {per_repeat.max():.1%})"
          f"   too weak {weak / 10:5.1f}   too strong {strong / 10:5.1f}")
