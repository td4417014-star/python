"""Discrete parameter space shared by optimizer, sensitivity and walk-forward.

Spec format (JSON/YAML, also produced by ``ubt.mq5.auto_space`` and ``read_set``)::

    {"InpGZ_ZscorePeriod": {"type": "int",   "low": 7,   "high": 21,  "step": 2},
     "InpGZ_ZscoreBuyTh":  {"type": "float", "low": -0.6, "high": -0.1, "step": 0.1},
     "InpGZ_AllowBothSides": {"type": "bool"},
     "InpGZ_TrailGrid":    {"type": "enum",  "values": [0, 1, 2, 3, 4, 5]}}
"""
from __future__ import annotations

import itertools
import json
import math
from pathlib import Path
from typing import Dict, Iterator, List, Optional

import numpy as np


class ParamSpace:
    def __init__(self, spec: Dict[str, dict]):
        self.spec = {k: dict(v) for k, v in spec.items()}
        self._vals: Dict[str, list] = {k: self._values(v) for k, v in self.spec.items()}

    @classmethod
    def load(cls, path: str | Path) -> "ParamSpace":
        p = Path(path)
        txt = p.read_text(encoding="utf-8")
        if p.suffix.lower() in (".yaml", ".yml"):
            import yaml
            return cls(yaml.safe_load(txt))
        if p.suffix.lower() == ".set":
            from ..mq5 import read_set
            return cls(read_set(p)[1])
        return cls(json.loads(txt))

    def save(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.spec, indent=2), encoding="utf-8")

    @staticmethod
    def _values(v: dict) -> list:
        t = v.get("type", "float")
        if "values" in v:
            return list(v["values"])
        if t == "bool":
            return [False, True]
        lo, hi = v["low"], v["high"]
        step = v.get("step") or (hi - lo) / 4 or 1
        if t == "int":
            step = max(1, int(round(step)))
            return list(range(int(lo), int(hi) + 1, step))
        n = int(math.floor((hi - lo) / step + 1e-9)) + 1
        return [round(lo + i * step, 10) for i in range(n)]

    # ------------------------------------------------------------------
    @property
    def names(self) -> List[str]:
        return list(self.spec)

    def values(self, name: str) -> list:
        return self._vals[name]

    def size(self) -> int:
        return int(np.prod([len(v) for v in self._vals.values()])) if self._vals else 0

    def grid(self) -> Iterator[dict]:
        names = self.names
        for combo in itertools.product(*(self._vals[n] for n in names)):
            yield dict(zip(names, combo))

    def random(self, n: int, seed: int = 0) -> List[dict]:
        rng = np.random.default_rng(seed)
        out, seen = [], set()
        tries = 0
        while len(out) < n and tries < n * 50:
            tries += 1
            p = {k: v[int(rng.integers(len(v)))] for k, v in self._vals.items()}
            key = self.key(p)
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def lhs(self, n: int, seed: int = 0) -> List[dict]:
        """Latin hypercube over the discrete grids (even coverage of every parameter)."""
        rng = np.random.default_rng(seed)
        cols = {}
        for k, v in self._vals.items():
            bins = (np.arange(n) + rng.random(n)) / n
            rng.shuffle(bins)
            cols[k] = [v[min(int(b * len(v)), len(v) - 1)] for b in bins]
        out, seen = [], set()
        for i in range(n):
            p = {k: cols[k][i] for k in self._vals}
            if self.key(p) not in seen:
                seen.add(self.key(p))
                out.append(p)
        return out

    def snap(self, name: str, value):
        vals = self._vals[name]
        if isinstance(vals[0], bool) or not isinstance(vals[0], (int, float)):
            return value if value in vals else vals[0]
        return min(vals, key=lambda x: abs(x - value))

    def index(self, name: str, value) -> int:
        vals = self._vals[name]
        try:
            return vals.index(value)
        except ValueError:
            return vals.index(self.snap(name, value))

    def neighbors(self, point: dict, radius: int = 1, joint: bool = False) -> List[dict]:
        """Grid neighbours: one-at-a-time (default) or all joint +-radius combinations."""
        names = [n for n in self.names if n in point]
        if not joint:
            out = []
            for n in names:
                vals = self._vals[n]
                i = self.index(n, point[n])
                for d in range(-radius, radius + 1):
                    if d == 0 or not (0 <= i + d < len(vals)):
                        continue
                    q = dict(point)
                    q[n] = vals[i + d]
                    out.append(q)
            return out
        ranges = []
        for n in names:
            vals = self._vals[n]
            i = self.index(n, point[n])
            ranges.append([vals[j] for j in range(max(0, i - radius), min(len(vals), i + radius + 1))])
        out = []
        for combo in itertools.product(*ranges):
            q = dict(point)
            q.update(dict(zip(names, combo)))
            if self.key(q) != self.key(point):
                out.append(q)
        return out

    def perturb(self, point: dict, pct: float, n: int, seed: int = 0, clip: bool = False) -> List[dict]:
        """Joint random perturbation: numeric params x (1 +- U(pct)), ints rounded, bools/enums flipped
        with probability pct/100 * 2. Values are NOT snapped to the grid (tests true sensitivity)."""
        rng = np.random.default_rng(seed)
        out = []
        for _ in range(n):
            q = dict(point)
            for k, sp in self.spec.items():
                if k not in point:
                    continue
                t = sp.get("type", "float")
                v = point[k]
                if t in ("bool", "enum") or isinstance(v, bool):
                    if rng.random() < min(1.0, pct / 100 * 2):
                        vals = [x for x in self._vals[k] if x != v]
                        if vals:
                            q[k] = vals[int(rng.integers(len(vals)))]
                    continue
                f = 1 + rng.uniform(-pct, pct) / 100
                nv = v * f if v != 0 else rng.uniform(-pct, pct) / 100 * (sp.get("high", 1) - sp.get("low", 0))
                if t == "int":
                    nv = int(round(nv))
                    if v > 0:
                        nv = max(1, nv)
                else:
                    nv = round(float(nv), 10)
                if clip and "low" in sp:
                    nv = min(max(nv, sp["low"]), sp["high"])
                q[k] = nv
            out.append(q)
        return out

    @staticmethod
    def key(p: dict) -> str:
        return json.dumps({k: p[k] for k in sorted(p)}, sort_keys=True, default=str)
