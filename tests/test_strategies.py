import importlib.util
import os

import pandas as pd

from ubt.engine.backtest import BacktestConfig, run_backtest
from ubt.transpile import transpile_file
from strategies.ma_cross_example import MACrossExample
from strategies.zscore_levando_mix import ZscoreLevandoMix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEAL_COLS = ["time_msc", "type", "entry", "volume", "price", "profit", "magic", "reason"]


def _cfg(root, **kw):
    base = dict(data_root=root, symbol="BTCUSD", timeframe="M5", start="2024-01-01", end="2024-01-04",
                model="m1_ohlc", warmup_days=10)
    base.update(kw)
    return BacktestConfig(**base)


def test_mix_runs_both_engines_and_is_deterministic(synth_root):
    a = run_backtest(ZscoreLevandoMix, {}, _cfg(synth_root))
    b = run_backtest(ZscoreLevandoMix, {}, _cfg(synth_root))
    assert a.init_code == 0 and a.ticks > 1000
    assert set(a.trades["magic"]) >= {774400}
    assert a.deals[DEAL_COLS].equals(b.deals[DEAL_COLS])
    m = a.metrics
    assert abs(m["final_balance"] - (10000 + a.trades["net"].sum())) < 1e-6
    # EA's OnTester: profit / relative equity DD
    assert abs(m["ontester"] - m["net_profit"] / max(m["equity_dd_rel_pct"], 0.01)) < 1e-9


def test_engine_toggle_and_magic_guard(synth_root):
    only_a = run_backtest(ZscoreLevandoMix, {"InpLV_Enable": False}, _cfg(synth_root))
    assert set(only_a.trades["magic"]) <= {774400}
    same_magic = run_backtest(ZscoreLevandoMix, {"InpLV_MagicNumber": 774400}, _cfg(synth_root))
    assert same_magic.init_code == 2 and same_magic.ticks == 0            # INIT_PARAMETERS_INCORRECT


def test_real_ticks_model(synth_root):
    r = run_backtest(ZscoreLevandoMix, {}, _cfg(synth_root, model="real", end="2024-01-02"))
    assert r.ticks > 10000 and r.metrics["trades"] > 0


def _load(path, cls_name):
    spec = importlib.util.spec_from_file_location("draft_" + cls_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return getattr(mod, cls_name)


def test_transpiled_ma_cross_equals_hand_port(synth_root, tmp_path):
    out = transpile_file(os.path.join(ROOT, "experts", "MA_Cross_Example.mq5"),
                         str(tmp_path / "strategies" / "draft_ma.py"))
    Draft = _load(out, "MaCrossExample")
    cfg = _cfg(synth_root, end="2024-01-05", timeframe="M1")
    a = run_backtest(Draft, {"InpFastPeriod": 5, "InpSlowPeriod": 20}, cfg)
    b = run_backtest(MACrossExample, {"InpFastPeriod": 5, "InpSlowPeriod": 20}, cfg)
    assert len(b.deals) > 5
    assert a.deals[DEAL_COLS].equals(b.deals[DEAL_COLS])


def test_transpiled_mix_equals_hand_port_after_flagged_fixes(synth_root, tmp_path):
    out = transpile_file(os.path.join(ROOT, "experts", "Zscore_and_Levando_MIX.mq5"),
                         str(tmp_path / "strategies" / "draft_mix.py"))
    code = out.read_text()
    # the 3 call sites the transpiler flags with TODO, fixed the way a user would
    code = code.replace(
        "        if not self.LV_GetClosedHA(tf, o1, c1, o2, c2):\n",
        "        _ok, o1, c1, o2, c2 = self.LV_GetClosedHA(tf, o1, c1, o2, c2)\n        if not _ok:\n")
    for eng, tag, var in (("InpGZ_Enable", "GridZ", "g_gzSymbol"), ("InpLV_Enable", "LeVanDo", "g_lvSymbol")):
        sym_in = "InpGZ_Symbol" if eng == "InpGZ_Enable" else "InpLV_Symbol"
        old = (f'        if self.{eng} and not self.ResolveSymbol(self.{sym_in}, "{tag}", self.{var}):\n'
               f"            return INIT_PARAMETERS_INCORRECT\n")
        new = (f"        if self.{eng}:\n"
               f'            _ok, self.{var} = self.ResolveSymbol(self.{sym_in}, "{tag}", self.{var})\n'
               f"            if not _ok:\n                return INIT_PARAMETERS_INCORRECT\n")
        assert old in code
        code = code.replace(old, new)
    out.write_text(code)
    Draft = _load(out, "ZscoreAndLevandoMix")
    cfg = _cfg(synth_root)
    a = run_backtest(Draft, {}, cfg)
    b = run_backtest(ZscoreLevandoMix, {}, cfg)
    assert len(b.deals) > 20
    assert a.deals[DEAL_COLS].equals(b.deals[DEAL_COLS])
