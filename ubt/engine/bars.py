"""Incremental OHLC bar series, built from ticks exactly like MT5 charts.

Bars are built on Bid. The last element is the forming bar (shift 0), which
is updated on every tick, so indicators read on shift 0 change intra-bar as
they do in the MT5 tester.
"""
from __future__ import annotations

import calendar
import datetime as _dt
from typing import List

import numpy as np

from ..mql5 import constants as C


def tf_seconds(tf: int) -> int:
    return C.TIMEFRAME_SECONDS[tf]


def bar_open_time(t: int, tf: int) -> int:
    """Open time (seconds) of the ``tf`` bar containing server time ``t``."""
    if tf == C.PERIOD_MN1:
        d = _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=t)
        return calendar.timegm((d.year, d.month, 1, 0, 0, 0))
    if tf == C.PERIOD_W1:
        days = t // 86400
        # 1970-01-01 was a Thursday; MT5 weeks start on Sunday
        start = ((days - 3) // 7) * 7 + 3
        return start * 86400
    s = C.TIMEFRAME_SECONDS[tf]
    return t - t % s


class BarSeries:
    """Chronological bars. Index 0 = oldest; ``[-1]`` = forming bar (shift 0)."""

    __slots__ = ("symbol", "tf", "sec", "time", "open", "high", "low", "close",
                 "tick_volume", "spread", "real_volume", "_cur_open", "_cur_end", "point",
                 "version")

    def __init__(self, symbol: str, tf: int, point: float = 0.01):
        self.symbol = symbol
        self.tf = tf
        self.sec = C.TIMEFRAME_SECONDS[tf]
        self.point = point if point > 0 else 1e-8
        self.time: List[int] = []
        self.open: List[float] = []
        self.high: List[float] = []
        self.low: List[float] = []
        self.close: List[float] = []
        self.tick_volume: List[int] = []
        self.spread: List[int] = []
        self.real_volume: List[float] = []
        self._cur_open = -1
        self._cur_end = -1
        self.version = 0     # increments when a new bar is appended

    def __len__(self):
        return len(self.time)

    # ------------------------------------------------------------------
    def load_history(self, time, open_, high, low, close, tick_volume=None, spread=None, real_volume=None):
        """Bulk-load closed history bars (chronological)."""
        n = len(time)
        self.time = [int(x) for x in time]
        self.open = [float(x) for x in open_]
        self.high = [float(x) for x in high]
        self.low = [float(x) for x in low]
        self.close = [float(x) for x in close]
        self.tick_volume = [int(x) for x in tick_volume] if tick_volume is not None else [0] * n
        self.spread = [int(x) for x in spread] if spread is not None else [0] * n
        self.real_volume = [float(x) for x in real_volume] if real_volume is not None else [0.0] * n
        if n:
            self._cur_open = self.time[-1]
            self._cur_end = self._next_open(self._cur_open)
        self.version += 1

    def _next_open(self, t_open: int) -> int:
        if self.tf == C.PERIOD_MN1:
            d = _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=t_open)
            y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
            return calendar.timegm((y, m, 1, 0, 0, 0))
        return t_open + self.sec

    def update(self, t: int, bid: float, ask: float, vol: float = 0.0):
        """Feed one tick (server seconds)."""
        if t < self._cur_end and t >= self._cur_open:
            i = -1
            if bid > self.high[i]:
                self.high[i] = bid
            if bid < self.low[i]:
                self.low[i] = bid
            self.close[i] = bid
            self.tick_volume[i] += 1
            self.real_volume[i] += vol
            return False
        if t < self._cur_open:
            return False          # late/out-of-order tick: ignore like MT5
        o = bar_open_time(t, self.tf)
        sp = int(round((ask - bid) / self.point)) if ask > 0 else 0
        self.time.append(o)
        self.open.append(bid)
        self.high.append(bid)
        self.low.append(bid)
        self.close.append(bid)
        self.tick_volume.append(1)
        self.spread.append(sp)
        self.real_volume.append(vol)
        self._cur_open = o
        self._cur_end = self._next_open(o)
        self.version += 1
        return True

    def add_bar(self, t_open, o, h, l, c, tv=0, sp=0, rv=0.0):
        """Append/merge an already-aggregated sub-bar (used to resample M1 into higher TFs)."""
        bo = bar_open_time(int(t_open), self.tf)
        if self.time and bo == self.time[-1]:
            if h > self.high[-1]:
                self.high[-1] = h
            if l < self.low[-1]:
                self.low[-1] = l
            self.close[-1] = c
            self.tick_volume[-1] += int(tv)
            self.real_volume[-1] += rv
            return
        self.time.append(bo)
        self.open.append(o)
        self.high.append(h)
        self.low.append(l)
        self.close.append(c)
        self.tick_volume.append(int(tv))
        self.spread.append(int(sp))
        self.real_volume.append(rv)
        self._cur_open = bo
        self._cur_end = self._next_open(bo)
        self.version += 1

    # ------------------------------------------------------------------ MQL accessors (shift based)
    def idx(self, shift: int) -> int:
        """Absolute index for an MQL shift, or -1 if not available."""
        i = len(self.time) - 1 - shift
        return i if 0 <= i < len(self.time) else -1

    def bar_shift(self, t: int, exact: bool = False) -> int:
        """iBarShift: shift of the bar containing time t."""
        import bisect
        i = bisect.bisect_right(self.time, t) - 1
        if i < 0:
            return -1
        if exact and self.time[i] != t:
            return -1
        return len(self.time) - 1 - i

    def to_frame(self):
        import pandas as pd
        return pd.DataFrame({"time": self.time, "open": self.open, "high": self.high, "low": self.low,
                             "close": self.close, "tick_volume": self.tick_volume, "spread": self.spread,
                             "real_volume": self.real_volume})


def resample_bars(src: BarSeries, tf: int) -> BarSeries:
    """Build a higher timeframe series from a (M1) series, forming bar included."""
    out = BarSeries(src.symbol, tf, src.point)
    for i in range(len(src.time)):
        out.add_bar(src.time[i], src.open[i], src.high[i], src.low[i], src.close[i],
                    src.tick_volume[i], src.spread[i], src.real_volume[i])
    return out


def resample_frame(df, tf: int):
    """Vectorised resample of a bar DataFrame (columns time/open/high/low/close/...) to ``tf``."""
    import pandas as pd
    if df.empty:
        return df.copy()
    t = df["time"].to_numpy(np.int64)
    if tf in (C.PERIOD_MN1, C.PERIOD_W1):
        key = np.array([bar_open_time(int(x), tf) for x in t], dtype=np.int64)
    else:
        s = C.TIMEFRAME_SECONDS[tf]
        key = t - t % s
    g = df.assign(_k=key).groupby("_k", sort=True)
    out = pd.DataFrame({
        "time": g["time"].first().index.to_numpy(np.int64),
        "open": g["open"].first().to_numpy(),
        "high": g["high"].max().to_numpy(),
        "low": g["low"].min().to_numpy(),
        "close": g["close"].last().to_numpy(),
        "tick_volume": g["tick_volume"].sum().to_numpy() if "tick_volume" in df else 0,
        "spread": g["spread"].min().to_numpy() if "spread" in df else 0,
        "real_volume": g["real_volume"].sum().to_numpy() if "real_volume" in df else 0,
    })
    return out
