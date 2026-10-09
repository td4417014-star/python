"""MQL5 function emulation.

A ported EA does ``from ubt.mql5 import *`` and calls these functions exactly
as in MQL5 (``PositionsTotal()``, ``OrderSend(req, res)``, ``CopyBuffer(...)``,
...). They operate on the terminal activated by the backtest runner.

Differences from MQL5 that a port has to respect:
* output arrays are Python lists passed in and filled in place; pass
  ``as_series=True`` where the MQL code called ``ArraySetAsSeries(arr, true)``;
* ``_Symbol``/``_Period``/``_Point``/``_Digits`` are the functions
  ``Symbol()``, ``Period()``, ``Point()``, ``Digits()``.
"""
from __future__ import annotations

import math as _m
import datetime as _dt

from . import constants as C
from .structs import MqlTradeRequest, MqlTradeResult, MqlTick, MqlRates

_T = None   # active Terminal

from operator import attrgetter as _attrgetter
from .records import Position as _Position, Order as _Order
_POS_GET = _attrgetter(*_Position.__slots__)
_POS_IDX = {k: i for i, k in enumerate(_Position.__slots__)}
_ORD_GET = _attrgetter(*_Order.__slots__)
_ORD_IDX = {k: i for i, k in enumerate(_Order.__slots__)}


def _activate(term):
    global _T
    _T = term


def _term():
    return _T


# ====================================================================== chart / info
def Symbol():
    return _T.chart_symbol


def Period():
    return _T.chart_period


def Point():
    return _T.broker.sym[_T.chart_symbol].spec.point


def Digits():
    return _T.broker.sym[_T.chart_symbol].spec.digits


MQL_TESTER = "tester"
MQL_OPTIMIZATION = "optimization"
MQL_VISUAL_MODE = "visual"


def MQLInfoInteger(prop):
    return 1 if prop == MQL_TESTER else 0


def IsStopped():
    return _T.stopped


def PeriodSeconds(tf=C.PERIOD_CURRENT):
    if tf == C.PERIOD_CURRENT:
        tf = _T.chart_period
    return C.TIMEFRAME_SECONDS[tf]


# ====================================================================== errors
def GetLastError():
    return _T.last_error


def ResetLastError():
    _T.last_error = 0


def SetUserError(code):
    _T.last_error = 65536 + code


# ====================================================================== output
def Print(*args):
    _T.print(*args)


def PrintFormat(fmt, *args):
    try:
        _T.print(fmt % args)
    except Exception:
        _T.print(fmt, *args)


def Alert(*args):
    _T.print("ALERT: ", *args)


def Comment(*args):
    _T.comment = "".join(str(a) for a in args)


# ====================================================================== math / conversion
def NormalizeDouble(value, digits):
    m = 10.0 ** digits
    v = value * m
    return (_m.floor(v + 0.5) if v >= 0 else -_m.floor(-v + 0.5)) / m


def DoubleToString(value, digits=8):
    return f"{value:.{int(digits)}f}"


def IntegerToString(value, str_len=0, fill=" "):
    s = str(int(value))
    return s.rjust(str_len, fill) if str_len else s


def StringToDouble(s):
    try:
        return float(str(s).strip())
    except ValueError:
        return 0.0


def StringToInteger(s):
    try:
        return int(float(str(s).strip()))
    except ValueError:
        return 0


def TimeToString(t, flags=3):
    return _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=int(t))


MathAbs = abs
MathMax = max
MathMin = min
MathPow = pow
MathSqrt = _m.sqrt
MathFloor = _m.floor
MathCeil = _m.ceil
MathLog = _m.log
MathLog10 = _m.log10
MathExp = _m.exp


def MathRound(x):
    return float(_m.floor(x + 0.5)) if x >= 0 else -float(_m.floor(-x + 0.5))


# ====================================================================== time
def TimeCurrent():
    return _T.broker.time


TimeTradeServer = TimeCurrent
TimeLocal = TimeCurrent
TimeGMT = TimeCurrent


def GetTickCount():
    return _T.broker.time_msc & 0xFFFFFFFF


def GetTickCount64():
    return _T.broker.time_msc


def GetMicrosecondCount():
    return _T.broker.time_msc * 1000


def Sleep(ms):
    return None   # the tester does not wait


# ====================================================================== timer
def EventSetMillisecondTimer(ms):
    _T.timer_ms = int(ms)
    _T.next_timer_msc = _T.broker.time_msc + int(ms)
    return True


def EventSetTimer(sec):
    return EventSetMillisecondTimer(int(sec) * 1000)


def EventKillTimer():
    _T.timer_ms = 0


# ====================================================================== symbols
def SymbolSelect(name, select=True):
    if name in _T.broker.sym:
        return True
    _T.last_error = C.ERR_MARKET_UNKNOWN_SYMBOL
    return False


def SymbolsTotal(selected=True):
    return len(_T.broker.sym)


def _symstate(sym):
    st = _T.broker.sym.get(sym)
    if st is None:
        _T.last_error = C.ERR_MARKET_UNKNOWN_SYMBOL
    return st


def SymbolInfoDouble(sym, prop):
    st = _symstate(sym)
    if st is None:
        return 0.0
    if prop == C.SYMBOL_BID:
        return st.bid
    if prop == C.SYMBOL_ASK:
        return st.ask
    if prop == C.SYMBOL_LAST:
        return st.last
    return float(st.spec.get(prop, 0.0))


def SymbolInfoInteger(sym, prop):
    st = _symstate(sym)
    if st is None:
        return 0
    if prop == C.SYMBOL_SPREAD:
        return int(round((st.ask - st.bid) / st.spec.point))
    if prop == C.SYMBOL_TIME:
        return st.time
    if prop in (C.SYMBOL_SELECT, C.SYMBOL_VISIBLE):
        return 1
    v = st.spec.get(prop, 0)
    return int(v) if not isinstance(v, str) else 0


def SymbolInfoString(sym, prop):
    st = _symstate(sym)
    if st is None:
        return ""
    return str(st.spec.get(prop, ""))


def SymbolInfoTick(sym, tick: MqlTick):
    st = _symstate(sym)
    if st is None or st.time_msc == 0:
        return False
    tick.time = st.time
    tick.time_msc = st.time_msc
    tick.bid = st.bid
    tick.ask = st.ask
    tick.last = st.last
    tick.volume = st.volume
    return True


# ====================================================================== account
def AccountInfoDouble(prop):
    b = _T.broker
    if prop == C.ACCOUNT_BALANCE:
        return b.balance
    if prop == C.ACCOUNT_CREDIT:
        return b.credit
    fl = b.floating() if b.positions else 0.0
    eq = b.balance + b.credit + fl
    if prop == C.ACCOUNT_EQUITY:
        return eq
    if prop == C.ACCOUNT_PROFIT:
        return fl
    margin = b.calc_margin() if b.positions else 0.0
    if prop == C.ACCOUNT_MARGIN:
        return margin
    if prop == C.ACCOUNT_MARGIN_FREE:
        return eq - margin
    if prop == C.ACCOUNT_MARGIN_LEVEL:
        return eq / margin * 100.0 if margin > 0 else 0.0
    if prop == C.ACCOUNT_MARGIN_SO_CALL:
        return b.account.margin_so_call
    if prop == C.ACCOUNT_MARGIN_SO_SO:
        return b.account.margin_so_so
    return 0.0


def AccountInfoInteger(prop):
    a = _T.broker.account
    if prop == C.ACCOUNT_LEVERAGE:
        return a.leverage
    if prop == C.ACCOUNT_LOGIN:
        return a.login
    if prop == C.ACCOUNT_MARGIN_MODE:
        return a.margin_mode
    if prop in (C.ACCOUNT_TRADE_ALLOWED, C.ACCOUNT_TRADE_EXPERT):
        return 1
    return 0


def AccountInfoString(prop):
    a = _T.broker.account
    return {C.ACCOUNT_CURRENCY: a.currency, C.ACCOUNT_COMPANY: a.company,
            C.ACCOUNT_SERVER: a.server, C.ACCOUNT_NAME: a.name}.get(prop, "")


# ====================================================================== positions
def _select_position(p):
    """MQL5 copies position data into the program at selection time (snapshot tuple)."""
    st = _T.broker.sym[p.symbol]
    price = st.bid if p.type == C.POSITION_TYPE_BUY else st.ask
    p.price_current = price
    p.profit = st.spec.profit(p.type, p.volume, p.price_open, price)
    _T.sel_pos = _POS_GET(p)


def PositionsTotal():
    return len(_T.broker.positions)


def PositionGetTicket(index):
    ps = _T.broker.positions
    if 0 <= index < len(ps):
        _select_position(ps[index])
        return ps[index].ticket
    _T.last_error = C.ERR_TRADE_POSITION_NOT_FOUND
    return 0


def PositionGetSymbol(index):
    ps = _T.broker.positions
    if 0 <= index < len(ps):
        _select_position(ps[index])
        return ps[index].symbol
    _T.last_error = C.ERR_TRADE_POSITION_NOT_FOUND
    return ""


def PositionSelect(symbol):
    for p in _T.broker.positions:
        if p.symbol == symbol:
            _select_position(p)
            return True
    _T.last_error = C.ERR_TRADE_POSITION_NOT_FOUND
    return False


def PositionSelectByTicket(ticket):
    p = _T.broker.position_by_ticket(ticket)
    if p is None:
        _T.last_error = C.ERR_TRADE_POSITION_NOT_FOUND
        return False
    _select_position(p)
    return True


def PositionGetDouble(prop):
    p = _T.sel_pos
    i = _POS_IDX.get(prop)
    return float(p[i]) if p is not None and i is not None else 0.0


def PositionGetInteger(prop):
    p = _T.sel_pos
    i = _POS_IDX.get(prop)
    return int(p[i]) if p is not None and i is not None else 0


def PositionGetString(prop):
    p = _T.sel_pos
    i = _POS_IDX.get(prop)
    return str(p[i]) if p is not None and i is not None else ""


# ====================================================================== orders
def OrdersTotal():
    return len(_T.broker.orders)


def OrderGetTicket(index):
    os_ = _T.broker.orders
    if 0 <= index < len(os_):
        _T.sel_ord = _ORD_GET(os_[index])
        return os_[index].ticket
    _T.last_error = C.ERR_TRADE_ORDER_NOT_FOUND
    return 0


def OrderSelect(ticket):
    o = _T.broker.order_by_ticket(ticket)
    if o is None:
        _T.last_error = C.ERR_TRADE_ORDER_NOT_FOUND
        return False
    _T.sel_ord = _ORD_GET(o)
    return True


def OrderGetDouble(prop):
    o = _T.sel_ord
    i = _ORD_IDX.get(prop)
    return float(o[i]) if o is not None and i is not None else 0.0


def OrderGetInteger(prop):
    o = _T.sel_ord
    i = _ORD_IDX.get(prop)
    return int(o[i]) if o is not None and i is not None else 0


def OrderGetString(prop):
    o = _T.sel_ord
    i = _ORD_IDX.get(prop)
    return str(o[i]) if o is not None and i is not None else ""


def OrderSend(request: MqlTradeRequest, result: MqlTradeResult):
    ok = _T.broker.order_send(request, result)
    if not ok:
        _T.last_error = C.ERR_TRADE_SEND_FAILED
    return ok


def OrderCheck(request, check_result):
    return True


# ====================================================================== history
def HistorySelect(from_date, to_date):
    b = _T.broker
    _T.hist_deals = [d for d in b.deals if from_date <= d.time <= to_date]
    _T.hist_orders = [o for o in b.history_orders if from_date <= o.time_setup <= to_date]
    return True


def HistorySelectByPosition(position_id):
    b = _T.broker
    _T.hist_deals = [d for d in b.deals if d.position_id == position_id]
    _T.hist_orders = [o for o in b.history_orders if o.position_id == position_id]
    return True


def HistoryDealsTotal():
    return len(_T.hist_deals)


def HistoryDealGetTicket(index):
    if 0 <= index < len(_T.hist_deals):
        return _T.hist_deals[index].ticket
    return 0


def _deal(ticket):
    for d in reversed(_T.broker.deals):
        if d.ticket == ticket:
            return d
    _T.last_error = C.ERR_TRADE_DEAL_NOT_FOUND
    return None


def HistoryDealSelect(ticket):
    return _deal(ticket) is not None


def HistoryDealGetDouble(ticket, prop):
    d = _deal(ticket)
    return float(getattr(d, prop, 0.0)) if d else 0.0


def HistoryDealGetInteger(ticket, prop):
    d = _deal(ticket)
    return int(getattr(d, prop, 0)) if d else 0


def HistoryDealGetString(ticket, prop):
    d = _deal(ticket)
    return str(getattr(d, prop, "")) if d else ""


def HistoryOrdersTotal():
    return len(_T.hist_orders)


def HistoryOrderGetTicket(index):
    if 0 <= index < len(_T.hist_orders):
        return _T.hist_orders[index].ticket
    return 0


# ====================================================================== series access
def _series(sym, tf):
    s = _T.series.get((sym, tf))
    return s if s is not None else _T.get_series(sym, tf)


def iTime(sym, tf, shift):
    s = _series(sym, tf)
    if s is None:
        return 0
    i = len(s.time) - 1 - shift
    return s.time[i] if 0 <= i < len(s.time) else 0


def _ival(arr_name, sym, tf, shift):
    s = _series(sym, tf)
    if s is None:
        return 0.0
    a = getattr(s, arr_name)
    i = len(a) - 1 - shift
    return a[i] if 0 <= i < len(a) else 0.0


def iOpen(sym, tf, shift):
    return _ival("open", sym, tf, shift)


def iHigh(sym, tf, shift):
    return _ival("high", sym, tf, shift)


def iLow(sym, tf, shift):
    return _ival("low", sym, tf, shift)


def iClose(sym, tf, shift):
    return _ival("close", sym, tf, shift)


def iVolume(sym, tf, shift):
    return int(_ival("tick_volume", sym, tf, shift))


iTickVolume = iVolume


def iSpread(sym, tf, shift):
    return int(_ival("spread", sym, tf, shift))


def iBars(sym, tf):
    s = _series(sym, tf)
    return len(s) if s is not None else 0


def Bars(sym, tf):
    return iBars(sym, tf)


def iBarShift(sym, tf, t, exact=False):
    s = _series(sym, tf)
    return s.bar_shift(int(t), exact) if s is not None else -1


def iHighest(sym, tf, mode_arr="high", count=0, start=0):
    s = _series(sym, tf)
    a = getattr(s, mode_arr)
    n = len(a)
    hi = n - 1 - start
    lo = max(0, hi - count + 1) if count > 0 else 0
    best = max(range(lo, hi + 1), key=lambda i: a[i])
    return n - 1 - best


def iLowest(sym, tf, mode_arr="low", count=0, start=0):
    s = _series(sym, tf)
    a = getattr(s, mode_arr)
    n = len(a)
    hi = n - 1 - start
    lo = max(0, hi - count + 1) if count > 0 else 0
    best = min(range(lo, hi + 1), key=lambda i: a[i])
    return n - 1 - best


def _copy_range(s, start, count):
    n = len(s.time)
    last = n - 1 - start
    if last < 0 or count <= 0:
        return -1, -1
    first = max(0, last - count + 1)
    return first, last


def _fill(out, values, as_series):
    out.clear()
    if as_series:
        out.extend(reversed(values))
    else:
        out.extend(values)
    return len(values)


def CopyRates(sym, tf, start, count, out, as_series=False):
    s = _series(sym, tf)
    if s is None:
        return -1
    first, last = _copy_range(s, start, count)
    if first < 0:
        out.clear()
        return -1
    vals = [MqlRates(s.time[i], s.open[i], s.high[i], s.low[i], s.close[i], s.tick_volume[i],
                     s.spread[i], s.real_volume[i]) for i in range(first, last + 1)]
    return _fill(out, vals, as_series)


def _copy_arr(name, sym, tf, start, count, out, as_series):
    s = _series(sym, tf)
    if s is None:
        return -1
    first, last = _copy_range(s, start, count)
    if first < 0:
        out.clear()
        return -1
    return _fill(out, getattr(s, name)[first:last + 1], as_series)


def CopyTime(sym, tf, start, count, out, as_series=False):
    return _copy_arr("time", sym, tf, start, count, out, as_series)


def CopyOpen(sym, tf, start, count, out, as_series=False):
    return _copy_arr("open", sym, tf, start, count, out, as_series)


def CopyHigh(sym, tf, start, count, out, as_series=False):
    return _copy_arr("high", sym, tf, start, count, out, as_series)


def CopyLow(sym, tf, start, count, out, as_series=False):
    return _copy_arr("low", sym, tf, start, count, out, as_series)


def CopyClose(sym, tf, start, count, out, as_series=False):
    return _copy_arr("close", sym, tf, start, count, out, as_series)


def CopyTickVolume(sym, tf, start, count, out, as_series=False):
    return _copy_arr("tick_volume", sym, tf, start, count, out, as_series)


def CopySpread(sym, tf, start, count, out, as_series=False):
    return _copy_arr("spread", sym, tf, start, count, out, as_series)


# ====================================================================== indicators
def _new_handle(ind):
    _T.handles.append(ind)
    return len(_T.handles) - 1


def _ind_series(sym, tf):
    if not sym:
        sym = _T.chart_symbol
    return _series(sym, tf)


def iMA(sym, tf, period, ma_shift, method, applied):
    from ..engine.indicators import MA
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(MA(s, period, ma_shift, method, applied))


def iStdDev(sym, tf, period, ma_shift, method, applied):
    from ..engine.indicators import StdDev
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(StdDev(s, period, ma_shift, method, applied))


def iATR(sym, tf, period):
    from ..engine.indicators import ATR
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(ATR(s, period))


def iRSI(sym, tf, period, applied):
    from ..engine.indicators import RSI
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(RSI(s, period, applied))


def iBands(sym, tf, period, shift, deviation, applied):
    from ..engine.indicators import Bands
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(Bands(s, period, shift, deviation, applied))


def iMACD(sym, tf, fast, slow, signal, applied):
    from ..engine.indicators import MACD
    s = _ind_series(sym, tf)
    return C.INVALID_HANDLE if s is None else _new_handle(MACD(s, fast, slow, signal, applied))


def IndicatorRelease(handle):
    if 0 <= handle < len(_T.handles):
        _T.handles[handle] = None
        return True
    return False


def BarsCalculated(handle):
    ind = _T.handles[handle] if 0 <= handle < len(_T.handles) else None
    return len(ind.s) if ind is not None else -1


def CopyBuffer(handle, buffer_num, start, count, out, as_series=False):
    ind = _T.handles[handle] if 0 <= handle < len(_T.handles) else None
    if ind is None:
        out.clear()
        return -1
    if count == 1:                      # fast path (the common "read one value" call)
        i = len(ind.s.time) - 1 - start
        out.clear()
        if i < 0:
            return -1
        out.append(ind.value(buffer_num, i))
        return 1
    vals = ind.copy(buffer_num, start, count)
    if not vals:
        out.clear()
        return -1
    return _fill(out, vals, as_series)


# ====================================================================== chart objects (no-op)
def ObjectFind(chart_id, name):
    return -1


def ObjectCreate(chart_id, name, obj_type, sub_window, *args):
    return True


def ObjectSetInteger(chart_id, name, prop, value, *args):
    return True


def ObjectSetString(chart_id, name, prop, value, *args):
    return True


def ObjectSetDouble(chart_id, name, prop, value, *args):
    return True


def ObjectDelete(chart_id, name):
    return True


def ObjectsDeleteAll(chart_id, prefix="", *args):
    return 0


def ChartRedraw(chart_id=0):
    return None


# ====================================================================== files (virtual, per run)
def FileOpen(name, flags, delimiter="\t", codepage=0):
    if isinstance(delimiter, int):          # MQL passes the delimiter as a ushort char code
        delimiter = chr(delimiter)
    key = name.lower()
    t = _T
    if flags & C.FILE_WRITE:
        t.files[key] = ""
    elif key not in t.files:
        t.last_error = 5004
        return C.INVALID_HANDLE
    t._fh += 1
    content = t.files.get(key, "")
    fields = []
    if flags & C.FILE_READ:
        for line in content.splitlines():
            fields.extend(line.split(delimiter) if (flags & C.FILE_CSV) else [line])
    t.open_files[t._fh] = {"name": key, "flags": flags, "delim": delimiter, "fields": fields, "pos": 0}
    return t._fh


def FileClose(handle):
    _T.open_files.pop(handle, None)


def FileWrite(handle, *args):
    f = _T.open_files.get(handle)
    if f is None:
        return 0
    line = f["delim"].join(str(a) for a in args) + "\n"
    _T.files[f["name"]] = _T.files.get(f["name"], "") + line
    return len(line)


def FileReadString(handle, length=0):
    f = _T.open_files.get(handle)
    if f is None or f["pos"] >= len(f["fields"]):
        return ""
    v = f["fields"][f["pos"]]
    f["pos"] += 1
    return v


def FileIsEnding(handle):
    f = _T.open_files.get(handle)
    return f is None or f["pos"] >= len(f["fields"])


def FileIsExist(name, flags=0):
    return name.lower() in _T.files


def FileDelete(name, flags=0):
    return _T.files.pop(name.lower(), None) is not None


# ====================================================================== global variables
def GlobalVariableSet(name, value):
    _T.global_vars[name] = float(value)
    return _T.broker.time


def GlobalVariableGet(name):
    return _T.global_vars.get(name, 0.0)


def GlobalVariableCheck(name):
    return name in _T.global_vars


def GlobalVariableDel(name):
    return _T.global_vars.pop(name, None) is not None


# ====================================================================== tester
def TesterStatistics(stat):
    st = getattr(_T, "tester_stats", None) or {}
    return float(st.get(stat, 0.0))


# ====================================================================== arrays / strings (porting helpers)
def ArraySize(arr):
    return len(arr)


def ArrayResize(arr, new_size, fill=0.0, reserve=0):
    """In-place resize of a Python list. ``fill`` may be a value or a zero-arg factory (struct class)."""
    n = len(arr)
    if new_size < n:
        del arr[new_size:]
    else:
        for _ in range(new_size - n):
            arr.append(fill() if callable(fill) else fill)
    return new_size


def ArrayFree(arr):
    arr.clear()


def ArrayInitialize(arr, value):
    for i in range(len(arr)):
        arr[i] = value
    return len(arr)


def ArraySetAsSeries(arr, flag):
    return True   # series order is chosen when copying (as_series=...)


def ArrayMaximum(arr, start=0, count=-1):
    seg = arr[start:] if count < 0 else arr[start:start + count]
    return start + max(range(len(seg)), key=lambda i: seg[i]) if seg else -1


def ArrayMinimum(arr, start=0, count=-1):
    seg = arr[start:] if count < 0 else arr[start:start + count]
    return start + min(range(len(seg)), key=lambda i: seg[i]) if seg else -1


def StringLen(s):
    return len(s)


def StringFind(s, sub, start=0):
    return s.find(sub, start)


def StringSubstr(s, start, length=-1):
    return s[start:] if length < 0 else s[start:start + length]


def StringSplit(s, sep, parts):
    """sep is a char code (StringGetCharacter) or a string; fills ``parts`` in place."""
    ch = chr(sep) if isinstance(sep, int) else sep
    parts.clear()
    parts.extend(s.split(ch))
    return len(parts)


def StringGetCharacter(s, pos):
    return ord(s[pos]) if 0 <= pos < len(s) else 0


def StringFormat(fmt, *args):
    try:
        return fmt % args
    except (TypeError, ValueError):
        return fmt


def EnumToString(value):
    """Enum values are plain ints here; timeframes are recognised (PERIOD_M5 ...), others print as numbers."""
    if isinstance(value, int) and not isinstance(value, bool) and value in C.TIMEFRAME_NAMES and value > 0:
        return "PERIOD_" + C.TIMEFRAME_NAMES[value]
    return str(value)


def CharToString(code):
    return chr(code)
