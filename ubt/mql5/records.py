"""Trade server records (positions, orders, deals)."""


class Position:
    __slots__ = ("ticket", "identifier", "symbol", "type", "volume", "price_open", "sl", "tp",
                 "time", "time_msc", "time_update", "magic", "comment", "swap", "commission",
                 "price_current", "profit", "reason")

    def copy(self) -> "Position":
        p = Position.__new__(Position)
        for s in Position.__slots__:
            setattr(p, s, getattr(self, s))
        return p


class Order:
    __slots__ = ("ticket", "symbol", "type", "volume_initial", "volume_current", "price_open",
                 "sl", "tp", "time_setup", "time_setup_msc", "time_expiration", "type_filling",
                 "type_time", "magic", "comment", "state", "position_id", "price_current",
                 "time_done", "stoplimit")

    def copy(self) -> "Order":
        o = Order.__new__(Order)
        for s in Order.__slots__:
            setattr(o, s, getattr(self, s))
        return o


class Deal:
    __slots__ = ("ticket", "order", "position_id", "symbol", "type", "entry", "volume", "price",
                 "profit", "commission", "swap", "time", "time_msc", "magic", "comment", "reason",
                 "balance", "equity")

    def as_dict(self) -> dict:
        return {s: getattr(self, s) for s in Deal.__slots__}
