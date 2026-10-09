import numpy as np
import pandas as pd

from ubt.data.cleaning import clean_bars, clean_ticks, ticks_to_bars
from ubt.data.store import DataStore


def _ticks(n=3000, seed=0):
    rng = np.random.default_rng(seed)
    t = 1_700_000_000_000 + np.arange(n) * 1000
    bid = 50000 + np.cumsum(rng.normal(0, 2, n)).round(2)
    return pd.DataFrame({"time_msc": t, "bid": bid, "ask": bid + 10, "last": 0.0, "volume": 0.0, "flags": 6})


def test_clean_ticks_removes_only_bad_records():
    df = _ticks()
    bad = df.copy()
    bad.loc[100, "bid"] = 0.0                            # non-positive
    bad.loc[200, "ask"] = bad.loc[200, "bid"] - 1        # crossed
    bad.loc[300, ["bid", "ask"]] = [90000.0, 90010.0]    # isolated spike
    bad = pd.concat([bad, bad.iloc[[400]]])              # duplicate
    out, rep = clean_ticks(bad, point=0.01, drop_unchanged=False)
    assert rep["removed_nonpositive_or_nan"] == 1
    assert rep["removed_crossed"] == 1
    assert rep["removed_duplicates"] == 1
    assert rep["removed_spikes"] == 1
    assert len(out) == len(df) - 3
    assert out["time_msc"].is_monotonic_increasing


def test_clean_keeps_genuine_trend_move():
    df = _ticks()
    df.loc[1500:, ["bid", "ask"]] += 3000.0               # a real level shift that does not revert
    out, rep = clean_ticks(df, point=0.01, drop_unchanged=False)
    assert rep["removed_spikes"] == 0 and len(out) == len(df)


def test_bars_roundtrip_and_ohlc_fix(tmp_path):
    t = _ticks()
    bars = ticks_to_bars(t, 60, 0.01)
    assert (bars.high >= bars[["open", "close"]].max(axis=1)).all()
    broken = bars.copy()
    broken.loc[3, "high"] = broken.loc[3, "low"] - 1
    fixed, rep = clean_bars(broken, 60, weekend_trading=True)
    assert rep["fixed_ohlc_inconsistent"] == 1
    st = DataStore(tmp_path)
    st.save_ticks("XYZ", t)
    st.save_bars("XYZ", "M1", fixed)
    back = st.load_ticks("XYZ", "2023-01-01", "2030-01-01")
    assert len(back) == len(t)
    assert len(st.load_bars("XYZ", "M1")) == len(fixed)
