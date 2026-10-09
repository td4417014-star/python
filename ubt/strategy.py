"""Base class for ported Expert Advisors.

A port subclasses :class:`Strategy`, points ``MQ5_FILE`` at the original
source and keeps the MQL5 code structure (OnInit/OnTick/OnTimer/OnDeinit/
OnTester). Inputs are read from the .mq5 automatically and exposed as
attributes with their MQL names (``self.InpGZ_ZscorePeriod``), so input
lists never have to be typed by hand and MT5 .set files apply directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from .mq5 import parse_mq5, Mq5Info
from .mql5 import constants as C

_INFO_CACHE: Dict[str, Mq5Info] = {}


class Strategy:
    MQ5_FILE: Optional[str] = None     # path to the original EA (relative to the strategy module or absolute)
    DEFAULTS: dict = {}                # used when no MQ5_FILE is given

    def __init__(self, inputs: Optional[dict] = None):
        vals = dict(self.defaults())
        if inputs:
            unknown = [k for k in inputs if k not in vals]
            if unknown and vals:
                raise KeyError(f"unknown inputs for {type(self).__name__}: {unknown}")
            vals.update(inputs)
        self.inputs = vals
        for k, v in vals.items():
            setattr(self, k, v)

    # ------------------------------------------------------------------ metadata
    @classmethod
    def mq5_path(cls) -> Optional[Path]:
        if not cls.MQ5_FILE:
            return None
        p = Path(cls.MQ5_FILE)
        if not p.is_absolute():
            import inspect
            base = Path(inspect.getfile(cls)).resolve().parent
            for cand in (base / p, base.parent / p, Path.cwd() / p):
                if cand.exists():
                    return cand
        return p

    @classmethod
    def mq5_info(cls) -> Optional[Mq5Info]:
        p = cls.mq5_path()
        if p is None:
            return None
        key = str(p)
        if key not in _INFO_CACHE:
            _INFO_CACHE[key] = parse_mq5(p)
        return _INFO_CACHE[key]

    @classmethod
    def defaults(cls) -> dict:
        info = cls.mq5_info()
        d = info.defaults() if info else {}
        d.update(cls.DEFAULTS)
        return d

    @classmethod
    def required_symbols(cls, inputs: dict, chart_symbol: str) -> List[str]:
        """Symbols the EA trades / reads. Default: chart symbol + symbol-like string inputs."""
        vals = dict(cls.defaults())
        vals.update(inputs or {})
        out = [chart_symbol]
        import re
        for k, v in vals.items():
            if isinstance(v, str) and re.search(r"symbol|asset|instrument", k, re.I):
                v = v.strip()
                if v and v not in out:
                    out.append(v)
        return out

    # ------------------------------------------------------------------ event handlers
    def OnInit(self) -> int:
        return C.INIT_SUCCEEDED

    def OnTick(self):
        pass

    def OnTimer(self):
        pass

    def OnDeinit(self, reason: int):
        pass

    def OnTester(self) -> float:
        return 0.0
