"""Monte Carlo on the trade sequence: how bad could the same edge have looked?"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def monte_carlo(trades: pd.DataFrame, deposit: float, sims: int = 2000, seed: int = 0,
                ruin_dd_pct: float = 50.0, skip_pct: float = 10.0) -> dict:
    """Three resampling schemes over trade net P/L:

    * shuffle   - same trades, random order (path risk)
    * bootstrap - trades drawn with replacement (sampling risk)
    * skip      - randomly miss ``skip_pct`` % of trades (execution risk)
    """
    net = pd.to_numeric(trades.get("net", pd.Series(dtype=float)), errors="coerce").dropna().to_numpy(float)
    out = {"trades": int(len(net)), "sims": sims, "deposit": deposit, "ruin_dd_pct": ruin_dd_pct}
    if len(net) < 3:
        out["note"] = "not enough trades"
        return out
    rng = np.random.default_rng(seed)

    def stats(paths: np.ndarray) -> dict:
        eq = deposit + np.cumsum(paths, axis=1)
        eq = np.concatenate([np.full((eq.shape[0], 1), deposit), eq], axis=1)
        peak = np.maximum.accumulate(eq, axis=1)
        dd = ((peak - eq) / np.where(peak > 0, peak, np.nan)).max(axis=1) * 100
        final = eq[:, -1] - deposit
        q = lambda a, p: float(np.nanpercentile(a, p))
        return {"net_profit_p05": q(final, 5), "net_profit_p50": q(final, 50), "net_profit_p95": q(final, 95),
                "max_dd_pct_p50": q(dd, 50), "max_dd_pct_p95": q(dd, 95), "max_dd_pct_p99": q(dd, 99),
                "prob_loss_pct": float((final <= 0).mean() * 100),
                "prob_ruin_pct": float((dd >= ruin_dd_pct).mean() * 100 + 0.0)}

    n = len(net)
    shuffle = np.array([rng.permutation(net) for _ in range(sims)])
    boot = net[rng.integers(0, n, size=(sims, n))]
    keep = rng.random((sims, n)) >= skip_pct / 100
    skip = np.where(keep, net[None, :], 0.0)
    out["shuffle"] = stats(shuffle)
    out["bootstrap"] = stats(boot)
    out["skip"] = stats(skip)
    peak = np.maximum.accumulate(np.concatenate([[deposit], deposit + np.cumsum(net)]))
    eq = np.concatenate([[deposit], deposit + np.cumsum(net)])
    out["original_max_dd_pct"] = float(((peak - eq) / peak).max() * 100)
    out["original_net_profit"] = float(net.sum())
    return out


def save_mc(res: dict, out_dir: str | Path):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "montecarlo.json", "w") as f:
        json.dump(res, f, indent=2)
    return out
