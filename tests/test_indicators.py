import numpy as np
import pandas as pd

from ubt.engine.bars import BarSeries, bar_open_time
from ubt.engine.indicators import ATR, MA, RSI, StdDev, Bands
from ubt.mql5 import constants as C


def _series(n=200, seed=1):
    rng = np.random.default_rng(seed)
    c = 100 + np.cumsum(rng.normal(0, 1, n))
    o = np.r_[c[0], c[:-1]]
    h = np.maximum(o, c) + rng.random(n)
    lo = np.minimum(o, c) - rng.random(n)
    s = BarSeries("X", C.PERIOD_M5, 0.01)
    s.load_history(np.arange(n) * 300, o, h, lo, c)
    return s, pd.DataFrame({"o": o, "h": h, "l": lo, "c": c})


def test_sma_stddev_match_pandas():
    s, df = _series()
    ma, sd = MA(s, 14), StdDev(s, 14)
    ref_ma = df.c.rolling(14).mean()
    ref_sd = df.c.rolling(14).std(ddof=0)
    for i in (13, 50, 199):
        assert abs(ma.value(0, i) - ref_ma[i]) < 1e-9
        assert abs(sd.value(0, i) - ref_sd[i]) < 1e-9
    assert ma.value(0, 5) == 0.0          # MT5 warm-up convention


def test_atr_matches_mt5_formula():
    s, df = _series()
    atr = ATR(s, 14)
    pc = df.c.shift(1)
    tr = np.maximum(df.h, pc) - np.minimum(df.l, pc)
    tr[0] = 0.0
    ref = tr.rolling(14).mean()           # ATR.mq5: simple mean of the last p true ranges (from bar 1)
    for i in (14, 77, 198, 199):
        assert abs(atr.value(0, i) - ref[i]) < 1e-9
    assert atr.value(0, 13) == 0.0


def test_ema_and_rsi_recursions():
    s, df = _series()
    ema = MA(s, 10, 0, C.MODE_EMA)
    a = 2 / 11
    ref = [df.c[0]]
    for x in df.c[1:]:
        ref.append(x * a + ref[-1] * (1 - a))
    for i in (0, 30, 199):
        assert abs(ema.value(0, i) - ref[i]) < 1e-9
    rsi = RSI(s, 14)
    v = rsi.value(0, 150)
    assert 0 <= v <= 100


def test_forming_bar_updates_live():
    s, _ = _series(50)
    ma = MA(s, 5)
    before = ma.value(0, len(s) - 1)
    s.update(s.time[-1] + 10, s.close[-1] + 50, s.close[-1] + 50.1)   # same bar, new tick
    assert ma.value(0, len(s) - 1) > before
    s.update(s.time[-1] + 300, 1.0, 1.1)                             # new bar
    assert s.close[-1] == 1.0 and len(s) == 51


def test_bands_and_bar_time():
    s, df = _series()
    b = Bands(s, 20, 0, 2.0)
    i = 120
    mid = df.c.rolling(20).mean()[i]
    sd = df.c.rolling(20).std(ddof=0)[i]
    assert abs(b.value(C.UPPER_BAND, i) - (mid + 2 * sd)) < 1e-9
    t = 1704070000
    assert bar_open_time(t, C.PERIOD_H4) == t - t % 14400
    assert pd.Timestamp(bar_open_time(t, C.PERIOD_W1), unit="s").weekday() == 6     # Sunday
    assert pd.Timestamp(bar_open_time(t, C.PERIOD_MN1), unit="s").day == 1
