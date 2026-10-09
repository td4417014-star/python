"""Optimisation: grid / random / latin-hypercube / genetic search.

Besides the single best result it reports:

* **robust best** - the parameter set whose grid neighbourhood scores best
  (plateau instead of a lucky spike),
* **global survival** - % of all tested sets that are profitable / pass criteria,
* **parameter importance** - share of objective variance explained by each parameter.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .runner import Criteria, Evaluator, objective_values
from .space import ParamSpace

log = logging.getLogger("ubt")


@dataclass
class OptimizationResult:
    table: pd.DataFrame
    space: ParamSpace
    objective: str
    criteria: Criteria
    best: dict
    robust_best: dict
    summary: dict
    importance: Dict[str, float] = field(default_factory=dict)

    def save(self, out_dir: str | Path):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.table.to_csv(out / "optimization_results.csv", index=False)
        with open(out / "optimization_summary.json", "w") as f:
            json.dump({"objective": self.objective, "criteria": self.criteria.as_dict(), "best": self.best,
                       "robust_best": self.robust_best, "summary": self.summary,
                       "importance": self.importance, "space": self.space.spec}, f, indent=2, default=str)
        return out


def _progress_printer(label):
    def _p(done, total):
        if total and (done == total or done % max(1, total // 20) == 0):
            log.info("%s %d/%d", label, done, total)
    return _p


def neighborhood_scores(df: pd.DataFrame, space: ParamSpace, obj: pd.Series, radius: int = 1,
                        knn: int = 0) -> pd.DataFrame:
    """Mean / min objective over each point and its neighbourhood.

    Dense (grid) results: the evaluated +-radius grid box. Sparse samples (random / lhs /
    genetic, where boxes are mostly empty): the k nearest evaluated points in normalised
    parameter space (k = ``knn`` or ~10 % of the sample, at least 3)."""
    names = [n for n in space.names if n in df.columns]
    idx = np.array([[space.index(n, v) for n, v in zip(names, row)] for row in df[names].itertuples(index=False)],
                   dtype=float)
    vals = obj.to_numpy(float)
    means, mins, counts, prof = [], [], [], []
    profitable = (pd.to_numeric(df.get("net_profit", 0), errors="coerce").fillna(-1) > 0).to_numpy()
    box = [np.all(np.abs(idx - idx[i]) <= radius, axis=1) for i in range(len(df))]
    use_knn = knn > 0 or (len(df) > 3 and np.median([b.sum() for b in box]) < 3)
    if use_knn:
        span = np.array([max(len(space.values(n)) - 1, 1) for n in names], dtype=float)
        z = idx / span
        k = knn or int(min(len(df), max(3, round(0.1 * len(df)))))
        d = np.sqrt(((z[:, None, :] - z[None, :, :]) ** 2).sum(axis=2))
    for i in range(len(df)):
        if use_knn:
            mask = np.zeros(len(df), dtype=bool)
            mask[np.argsort(d[i], kind="stable")[:k]] = True
        else:
            mask = box[i]
        v = vals[mask]
        v = v[np.isfinite(v)]
        means.append(v.mean() if len(v) else -np.inf)
        mins.append(v.min() if len(v) else -np.inf)
        counts.append(int(mask.sum()))
        prof.append(profitable[mask].mean() * 100 if mask.any() else 0.0)
    return pd.DataFrame({"nbr_mean": means, "nbr_min": mins, "nbr_count": counts, "nbr_survival_pct": prof},
                        index=df.index)


def parameter_importance(df: pd.DataFrame, space: ParamSpace, obj: pd.Series) -> Dict[str, float]:
    """Eta-squared: between-group variance of the objective per parameter / total variance."""
    y = obj.replace([np.inf, -np.inf], np.nan)
    tot = y.var(ddof=0)
    out = {}
    for n in space.names:
        if n not in df.columns or tot is None or not np.isfinite(tot) or tot == 0:
            continue
        g = y.groupby(df[n].astype(str))
        between = (g.count() * (g.mean() - y.mean()) ** 2).sum() / y.count()
        out[n] = float(between / tot)
    s = sum(out.values()) or 1.0
    return dict(sorted(((k, v / s) for k, v in out.items()), key=lambda kv: -kv[1]))


def _genetic(evalr: Evaluator, space: ParamSpace, objective: str, n: int, seed: int, pop: int = 24) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    population = space.lhs(pop, seed)
    frames = []
    evaluated = 0
    seen = set()
    while evaluated < n:
        batch = [p for p in population if space.key(p) not in seen][: max(1, n - evaluated)]
        for p in batch:
            seen.add(space.key(p))
        if not batch:
            batch = space.random(pop, int(rng.integers(1 << 30)))
        df = evalr.run(batch, progress=_progress_printer("genetic"))
        frames.append(df)
        evaluated += len(batch)
        allr = pd.concat(frames, ignore_index=True)
        allr["_obj"] = objective_values(allr, objective)
        elite = allr.sort_values("_obj", ascending=False).head(max(4, pop // 3))
        parents = [{k: r[k] for k in space.names} for _, r in elite.iterrows()]
        children = []
        while len(children) < pop:
            a, b = rng.choice(len(parents), 2, replace=True)
            child = {k: (parents[a][k] if rng.random() < 0.5 else parents[b][k]) for k in space.names}
            for k in space.names:                       # mutation: move 1 grid step
                if rng.random() < 0.2:
                    vals = space.values(k)
                    i = space.index(k, child[k])
                    child[k] = vals[int(np.clip(i + rng.choice([-1, 1]), 0, len(vals) - 1))]
            children.append(child)
        population = children
    return pd.concat(frames, ignore_index=True)


def optimize(evalr: Evaluator, space: ParamSpace, method: str = "grid", n: int = 200, objective: str = "ontester",
             criteria: Optional[Criteria] = None, seed: int = 0, robust_radius: int = 1,
             min_neighbors: int = 3) -> OptimizationResult:
    criteria = criteria or Criteria()
    if method == "grid":
        total = space.size()
        if total > 20000:
            raise ValueError(f"grid has {total} combinations - use method=random/lhs/genetic or a smaller space")
        sets = list(space.grid())
        df = evalr.run(sets, progress=_progress_printer("grid"))
    elif method == "random":
        df = evalr.run(space.random(n, seed), progress=_progress_printer("random"))
    elif method == "lhs":
        df = evalr.run(space.lhs(n, seed), progress=_progress_printer("lhs"))
    elif method == "genetic":
        df = _genetic(evalr, space, objective, n, seed)
    else:
        raise ValueError(f"unknown method {method}")

    df = df.reset_index(drop=True)
    obj = objective_values(df, objective)
    df["objective"] = obj
    df["profitable"] = criteria.profitable(df)
    df["passed"] = criteria.passed(df)
    nb = neighborhood_scores(df, space, obj, robust_radius)
    df = pd.concat([df, nb], axis=1)
    # robust score: neighbourhood mean, but only where the point itself passes
    df["robust_score"] = np.where(df["passed"] & (df["nbr_count"] >= min(min_neighbors, len(df))),
                                  df["nbr_mean"], -np.inf)
    nbr_mode = "grid box" if method == "grid" and df["nbr_count"].median() >= 3 else "k-nearest"
    df = df.sort_values("objective", ascending=False).reset_index(drop=True)

    names = space.names
    cand = df[df["passed"]] if df["passed"].any() else df
    best_row = cand.iloc[0]
    rb = df.sort_values("robust_score", ascending=False).iloc[0]
    if not np.isfinite(rb["robust_score"]):
        rb = best_row
    best = {k: _py(best_row[k]) for k in names}
    robust_best = {k: _py(rb[k]) for k in names}
    ok = df.get("_ok", pd.Series(True, index=df.index)).fillna(False).astype(bool)
    summary = {
        "method": method, "evaluated": int(len(df)), "failed_runs": int((~ok).sum()),
        "global_survival_profitable_pct": float(df["profitable"].mean() * 100),
        "global_survival_passed_pct": float(df["passed"].mean() * 100),
        "best_objective": float(best_row["objective"]),
        "best_metrics": {k: _py(best_row.get(k)) for k in ("net_profit", "profit_factor", "trades",
                                                            "equity_dd_rel_pct", "sharpe_annual", "ontester")},
        "robust_best_objective": float(rb["objective"]),
        "robust_best_neighborhood_mean": float(rb["nbr_mean"]),
        "robust_best_neighborhood_survival_pct": float(rb["nbr_survival_pct"]),
        "robust_best_neighborhood_size": int(rb["nbr_count"]),
        "neighborhood_mode": nbr_mode,
        "objective_median": float(np.nanmedian(obj.replace([np.inf, -np.inf], np.nan))),
    }
    imp = parameter_importance(df, space, obj)
    return OptimizationResult(df, space, objective, criteria, best, robust_best, summary, imp)


def _py(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v
