"""MT5 built-in indicators re-implemented with the same formulas as the
MetaQuotes reference sources (MovingAverages.mqh, ATR.mq5, StdDev.mq5, RSI.mq5,
BB.mq5, MACD.mq5), including their warm-up conventions (value 0 before the
first full window).

Each indicator reads a live :class:`BarSeries`; the forming bar (shift 0) is
recomputed on every call, closed bars of recursive indicators are cached.
"""
from __future__ import annotations

import math
from typing import List

from ..mql5 import constants as C
from .bars import BarSeries


def applied_price(s: BarSeries, i: int, applied: int) -> float:
    if applied == C.PRICE_CLOSE:
        return s.close[i]
    if applied == C.PRICE_OPEN:
        return s.open[i]
    if applied == C.PRICE_HIGH:
        return s.high[i]
    if applied == C.PRICE_LOW:
        return s.low[i]
    if applied == C.PRICE_MEDIAN:
        return (s.high[i] + s.low[i]) / 2.0
    if applied == C.PRICE_TYPICAL:
        return (s.high[i] + s.low[i] + s.close[i]) / 3.0
    if applied == C.PRICE_WEIGHTED:
        return (s.high[i] + s.low[i] + 2.0 * s.close[i]) / 4.0
    return s.close[i]


class Indicator:
    buffers = 1

    def __init__(self, series: BarSeries):
        self.s = series

    def value(self, buf: int, i: int) -> float:  # absolute index
        raise NotImplementedError

    def copy(self, buf: int, start_shift: int, count: int) -> List[float]:
        """Values from shift ``start_shift`` back ``count`` bars, chronological (oldest first)."""
        n = len(self.s)
        last = n - 1 - start_shift
        if last < 0 or count <= 0:
            return []
        first = max(0, last - count + 1)
        return [self.value(buf, i) for i in range(first, last + 1)]


# ---------------------------------------------------------------------- MA
class MA(Indicator):
    def __init__(self, series, period, ma_shift=0, method=C.MODE_SMA, applied=C.PRICE_CLOSE):
        super().__init__(series)
        self.p = max(1, int(period))
        self.ma_shift = int(ma_shift)
        self.method = method
        self.applied = applied
        self._cache: List[float] = []      # recursive methods: closed-bar values

    def _price(self, i):
        return applied_price(self.s, i, self.applied)

    def _raw(self, i: int) -> float:
        p = self.p
        m = self.method
        if m == C.MODE_SMA:
            if i < p - 1:
                return 0.0
            return math.fsum(self._price(j) for j in range(i - p + 1, i + 1)) / p
        if m == C.MODE_LWMA:
            if i < p - 1:
                return 0.0
            ws = 0.0
            sm = 0.0
            for k, j in enumerate(range(i - p + 1, i + 1), start=1):
                sm += self._price(j) * k
                ws += k
            return sm / ws
        # recursive: EMA / SMMA
        closed = len(self.s) - 1
        self._extend(closed)
        if i < len(self._cache):
            return self._cache[i]
        prev = self._cache[i - 1] if i >= 1 else None
        return self._step(i, prev)

    def _step(self, i, prev):
        p = self.p
        if self.method == C.MODE_EMA:
            a = 2.0 / (p + 1.0)
            if i == 0 or prev is None:
                return self._price(i)
            return self._price(i) * a + prev * (1.0 - a)
        # SMMA
        if i < p - 1:
            return 0.0
        if i == p - 1:
            return math.fsum(self._price(j) for j in range(0, p)) / p
        return (prev * (p - 1) + self._price(i)) / p

    def _extend(self, upto: int):
        c = self._cache
        while len(c) < upto:
            i = len(c)
            c.append(self._step(i, c[i - 1] if i else None))

    def value(self, buf, i):
        j = i - self.ma_shift
        if j < 0:
            return 0.0
        return self._raw(j)


class StdDev(Indicator):
    def __init__(self, series, period, ma_shift=0, method=C.MODE_SMA, applied=C.PRICE_CLOSE):
        super().__init__(series)
        self.p = max(1, int(period))
        self.ma = MA(series, period, 0, method, applied)
        self.applied = applied
        self.ma_shift = int(ma_shift)

    def value(self, buf, i):
        i -= self.ma_shift
        p = self.p
        if i < p - 1:
            return 0.0
        ma = self.ma._raw(i)
        s = self.s
        acc = 0.0
        for j in range(i - p + 1, i + 1):
            d = applied_price(s, j, self.applied) - ma
            acc += d * d
        return math.sqrt(acc / p)


class ATR(Indicator):
    """ATR.mq5: TR[0]=0, ATR[p] = mean(TR[1..p]), then a rolling mean of p TRs."""

    def __init__(self, series, period):
        super().__init__(series)
        self.p = max(1, int(period))
        self._cum: List[float] = [0.0]   # _cum[i] = sum TR[1..i] for closed bars

    def _tr(self, i):
        s = self.s
        if i <= 0:
            return 0.0
        pc = s.close[i - 1]
        h = s.high[i]
        lo = s.low[i]
        return (h if h > pc else pc) - (lo if lo < pc else pc)

    def _extend(self, upto):
        c = self._cum
        while len(c) <= upto:
            i = len(c)
            c.append(c[-1] + self._tr(i))

    def value(self, buf, i):
        p = self.p
        if i < p:
            return 0.0
        n = len(self.s)
        if i < n - 1:
            self._extend(i)
            return (self._cum[i] - self._cum[i - p]) / p
        # forming bar
        self._extend(i - 1)
        return (self._cum[i - 1] - self._cum[i - p] + self._tr(i)) / p


class RSI(Indicator):
    def __init__(self, series, period, applied=C.PRICE_CLOSE):
        super().__init__(series)
        self.p = max(1, int(period))
        self.applied = applied
        self._pos: List[float] = []
        self._neg: List[float] = []

    def _calc(self, i, ppos, pneg):
        p = self.p
        s = self.s
        if i < p:
            return 0.0, 0.0
        if i == p:
            sp = sn = 0.0
            for j in range(1, p + 1):
                d = applied_price(s, j, self.applied) - applied_price(s, j - 1, self.applied)
                sp += d if d > 0 else 0.0
                sn += -d if d < 0 else 0.0
            return sp / p, sn / p
        d = applied_price(s, i, self.applied) - applied_price(s, i - 1, self.applied)
        return ((ppos * (p - 1) + (d if d > 0 else 0.0)) / p,
                (pneg * (p - 1) + (-d if d < 0 else 0.0)) / p)

    def _extend(self, upto):
        while len(self._pos) < upto:
            i = len(self._pos)
            pp = self._pos[i - 1] if i else 0.0
            pn = self._neg[i - 1] if i else 0.0
            a, b = self._calc(i, pp, pn)
            self._pos.append(a)
            self._neg.append(b)

    def value(self, buf, i):
        if i < self.p:
            return 0.0
        n = len(self.s)
        self._extend(min(i, n - 1))
        if i < len(self._pos):
            pos, neg = self._pos[i], self._neg[i]
        else:
            pos, neg = self._calc(i, self._pos[i - 1], self._neg[i - 1])
        if neg != 0.0:
            return 100.0 - 100.0 / (1.0 + pos / neg)
        return 100.0 if pos != 0.0 else 50.0


class Bands(Indicator):
    buffers = 3

    def __init__(self, series, period, shift, deviation, applied=C.PRICE_CLOSE):
        super().__init__(series)
        self.p = max(1, int(period))
        self.shift = int(shift)
        self.dev = float(deviation)
        self.std = StdDev(series, period, 0, C.MODE_SMA, applied)

    def value(self, buf, i):
        i -= self.shift
        if i < self.p - 1:
            return 0.0
        mid = self.std.ma._raw(i)
        if buf == C.BASE_LINE:
            return mid
        sd = self.std.value(0, i)
        return mid + self.dev * sd if buf == C.UPPER_BAND else mid - self.dev * sd


class MACD(Indicator):
    buffers = 2

    def __init__(self, series, fast, slow, signal, applied=C.PRICE_CLOSE):
        super().__init__(series)
        self.fast = MA(series, fast, 0, C.MODE_EMA, applied)
        self.slow = MA(series, slow, 0, C.MODE_EMA, applied)
        self.sig_p = max(1, int(signal))

    def _main(self, i):
        return self.fast.value(0, i) - self.slow.value(0, i)

    def value(self, buf, i):
        if buf == C.MAIN_LINE:
            return self._main(i)
        p = self.sig_p
        if i < p - 1:
            return 0.0
        return math.fsum(self._main(j) for j in range(i - p + 1, i + 1)) / p
