import pytest

from ubt.engine.broker import Broker, CostModel
from ubt.engine.symbol import AccountSpec, SymbolSpec
from ubt.mql5 import constants as C
from ubt.mql5.structs import MqlTradeRequest, MqlTradeResult


def _broker(**kw):
    spec = SymbolSpec(name="BTCUSD", digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=0.01,
                      trade_contract_size=1, volume_min=0.01, volume_step=0.01, volume_max=10,
                      trade_stops_level=kw.pop("stops", 0))
    b = Broker(AccountSpec(deposit=10000, leverage=100), {"BTCUSD": spec}, CostModel(**kw))
    b.on_tick("BTCUSD", 1_000_000, 50000.0, 50010.0)
    return b


def _send(b, **kw):
    req = MqlTradeRequest(symbol="BTCUSD", **kw)
    res = MqlTradeResult()
    ok = b.order_send(req, res)
    return ok, res


def test_market_open_close_profit():
    b = _broker()
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=0.1, magic=7)
    assert ok and r.retcode == C.TRADE_RETCODE_DONE
    pos = b.positions[0]
    assert pos.ticket == r.order and pos.price_open == 50010.0      # buy at ask
    b.on_tick("BTCUSD", 1_001_000, 50110.0, 50120.0)
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_SELL, volume=0.1, position=pos.ticket)
    assert ok and not b.positions
    assert b.balance == pytest.approx(10000 + (50110.0 - 50010.0) * 0.1)  # closed at bid


def test_sl_tp_trigger_rules_and_gap_fill():
    b = _broker()
    _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=0.1, sl=49900.0, tp=50500.0)
    b.on_tick("BTCUSD", 1_001_000, 49950.0, 49960.0)
    assert b.positions                                              # bid above SL
    b.on_tick("BTCUSD", 1_002_000, 49800.0, 49810.0)                # gap through SL
    assert not b.positions
    out = b.deals[-1]
    assert out.reason == C.DEAL_REASON_SL and out.price == 49800.0  # worse tick price on a gap


def test_pending_order_becomes_position_with_same_ticket():
    b = _broker()
    ok, r = _send(b, action=C.TRADE_ACTION_PENDING, type=C.ORDER_TYPE_BUY_STOP, volume=0.05, price=50100.0)
    assert ok and b.orders and not b.positions
    t = r.order
    b.on_tick("BTCUSD", 1_001_000, 50095.0, 50105.0)               # ask crosses the stop
    assert not b.orders and b.positions[0].ticket == t
    assert b.positions[0].price_open == 50105.0                     # gapped: worse price


def test_stop_level_and_volume_validation():
    b = _broker(stops=500)
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=0.1, sl=49999.0)
    assert not ok and r.retcode == C.TRADE_RETCODE_INVALID_STOPS
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=0.015)
    assert not ok and r.retcode == C.TRADE_RETCODE_INVALID_VOLUME
    ok, r = _send(b, action=C.TRADE_ACTION_PENDING, type=C.ORDER_TYPE_BUY_STOP, volume=0.1, price=50011.0)
    assert not ok and r.retcode == C.TRADE_RETCODE_INVALID_PRICE


def test_sltp_modify_no_changes_and_margin():
    b = _broker()
    _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=0.1)
    p = b.positions[0]
    ok, r = _send(b, action=C.TRADE_ACTION_SLTP, position=p.ticket, sl=49000.0)
    assert ok and p.sl == 49000.0
    ok, r = _send(b, action=C.TRADE_ACTION_SLTP, position=p.ticket, sl=49000.0)
    assert not ok and r.retcode == C.TRADE_RETCODE_NO_CHANGES
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=10.0)   # margin 5000 of 10000
    assert ok
    ok, r = _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=10.0)   # would need 10000+
    assert not ok and r.retcode == C.TRADE_RETCODE_NO_MONEY


def test_commission_and_spread_stress():
    b = _broker(commission_per_lot=5.0, spread_multiplier=2.0)
    b.on_tick("BTCUSD", 1_001_000, 50000.0, 50010.0)
    assert b.sym["BTCUSD"].ask == pytest.approx(50020.0)
    _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=1.0)
    assert b.balance == pytest.approx(10000 - 5.0)


def test_stop_out_closes_positions():
    b = _broker()
    _send(b, action=C.TRADE_ACTION_DEAL, type=C.ORDER_TYPE_BUY, volume=1.0)
    b.on_tick("BTCUSD", 1_001_000, 40000.0, 40010.0)                 # -10k: equity ~0
    assert not b.positions and b.stopped_out
