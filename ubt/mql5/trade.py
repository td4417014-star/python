"""Standard library classes CTrade / CPositionInfo / COrderInfo / CSymbolInfo.

Behaviour follows MQL5\\Include\\Trade\\*.mqh: they are thin wrappers around
the global selection and OrderSend, so retcodes and GetLastError() behave the
same as in the terminal.
"""
from __future__ import annotations

from . import constants as C
from . import api as A
from .structs import MqlTradeRequest, MqlTradeResult


class CTrade:
    def __init__(self):
        self.m_request = MqlTradeRequest()
        self.m_result = MqlTradeResult()
        self.m_magic = 0
        self.m_deviation = 10
        self.m_type_filling = C.ORDER_FILLING_FOK
        self.m_async_mode = False

    # --- settings
    def SetExpertMagicNumber(self, magic):
        self.m_magic = magic

    def SetDeviationInPoints(self, deviation):
        self.m_deviation = deviation

    def SetTypeFilling(self, filling):
        self.m_type_filling = filling

    def SetTypeFillingBySymbol(self, symbol):
        fm = A.SymbolInfoInteger(symbol, C.SYMBOL_FILLING_MODE)
        self.m_type_filling = (C.ORDER_FILLING_FOK if fm & C.SYMBOL_FILLING_FOK else
                               C.ORDER_FILLING_IOC if fm & C.SYMBOL_FILLING_IOC else C.ORDER_FILLING_RETURN)
        return True

    def SetAsyncMode(self, mode):
        self.m_async_mode = mode

    def LogLevel(self, level):
        pass

    # --- results
    def ResultRetcode(self):
        return self.m_result.retcode

    def ResultRetcodeDescription(self):
        return C.RETCODE_TEXT.get(self.m_result.retcode, str(self.m_result.retcode))

    def ResultOrder(self):
        return self.m_result.order

    def ResultDeal(self):
        return self.m_result.deal

    def ResultPrice(self):
        return self.m_result.price

    def ResultVolume(self):
        return self.m_result.volume

    def ResultComment(self):
        return self.m_result.comment

    def Request(self):
        return self.m_request

    def Result(self):
        return self.m_result

    # --- internals
    def _new_request(self, **kw):
        r = MqlTradeRequest(magic=self.m_magic, deviation=self.m_deviation,
                            type_filling=self.m_type_filling)
        for k, v in kw.items():
            setattr(r, k, v)
        self.m_request = r
        self.m_result = MqlTradeResult()
        return r

    def OrderSend(self, request, result):
        return A.OrderSend(request, result)

    # --- positions
    def PositionOpen(self, symbol, order_type, volume, price, sl, tp, comment=""):
        if A.IsStopped():
            return False
        r = self._new_request(action=C.TRADE_ACTION_DEAL, symbol=symbol, volume=volume,
                              type=order_type, price=price, sl=sl, tp=tp, comment=comment)
        return self.OrderSend(r, self.m_result)

    def Buy(self, volume, symbol=None, price=0.0, sl=0.0, tp=0.0, comment=""):
        symbol = symbol or A.Symbol()
        if price == 0.0:
            price = A.SymbolInfoDouble(symbol, C.SYMBOL_ASK)
        return self.PositionOpen(symbol, C.ORDER_TYPE_BUY, volume, price, sl, tp, comment)

    def Sell(self, volume, symbol=None, price=0.0, sl=0.0, tp=0.0, comment=""):
        symbol = symbol or A.Symbol()
        if price == 0.0:
            price = A.SymbolInfoDouble(symbol, C.SYMBOL_BID)
        return self.PositionOpen(symbol, C.ORDER_TYPE_SELL, volume, price, sl, tp, comment)

    def PositionModify(self, ticket_or_symbol, sl, tp):
        if A.IsStopped():
            return False
        if isinstance(ticket_or_symbol, str):
            if not A.PositionSelect(ticket_or_symbol):
                return False
        elif not A.PositionSelectByTicket(ticket_or_symbol):
            return False
        r = self._new_request(action=C.TRADE_ACTION_SLTP,
                              symbol=A.PositionGetString(C.POSITION_SYMBOL),
                              position=A.PositionGetInteger(C.POSITION_TICKET), sl=sl, tp=tp)
        return self.OrderSend(r, self.m_result)

    def PositionClose(self, ticket_or_symbol, deviation=-1):
        if A.IsStopped():
            return False
        if isinstance(ticket_or_symbol, str):
            if not A.PositionSelect(ticket_or_symbol):
                return False
        elif not A.PositionSelectByTicket(ticket_or_symbol):
            return False
        sym = A.PositionGetString(C.POSITION_SYMBOL)
        ptype = A.PositionGetInteger(C.POSITION_TYPE)
        if ptype == C.POSITION_TYPE_BUY:
            otype, price = C.ORDER_TYPE_SELL, A.SymbolInfoDouble(sym, C.SYMBOL_BID)
        else:
            otype, price = C.ORDER_TYPE_BUY, A.SymbolInfoDouble(sym, C.SYMBOL_ASK)
        r = self._new_request(action=C.TRADE_ACTION_DEAL, symbol=sym, type=otype, price=price,
                              volume=A.PositionGetDouble(C.POSITION_VOLUME),
                              position=A.PositionGetInteger(C.POSITION_TICKET),
                              magic=self.m_magic,
                              deviation=self.m_deviation if deviation == -1 else deviation)
        return self.OrderSend(r, self.m_result)

    def PositionClosePartial(self, ticket, volume, deviation=-1):
        if not A.PositionSelectByTicket(ticket):
            return False
        sym = A.PositionGetString(C.POSITION_SYMBOL)
        ptype = A.PositionGetInteger(C.POSITION_TYPE)
        otype = C.ORDER_TYPE_SELL if ptype == C.POSITION_TYPE_BUY else C.ORDER_TYPE_BUY
        price = A.SymbolInfoDouble(sym, C.SYMBOL_BID if ptype == C.POSITION_TYPE_BUY else C.SYMBOL_ASK)
        r = self._new_request(action=C.TRADE_ACTION_DEAL, symbol=sym, type=otype, price=price,
                              volume=volume, position=ticket)
        return self.OrderSend(r, self.m_result)

    # --- pending orders
    def OrderOpen(self, symbol, order_type, volume, limit_price, price, sl, tp,
                  type_time=C.ORDER_TIME_GTC, expiration=0, comment=""):
        if A.IsStopped():
            return False
        r = self._new_request(action=C.TRADE_ACTION_PENDING, symbol=symbol, volume=volume,
                              type=order_type, price=price, stoplimit=limit_price, sl=sl, tp=tp,
                              type_time=type_time, expiration=expiration, comment=comment)
        return self.OrderSend(r, self.m_result)

    def BuyLimit(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=C.ORDER_TIME_GTC, expiration=0, comment=""):
        return self.OrderOpen(symbol or A.Symbol(), C.ORDER_TYPE_BUY_LIMIT, volume, 0.0, price, sl, tp, type_time, expiration, comment)

    def BuyStop(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=C.ORDER_TIME_GTC, expiration=0, comment=""):
        return self.OrderOpen(symbol or A.Symbol(), C.ORDER_TYPE_BUY_STOP, volume, 0.0, price, sl, tp, type_time, expiration, comment)

    def SellLimit(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=C.ORDER_TIME_GTC, expiration=0, comment=""):
        return self.OrderOpen(symbol or A.Symbol(), C.ORDER_TYPE_SELL_LIMIT, volume, 0.0, price, sl, tp, type_time, expiration, comment)

    def SellStop(self, volume, price, symbol=None, sl=0.0, tp=0.0, type_time=C.ORDER_TIME_GTC, expiration=0, comment=""):
        return self.OrderOpen(symbol or A.Symbol(), C.ORDER_TYPE_SELL_STOP, volume, 0.0, price, sl, tp, type_time, expiration, comment)

    def OrderModify(self, ticket, price, sl, tp, type_time=C.ORDER_TIME_GTC, expiration=0, stoplimit=0.0):
        if not A.OrderSelect(ticket):
            return False
        r = self._new_request(action=C.TRADE_ACTION_MODIFY, order=ticket, price=price, sl=sl, tp=tp,
                              type_time=type_time, expiration=expiration, stoplimit=stoplimit,
                              symbol=A.OrderGetString(C.ORDER_SYMBOL))
        return self.OrderSend(r, self.m_result)

    def OrderDelete(self, ticket):
        if A.IsStopped():
            return False
        r = self._new_request(action=C.TRADE_ACTION_REMOVE, order=ticket)
        return self.OrderSend(r, self.m_result)


class CPositionInfo:
    def SelectByIndex(self, index):
        return A.PositionGetTicket(index) > 0

    def SelectByTicket(self, ticket):
        return A.PositionSelectByTicket(ticket)

    def Select(self, symbol):
        return A.PositionSelect(symbol)

    def Ticket(self):
        return A.PositionGetInteger(C.POSITION_TICKET)

    def Identifier(self):
        return A.PositionGetInteger(C.POSITION_IDENTIFIER)

    def Symbol(self):
        return A.PositionGetString(C.POSITION_SYMBOL)

    def Magic(self):
        return A.PositionGetInteger(C.POSITION_MAGIC)

    def PositionType(self):
        return A.PositionGetInteger(C.POSITION_TYPE)

    def Volume(self):
        return A.PositionGetDouble(C.POSITION_VOLUME)

    def PriceOpen(self):
        return A.PositionGetDouble(C.POSITION_PRICE_OPEN)

    def PriceCurrent(self):
        return A.PositionGetDouble(C.POSITION_PRICE_CURRENT)

    def StopLoss(self):
        return A.PositionGetDouble(C.POSITION_SL)

    def TakeProfit(self):
        return A.PositionGetDouble(C.POSITION_TP)

    def Profit(self):
        return A.PositionGetDouble(C.POSITION_PROFIT)

    def Swap(self):
        return A.PositionGetDouble(C.POSITION_SWAP)

    def Commission(self):
        return A.PositionGetDouble(C.POSITION_COMMISSION)

    def Comment(self):
        return A.PositionGetString(C.POSITION_COMMENT)

    def Time(self):
        return A.PositionGetInteger(C.POSITION_TIME)


class COrderInfo:
    def SelectByIndex(self, index):
        return A.OrderGetTicket(index) > 0

    def Select(self, ticket):
        return A.OrderSelect(ticket)

    def Ticket(self):
        return A.OrderGetInteger(C.ORDER_TICKET)

    def Symbol(self):
        return A.OrderGetString(C.ORDER_SYMBOL)

    def Magic(self):
        return A.OrderGetInteger(C.ORDER_MAGIC)

    def OrderType(self):
        return A.OrderGetInteger(C.ORDER_TYPE)

    def VolumeCurrent(self):
        return A.OrderGetDouble(C.ORDER_VOLUME_CURRENT)

    def PriceOpen(self):
        return A.OrderGetDouble(C.ORDER_PRICE_OPEN)

    def StopLoss(self):
        return A.OrderGetDouble(C.ORDER_SL)

    def TakeProfit(self):
        return A.OrderGetDouble(C.ORDER_TP)

    def Comment(self):
        return A.OrderGetString(C.ORDER_COMMENT)


class CSymbolInfo:
    def __init__(self):
        self._name = ""

    def Name(self, name=None):
        if name is None:
            return self._name
        self._name = name
        return A.SymbolSelect(name, True)

    def RefreshRates(self):
        return True

    def Bid(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_BID)

    def Ask(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_ASK)

    def Point(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_POINT)

    def Digits(self):
        return A.SymbolInfoInteger(self._name, C.SYMBOL_DIGITS)

    def LotsMin(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_VOLUME_MIN)

    def LotsMax(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_VOLUME_MAX)

    def LotsStep(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_VOLUME_STEP)

    def TickValue(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_TRADE_TICK_VALUE)

    def TickSize(self):
        return A.SymbolInfoDouble(self._name, C.SYMBOL_TRADE_TICK_SIZE)

    def StopsLevel(self):
        return A.SymbolInfoInteger(self._name, C.SYMBOL_TRADE_STOPS_LEVEL)
