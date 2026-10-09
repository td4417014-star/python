"""Tick streams for the backtest.

Models (same names/ideas as the MT5 tester):

* ``real``       - real purified broker ticks ("Every tick based on real ticks")
* ``every_tick`` - synthetic ticks generated from M1 bars along O->H/L->L/H->C
* ``m1_ohlc``    - 4 ticks per M1 bar (O, L, H, C for bullish bars, O, H, L, C for bearish)
                   ("1 minute OHLC" - fast, good for optimisation)

Streams are yielded month by month to keep memory bounded.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List

import numpy as np
import pandas as pd

from ..data.store import DataStore, month_range, to_epoch
from .symbol import SymbolSpec


@dataclass
class TickChunk:
    sym: np.ndarray        # int index into symbols list
    time_msc: np.ndarray
    bid: np.ndarray
    ask: np.ndarray
    last: np.ndarray
    volume: np.ndarray

    def __len__(self):
        return len(self.time_msc)


def _ticks_from_bars(bars: pd.DataFrame, spec: SymbolSpec, model: str, ticks_per_bar: int,
                     default_spread_points: float) -> pd.DataFrame:
    if bars.empty:
        return pd.DataFrame(columns=["time_msc", "bid", "ask", "last", "volume"])
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    lo = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    t = bars["time"].to_numpy(np.int64) * 1000
    sp_pts = bars["spread"].to_numpy(float) if "spread" in bars else np.zeros(len(bars))
    sp_pts = np.where(sp_pts > 0, sp_pts, default_spread_points if default_spread_points > 0 else spec.spread)
    spread = sp_pts * spec.point
    bull = c >= o
    first = np.where(bull, lo, h)
    second = np.where(bull, h, lo)
    if model == "m1_ohlc":
        k = 4
        px = np.stack([o, first, second, c], axis=1)
        offs = np.array([0, 15000, 30000, 59000], dtype=np.int64)
    else:
        k = max(4, int(ticks_per_bar))
        a1 = (k - 1) // 3
        a2 = 2 * (k - 1) // 3
        idx = np.arange(k)
        anchors_x = np.array([0, a1, a2, k - 1], dtype=float)
        # piecewise-linear interpolation of the 4 anchors for every bar
        w = np.empty((k, 4))
        for j in range(k):
            x = idx[j]
            seg = 0 if x <= a1 else (1 if x <= a2 else 2)
            x0, x1 = anchors_x[seg], anchors_x[seg + 1]
            f = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            row = np.zeros(4)
            row[seg] = 1 - f
            row[seg + 1] = f
            w[j] = row
        anchors = np.stack([o, first, second, c], axis=1)          # (n, 4)
        px = anchors @ w.T                                          # (n, k)
        offs = (idx * (60000 // k)).astype(np.int64)
    if spec.point > 0:
        px = np.round(px / spec.point) * spec.point
    times = (t[:, None] + offs[None, :]).ravel()
    bid = px.ravel()
    ask = bid + np.repeat(spread, k)
    df = pd.DataFrame({"time_msc": times, "bid": bid, "ask": ask, "last": 0.0, "volume": 0.0})
    # drop exact repeats inside a bar (e.g. doji/flat bars)
    same = np.zeros(len(df), dtype=bool)
    same[1:] = (bid[1:] == bid[:-1]) & (ask[1:] == ask[:-1])
    return df[~same]


def tick_stream(store: DataStore, symbols: List[str], specs: Dict[str, SymbolSpec], start, end,
                model: str = "real", ticks_per_bar: int = 12, default_spread_points: float = 0.0,
                bar_source: str = "auto") -> Iterator[TickChunk]:
    s, e = to_epoch(start), to_epoch(end)
    for m in month_range(s, e - 1):
        y, mo = int(m[:4]), int(m[5:])
        ms = max(s, to_epoch(f"{y:04d}-{mo:02d}-01"))
        ny, nm = (y + 1, 1) if mo == 12 else (y, mo + 1)
        me = min(e, to_epoch(f"{ny:04d}-{nm:02d}-01"))
        frames = []
        for si, sym in enumerate(symbols):
            if model == "real":
                parts = list(store.iter_ticks(sym, ms, me))
                df = pd.concat(parts, ignore_index=True) if parts else None
            else:
                bars = store.load_bars(sym, "M1", ms, me, source=bar_source)
                df = _ticks_from_bars(bars, specs[sym], model, ticks_per_bar, default_spread_points)
            if df is None or df.empty:
                continue
            df = df.assign(sym=si)
            frames.append(df[["sym", "time_msc", "bid", "ask", "last", "volume"]])
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True)
        if len(frames) > 1:
            df = df.sort_values(["time_msc", "sym"], kind="stable")
        yield TickChunk(df["sym"].to_numpy(np.int64), df["time_msc"].to_numpy(np.int64),
                        df["bid"].to_numpy(float), df["ask"].to_numpy(float),
                        df["last"].to_numpy(float) if "last" in df else np.zeros(len(df)),
                        df["volume"].to_numpy(float) if "volume" in df else np.zeros(len(df)))
