"""Symbol contract specification (what MT5 calls symbol properties).

The downloader stores the broker's real ``symbol_info`` as ``symbol_spec.json``
next to the data, so the backtest uses exactly the broker's tick value,
contract size, volume limits, stop levels, swaps and margin settings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields
from pathlib import Path

from ..mql5 import constants as C


@dataclass
class SymbolSpec:
    name: str = "BTCUSD"
    digits: int = 2
    point: float = 0.01
    trade_tick_size: float = 0.01
    trade_tick_value: float = 0.01
    trade_tick_value_profit: float = 0.0
    trade_tick_value_loss: float = 0.0
    trade_contract_size: float = 1.0
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    volume_limit: float = 0.0
    trade_stops_level: int = 0
    trade_freeze_level: int = 0
    filling_mode: int = C.SYMBOL_FILLING_FOK | C.SYMBOL_FILLING_IOC
    trade_mode: int = 4            # SYMBOL_TRADE_MODE_FULL
    trade_exemode: int = 2         # SYMBOL_TRADE_EXECUTION_MARKET
    trade_calc_mode: int = C.SYMBOL_CALC_MODE_CFDLEVERAGE
    swap_mode: int = C.SYMBOL_SWAP_MODE_DISABLED
    swap_long: float = 0.0
    swap_short: float = 0.0
    swap_rollover3days: int = 3    # Wednesday
    margin_initial: float = 0.0
    margin_maintenance: float = 0.0
    margin_hedged: float = 0.0
    margin_rate: float = 1.0
    currency_base: str = "BTC"
    currency_profit: str = "USD"
    currency_margin: str = "BTC"
    description: str = ""
    path: str = ""
    spread: int = 0
    spread_float: bool = True
    # Margin for 1.0 lot measured by the broker (mt5.order_calc_margin) at ref price.
    margin_per_lot_ref: float = 0.0
    margin_ref_price: float = 0.0
    margin_ref_leverage: int = 0
    # Derived from data: does the symbol trade on Saturday/Sunday (crypto)?
    weekend_trading: bool = False
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.trade_tick_value_profit <= 0:
            self.trade_tick_value_profit = self.trade_tick_value
        if self.trade_tick_value_loss <= 0:
            self.trade_tick_value_loss = self.trade_tick_value
        if self.trade_tick_size <= 0:
            self.trade_tick_size = self.point

    # ------------------------------------------------------------------
    def profit(self, pos_type: int, volume: float, price_open: float, price_close: float) -> float:
        """Profit in deposit currency, MT5 style (tick size / tick value)."""
        diff = (price_close - price_open) if pos_type == C.POSITION_TYPE_BUY else (price_open - price_close)
        tv = self.trade_tick_value_profit if diff >= 0 else self.trade_tick_value_loss
        return diff / self.trade_tick_size * tv * volume

    def margin(self, volume: float, price: float, leverage: int) -> float:
        """Margin required for ``volume`` lots in deposit currency."""
        if volume <= 0:
            return 0.0
        price_prop = self.trade_calc_mode not in (C.SYMBOL_CALC_MODE_FUTURES,)
        lev_dep = self.trade_calc_mode in (C.SYMBOL_CALC_MODE_FOREX, C.SYMBOL_CALC_MODE_CFDLEVERAGE)
        if self.margin_per_lot_ref > 0 and self.margin_ref_price > 0:
            m = self.margin_per_lot_ref * volume
            if price_prop and price > 0:
                m *= price / self.margin_ref_price
            if lev_dep and self.margin_ref_leverage > 0 and leverage > 0:
                m *= self.margin_ref_leverage / leverage
            return m
        cs = self.trade_contract_size
        rate = self.margin_rate if self.margin_rate > 0 else 1.0
        mode = self.trade_calc_mode
        if mode == C.SYMBOL_CALC_MODE_FOREX:
            m = volume * cs / max(leverage, 1) * rate
            # margin is in base currency; convert with price when profit ccy = deposit ccy
            return m * price if self.currency_base != self.currency_profit else m
        if mode == C.SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE:
            return volume * cs * rate * (price if self.currency_base != self.currency_profit else 1.0)
        if mode == C.SYMBOL_CALC_MODE_FUTURES:
            return volume * (self.margin_initial or 0.0)
        if mode == C.SYMBOL_CALC_MODE_CFDLEVERAGE:
            return volume * cs * price / max(leverage, 1) * rate
        # CFD, CFDINDEX, exchange modes
        return volume * cs * price * rate

    @property
    def hedged_factor(self) -> float:
        """Fraction of the hedged (smaller) leg that is still charged margin.

        MT5 stores the hedged margin as a contract size per lot; 0 is treated
        conservatively as "no hedge discount" (both legs charged in full)."""
        if self.margin_hedged <= 0 or self.trade_contract_size <= 0:
            return 1.0
        return max(0.0, min(1.0, self.margin_hedged / self.trade_contract_size))

    # ------------------------------------------------------------------
    @classmethod
    def from_mt5(cls, info: dict, **overrides) -> "SymbolSpec":
        """Build from ``mt5.symbol_info(sym)._asdict()``."""
        known = {f.name for f in fields(cls)}
        kw = {k: v for k, v in info.items() if k in known}
        extra = {k: v for k, v in info.items() if k not in known}
        kw.setdefault("name", info.get("name", "UNKNOWN"))
        kw["extra"] = extra
        kw.update(overrides)
        return cls(**kw)

    @classmethod
    def load(cls, path: str | Path) -> "SymbolSpec":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        known = {f.name for f in fields(cls)}
        extra = d.pop("extra", {}) or {}
        for k in list(d):
            if k not in known:
                extra[k] = d.pop(k)
        return cls(**d, extra=extra)

    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2, default=str)

    def get(self, prop: str, default=0):
        if hasattr(self, prop):
            return getattr(self, prop)
        return self.extra.get(prop, default)


@dataclass
class AccountSpec:
    deposit: float = 10000.0
    currency: str = "USD"
    leverage: int = 100
    margin_mode: int = C.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
    margin_so_call: float = 100.0   # percent
    margin_so_so: float = 50.0      # percent
    login: int = 0
    server: str = "Backtest"
    company: str = "UBT"
    name: str = "Universal Backtester"
