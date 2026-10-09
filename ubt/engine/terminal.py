"""Terminal = the runtime an EA sees: broker, chart series, indicator handles,
selection state, virtual files, timer. One terminal is active per process at
a time (``ubt.mql5.api`` functions operate on the active terminal)."""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from ..mql5 import constants as C
from .bars import BarSeries, resample_bars
from .broker import Broker

log = logging.getLogger("ubt.ea")


class Terminal:
    def __init__(self, broker: Broker, chart_symbol: str, chart_period: int,
                 verbose: bool = False, log_limit: int = 200000):
        self.broker = broker
        self.chart_symbol = chart_symbol
        self.chart_period = chart_period
        self.series: Dict[Tuple[str, int], BarSeries] = {}
        self._by_symbol: Dict[str, List[BarSeries]] = {}
        self.handles: List[object] = []
        self.sel_pos = None
        self.sel_ord = None
        self.hist_from = 0
        self.hist_to = 0
        self.hist_deals = []
        self.hist_orders = []
        self.last_error = 0
        self.files: Dict[str, str] = {}
        self.open_files: Dict[int, dict] = {}
        self._fh = 0
        self.global_vars: Dict[str, float] = {}
        self.verbose = verbose
        self.logs: List[str] = []
        self.log_limit = log_limit
        self.timer_ms = 0
        self.next_timer_msc = 0
        self.comment = ""
        self.stopped = False

    # ------------------------------------------------------------------ series
    def add_m1_history(self, symbol: str, frame):
        """Register warm-up M1 history for a symbol (DataFrame with time/open/high/low/close...)."""
        point = self.broker.sym[symbol].spec.point if symbol in self.broker.sym else 0.01
        s = BarSeries(symbol, C.PERIOD_M1, point)
        if frame is not None and len(frame):
            s.load_history(frame["time"].to_numpy(), frame["open"].to_numpy(), frame["high"].to_numpy(),
                           frame["low"].to_numpy(), frame["close"].to_numpy(),
                           frame["tick_volume"].to_numpy() if "tick_volume" in frame else None,
                           frame["spread"].to_numpy() if "spread" in frame else None,
                           frame["real_volume"].to_numpy() if "real_volume" in frame else None)
        self.series[(symbol, C.PERIOD_M1)] = s
        self._by_symbol.setdefault(symbol, [])
        if s not in self._by_symbol[symbol]:
            self._by_symbol[symbol].insert(0, s)

    def get_series(self, symbol: str, tf: int) -> Optional[BarSeries]:
        if tf == C.PERIOD_CURRENT or tf == 0:
            tf = self.chart_period
        key = (symbol, tf)
        s = self.series.get(key)
        if s is not None:
            return s
        if symbol not in self.broker.sym:
            return None
        m1 = self.series.get((symbol, C.PERIOD_M1))
        if m1 is None:
            self.add_m1_history(symbol, None)
            m1 = self.series[(symbol, C.PERIOD_M1)]
        s = resample_bars(m1, tf) if len(m1) else BarSeries(symbol, tf, m1.point)
        self.series[key] = s
        self._by_symbol.setdefault(symbol, []).append(s)
        return s

    def feed_tick(self, symbol: str, time_msc: int, bid: float, ask: float, last: float = 0.0,
                  volume: float = 0.0):
        t = time_msc // 1000
        for s in self._by_symbol.get(symbol, ()):
            s.update(t, bid, ask, volume)
        self.broker.on_tick(symbol, time_msc, bid, ask, last, int(volume))

    # ------------------------------------------------------------------ logging
    def print(self, *args):
        msg = "".join(str(a) for a in args)
        if len(self.logs) < self.log_limit:
            self.logs.append(f"{self.broker.time}\t{msg}")
        if self.verbose:
            log.info(msg)
