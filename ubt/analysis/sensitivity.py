"""Parameter sensitivity and survival analysis around a chosen parameter set.

Tests (each returns tables + a summary):

1. ``one_at_a_time``  - sweep each parameter over its range, others fixed:
   sensitivity index, elasticity at the base value, per-parameter survival %.
2. ``neighborhood``   - joint random perturbation of ALL parameters by +-p %
   (e.g. 5/10/20 %): survival % (still profitable), pass %, objective
   degradation distribution.
3. ``cost_stress``    - wider spread / slippage / commission: survival %.
4. ``period_stability`` - same parameters on K consecutive sub-periods: %
   profitable periods ("time survival").

``robustness_score`` combines them into one 0-100 number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..data.store import to_epoch
from .runner import Criteria, Evaluator, objective_values
from .space import ParamSpace


@dataclass
class SensitivityResult:
    base: dict
    base_metrics: dict
    objective: str
    oat: pd.DataFrame = field(default_factory=pd.DataFrame)
    oat_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    neighborhood: pd.DataFrame = field(default_factory=pd.DataFrame)
    neighborhood_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    costs: pd.DataFrame = field(default_factory=pd.DataFrame)
    periods: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict = field(default_factory=dict)

    def save(self, out_dir: str | Path):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        for name in ("oat", "oat_summary", "neighborhood", "neighborhood_summary", "costs", "periods"):
            df = getattr(self, name)
            if len(df):
                df.to_csv(out / f"sensitivity_{name}.csv", index=False)
        with open(out / "sensitivity_summary.json", "w") as f:
            json.dump({"base": self.base, "base_metrics": self.base_metrics, "objective": self.objective,
                       "summary": self.summary}, f, indent=2, default=str)
        return out


def _base_eval(evalr: Evaluator, base: dict, objective: str) -> tuple[dict, float]:
    df = evalr.run([base])
    m = df.iloc[0].to_dict()
    return m, float(objective_values(df, objective).iloc[0])


def one_at_a_time(evalr: Evaluator, space: ParamSpace, base: dict, objective: str, criteria: Criteria,
                  max_points: int = 9) -> tuple[pd.DataFrame, pd.DataFrame]:
    sets, owner = [], []
    for n in space.names:
        vals = space.values(n)
        if len(vals) > max_points:
            pick = np.unique(np.linspace(0, len(vals) - 1, max_points).round().astype(int))
            vals = [vals[i] for i in pick]
            if base.get(n) not in vals and n in base:
                vals = sorted(set(vals) | {base[n]}, key=lambda x: (str(type(x)), x))
        for v in vals:
            p = dict(base)
            p[n] = v
            sets.append(p)
            owner.append(n)
    df = evalr.run(sets)
    df["param"] = owner
    df["value"] = [s[o] for s, o in zip(sets, owner)]
    df["objective"] = objective_values(df, objective)
    df["profitable"] = criteria.profitable(df)
    df["passed"] = criteria.passed(df)
    _, base_obj = _base_eval(evalr, base, objective)
    rows = []
    for n, g in df.groupby("param", sort=False):
        obj = g["objective"].replace([np.inf, -np.inf], np.nan)
        rng_obj = float(obj.max() - obj.min()) if obj.notna().any() else 0.0
        denom = abs(base_obj) if base_obj not in (0, np.inf, -np.inf) and np.isfinite(base_obj) else 1.0
        # elasticity around the base value from the nearest lower/higher neighbours
        elast = np.nan
        try:
            gg = g[pd.to_numeric(g["value"], errors="coerce").notna()].copy()
            gg["v"] = gg["value"].astype(float)
            gg = gg.sort_values("v")
            bv = float(base[n])
            lo = gg[gg["v"] < bv].tail(1)
            hi = gg[gg["v"] > bv].head(1)
            if len(lo) and len(hi) and bv != 0 and np.isfinite(base_obj) and base_obj != 0:
                dv = (hi["v"].iloc[0] - lo["v"].iloc[0]) / abs(bv)
                do = (hi["objective"].iloc[0] - lo["objective"].iloc[0]) / abs(base_obj)
                elast = float(do / dv) if dv else np.nan
        except (TypeError, ValueError):
            pass
        best_i = obj.idxmax() if obj.notna().any() else g.index[0]
        rows.append({"param": n, "base_value": base.get(n), "points": len(g),
                     "objective_min": float(obj.min()), "objective_max": float(obj.max()),
                     "sensitivity_index": rng_obj / denom, "elasticity": elast,
                     "survival_profitable_pct": float(g["profitable"].mean() * 100),
                     "survival_passed_pct": float(g["passed"].mean() * 100),
                     "best_value": g.loc[best_i, "value"]})
    summ = pd.DataFrame(rows).sort_values("sensitivity_index", ascending=False).reset_index(drop=True)
    return df, summ


def neighborhood(evalr: Evaluator, space: ParamSpace, base: dict, objective: str, criteria: Criteria,
                 pcts=(5, 10, 20), n: int = 40, seed: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    _, base_obj = _base_eval(evalr, base, objective)
    frames, rows = [], []
    for k, pct in enumerate(pcts):
        sets = space.perturb(base, pct, n, seed + k)
        df = evalr.run(sets)
        df["pct"] = pct
        df["objective"] = objective_values(df, objective)
        df["profitable"] = criteria.profitable(df)
        df["passed"] = criteria.passed(df)
        frames.append(df)
        obj = df["objective"].replace([np.inf, -np.inf], np.nan)
        ratio = obj / base_obj if base_obj and np.isfinite(base_obj) and base_obj > 0 else obj * np.nan
        rows.append({"perturbation_pct": pct, "runs": len(df),
                     "survival_profitable_pct": float(df["profitable"].mean() * 100),
                     "survival_passed_pct": float(df["passed"].mean() * 100),
                     "objective_median": float(obj.median()), "objective_p05": float(obj.quantile(0.05)),
                     "objective_p95": float(obj.quantile(0.95)),
                     "median_ratio_to_base": float(ratio.median()) if ratio.notna().any() else np.nan,
                     "worst_net_profit": float(pd.to_numeric(df.get("net_profit"), errors="coerce").min()),
                     "worst_dd_pct": float(pd.to_numeric(df.get("equity_dd_rel_pct"), errors="coerce").max())})
    return pd.concat(frames, ignore_index=True), pd.DataFrame(rows)


def cost_stress(evalr: Evaluator, base: dict, objective: str, criteria: Criteria,
                spread_mults=(1.0, 1.5, 2.0, 3.0), slippages=(0.0, 10.0, 50.0),
                commission_per_lot=(0.0,)) -> pd.DataFrame:
    overs = [{"spread_multiplier": sm, "slippage_points": sl, "commission_per_lot": cm}
             for sm in spread_mults for sl in slippages for cm in commission_per_lot]
    df = evalr.run([dict(base) for _ in overs], cfg_overs=overs)
    for k in ("spread_multiplier", "slippage_points", "commission_per_lot"):
        df[k] = [o[k] for o in overs]
    df["objective"] = objective_values(df, objective)
    df["profitable"] = criteria.profitable(df)
    df["passed"] = criteria.passed(df)
    return df


def period_stability(evalr: Evaluator, base: dict, objective: str, criteria: Criteria, k: int = 4) -> pd.DataFrame:
    s, e = to_epoch(evalr.cfg.start), to_epoch(evalr.cfg.end)
    edges = np.linspace(s, e, k + 1).astype(int)
    fmt = lambda t: pd.Timestamp(int(t), unit="s").strftime("%Y-%m-%d %H:%M:%S")
    overs = [{"start": fmt(edges[i]), "end": fmt(edges[i + 1])} for i in range(k)]
    df = evalr.run([dict(base) for _ in overs], cfg_overs=overs)
    df["period"] = [f"{o['start'][:10]}..{o['end'][:10]}" for o in overs]
    df["objective"] = objective_values(df, objective)
    df["profitable"] = criteria.profitable(df)
    df["passed"] = criteria.passed(df)
    return df


def robustness_score(summary: dict) -> float:
    """0-100: weighted survival across the tests that were run."""
    parts = []
    if "neighborhood_survival_10pct" in summary:
        parts.append((0.35, summary["neighborhood_survival_10pct"]))
    if "oat_mean_survival_pct" in summary:
        parts.append((0.25, summary["oat_mean_survival_pct"]))
    if "cost_survival_pct" in summary:
        parts.append((0.2, summary["cost_survival_pct"]))
    if "period_survival_pct" in summary:
        parts.append((0.2, summary["period_survival_pct"]))
    w = sum(p[0] for p in parts)
    return float(sum(p[0] * p[1] for p in parts) / w) if w else 0.0


def analyze(evalr: Evaluator, space: ParamSpace, base: dict, objective: str = "ontester",
            criteria: Optional[Criteria] = None, tests=("oat", "neighborhood", "costs", "periods"),
            pcts=(5, 10, 20), n_perturb: int = 40, max_points: int = 9, periods: int = 4,
            spread_mults=(1.0, 1.5, 2.0, 3.0), slippages=(0.0, 10.0, 50.0)) -> SensitivityResult:
    criteria = criteria or Criteria()
    base = {k: base[k] for k in base}
    bm, bobj = _base_eval(evalr, base, objective)
    res = SensitivityResult(base=base, base_metrics={k: v for k, v in bm.items() if not isinstance(v, (list, dict))},
                            objective=objective)
    s = {"base_objective": bobj, "base_net_profit": bm.get("net_profit"), "base_dd_pct": bm.get("equity_dd_rel_pct")}
    if "oat" in tests:
        res.oat, res.oat_summary = one_at_a_time(evalr, space, base, objective, criteria, max_points)
        s["oat_mean_survival_pct"] = float(res.oat_summary["survival_profitable_pct"].mean())
        s["most_sensitive_params"] = res.oat_summary.head(5)["param"].tolist()
    if "neighborhood" in tests:
        res.neighborhood, res.neighborhood_summary = neighborhood(evalr, space, base, objective, criteria,
                                                                  pcts, n_perturb)
        for _, r in res.neighborhood_summary.iterrows():
            s[f"neighborhood_survival_{int(r['perturbation_pct'])}pct"] = r["survival_profitable_pct"]
            s[f"neighborhood_pass_{int(r['perturbation_pct'])}pct"] = r["survival_passed_pct"]
        if "neighborhood_survival_10pct" not in s and len(res.neighborhood_summary):
            s["neighborhood_survival_10pct"] = float(res.neighborhood_summary["survival_profitable_pct"].mean())
    if "costs" in tests:
        res.costs = cost_stress(evalr, base, objective, criteria, spread_mults, slippages)
        s["cost_survival_pct"] = float(res.costs["profitable"].mean() * 100)
    if "periods" in tests:
        res.periods = period_stability(evalr, base, objective, criteria, periods)
        s["period_survival_pct"] = float(res.periods["profitable"].mean() * 100)
    s["robustness_score"] = robustness_score(s)
    res.summary = s
    return res
