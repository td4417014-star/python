"""Port of experts/MA_Cross_Example.mq5 - the smallest example of the workflow.

Generated with ``python -m ubt port`` and needed no manual edits; kept
here as a reference for how a port reads.
"""
from ubt.mql5 import *  # noqa: F401,F403
from ubt.strategy import Strategy


class MACrossExample(Strategy):
    MQ5_FILE = "../experts/MA_Cross_Example.mq5"

    def __init__(self, inputs=None):
        super().__init__(inputs)
        self.trade = CTrade()
        self.hFast = INVALID_HANDLE
        self.hSlow = INVALID_HANDLE
        self.lastBar = 0

    def OnInit(self):
        if self.InpFastPeriod >= self.InpSlowPeriod:
            return INIT_PARAMETERS_INCORRECT
        self.hFast = iMA(Symbol(), Period(), self.InpFastPeriod, 0, self.InpMethod, PRICE_CLOSE)
        self.hSlow = iMA(Symbol(), Period(), self.InpSlowPeriod, 0, self.InpMethod, PRICE_CLOSE)
        if self.hFast == INVALID_HANDLE or self.hSlow == INVALID_HANDLE:
            return INIT_FAILED
        self.trade.SetExpertMagicNumber(self.InpMagic)
        return INIT_SUCCEEDED

    def HasPosition(self, type_):
        """returns (has, type)"""
        for i in range(PositionsTotal() - 1, -1, -1):
            t = PositionGetTicket(i)
            if t == 0:
                continue
            if PositionGetString(POSITION_SYMBOL) != Symbol() or PositionGetInteger(POSITION_MAGIC) != self.InpMagic:
                continue
            type_ = PositionGetInteger(POSITION_TYPE)
            return True, type_
        return False, type_

    def OnTick(self):
        bar = iTime(Symbol(), Period(), 0)
        if bar == self.lastBar:
            return
        self.lastBar = bar
        f, s = [], []
        if (CopyBuffer(self.hFast, 0, 1, 2, f, as_series=True) < 2
                or CopyBuffer(self.hSlow, 0, 1, 2, s, as_series=True) < 2):
            return
        crossUp = f[1] <= s[1] and f[0] > s[0]
        crossDn = f[1] >= s[1] and f[0] < s[0]
        has, type_ = self.HasPosition(-1)
        ask = SymbolInfoDouble(Symbol(), SYMBOL_ASK)
        bid = SymbolInfoDouble(Symbol(), SYMBOL_BID)
        if crossUp:
            if has and type_ == POSITION_TYPE_SELL and self.InpReverse:
                self.trade.PositionClose(Symbol())
                has = False
            if not has:
                self.trade.Buy(self.InpLots, Symbol(), ask,
                               ask - self.InpStopLoss * Point() if self.InpStopLoss > 0 else 0,
                               ask + self.InpTakeProfit * Point() if self.InpTakeProfit > 0 else 0, "MA up")
        elif crossDn:
            if has and type_ == POSITION_TYPE_BUY and self.InpReverse:
                self.trade.PositionClose(Symbol())
                has = False
            if not has:
                self.trade.Sell(self.InpLots, Symbol(), bid,
                                bid + self.InpStopLoss * Point() if self.InpStopLoss > 0 else 0,
                                bid - self.InpTakeProfit * Point() if self.InpTakeProfit > 0 else 0, "MA down")

    def OnTester(self):
        pf = TesterStatistics(STAT_PROFIT_FACTOR)
        dd = TesterStatistics(STAT_EQUITY_DDREL_PERCENT)
        return pf / max(dd, 1.0)
