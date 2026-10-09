"""Parallel, cached evaluation of many parameter sets (any strategy, any config)."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from ..engine.backtest import BacktestConfig, run_backtest

log = logging.getLogger("ubt")


def load_strategy(ref: str):
    """'package.module:Class' or 'path/to/file.py:Class' -> class."""
    if ":" not in ref:
        raise ValueError("strategy must look like 'module:Class' or 'file.py:Class'")
    mod, cls = ref.rsplit(":", 1)
    if mod.endswith(".py") or os.sep in mod or "/" in mod:
        path = Path(mod).resolve()
        root = str(path.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        name = f"{path.parent.name}.{path.stem}" if (path.parent / "__init__.py").exists() else path.stem
        if name in sys.modules:
            m = sys.modules[name]
        else:
            spec = importlib.util.spec_from_file_location(name, path)
            m = importlib.util.module_from_spec(spec)
            sys.modules[name] = m
            spec.loader.exec_module(m)
    else:
        if os.getcwd() not in sys.path:
            sys.path.insert(0, os.getcwd())
        m = importlib.import_module(mod)
    return getattr(m, cls)


def _hash(strategy: str, inputs: dict, cfg: dict) -> str:
    blob = json.dumps({"s": strategy, "i": inputs, "c": cfg}, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def _job(strategy: str, inputs: dict, cfg: dict) -> dict:
    t0 = time.time()
    try:
        cls = load_strategy(strategy)
        res = run_backtest(cls, inputs, BacktestConfig(**cfg))
        m = dict(res.metrics)
        m["_ok"] = True
    except Exception as e:   # a failing parameter set must not kill a whole optimisation
        m = {"_ok": False, "_error": f"{type(e).__name__}: {e}"}
    m["_seconds"] = time.time() - t0
    return m


class Evaluator:
    """Runs backtests for parameter sets, in parallel, with an on-disk result cache."""

    def __init__(self, strategy: str, base_inputs: Optional[dict] = None, cfg: Optional[BacktestConfig] = None,
                 workers: int = 0, cache_file: Optional[str | Path] = None):
        self.strategy = strategy
        self.base_inputs = dict(base_inputs or {})
        self.cfg = cfg or BacktestConfig()
        self.workers = workers if workers > 0 else max(1, (os.cpu_count() or 2) - 1)
        self.cache_file = Path(cache_file) if cache_file else None
        self.cache: Dict[str, dict] = {}
        if self.cache_file and self.cache_file.exists():
            for line in self.cache_file.read_text(encoding="utf-8").splitlines():
                try:
                    rec = json.loads(line)
                    self.cache[rec["hash"]] = rec["metrics"]
                except Exception:
                    pass

    def _cfg_dict(self, cfg_over: Optional[dict] = None) -> dict:
        d = asdict(self.cfg)
        if cfg_over:
            d.update(cfg_over)
        return d

    def run(self, param_sets: List[dict], cfg_over: Optional[dict] = None,
            progress: Optional[Callable[[int, int], None]] = None, tag: str = "",
            cfg_overs: Optional[List[dict]] = None) -> pd.DataFrame:
        """Evaluate parameter sets. ``cfg_over`` applies to all, ``cfg_overs[i]`` to set i only."""
        cfgs = [self._cfg_dict({**(cfg_over or {}), **((cfg_overs[i] if cfg_overs else None) or {})})
                for i in range(len(param_sets))]
        jobs, rows = [], [None] * len(param_sets)
        for i, p in enumerate(param_sets):
            inputs = {**self.base_inputs, **p}
            h = _hash(self.strategy, inputs, cfgs[i])
            if h in self.cache:
                rows[i] = {**p, **self.cache[h]}
            else:
                jobs.append((i, p, inputs, h))
        done = len(param_sets) - len(jobs)
        if progress:
            progress(done, len(param_sets))

        def _store(i, p, h, m):
            rows[i] = {**p, **m}
            if m.get("_ok"):
                self.cache[h] = m
                if self.cache_file:
                    self.cache_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.cache_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"hash": h, "params": p, "metrics": m}, default=str) + "\n")

        if self.workers <= 1 or len(jobs) <= 1:
            for i, p, inputs, h in jobs:
                _store(i, p, h, _job(self.strategy, inputs, cfgs[i]))
                done += 1
                if progress:
                    progress(done, len(param_sets))
        else:
            with ProcessPoolExecutor(max_workers=min(self.workers, len(jobs))) as ex:
                futs = {ex.submit(_job, self.strategy, inputs, cfgs[i]): (i, p, h) for i, p, inputs, h in jobs}
                for f in as_completed(futs):
                    i, p, h = futs[f]
                    _store(i, p, h, f.result())
                    done += 1
                    if progress:
                        progress(done, len(param_sets))
        df = pd.DataFrame(rows)
        if tag:
            df["_tag"] = tag
        return df


# ---------------------------------------------------------------------- objective / pass criteria
def objective_values(df: pd.DataFrame, objective: str) -> pd.Series:
    """Column name or a Python expression over metric columns (e.g. 'net_profit / max(equity_dd_rel_pct, 1)')."""
    if objective in df.columns:
        return pd.to_numeric(df[objective], errors="coerce").fillna(-np.inf)
    out = []
    for _, r in df.iterrows():
        env = {k: v for k, v in r.items() if isinstance(k, str)}
        env.update({"max": max, "min": min, "abs": abs, "np": np})
        try:
            out.append(float(eval(objective, {"__builtins__": {}}, env)))
        except Exception:
            out.append(-np.inf)
    return pd.Series(out, index=df.index)


class Criteria:
    """When a result counts as 'surviving' (used for survival percentages)."""

    def __init__(self, min_trades: int = 10, min_profit_factor: float = 1.0, max_dd_pct: float = 100.0,
                 min_net_profit: float = 0.0, require_no_stopout: bool = True):
        self.min_trades = min_trades
        self.min_profit_factor = min_profit_factor
        self.max_dd_pct = max_dd_pct
        self.min_net_profit = min_net_profit
        self.require_no_stopout = require_no_stopout

    def profitable(self, df: pd.DataFrame) -> pd.Series:
        ok = df.get("_ok", pd.Series(True, index=df.index)).fillna(False).astype(bool)
        return ok & (pd.to_numeric(df.get("net_profit", 0), errors="coerce").fillna(-1) > self.min_net_profit)

    def passed(self, df: pd.DataFrame) -> pd.Series:
        p = self.profitable(df)
        p &= pd.to_numeric(df.get("trades", 0), errors="coerce").fillna(0) >= self.min_trades
        p &= pd.to_numeric(df.get("profit_factor", 0), errors="coerce").fillna(0) >= self.min_profit_factor
        p &= pd.to_numeric(df.get("equity_dd_rel_pct", 100), errors="coerce").fillna(100) <= self.max_dd_pct
        if self.require_no_stopout and "stopped_out" in df:
            p &= ~df["stopped_out"].fillna(False).astype(bool)
        return p

    def as_dict(self):
        return dict(self.__dict__)
