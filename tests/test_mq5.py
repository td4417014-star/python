import ast
import os

from ubt.mq5 import auto_space, parse_mq5, read_set, write_set
from ubt.mql5 import constants as C
from ubt.transpile import transpile_file

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIX = os.path.join(ROOT, "experts", "Zscore_and_Levando_MIX.mq5")
MA = os.path.join(ROOT, "experts", "MA_Cross_Example.mq5")


def test_parse_inputs_enums_assets():
    info = parse_mq5(MIX)
    d = info.defaults()
    assert len(info.inputs) == 45
    assert d["InpGZ_ZscorePeriod"] == 14 and d["InpGZ_ZscoreBuyTh"] == -0.3
    assert d["InpGZ_Timeframe"] == C.PERIOD_M5
    assert d["InpGZ_GapMode"] == 1 and d["InpGZ_TrailGrid"] == 3          # EA's own enums resolved
    assert info.symbols() == ["BTCUSD"]
    assert info.timeframes() == [C.PERIOD_M5, C.PERIOD_M30, C.PERIOD_H1, C.PERIOD_H2, C.PERIOD_H4]


def test_auto_space_skips_technical_inputs():
    sp = auto_space(parse_mq5(MIX))
    assert "InpGZ_ZscorePeriod" in sp and "InpGZ_Magic" not in sp and "InpLV_Comment" not in sp
    assert sp["InpGZ_TrailFirst"]["values"] == [0, 1, 2, 3, 4, 5]


def test_set_file_roundtrip(tmp_path):
    info = parse_mq5(MIX)
    vals = info.defaults()
    vals["InpGZ_ZscorePeriod"] = 21
    space = {"InpGZ_ZscorePeriod": {"type": "int", "low": 10, "high": 30, "step": 5}}
    p = tmp_path / "x.set"
    write_set(p, vals, space, info)
    back, sp = read_set(p)
    assert back["InpGZ_ZscorePeriod"] == 21 and back["InpLV_Timeframes"] == "30,60,120,240"
    assert sp["InpGZ_ZscorePeriod"] == {"type": "int", "low": 10, "high": 30, "step": 5}


def test_transpiler_produces_valid_python(tmp_path):
    for src in (MIX, MA):
        out = transpile_file(src, str(tmp_path / "strategies" / "draft.py"))
        code = out.read_text()
        ast.parse(code)
        assert "NotImplementedError" not in code
