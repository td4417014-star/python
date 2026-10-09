"""UBT - Universal Backtester for MetaTrader 5 Expert Advisors.

Modules
-------
ubt.mql5        MQL5 API emulation used by ported EAs (``from ubt.mql5 import *``)
ubt.engine      simulated trade server, bars, indicators, tick sources, backtest runner
ubt.data        MT5 downloader (ticks + OHLCV), data purification, storage, synthetic data
ubt.analysis    metrics, optimizer, parameter sensitivity / survival, walk-forward, Monte Carlo, reports
ubt.mt5_tester  drive the real MT5 Strategy Tester (100% original EA) and parse its reports
"""
__version__ = "1.0.0"
