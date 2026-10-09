"""Walk-forward analysis: optimise in-sample, trade the next out-of-sample window."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from ..data.store import to_epoch
from .optimizer import optimize, _py
from .runner import Criteria, Evaluator
from .space import ParamSpace


@dataclass
class WalkForwardResult:
    windows: pd.DataFrame
    summary: dict
    params: List[dict] = field(default_factory=list)

    def save(self, out_dir: str | Path):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        self.windows.to_csv(out / "walkforward_windows.csv", index=False)
        with open(out / "walkforward_summary.json", "w") as f:
            json.dump({"summary": self.summary, "params": self.params}, f, indent=2, default=str)
        return out


def _fmt(t):
    return pd.Timestamp(int(t), unit="s").strftime("%Y-%m-%d %H:%M:%S")


def walk_forward(evalr: Evaluator, space: ParamSpace, is_days: float, oos_days: float, method: str = "lhs",
                 n: int = 60, objective: str = "ontester", criteria: Optional[Criteria] = None,
                 pick: str = "robust", anchored: bool = False, seed: int = 0) -> WalkForwardResult:
    criteria = criteria or Criteria()
    s, e = to_epoch(evalr.cfg.start), to_epoch(evalr.cfg.end)
    is_s, oos_s = int(is_days * 86400), int(oos_days * 86400)
    rows, chosen = [], []
    k = 0
    cur = s
    while cur + is_s + oos_s <= e + 1:
        is_a = s if anchored else cur
        is_b = cur + is_s
        oos_b = min(is_b + oos_s, e)
        sub = Evaluator(evalr.strategy, evalr.base_inputs, evalr.cfg, evalr.workers, evalr.cache_file)
        sub.cache = evalr.cache
        sub.cfg = type(evalr.cfg)(**{**evalr.cfg.__dict__, "start": _fmt(is_a), "end": _fmt(is_b)})
        opt = optimize(sub, space, method, n, objective, criteria, seed + k)
        params = opt.robust_best if pick == "robust" else opt.best
        keys = opt.table[space.names].apply(lambda r: space.key({c: _py(v) for c, v in r.items()}), axis=1)
        is_row = opt.table[keys == space.key(params)].head(1)
        oos = evalr.run([params], cfg_over={"start": _fmt(is_b), "end": _fmt(oos_b)}).iloc[0]
        rows.append({"window": k, "is_start": _fmt(is_a), "is_end": _fmt(is_b), "oos_end": _fmt(oos_b),
                     "is_net_profit": float(is_row["net_profit"].iloc[0]) if len(is_row) else np.nan,
                     "is_objective": float(is_row["objective"].iloc[0]) if len(is_row) else np.nan,
                     "oos_net_profit": float(oos.get("net_profit", np.nan)),
                     "oos_dd_pct": float(oos.get("equity_dd_rel_pct", np.nan)),
                     "oos_trades": int(oos.get("trades", 0) or 0),
                     "oos_profit_factor": float(oos.get("profit_factor", np.nan)),
                     "is_global_survival_pct": opt.summary["global_survival_profitable_pct"],
                     **{f"p_{kk}": vv for kk, vv in params.items()}})
        chosen.append(params)
        k += 1
        cur += oos_s
    df = pd.DataFrame(rows)
    summ = {}
    if len(df):
        is_len = df.apply(lambda r: (pd.Timestamp(r["is_end"]) - pd.Timestamp(r["is_start"])).total_seconds() / 86400,
                          axis=1)
        is_rate = (df["is_net_profit"] / is_len).mean()
        oos_rate = (df["oos_net_profit"] / oos_days).mean()
        summ = {"windows": int(len(df)), "oos_total_net_profit": float(df["oos_net_profit"].sum()),
                "oos_profitable_windows_pct": float((df["oos_net_profit"] > 0).mean() * 100),
                "oos_worst_window": float(df["oos_net_profit"].min()),
                "oos_max_dd_pct": float(df["oos_dd_pct"].max()),
                "walk_forward_efficiency": float(oos_rate / is_rate) if is_rate and np.isfinite(is_rate) and is_rate > 0 else None,
                "param_changes": int(sum(1 for a, b in zip(chosen, chosen[1:]) if a != b)),
                "anchored": anchored, "is_days": is_days, "oos_days": oos_days, "pick": pick}
    return WalkForwardResult(df, summ, chosen)
