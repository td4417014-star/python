"""Drive the real MetaTrader 5 Strategy Tester from Python (the 100%-original EA).

Use this to (a) validate the Python port against MT5 on the same data and
settings (``parity``), and (b) run MT5-native optimisations whose results feed
the same sensitivity / survival analysis.

Requirements: Windows, an installed MT5 terminal logged into the account,
the EA compiled to .ex5 under <data folder>/MQL5/Experts (``compile_ea`` can
do that with MetaEditor).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

from ..mq5 import Mq5Info, parse_mq5, set_lines
from .report import parse_html_report, parse_optimization_xml

log = logging.getLogger("ubt.mt5")

MODEL = {"every_tick": 0, "m1_ohlc": 1, "open_prices": 2, "math": 3, "real": 4}
OPT = {"none": 0, "slow": 1, "genetic": 2, "all_symbols": 3}
CRITERION = {"balance": 0, "profit_factor": 1, "expected_payoff": 2, "drawdown": 3, "recovery": 4,
             "sharpe": 5, "custom": 6, "complex": 7}


@dataclass
class MT5TesterConfig:
    terminal: str                          # ...\terminal64.exe
    data_dir: str                          # terminal data folder (File > Open Data Folder)
    expert: str                            # path relative to MQL5\Experts, e.g. "Zscore_and_Levando_MIX.ex5"
    symbol: str = "BTCUSD"
    period: str = "M5"
    start: str = "2024.01.01"
    end: str = "2024.06.01"
    model: str = "real"
    deposit: float = 10000
    currency: str = "USD"
    leverage: int = 100
    optimization: str = "none"
    criterion: str = "custom"
    delay_ms: int = 0
    report_name: str = "ubt_report"
    timeout_s: int = 6 * 3600
    portable: bool = False
    extra: Dict[str, str] = field(default_factory=dict)


def _date(s: str) -> str:
    return pd.Timestamp(s.replace(".", "-")).strftime("%Y.%m.%d")


def build_ini(cfg: MT5TesterConfig, inputs: dict, space: Optional[dict] = None,
              info: Optional[Mq5Info] = None) -> str:
    lines = ["[Tester]",
             f"Expert={cfg.expert}",
             f"Symbol={cfg.symbol}",
             f"Period={cfg.period}",
             f"Model={MODEL[cfg.model]}",
             f"ExecutionMode={cfg.delay_ms}",
             f"Optimization={OPT[cfg.optimization]}",
             f"OptimizationCriterion={CRITERION[cfg.criterion]}",
             f"FromDate={_date(cfg.start)}",
             f"ToDate={_date(cfg.end)}",
             "ForwardMode=0",
             f"Deposit={cfg.deposit:g}",
             f"Currency={cfg.currency}",
             f"Leverage={cfg.leverage}",
             f"Report={cfg.report_name}",
             "ReplaceReport=1",
             "ShutdownTerminal=1",
             "Visual=0"]
    for k, v in cfg.extra.items():
        lines.append(f"{k}={v}")
    lines.append("[TesterInputs]")
    lines.extend(set_lines(inputs, space or {}, info))
    return "\r\n".join(lines) + "\r\n"


def compile_ea(metaeditor: str, mq5_path: str, timeout_s: int = 600) -> bool:
    log_path = str(Path(mq5_path).with_suffix(".compile.log"))
    r = subprocess.run([metaeditor, f"/compile:{mq5_path}", f"/log:{log_path}"], timeout=timeout_s)
    ok = Path(mq5_path).with_suffix(".ex5").exists()
    log.info("compile %s -> %s (exit %s, log %s)", mq5_path, "OK" if ok else "FAILED", r.returncode, log_path)
    return ok


def run_tester(cfg: MT5TesterConfig, inputs: dict, space: Optional[dict] = None,
               mq5: Optional[str] = None, work_dir: str = "mt5_runs") -> dict:
    """Run one MT5 test (or MT5 optimisation) and return the parsed report."""
    info = parse_mq5(mq5) if mq5 else None
    if info:
        inputs = {**info.defaults(), **inputs}
    wd = Path(work_dir).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    ini = wd / f"{cfg.report_name}.ini"
    ini.write_text(build_ini(cfg, inputs, space, info), encoding="utf-16")
    data = Path(cfg.data_dir)
    for ext in (".htm", ".html", ".xml"):
        old = data / f"{cfg.report_name}{ext}"
        if old.exists():
            old.unlink()
    cmd = [cfg.terminal, f"/config:{ini}"]
    if cfg.portable:
        cmd.append("/portable")
    log.info("running MT5 tester: %s", " ".join(cmd))
    t0 = time.time()
    subprocess.run(cmd, timeout=cfg.timeout_s)
    out = {"seconds": time.time() - t0, "ini": str(ini)}
    if cfg.optimization == "none":
        rep = next((data / f"{cfg.report_name}{e}" for e in (".htm", ".html") if (data / f"{cfg.report_name}{e}").exists()), None)
        if rep is None:
            raise RuntimeError(f"MT5 produced no report in {data} (check the tester journal)")
        out.update(parse_html_report(rep))
        out["report"] = str(rep)
    else:
        rep = data / f"{cfg.report_name}.xml"
        if not rep.exists():
            raise RuntimeError(f"MT5 produced no optimisation report {rep}")
        out["passes"] = parse_optimization_xml(rep)
        out["report"] = str(rep)
    return out


# ---------------------------------------------------------------------- parity
def parity(py_deals: pd.DataFrame, mt5_deals: pd.DataFrame, price_tol: float = 0.0, time_tol_s: int = 1) -> dict:
    """Compare the Python backtest's deals with the MT5 report's deals, in order."""
    py = py_deals[py_deals["type"].isin([0, 1])].reset_index(drop=True)
    mt = mt5_deals.copy()
    if "type" in mt:
        mt = mt[mt["type"].astype(str).str.lower().isin(["buy", "sell"])].reset_index(drop=True)
    n = min(len(py), len(mt))
    matched = 0
    first_diff = None
    for i in range(n):
        a, b = py.iloc[i], mt.iloc[i]
        tb = pd.Timestamp(str(b.get("time")).replace(".", "-")).timestamp() if "time" in b else a["time"]
        same = (("buy" if a["type"] == 0 else "sell") == str(b.get("type", "")).lower()
                and abs(float(a["volume"]) - float(b.get("volume", a["volume"]))) < 1e-9
                and abs(float(a["price"]) - float(b.get("price", a["price"]))) <= price_tol + 1e-9
                and abs(a["time"] - tb) <= time_tol_s)
        if same:
            matched += 1
        elif first_diff is None:
            first_diff = {"index": i, "python": a.to_dict(), "mt5": b.to_dict()}
    return {"python_deals": int(len(py)), "mt5_deals": int(len(mt)), "compared": n,
            "matched": matched, "match_pct": matched / n * 100 if n else 0.0, "first_difference": first_diff}
