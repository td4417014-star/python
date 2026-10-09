"""Simulated MT5 trade server (hedging account).

Mirrors the MetaTrader 5 strategy tester rules that matter for EA parity:

* position ticket == ticket of the order that opened it (MT5 behaviour);
* on every tick pending orders and SL/TP are checked BEFORE the EA's OnTick;
* Buy positions close on Bid, Sell positions on Ask; Buy SL fires when
  Bid <= SL, Buy TP when Bid >= TP, Sell SL when Ask >= SL, Sell TP when Ask <= TP;
* Buy Stop fires on Ask >= price, Buy Limit on Ask <= price,
  Sell Stop on Bid <= price, Sell Limit on Bid >= price;
* limit orders / TP fill at the order price, stop orders / SL fill at the order
  price, or at the (worse) tick price when the market gapped through it;
* stop-level and freeze-level validation, volume validation, margin check,
  stop-out, swaps at rollover, commissions per deal.
"""
from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional

from ..mql5 import constants as C
from ..mql5.structs import MqlTradeRequest, MqlTradeResult
from ..mql5.records import Position, Order, Deal
from .symbol import SymbolSpec, AccountSpec


class _SymState:
    __slots__ = ("spec", "bid", "ask", "last", "time", "time_msc", "volume", "positions_dirty")

    def __init__(self, spec: SymbolSpec):
        self.spec = spec
        self.bid = 0.0
        self.ask = 0.0
        self.last = 0.0
        self.time = 0
        self.time_msc = 0
        self.volume = 0


class CostModel:
    """Trading costs that are not part of the MT5 symbol spec."""

    def __init__(self, commission_per_lot: float = 0.0, commission_pct: float = 0.0,
                 slippage_points: float = 0.0, spread_multiplier: float = 1.0,
                 extra_spread_points: float = 0.0, min_spread_points: float = 0.0):
        self.commission_per_lot = commission_per_lot   # per side, deposit currency
        self.commission_pct = commission_pct           # per side, % of notional
        self.slippage_points = slippage_points         # adverse slippage on market + stop fills
        self.spread_multiplier = spread_multiplier     # stress test: widen spread
        self.extra_spread_points = extra_spread_points
        self.min_spread_points = min_spread_points

    def as_dict(self):
        return dict(self.__dict__)


def _vol_ok(vol: float, spec: SymbolSpec) -> bool:
    if vol < spec.volume_min - 1e-9 or (spec.volume_max > 0 and vol > spec.volume_max + 1e-9):
        return False
    step = spec.volume_step if spec.volume_step > 0 else 0.01
    k = round(vol / step)
    return abs(k * step - vol) < step * 1e-4


class Broker:
    def __init__(self, account: AccountSpec, specs: Dict[str, SymbolSpec],
                 costs: Optional[CostModel] = None, gap_fill: str = "worse",
                 stop_out: bool = True, swaps: bool = True):
        self.account = account
        self.costs = costs or CostModel()
        self.gap_fill = gap_fill          # "worse" (MT5 real ticks) or "exact"
        self.stop_out_enabled = stop_out
        self.swaps_enabled = swaps
        self.sym: Dict[str, _SymState] = {n: _SymState(s) for n, s in specs.items()}

        self.balance = account.deposit
        self.credit = 0.0
        self.positions: List[Position] = []
        self.orders: List[Order] = []
        self.deals: List[Deal] = []
        self.history_orders: List[Order] = []
        self._ticket = 1          # shared counter for orders (positions inherit order tickets)
        self._deal_ticket = 1
        self.time = 0
        self.time_msc = 0
        self._last_day = None

        # equity statistics, updated every tick (MT5 measures equity DD per tick)
        self.equity = self.balance
        self.margin = 0.0
        self.peak_equity = self.balance
        self.min_equity = self.balance
        self.max_dd_money = 0.0
        self.max_dd_money_pct = 0.0   # % at the moment of the max money DD
        self.max_dd_rel_pct = 0.0
        self.max_dd_rel_money = 0.0
        self.min_margin_level = float("inf")
        self.stopped_out = False
        self.blown = False
        self.last_error = 0

        # balance deal #1 like MT5
        d = self._new_deal(None, C.DEAL_TYPE_BALANCE, C.DEAL_ENTRY_IN, 0.0, 0.0, "", 0, "", C.DEAL_REASON_CLIENT)
        d.profit = self.balance

    # ------------------------------------------------------------------ prices
    def spread_adjust(self, bid: float, ask: float, spec: SymbolSpec):
        c = self.costs
        if c.spread_multiplier == 1.0 and c.extra_spread_points == 0.0 and c.min_spread_points == 0.0:
            return bid, ask
        sp = (ask - bid) * c.spread_multiplier + c.extra_spread_points * spec.point
        sp = max(sp, c.min_spread_points * spec.point)
        mid = (ask + bid) / 2.0
        # keep Bid (chart price) and move Ask, like MT5 custom spread settings
        return bid, bid + sp if mid > 0 else ask

    def set_price(self, symbol: str, time_msc: int, bid: float, ask: float, last: float = 0.0, volume: int = 0):
        st = self.sym[symbol]
        st.bid, st.ask = self.spread_adjust(bid, ask, st.spec)
        st.last = last
        st.time_msc = time_msc
        st.time = time_msc // 1000
        st.volume = volume
        if time_msc > self.time_msc:
            self.time_msc = time_msc
            self.time = time_msc // 1000

    # ------------------------------------------------------------------ tick
    def on_tick(self, symbol: str, time_msc: int, bid: float, ask: float, last: float = 0.0, volume: int = 0):
        """Apply a new quote: rollover/swaps, pending orders, SL/TP, stop-out, equity stats."""
        self.set_price(symbol, time_msc, bid, ask, last, volume)
        if self.swaps_enabled:
            self._rollover()
        if self.orders:
            self._check_pending(symbol)
        if self.positions:
            self._check_sltp(symbol)
        self._update_equity()

    def _rollover(self):
        day = self.time // 86400
        if self._last_day is None:
            self._last_day = day
            return
        if day == self._last_day:
            return
        prev, self._last_day = self._last_day, day
        if not self.positions:
            return
        for d in range(prev + 1, day + 1):
            ended = _dt.datetime(1970, 1, 1) + _dt.timedelta(days=d - 1)
            wd = (ended.weekday() + 1) % 7          # MQL: 0=Sunday
            for p in self.positions:
                spec = self.sym[p.symbol].spec
                if not spec.weekend_trading and wd in (0, 6):
                    continue
                mult = 3 if (wd == spec.swap_rollover3days and not spec.weekend_trading) else 1
                p.swap += self._swap_value(p, spec) * mult

    def _swap_value(self, p: Position, spec: SymbolSpec) -> float:
        rate = spec.swap_long if p.type == C.POSITION_TYPE_BUY else spec.swap_short
        mode = spec.swap_mode
        if mode == C.SYMBOL_SWAP_MODE_DISABLED or rate == 0:
            return 0.0
        if mode == C.SYMBOL_SWAP_MODE_POINTS:
            return rate * spec.point / spec.trade_tick_size * spec.trade_tick_value * p.volume
        if mode in (C.SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT, C.SYMBOL_SWAP_MODE_CURRENCY_SYMBOL,
                    C.SYMBOL_SWAP_MODE_CURRENCY_MARGIN):
            return rate * p.volume
        if mode in (C.SYMBOL_SWAP_MODE_INTEREST_CURRENT, C.SYMBOL_SWAP_MODE_INTEREST_OPEN):
            st = self.sym[p.symbol]
            price = (st.bid if mode == C.SYMBOL_SWAP_MODE_INTEREST_CURRENT else p.price_open)
            # value of the position in deposit currency via tick value
            notional = price / spec.trade_tick_size * spec.trade_tick_value * p.volume
            return notional * rate / 100.0 / 360.0
        return 0.0

    def _check_pending(self, symbol: str):
        st = self.sym[symbol]
        bid, ask = st.bid, st.ask
        for o in list(self.orders):
            if o.symbol != symbol:
                continue
            t = o.type
            if o.type_time == C.ORDER_TIME_SPECIFIED and o.time_expiration and self.time >= o.time_expiration:
                self._finish_order(o, C.ORDER_STATE_EXPIRED)
                continue
            fire = False
            fill = o.price_open
            if t == C.ORDER_TYPE_BUY_STOP:
                fire = ask >= o.price_open
                if fire and self.gap_fill == "worse":
                    fill = max(o.price_open, ask)
            elif t == C.ORDER_TYPE_BUY_LIMIT:
                fire = ask <= o.price_open
            elif t == C.ORDER_TYPE_SELL_STOP:
                fire = bid <= o.price_open
                if fire and self.gap_fill == "worse":
                    fill = min(o.price_open, bid)
            elif t == C.ORDER_TYPE_SELL_LIMIT:
                fire = bid >= o.price_open
            if not fire:
                continue
            ptype = C.POSITION_TYPE_BUY if t in (C.ORDER_TYPE_BUY_STOP, C.ORDER_TYPE_BUY_LIMIT) else C.POSITION_TYPE_SELL
            if t in (C.ORDER_TYPE_BUY_STOP, C.ORDER_TYPE_SELL_STOP) and self.costs.slippage_points:
                sl_pts = self.costs.slippage_points * st.spec.point
                fill = fill + sl_pts if ptype == C.POSITION_TYPE_BUY else fill - sl_pts
            # margin check at activation
            if not self._margin_ok(symbol, ptype, o.volume_current, fill):
                self._finish_order(o, C.ORDER_STATE_REJECTED)
                continue
            self.orders.remove(o)
            o.state = C.ORDER_STATE_FILLED
            o.time_done = self.time
            self.history_orders.append(o)
            self._open_position(o.ticket, symbol, ptype, o.volume_current, fill, o.sl, o.tp,
                                o.magic, o.comment, C.DEAL_REASON_EXPERT)

    def _check_sltp(self, symbol: str):
        st = self.sym[symbol]
        bid, ask = st.bid, st.ask
        gap_worse = self.gap_fill == "worse"
        hits = []
        for p in self.positions:
            if p.symbol != symbol:
                continue
            if p.type == C.POSITION_TYPE_BUY:
                if p.sl > 0 and bid <= p.sl:
                    hits.append((p, min(p.sl, bid) if gap_worse else p.sl, C.DEAL_REASON_SL))
                elif p.tp > 0 and bid >= p.tp:
                    hits.append((p, p.tp, C.DEAL_REASON_TP))
            else:
                if p.sl > 0 and ask >= p.sl:
                    hits.append((p, max(p.sl, ask) if gap_worse else p.sl, C.DEAL_REASON_SL))
                elif p.tp > 0 and ask <= p.tp:
                    hits.append((p, p.tp, C.DEAL_REASON_TP))
        for p, price, reason in hits:
            if reason == C.DEAL_REASON_SL and self.costs.slippage_points:
                s = self.costs.slippage_points * st.spec.point
                price = price - s if p.type == C.POSITION_TYPE_BUY else price + s
            tag = "[sl " if reason == C.DEAL_REASON_SL else "[tp "
            self._close_position(p, p.volume, price, reason, f"{tag}{p.sl if reason == C.DEAL_REASON_SL else p.tp}]")

    # ------------------------------------------------------------------ equity / margin
    def floating(self) -> float:
        tot = 0.0
        for p in self.positions:
            st = self.sym[p.symbol]
            price = st.bid if p.type == C.POSITION_TYPE_BUY else st.ask
            p.price_current = price
            p.profit = st.spec.profit(p.type, p.volume, p.price_open, price)
            tot += p.profit + p.swap
        return tot

    def calc_margin(self, extra: Optional[tuple] = None) -> float:
        per = {}
        for p in self.positions:
            k = p.symbol
            b, s = per.get(k, (0.0, 0.0))
            if p.type == C.POSITION_TYPE_BUY:
                b += p.volume
            else:
                s += p.volume
            per[k] = (b, s)
        if extra:
            sym, ptype, vol = extra
            b, s = per.get(sym, (0.0, 0.0))
            per[sym] = (b + vol, s) if ptype == C.POSITION_TYPE_BUY else (b, s + vol)
        total = 0.0
        lev = self.account.leverage
        for sym, (b, s) in per.items():
            st = self.sym[sym]
            spec = st.spec
            hedged = min(b, s)
            hf = spec.hedged_factor
            if hedged <= 0 or hf >= 1.0:
                total += spec.margin(b, st.ask, lev) + spec.margin(s, st.bid, lev)
            else:
                # net (unhedged) part of the larger leg in full, both hedged legs at the factor
                net_price = st.ask if b >= s else st.bid
                total += spec.margin(abs(b - s), net_price, lev)
                total += hf * 2.0 * spec.margin(hedged, (st.ask + st.bid) / 2.0, lev)
        return total

    def _margin_ok(self, symbol: str, ptype: int, volume: float, price: float) -> bool:
        need = self.calc_margin((symbol, ptype, volume))
        equity = self.balance + self.credit + self.floating()
        return equity - need >= 0.0

    def _update_equity(self):
        eq = self.balance + self.credit + (self.floating() if self.positions else 0.0)
        self.equity = eq
        if self.positions:
            self.margin = self.calc_margin()
            if self.margin > 0:
                ml = eq / self.margin * 100.0
                if ml < self.min_margin_level:
                    self.min_margin_level = ml
                so_hit = (eq <= self.account.margin_so_so if self.account.margin_so_mode == 1
                          else ml <= self.account.margin_so_so)
                if self.stop_out_enabled and so_hit:
                    self._stop_out()
                    eq = self.equity
        else:
            self.margin = 0.0
        if eq > self.peak_equity:
            self.peak_equity = eq
        if eq < self.min_equity:
            self.min_equity = eq
        dd = self.peak_equity - eq
        if dd > self.max_dd_money:
            self.max_dd_money = dd
            self.max_dd_money_pct = dd / self.peak_equity * 100.0 if self.peak_equity > 0 else 0.0
        if self.peak_equity > 0:
            rel = dd / self.peak_equity * 100.0
            if rel > self.max_dd_rel_pct:
                self.max_dd_rel_pct = rel
                self.max_dd_rel_money = dd
        if eq <= 0 and not self.blown:
            self.blown = True

    def _stop_out(self):
        self.stopped_out = True
        while self.positions:
            self.floating()
            worst = min(self.positions, key=lambda p: p.profit + p.swap)
            st = self.sym[worst.symbol]
            price = st.bid if worst.type == C.POSITION_TYPE_BUY else st.ask
            self._close_position(worst, worst.volume, price, C.DEAL_REASON_SO, "so")
            eq = self.balance + self.credit + self.floating()
            self.equity = eq
            m = self.calc_margin()
            level_ok = (eq > self.account.margin_so_so if self.account.margin_so_mode == 1
                        else m <= 0 or eq / m * 100.0 > self.account.margin_so_so)
            if m <= 0 or level_ok:
                break
        # MT5 keeps pending orders on stop-out

    # ------------------------------------------------------------------ internals
    def _next_ticket(self) -> int:
        self._ticket += 1
        return self._ticket

    def _commission(self, spec: SymbolSpec, volume: float, price: float) -> float:
        c = self.costs
        com = c.commission_per_lot * volume
        if c.commission_pct:
            notional = price / spec.trade_tick_size * spec.trade_tick_value * volume
            com += notional * c.commission_pct / 100.0
        return -abs(com)

    def _new_deal(self, order: Optional[int], dtype: int, entry: int, volume: float, price: float,
                  symbol: str, magic: int, comment: str, reason: int, position_id: int = 0) -> Deal:
        self._deal_ticket += 1
        d = Deal()
        d.ticket = self._deal_ticket
        d.order = order or 0
        d.position_id = position_id
        d.symbol = symbol
        d.type = dtype
        d.entry = entry
        d.volume = volume
        d.price = price
        d.profit = 0.0
        d.commission = 0.0
        d.swap = 0.0
        d.time = self.time
        d.time_msc = self.time_msc
        d.magic = magic
        d.comment = comment
        d.reason = reason
        d.balance = self.balance
        d.equity = self.equity
        self.deals.append(d)
        return d

    def _open_position(self, ticket: int, symbol: str, ptype: int, volume: float, price: float,
                       sl: float, tp: float, magic: int, comment: str, reason: int) -> Position:
        spec = self.sym[symbol].spec
        p = Position()
        p.ticket = ticket
        p.identifier = ticket
        p.symbol = symbol
        p.type = ptype
        p.volume = volume
        p.price_open = price
        p.sl = sl
        p.tp = tp
        p.time = self.time
        p.time_msc = self.time_msc
        p.time_update = self.time
        p.magic = magic
        p.comment = comment
        p.swap = 0.0
        p.commission = 0.0
        p.price_current = price
        p.profit = 0.0
        p.reason = reason
        self.positions.append(p)
        d = self._new_deal(ticket, C.DEAL_TYPE_BUY if ptype == C.POSITION_TYPE_BUY else C.DEAL_TYPE_SELL,
                           C.DEAL_ENTRY_IN, volume, price, symbol, magic, comment, reason, ticket)
        d.commission = self._commission(spec, volume, price)
        self.balance += d.commission
        d.balance = self.balance
        return p

    def _close_position(self, p: Position, volume: float, price: float, reason: int, comment: str,
                        order_ticket: Optional[int] = None, magic: Optional[int] = None) -> Deal:
        spec = self.sym[p.symbol].spec
        volume = min(volume, p.volume)
        profit = spec.profit(p.type, volume, p.price_open, price)
        frac = volume / p.volume if p.volume > 0 else 1.0
        swap = p.swap * frac
        dtype = C.DEAL_TYPE_SELL if p.type == C.POSITION_TYPE_BUY else C.DEAL_TYPE_BUY
        if order_ticket is None:
            order_ticket = self._next_ticket()
            o = Order()
            o.ticket = order_ticket
            o.symbol = p.symbol
            o.type = C.ORDER_TYPE_SELL if p.type == C.POSITION_TYPE_BUY else C.ORDER_TYPE_BUY
            o.volume_initial = o.volume_current = volume
            o.price_open = price
            o.sl = o.tp = 0.0
            o.time_setup = o.time_done = self.time
            o.time_setup_msc = self.time_msc
            o.time_expiration = 0
            o.type_filling = C.ORDER_FILLING_FOK
            o.type_time = C.ORDER_TIME_GTC
            o.magic = p.magic if magic is None else magic
            o.comment = comment
            o.state = C.ORDER_STATE_FILLED
            o.position_id = p.ticket
            o.price_current = price
            o.stoplimit = 0.0
            self.history_orders.append(o)
        d = self._new_deal(order_ticket, dtype, C.DEAL_ENTRY_OUT, volume, price, p.symbol,
                           p.magic if magic is None else magic, comment, reason, p.ticket)
        d.profit = profit
        d.swap = swap
        d.commission = self._commission(spec, volume, price)
        self.balance += profit + swap + d.commission
        d.balance = self.balance
        p.swap -= swap
        p.volume = round(p.volume - volume, 8)
        if p.volume <= 1e-12:
            self.positions.remove(p)
        self.equity = self.balance + self.credit + (self.floating() if self.positions else 0.0)
        d.equity = self.equity
        return d

    def _finish_order(self, o: Order, state: int):
        if o in self.orders:
            self.orders.remove(o)
        o.state = state
        o.time_done = self.time
        self.history_orders.append(o)

    # ------------------------------------------------------------------ lookup
    def position_by_ticket(self, ticket: int) -> Optional[Position]:
        for p in self.positions:
            if p.ticket == ticket:
                return p
        return None

    def order_by_ticket(self, ticket: int) -> Optional[Order]:
        for o in self.orders:
            if o.ticket == ticket:
                return o
        return None

    # ------------------------------------------------------------------ validation helpers
    def _stops_ok_position(self, st: _SymState, ptype: int, sl: float, tp: float) -> bool:
        spec = st.spec
        lvl = spec.trade_stops_level * spec.point
        if ptype == C.POSITION_TYPE_BUY:
            if sl > 0 and not (st.bid - sl >= lvl - 1e-12):
                return False
            if tp > 0 and not (tp - st.bid >= lvl - 1e-12):
                return False
        else:
            if sl > 0 and not (sl - st.ask >= lvl - 1e-12):
                return False
            if tp > 0 and not (st.ask - tp >= lvl - 1e-12):
                return False
        return True

    def _frozen_position(self, st: _SymState, p: Position) -> bool:
        spec = st.spec
        fl = spec.trade_freeze_level * spec.point
        if fl <= 0:
            return False
        if p.type == C.POSITION_TYPE_BUY:
            return (p.sl > 0 and st.bid - p.sl < fl) or (p.tp > 0 and p.tp - st.bid < fl)
        return (p.sl > 0 and p.sl - st.ask < fl) or (p.tp > 0 and st.ask - p.tp < fl)

    def _pending_price_ok(self, st: _SymState, otype: int, price: float, sl: float, tp: float) -> int:
        spec = st.spec
        lvl = spec.trade_stops_level * spec.point
        eps = 1e-12
        if otype == C.ORDER_TYPE_BUY_LIMIT:
            ok = st.ask - price >= lvl - eps
        elif otype == C.ORDER_TYPE_BUY_STOP:
            ok = price - st.ask >= lvl - eps
        elif otype == C.ORDER_TYPE_SELL_LIMIT:
            ok = price - st.bid >= lvl - eps
        elif otype == C.ORDER_TYPE_SELL_STOP:
            ok = st.bid - price >= lvl - eps
        else:
            return C.TRADE_RETCODE_INVALID_ORDER
        if not ok:
            return C.TRADE_RETCODE_INVALID_PRICE
        buy = otype in (C.ORDER_TYPE_BUY_LIMIT, C.ORDER_TYPE_BUY_STOP)
        if sl > 0 and not ((price - sl if buy else sl - price) >= lvl - eps):
            return C.TRADE_RETCODE_INVALID_STOPS
        if tp > 0 and not ((tp - price if buy else price - tp) >= lvl - eps):
            return C.TRADE_RETCODE_INVALID_STOPS
        return 0

    # ------------------------------------------------------------------ OrderSend
    def order_send(self, req: MqlTradeRequest, res: MqlTradeResult) -> bool:
        res.clear()
        sym = req.symbol
        a = req.action
        if a in (C.TRADE_ACTION_REMOVE, C.TRADE_ACTION_MODIFY):
            o = self.order_by_ticket(req.order)
            if o is None:
                return self._fail(res, C.TRADE_RETCODE_INVALID_ORDER)
            sym = o.symbol
        if a == C.TRADE_ACTION_SLTP and not sym and req.position:
            p = self.position_by_ticket(req.position)
            sym = p.symbol if p else ""
        st = self.sym.get(sym)
        if st is None:
            return self._fail(res, C.TRADE_RETCODE_INVALID)
        res.bid, res.ask = st.bid, st.ask
        spec = st.spec
        if spec.trade_mode == 0:
            return self._fail(res, C.TRADE_RETCODE_TRADE_DISABLED)

        if a == C.TRADE_ACTION_DEAL:
            return self._action_deal(req, res, st)
        if a == C.TRADE_ACTION_PENDING:
            return self._action_pending(req, res, st)
        if a == C.TRADE_ACTION_SLTP:
            return self._action_sltp(req, res, st)
        if a == C.TRADE_ACTION_MODIFY:
            return self._action_modify(req, res, st)
        if a == C.TRADE_ACTION_REMOVE:
            o = self.order_by_ticket(req.order)
            self._finish_order(o, C.ORDER_STATE_CANCELED)
            res.retcode = C.TRADE_RETCODE_DONE
            res.order = o.ticket
            return True
        if a == C.TRADE_ACTION_CLOSE_BY:
            return self._action_close_by(req, res, st)
        return self._fail(res, C.TRADE_RETCODE_INVALID)

    def _fail(self, res: MqlTradeResult, code: int) -> bool:
        res.retcode = code
        res.comment = C.RETCODE_TEXT.get(code, "error")
        return False

    def _action_deal(self, req, res, st: _SymState) -> bool:
        spec = st.spec
        if req.type not in (C.ORDER_TYPE_BUY, C.ORDER_TYPE_SELL):
            return self._fail(res, C.TRADE_RETCODE_INVALID)
        vol = float(req.volume)
        if not _vol_ok(vol, spec):
            return self._fail(res, C.TRADE_RETCODE_INVALID_VOLUME)
        buy = req.type == C.ORDER_TYPE_BUY
        price = st.ask if buy else st.bid
        if self.costs.slippage_points:
            s = self.costs.slippage_points * spec.point
            price = price + s if buy else price - s

        if req.position:   # close (part of) a position
            p = self.position_by_ticket(req.position)
            if p is None:
                return self._fail(res, C.TRADE_RETCODE_POSITION_CLOSED)
            if (p.type == C.POSITION_TYPE_BUY) == buy:
                return self._fail(res, C.TRADE_RETCODE_INVALID)
            if vol > p.volume + 1e-9:
                return self._fail(res, C.TRADE_RETCODE_INVALID_CLOSE_VOLUME)
            order_ticket = self._next_ticket()
            self._record_market_order(order_ticket, req, price, p.ticket)
            d = self._close_position(p, vol, price, C.DEAL_REASON_EXPERT, req.comment, order_ticket, req.magic)
            res.retcode = C.TRADE_RETCODE_DONE
            res.order = order_ticket
            res.deal = d.ticket
            res.volume = vol
            res.price = price
            res.comment = "Request executed"
            return True

        ptype = C.POSITION_TYPE_BUY if buy else C.POSITION_TYPE_SELL
        if (req.sl or req.tp) and not self._stops_ok_position(st, ptype, req.sl, req.tp):
            return self._fail(res, C.TRADE_RETCODE_INVALID_STOPS)
        if not self._margin_ok(req.symbol, ptype, vol, price):
            return self._fail(res, C.TRADE_RETCODE_NO_MONEY)
        ticket = self._next_ticket()
        self._record_market_order(ticket, req, price, ticket)
        self._open_position(ticket, req.symbol, ptype, vol, price, float(req.sl or 0.0),
                            float(req.tp or 0.0), req.magic, req.comment, C.DEAL_REASON_EXPERT)
        self._update_equity()
        res.retcode = C.TRADE_RETCODE_DONE
        res.order = ticket
        res.deal = self._deal_ticket
        res.volume = vol
        res.price = price
        res.comment = "Request executed"
        return True

    def _record_market_order(self, ticket, req, price, position_id):
        o = Order()
        o.ticket = ticket
        o.symbol = req.symbol
        o.type = req.type
        o.volume_initial = o.volume_current = float(req.volume)
        o.price_open = price
        o.sl = float(req.sl or 0.0)
        o.tp = float(req.tp or 0.0)
        o.time_setup = o.time_done = self.time
        o.time_setup_msc = self.time_msc
        o.time_expiration = 0
        o.type_filling = req.type_filling
        o.type_time = req.type_time
        o.magic = req.magic
        o.comment = req.comment
        o.state = C.ORDER_STATE_FILLED
        o.position_id = position_id
        o.price_current = price
        o.stoplimit = 0.0
        self.history_orders.append(o)

    def _action_pending(self, req, res, st: _SymState) -> bool:
        spec = st.spec
        vol = float(req.volume)
        if not _vol_ok(vol, spec):
            return self._fail(res, C.TRADE_RETCODE_INVALID_VOLUME)
        if req.type in (C.ORDER_TYPE_BUY_STOP_LIMIT, C.ORDER_TYPE_SELL_STOP_LIMIT):
            return self._fail(res, C.TRADE_RETCODE_INVALID_ORDER)   # not emulated
        code = self._pending_price_ok(st, req.type, float(req.price), float(req.sl or 0), float(req.tp or 0))
        if code:
            return self._fail(res, code)
        o = Order()
        o.ticket = self._next_ticket()
        o.symbol = req.symbol
        o.type = req.type
        o.volume_initial = o.volume_current = vol
        o.price_open = float(req.price)
        o.sl = float(req.sl or 0.0)
        o.tp = float(req.tp or 0.0)
        o.time_setup = self.time
        o.time_setup_msc = self.time_msc
        o.time_expiration = int(req.expiration or 0)
        o.type_filling = req.type_filling
        o.type_time = req.type_time
        o.magic = req.magic
        o.comment = req.comment
        o.state = C.ORDER_STATE_PLACED
        o.position_id = 0
        o.price_current = st.ask if req.type in (C.ORDER_TYPE_BUY_LIMIT, C.ORDER_TYPE_BUY_STOP) else st.bid
        o.time_done = 0
        o.stoplimit = 0.0
        self.orders.append(o)
        res.retcode = C.TRADE_RETCODE_DONE
        res.order = o.ticket
        res.volume = vol
        res.price = o.price_open
        res.comment = "Request executed"
        return True

    def _action_sltp(self, req, res, st: _SymState) -> bool:
        p = self.position_by_ticket(req.position)
        if p is None:
            return self._fail(res, C.TRADE_RETCODE_POSITION_CLOSED)
        sl = float(req.sl or 0.0)
        tp = float(req.tp or 0.0)
        pt = st.spec.point
        if abs(sl - p.sl) < pt * 1e-3 and abs(tp - p.tp) < pt * 1e-3:
            return self._fail(res, C.TRADE_RETCODE_NO_CHANGES)
        if self._frozen_position(st, p):
            return self._fail(res, C.TRADE_RETCODE_FROZEN)
        if not self._stops_ok_position(st, p.type, sl, tp):
            return self._fail(res, C.TRADE_RETCODE_INVALID_STOPS)
        p.sl = sl
        p.tp = tp
        p.time_update = self.time
        res.retcode = C.TRADE_RETCODE_DONE
        res.order = 0
        res.comment = "Request executed"
        return True

    def _action_modify(self, req, res, st: _SymState) -> bool:
        o = self.order_by_ticket(req.order)
        price = float(req.price) if req.price else o.price_open
        sl = float(req.sl or 0.0)
        tp = float(req.tp or 0.0)
        pt = st.spec.point
        if abs(price - o.price_open) < pt * 1e-3 and abs(sl - o.sl) < pt * 1e-3 and abs(tp - o.tp) < pt * 1e-3:
            return self._fail(res, C.TRADE_RETCODE_NO_CHANGES)
        code = self._pending_price_ok(st, o.type, price, sl, tp)
        if code:
            return self._fail(res, code)
        o.price_open, o.sl, o.tp = price, sl, tp
        if req.expiration:
            o.time_expiration = int(req.expiration)
        res.retcode = C.TRADE_RETCODE_DONE
        res.order = o.ticket
        return True

    def _action_close_by(self, req, res, st: _SymState) -> bool:
        p1 = self.position_by_ticket(req.position)
        p2 = self.position_by_ticket(req.position_by)
        if p1 is None or p2 is None or p1.type == p2.type or p1.symbol != p2.symbol:
            return self._fail(res, C.TRADE_RETCODE_INVALID)
        vol = min(p1.volume, p2.volume)
        # close both at p2's open price (MT5 close-by semantics: no spread paid)
        price = p2.price_open
        t = self._next_ticket()
        self._close_position(p1, vol, price, C.DEAL_REASON_EXPERT, req.comment, t, req.magic)
        self._close_position(p2, vol, price, C.DEAL_REASON_EXPERT, req.comment, t, req.magic)
        res.retcode = C.TRADE_RETCODE_DONE
        res.order = t
        return True
