"""Backtest runner: replays ticks through the simulated MT5 terminal and the EA."""
from __future__ import annotations

import json
import logging
import time as _time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Type

import numpy as np
import pandas as pd

from ..analysis.metrics import compute_metrics, trades_from_deals
from ..data.store import DataStore, to_epoch
from ..mql5 import api as A
from ..mql5 import constants as C
from ..strategy import Strategy
from .broker import Broker, CostModel
from .symbol import AccountSpec, SymbolSpec
from .terminal import Terminal
from .ticks import tick_stream

log = logging.getLogger("ubt")


@dataclass
class BacktestConfig:
    data_root: str = "data"
    symbol: str = "BTCUSD"               # chart symbol
    timeframe: str = "M5"                # chart timeframe
    start: str = "2024-01-01"
    end: str = "2024-02-01"
    model: str = "real"                  # real | every_tick | m1_ohlc
    ticks_per_bar: int = 12              # every_tick model density
    deposit: float = 10000.0
    currency: str = "USD"
    leverage: Optional[int] = None       # None = account leverage from download (or 100)
    margin_so_so: Optional[float] = None
    margin_so_call: Optional[float] = None
    commission_per_lot: float = 0.0
    commission_pct: float = 0.0
    slippage_points: float = 0.0
    spread_multiplier: float = 1.0
    extra_spread_points: float = 0.0
    default_spread_points: float = 0.0   # for bar-generated ticks when bars carry no spread
    gap_fill: str = "worse"              # worse | exact
    stop_out: bool = True
    swaps: bool = True
    warmup_days: int = 30
    close_at_end: bool = True
    stop_when_blown: bool = True
    verbose: bool = False
    bar_source: str = "auto"             # auto | bars | bars_from_ticks
    spec_overrides: dict = field(default_factory=dict)

    def costs(self) -> CostModel:
        return CostModel(self.commission_per_lot, self.commission_pct, self.slippage_points,
                         self.spread_multiplier, self.extra_spread_points)


@dataclass
class BacktestResult:
    config: dict
    inputs: dict
    metrics: dict
    deals: pd.DataFrame
    trades: pd.DataFrame
    equity: pd.DataFrame
    logs: List[str]
    init_code: int = 0
    ticks: int = 0
    seconds: float = 0.0

    def save(self, out_dir: str | Path):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "metrics.json", "w") as f:
            json.dump({"metrics": self.metrics, "inputs": self.inputs, "config": self.config,
                       "ticks": self.ticks, "seconds": self.seconds, "init_code": self.init_code},
                      f, indent=2, default=str)
        self.deals.to_csv(out / "deals.csv", index=False)
        self.trades.to_csv(out / "trades.csv", index=False)
        self.equity.to_csv(out / "equity.csv", index=False)
        with open(out / "journal.log", "w", encoding="utf-8") as f:
            f.write("\n".join(self.logs))
        return out


def _resolve_tf(tf) -> int:
    if isinstance(tf, int):
        return tf
    return C.TIMEFRAME_BY_NAME[str(tf).upper()]


def _load_specs(store: DataStore, symbols: List[str], cfg: BacktestConfig) -> Dict[str, SymbolSpec]:
    specs = {}
    for s in symbols:
        spec = store.load_spec(s)
        if spec is None:
            log.warning("no symbol_spec.json for %s - using generic defaults", s)
            spec = SymbolSpec(name=s)
        for k, v in (cfg.spec_overrides.get(s, {}) if isinstance(cfg.spec_overrides.get(s), dict)
                     else cfg.spec_overrides).items():
            setattr(spec, k, v)
        specs[s] = spec
    return specs


def _account(store: DataStore, symbol: str, cfg: BacktestConfig) -> AccountSpec:
    acc = AccountSpec(deposit=cfg.deposit, currency=cfg.currency)
    info = store.load_json(symbol, "account.json") or {}
    acc.leverage = int(cfg.leverage or info.get("leverage") or 100)
    acc.margin_so_so = float(cfg.margin_so_so if cfg.margin_so_so is not None else info.get("margin_so_so", 50.0))
    acc.margin_so_call = float(cfg.margin_so_call if cfg.margin_so_call is not None else info.get("margin_so_call", 100.0))
    return acc


def run_backtest(strategy_cls: Type[Strategy], inputs: Optional[dict] = None,
                 cfg: Optional[BacktestConfig] = None, **overrides) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    if overrides:
        cfg = BacktestConfig(**{**asdict(cfg), **overrides})
    t0 = _time.time()
    store = DataStore(cfg.data_root)
    start, end = to_epoch(cfg.start), to_epoch(cfg.end)
    chart_tf = _resolve_tf(cfg.timeframe)

    wanted = strategy_cls.required_symbols(inputs or {}, cfg.symbol)
    symbols = [cfg.symbol] + [s for s in wanted[1:] if (store.sym_dir(s).exists())]
    specs = _load_specs(store, symbols, cfg)
    broker = Broker(_account(store, cfg.symbol, cfg), specs, cfg.costs(), cfg.gap_fill,
                    cfg.stop_out, cfg.swaps)
    term = Terminal(broker, cfg.symbol, chart_tf, verbose=cfg.verbose)
    A._activate(term)

    # warm-up history (closed M1 bars before the start), like the MT5 tester's preloaded history
    for s in symbols:
        hist = store.load_bars(s, "M1", start - cfg.warmup_days * 86400, start, source=cfg.bar_source)
        term.add_m1_history(s, hist)

    stream = tick_stream(store, symbols, specs, start, end, cfg.model, cfg.ticks_per_bar,
                         cfg.default_spread_points, cfg.bar_source)
    first = next(stream, None)
    strategy = strategy_cls(inputs)
    if first is None or len(first) == 0:
        raise RuntimeError(f"no {cfg.model} data for {symbols} in {cfg.start}..{cfg.end} under {cfg.data_root}")

    # prices visible in OnInit = first quote of each symbol
    for si, s in enumerate(symbols):
        idx = np.flatnonzero(first.sym == si)
        if len(idx):
            j = idx[0]
            broker.set_price(s, int(first.time_msc[j]) - 1, float(first.bid[j]), float(first.ask[j]))
    broker.time_msc = int(first.time_msc[0]) - 1
    broker.time = broker.time_msc // 1000

    init_code = strategy.OnInit()
    init_code = 0 if init_code is None else int(init_code)
    eq_rows: List[tuple] = []
    nticks = 0
    if init_code == C.INIT_SUCCEEDED:
        nticks = _run_loop(term, broker, strategy, symbols, cfg, first, stream, eq_rows)

    # end of test: close everything at the last prices (MT5 tester behaviour)
    if cfg.close_at_end:
        for o in list(broker.orders):
            broker._finish_order(o, C.ORDER_STATE_CANCELED)
        for p in list(broker.positions):
            st = broker.sym[p.symbol]
            broker._close_position(p, p.volume, st.bid if p.type == C.POSITION_TYPE_BUY else st.ask,
                                   C.DEAL_REASON_CLIENT, "end of test")
        broker._update_equity()
    if init_code == C.INIT_SUCCEEDED:
        strategy.OnDeinit(0)

    deals = pd.DataFrame([d.as_dict() for d in broker.deals])
    equity = pd.DataFrame(eq_rows, columns=["time", "balance", "equity", "equity_min", "in_market"])
    if len(equity) == 0:
        equity = pd.DataFrame([(start, broker.balance, broker.equity, broker.equity, 0)],
                              columns=["time", "balance", "equity", "equity_min", "in_market"])
    bstats = {"max_dd_money": broker.max_dd_money, "max_dd_money_pct": broker.max_dd_money_pct,
              "max_dd_rel_pct": broker.max_dd_rel_pct, "min_equity": broker.min_equity,
              "min_margin_level": broker.min_margin_level if broker.min_margin_level != float("inf") else 0.0,
              "stopped_out": broker.stopped_out, "blown": broker.blown, "final_balance": broker.balance}
    metrics = compute_metrics(deals, equity, cfg.deposit, start, end, bstats)
    term.tester_stats = metrics
    metrics["ontester"] = float(strategy.OnTester() or 0.0) if init_code == C.INIT_SUCCEEDED else 0.0
    metrics["init_code"] = init_code
    metrics["ticks"] = nticks
    trades = trades_from_deals(deals)
    res = BacktestResult(asdict(cfg), dict(strategy.inputs), metrics, deals, trades, equity, term.logs,
                         init_code, nticks, _time.time() - t0)
    A._activate(None)
    return res


def _run_loop(term: Terminal, broker: Broker, strategy: Strategy, symbols: List[str], cfg: BacktestConfig,
              first, stream, eq_rows) -> int:
    chart_idx = 0
    feed = term.feed_tick
    on_tick = strategy.OnTick
    on_timer = strategy.OnTimer
    nticks = 0
    cur_min = -1
    min_eq = last_eq = last_bal = broker.equity
    last_in = 0
    single = len(symbols) == 1
    sym0 = symbols[0]

    chunk = first
    while chunk is not None:
        syms = chunk.sym.tolist()
        tms = chunk.time_msc.tolist()
        bids = chunk.bid.tolist()
        asks = chunk.ask.tolist()
        lasts = chunk.last.tolist()
        vols = chunk.volume.tolist()
        for k in range(len(tms)):
            tm = tms[k]
            si = 0 if single else syms[k]
            feed(sym0 if single else symbols[si], tm, bids[k], asks[k], lasts[k], vols[k])
            if si == chart_idx:
                on_tick()
            if term.timer_ms and tm >= term.next_timer_msc:
                term.next_timer_msc = tm + term.timer_ms
                on_timer()
            nticks += 1
            eq = broker.equity
            m = tm // 60000
            if m != cur_min:
                if cur_min >= 0:
                    eq_rows.append((cur_min * 60, last_bal, last_eq, min_eq, last_in))
                cur_min = m
                min_eq = eq
            elif eq < min_eq:
                min_eq = eq
            last_eq = eq
            last_bal = broker.balance
            last_in = 1 if broker.positions else 0
            if broker.blown and cfg.stop_when_blown:
                term.print("equity <= 0: test stopped")
                eq_rows.append((cur_min * 60, last_bal, last_eq, min_eq, last_in))
                return nticks
        chunk = next(stream, None)
    if cur_min >= 0:
        eq_rows.append((cur_min * 60, last_bal, last_eq, min_eq, last_in))
    return nticks
