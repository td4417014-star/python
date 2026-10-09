"""MQL5 structures (MqlTradeRequest, MqlTradeResult, MqlTick, MqlRates)."""


class MqlTradeRequest:
    __slots__ = ("action", "magic", "order", "symbol", "volume", "price", "stoplimit",
                 "sl", "tp", "deviation", "type", "type_filling", "type_time",
                 "expiration", "comment", "position", "position_by")

    def __init__(self, **kw):
        self.action = 0
        self.magic = 0
        self.order = 0
        self.symbol = ""
        self.volume = 0.0
        self.price = 0.0
        self.stoplimit = 0.0
        self.sl = 0.0
        self.tp = 0.0
        self.deviation = 0
        self.type = 0
        self.type_filling = 0
        self.type_time = 0
        self.expiration = 0
        self.comment = ""
        self.position = 0
        self.position_by = 0
        for k, v in kw.items():
            setattr(self, k, v)

    def __repr__(self):
        return "MqlTradeRequest(" + ", ".join(f"{k}={getattr(self, k)!r}" for k in self.__slots__) + ")"


class MqlTradeResult:
    __slots__ = ("retcode", "deal", "order", "volume", "price", "bid", "ask", "comment",
                 "request_id", "retcode_external")

    def __init__(self):
        self.clear()

    def clear(self):
        self.retcode = 0
        self.deal = 0
        self.order = 0
        self.volume = 0.0
        self.price = 0.0
        self.bid = 0.0
        self.ask = 0.0
        self.comment = ""
        self.request_id = 0
        self.retcode_external = 0

    def __repr__(self):
        return "MqlTradeResult(" + ", ".join(f"{k}={getattr(self, k)!r}" for k in self.__slots__) + ")"


class MqlTick:
    __slots__ = ("time", "bid", "ask", "last", "volume", "time_msc", "flags", "volume_real")

    def __init__(self):
        self.time = 0
        self.bid = 0.0
        self.ask = 0.0
        self.last = 0.0
        self.volume = 0
        self.time_msc = 0
        self.flags = 0
        self.volume_real = 0.0


class MqlRates:
    __slots__ = ("time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume")

    def __init__(self, time=0, open=0.0, high=0.0, low=0.0, close=0.0,
                 tick_volume=0, spread=0, real_volume=0):
        self.time = time
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.tick_volume = tick_volume
        self.spread = spread
        self.real_volume = real_volume

    def __repr__(self):
        return (f"MqlRates(time={self.time}, o={self.open}, h={self.high}, "
                f"l={self.low}, c={self.close}, tv={self.tick_volume})")
