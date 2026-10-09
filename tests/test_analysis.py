import numpy as np
import pandas as pd

from ubt.analysis.montecarlo import monte_carlo
from ubt.analysis.optimizer import optimize
from ubt.analysis.runner import Criteria, Evaluator
from ubt.analysis.sensitivity import analyze
from ubt.analysis.space import ParamSpace
from ubt.engine.backtest import BacktestConfig

STRAT = "strategies.ma_cross_example:MACrossExample"


def _ev(root, tmp_path, workers=1):
    cfg = BacktestConfig(data_root=root, symbol="BTCUSD", timeframe="M1", start="2024-01-01", end="2024-01-04",
                         model="m1_ohlc", warmup_days=5)
    return Evaluator(STRAT, {}, cfg, workers, tmp_path / "cache.jsonl")


def test_space_grid_neighbors_perturb():
    sp = ParamSpace({"a": {"type": "int", "low": 1, "high": 5, "step": 1},
                     "b": {"type": "float", "low": 0.1, "high": 0.3, "step": 0.1},
                     "c": {"type": "bool"}})
    assert sp.size() == 5 * 3 * 2
    assert len(list(sp.grid())) == 30
    nb = sp.neighbors({"a": 3, "b": 0.2, "c": True})
    assert len(nb) == 2 + 2 + 1
    pert = sp.perturb({"a": 3, "b": 0.2, "c": True}, 10, 20, seed=1)
    assert all(2 <= p["a"] <= 4 for p in pert)
    assert len(sp.lhs(8)) == 8


def test_optimize_and_sensitivity_end_to_end(synth_root, tmp_path):
    ev = _ev(synth_root, tmp_path)
    sp = ParamSpace({"InpFastPeriod": {"type": "int", "low": 4, "high": 10, "step": 3},
                     "InpSlowPeriod": {"type": "int", "low": 20, "high": 40, "step": 10}})
    crit = Criteria(min_trades=1)
    opt = optimize(ev, sp, "grid", objective="net_profit", criteria=crit)
    assert opt.summary["evaluated"] == 9 and opt.summary["failed_runs"] == 0
    assert 0 <= opt.summary["global_survival_profitable_pct"] <= 100
    assert set(opt.best) == {"InpFastPeriod", "InpSlowPeriod"}
    assert abs(sum(opt.importance.values()) - 1) < 1e-9
    # cache: re-running costs nothing and returns the same table
    again = optimize(ev, sp, "grid", objective="net_profit", criteria=crit)
    assert again.best == opt.best
    sens = analyze(ev, sp, opt.robust_best, "net_profit", crit, tests=("oat", "neighborhood", "costs", "periods"),
                   pcts=(10,), n_perturb=4, periods=2, spread_mults=(1.0, 2.0), slippages=(0.0,))
    s = sens.summary
    for k in ("oat_mean_survival_pct", "neighborhood_survival_10pct", "cost_survival_pct",
              "period_survival_pct", "robustness_score"):
        assert 0 <= s[k] <= 100
    assert len(sens.oat_summary) == 2


def test_monte_carlo_shapes():
    tr = pd.DataFrame({"net": np.r_[np.full(30, 10.0), np.full(20, -8.0)]})
    mc = monte_carlo(tr, 1000, sims=200)
    assert mc["shuffle"]["net_profit_p50"] == mc["original_net_profit"]     # shuffle keeps the total
    assert mc["bootstrap"]["max_dd_pct_p95"] >= mc["bootstrap"]["max_dd_pct_p50"]
