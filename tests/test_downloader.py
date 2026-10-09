"""Data taker pipeline against a fake MetaTrader5 module (same API shapes as the real one)."""
import datetime as dt
from collections import namedtuple

import numpy as np
import pandas as pd

from ubt.data import mt5_downloader as D
from ubt.data.cleaning import ticks_to_bars
from ubt.data.store import DataStore
from ubt.data.synthetic import make_ticks
from ubt.engine.backtest import BacktestConfig, run_backtest


class FakeMT5:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1 = 1, 5, 16385
    COPY_TICKS_ALL = -1
    ORDER_TYPE_BUY = 0

    def __init__(self):
        t = make_ticks("2023-11-28", "2023-12-05", seed=3, mean_dt=20.0)
        t.loc[500, ["bid", "ask"]] = [999999.0, 1000009.0]        # a bad spike the purifier must drop
        self.ticks = t
        self.calls = []

    # --- session
    def initialize(self, *a, **kw):
        self.calls.append(("initialize", kw.get("login"), "password" in kw))
        return True

    def shutdown(self):
        pass

    def last_error(self):
        return (1, "ok")

    def account_info(self):
        A = namedtuple("A", "login server company currency leverage margin_mode margin_so_mode margin_so_call "
                            "margin_so_so trade_mode")
        return A(42, "Demo-Server", "Broker", "USD", 200, 2, 0, 100.0, 50.0, 0)

    def terminal_info(self):
        return namedtuple("T", "maxbars")(100000000)

    # --- symbols
    def symbol_info(self, name):
        if name != "BTCUSDm":
            return None
        S = namedtuple("S", "name digits point trade_tick_size trade_tick_value trade_contract_size volume_min "
                            "volume_max volume_step trade_stops_level filling_mode trade_calc_mode currency_base "
                            "currency_profit swap_mode ask bid")
        return S("BTCUSDm", 2, 0.01, 0.01, 0.01, 1.0, 0.01, 100.0, 0.01, 0, 3, 4, "BTC", "USD", 0, 37000.0, 36990.0)

    def symbols_get(self, group=""):
        return [namedtuple("X", "name")("BTCUSDm")]

    def symbol_select(self, name, flag):
        return True

    def symbol_info_tick(self, name):
        return namedtuple("K", "ask bid")(37000.0, 36990.0)

    def order_calc_margin(self, action, sym, vol, price):
        return price * vol / 200

    # --- data
    def _tick_rec(self, df):
        out = np.zeros(len(df), dtype=[("time", "i8"), ("bid", "f8"), ("ask", "f8"), ("last", "f8"),
                                       ("volume", "u8"), ("time_msc", "i8"), ("flags", "u4"), ("volume_real", "f8")])
        out["time"] = df.time_msc // 1000
        out["time_msc"] = df.time_msc
        out["bid"] = df.bid
        out["ask"] = df.ask
        out["flags"] = 6
        return out

    def copy_ticks_range(self, sym, a, b, flags):
        ms_a, ms_b = int(a.timestamp() * 1000), int(b.timestamp() * 1000)
        t = self.ticks
        return self._tick_rec(t[(t.time_msc >= ms_a) & (t.time_msc < ms_b)])

    def copy_ticks_from(self, sym, a, count, flags):
        t = self.ticks[self.ticks.time_msc >= int(a.timestamp() * 1000)].head(count)
        return self._tick_rec(t)

    def copy_rates_range(self, sym, tf, a, b):
        sec = {1: 60, 5: 300, 16385: 3600}[tf]
        bars = ticks_to_bars(self.ticks, sec, 0.01)
        bars = bars[(bars.time >= int(a.timestamp())) & (bars.time < int(b.timestamp()))]
        out = np.zeros(len(bars), dtype=[("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
                                         ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"),
                                         ("real_volume", "u8")])
        for c in ("time", "open", "high", "low", "close", "tick_volume", "spread"):
            out[c] = bars[c].to_numpy()
        return out


def test_download_pipeline(tmp_path, monkeypatch):
    fake = FakeMT5()
    monkeypatch.setattr(D, "_import_mt5", lambda: fake)
    summary = D.run_download(42, "secret", "Demo-Server", ["BTCUSD"], str(tmp_path), ["M1", "M5", "H1"],
                             date_from="2023-11-01", date_to="2023-12-06")
    st = DataStore(tmp_path)
    assert "BTCUSDm" in summary                              # broker suffix resolved
    assert st.tick_months("BTCUSDm") == ["2023-11", "2023-12"]
    ticks = st.load_ticks("BTCUSDm", "2023-11-01", "2023-12-06")
    assert ticks.bid.max() < 900000                          # spike purified
    rep = st.load_json("BTCUSDm", "quality_report.json")
    assert sum(m["removed_spikes"] for m in rep["ticks"].values()) == 1
    assert rep["bars_from_ticks_vs_broker"]["M1"]["overlap_bars"] > 1000
    acc = st.load_json("BTCUSDm", "account.json")
    assert acc["leverage"] == 200 and "password" not in str(acc)
    spec = st.load_spec("BTCUSDm")
    assert spec.margin_per_lot_ref == 37000.0 / 200 and spec.weekend_trading
    # resumable: a second run re-downloads only the last month
    D.run_download(42, "secret", "Demo-Server", ["BTCUSD"], str(tmp_path), ["M1"], date_from="2023-11-01",
                   date_to="2023-12-06")
    # and the downloaded data is directly usable by the backtester
    from strategies.ma_cross_example import MACrossExample
    r = run_backtest(MACrossExample, {"InpFastPeriod": 5, "InpSlowPeriod": 20},
                     BacktestConfig(data_root=str(tmp_path), symbol="BTCUSDm", timeframe="M1",
                                    start="2023-12-01", end="2023-12-05", model="real", warmup_days=2))
    assert r.ticks > 1000 and r.init_code == 0
